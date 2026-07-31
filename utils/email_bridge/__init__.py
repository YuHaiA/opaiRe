"""CPA email relay: server store/fanout + local code_pool inject.

CF Worker (openai-cpa-email) -> POST /api/webhook/email
  headers: X-Webhook-Secret
  body: {message_id, to_addr, raw_content}

Receive modes (openai_cpa.receive_mode):
  remote_bridge: public server stores codes; local opaiRe pulls via WS/HTTP
  local_webhook: Worker/Tunnel posts into this process and injects code_pool
  dual: both paths

Public bridge also exposes opaiRe client paths:
  /api/email-bridge/webhook|check|ws|health
"""
from __future__ import annotations

import asyncio
import hmac
import re
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
XAI_SUBJECT_CODE_RE = re.compile(
    r"(?i)(?:SpaceXAI|xAI|Grok).{0,40}(?:confirmation\s+)?code\s*[:：]\s*([A-Z0-9]{3}-[A-Z0-9]{3})"
)
XAI_INLINE_CODE_RE = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9])")


def extract_code(content: str) -> str:
    """Extract OTP from raw mail.

    Supports:
      - OpenAI/ChatGPT 6-digit codes
      - Grok/xAI/SpaceXAI codes like 881-ELG
    Avoid bare 6-digit fallbacks from MIME headers when a better code exists.
    """
    text = str(content or "")
    if not text:
        return ""

    looks_xai = bool(re.search(r"(?i)(?:noreply@x\.ai|\bx\.ai\b|spacexai|\bgrok\b|(?<![a-z])xai(?![a-z]))", text))

    # Explicit OpenAI digit patterns first — avoid treating words like "OpenAI" as xAI codes.
    openai_patterns = [
        r"enter this code:\s*(\d{6})",
        r"verification code to continue:\s*(\d{6})",
        r"Your (?:ChatGPT|OpenAI) code is\s*(\d{6})",
        r"输入此(?:临时)?验证码以继续[：:]\s*(\d{6})",
        r"(?i)(?:verification|security|login|sign[- ]?up) code[:\s]+(\d{6})",
        r"(?i)(?:ChatGPT|OpenAI).{0,40}code is[:\s]+(\d{6})",
        r"(?i)code is[:\s]+(\d{6})",
    ]
    for pat in openai_patterns:
        found = re.findall(pat, text, flags=re.I)
        if found:
            return found[-1]

    # xAI / SpaceXAI alphanumeric codes
    m = XAI_SUBJECT_CODE_RE.search(text)
    if m:
        return m.group(1).upper()
    if looks_xai:
        try:
            from utils.grok_auth.otp import extract_xai_code

            xai_code = extract_xai_code(text)
            if xai_code:
                return str(xai_code).upper()
        except Exception:
            pass
        m = XAI_INLINE_CODE_RE.search(text)
        if m:
            return m.group(1).upper()

    # Last-resort pure digits only on a narrowed body window to avoid header junk.
    body_window = text
    lower = text.lower()
    for marker in ("\r\n\r\n", "\n\n", "<html", "<body"):
        idx = lower.find(marker)
        if idx >= 0:
            body_window = text[idx:]
            break
    m = OTP_RE.search(body_window)
    return m.group(1) if m else ""


def normalize_address(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    # Angle-bracket / display-name forms: Name <user@x.com>
    m = re.search(r"([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", raw, flags=re.I)
    return m.group(1).lower() if m else raw


def bearer_token(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


class EmailCodeRelay:
    """In-memory + sqlite backed code store with websocket listener fanout."""

    def __init__(self, db_path: Path, ttl_sec: int = 300):
        self.db_path = Path(db_path)
        self.ttl_sec = max(30, int(ttl_sec or 300))
        self._lock = asyncio.Lock()
        self.listeners: Dict[str, Set[Any]] = defaultdict(set)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS email_codes ("
            "address TEXT NOT NULL, code TEXT NOT NULL, sender TEXT NOT NULL, "
            "raw_text TEXT NOT NULL DEFAULT '', received_at REAL NOT NULL)"
        )
        cols = {row[1] for row in conn.execute("PRAGMA table_info(email_codes)").fetchall()}
        if "raw_text" not in cols:
            conn.execute("ALTER TABLE email_codes ADD COLUMN raw_text TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_email_codes_address_time "
            "ON email_codes(address, received_at DESC)"
        )
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            pass

    async def store(self, address: str, code: str, sender: str = "", raw_text: str = "") -> None:
        address = normalize_address(address)
        code = str(code or "").strip()
        if not address or not code:
            return
        raw_text = raw_text or code
        now = time.time()
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM email_codes WHERE received_at < ?",
                    (now - self.ttl_sec,),
                )
                conn.execute(
                    "INSERT INTO email_codes (address, code, sender, raw_text, received_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (address, code, sender, raw_text, now),
                )

    async def latest(self, address: str) -> Optional[Tuple[str, str, str]]:
        address = normalize_address(address)
        now = time.time()
        async with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM email_codes WHERE received_at < ?",
                    (now - self.ttl_sec,),
                )
                row = conn.execute(
                    "SELECT code, sender, raw_text FROM email_codes "
                    "WHERE address = ? ORDER BY received_at DESC LIMIT 1",
                    (address,),
                ).fetchone()
                return row if row else None

    async def publish(self, address: str, code: str, sender: str = "", raw_text: str = "") -> int:
        address = normalize_address(address)
        await self.store(address, code, sender=sender, raw_text=raw_text or code)
        payload = {"code": code, "from": sender, "email": address, "raw_text": raw_text or code}
        stale = []
        delivered = 0
        for socket in tuple(self.listeners.get(address, ())):
            try:
                await socket.send_json(payload)
                delivered += 1
            except Exception:
                stale.append(socket)
        for socket in stale:
            self.listeners[address].discard(socket)
        if not self.listeners.get(address):
            self.listeners.pop(address, None)
        return delivered


_relay: Optional[EmailCodeRelay] = None
_relay_lock = threading.Lock()


def get_relay() -> EmailCodeRelay:
    global _relay
    if _relay is not None:
        return _relay
    with _relay_lock:
        if _relay is None:
            root = Path(__file__).resolve().parents[2]
            db_path = root / "data" / "email-bridge-codes.db"
            _relay = EmailCodeRelay(db_path=db_path, ttl_sec=300)
            _relay.init_db()
        return _relay


def latest_code_sync(address: str) -> Optional[Tuple[str, str, str]]:
    """Sync helper for registration threads: read latest code from local relay DB."""
    address = normalize_address(address)
    if not address:
        return None
    relay = get_relay()
    now = time.time()
    try:
        with relay._connect() as conn:
            conn.execute(
                "DELETE FROM email_codes WHERE received_at < ?",
                (now - relay.ttl_sec,),
            )
            row = conn.execute(
                "SELECT code, sender, raw_text FROM email_codes "
                "WHERE address = ? ORDER BY received_at DESC LIMIT 1",
                (address,),
            ).fetchone()
            return row if row else None
    except Exception:
        return None


def parse_webhook_payload(data: Dict[str, Any]) -> Tuple[str, str, str, str]:
    """Return (address, sender, code, raw_text).

    Supports official openai-cpa-email Worker payload and flexible aliases.
    """
    address = normalize_address(
        data.get("to_addr")
        or data.get("to")
        or data.get("recipient")
        or data.get("email")
        or data.get("address")
        or ""
    )
    sender = str(
        data.get("from_addr")
        or data.get("from")
        or data.get("sender")
        or ""
    )
    subject = str(data.get("subject") or "")
    text = str(data.get("text") or data.get("body") or data.get("content") or "")
    html = str(data.get("html") or data.get("raw_html") or "")
    raw = str(data.get("raw_content") or data.get("raw") or "")
    raw_text = "\n".join(part for part in (subject, text, html, raw) if part)
    code = str(data.get("code") or "").strip() or extract_code(raw_text)
    return address, sender, code, raw_text


def token_matches(provided: Optional[str], expected: str) -> bool:
    expected = str(expected or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(bearer_token(provided), expected)
