"""Standalone OpenAI-CPA / xAI email code bridge for public servers.

Deploy on a public host so CF Worker can POST codes,
while local opaiRe pulls them via /api/email-bridge/check or WebSocket.

Env:
  EMAIL_WEBHOOK_TOKEN / EMAIL_WEBHOOK_SECRET  webhook auth (Worker X-Webhook-Secret)
  EMAIL_API_TOKEN                             client check/ws auth (fallback webhook token)
  EMAIL_DATABASE_PATH                         sqlite path
  EMAIL_CODE_TTL_SEC                          code TTL seconds (default 300)
"""
from __future__ import annotations

import asyncio
import hmac
import os
import re
import sqlite3
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple
from urllib.parse import unquote

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect

OTP_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
XAI_SUBJECT_CODE_RE = re.compile(
    r"(?i)(?:SpaceXAI|xAI|Grok).{0,40}(?:confirmation\s+)?code\s*[:：]\s*([A-Z0-9]{3}-[A-Z0-9]{3})"
)
XAI_LABELED_DASH = re.compile(
    r"(?i)(?:confirmation\s+)?(?:code|otp|验证码|verification code|verify code|code is|your code)"
    r"\s*[:：]?\s*([A-Z0-9]{3}-[A-Z0-9]{3})"
)
XAI_LABELED_PLAIN = re.compile(
    r"(?i)(?:confirmation\s+)?(?:code|otp|验证码|verification code|verify code|code is|your code)"
    r"\s*[:：]?\s*([A-Z0-9]{6,8})"
)
XAI_SUBJECT_LINE = re.compile(
    r"(?im)^subject:[^\n]{0,120}?(?:code|otp|验证码)\s*[:：]?\s*([A-Z0-9]{3}-[A-Z0-9]{3})"
)
XAI_DASH = re.compile(r"(?<![A-Z0-9])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9])")

DATABASE_PATH = Path(os.environ.get("EMAIL_DATABASE_PATH", "email-codes.db"))
WEBHOOK_TOKEN = (
    os.environ.get("EMAIL_WEBHOOK_SECRET", "").strip()
    or os.environ.get("EMAIL_WEBHOOK_TOKEN", "").strip()
)
API_TOKEN = os.environ.get("EMAIL_API_TOKEN", WEBHOOK_TOKEN).strip() or WEBHOOK_TOKEN
TTL_SEC = max(30, int(os.environ.get("EMAIL_CODE_TTL_SEC", "300") or 300))
MAX_BODY = 1024 * 1024

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
listeners: Dict[str, Set[WebSocket]] = defaultdict(set)
database_lock = asyncio.Lock()


def _looks_like_xai_code(raw: str) -> bool:
    s = (raw or "").strip().upper()
    if not s:
        return False
    if re.fullmatch(r"[A-Z0-9]{3}-[A-Z0-9]{3}", s):
        return True
    compact = re.sub(r"[\s\-]+", "", s)
    if len(compact) not in (6, 8):
        return False
    if not re.fullmatch(r"[A-Z0-9]+", compact):
        return False
    if compact.isdigit() or compact.isalpha():
        return False
    return True


def _is_domain_fragment(text: str, start: int, end: int, raw: str) -> bool:
    left = text[max(0, start - 2) : start]
    right = text[end : min(len(text), end + 2)]
    if "." in left or left.endswith("@") or left.endswith("/") or left.endswith("="):
        return True
    if right.startswith(".") or right.startswith("@") or right.startswith("/"):
        return True
    window = text[max(0, start - 40) : min(len(text), end + 40)]
    compact = re.sub(r"[\s\-]+", "", raw).lower()
    if re.search(rf"(?i)(?:@|[a-z0-9-]\.){re.escape(compact)}(?:\.[a-z0-9-]+)", window):
        return True
    if re.search(rf"(?i){re.escape(compact)}\.(?:kdns|com|net|org|fr|ai|io|co)\b", window):
        return True
    return False


def extract_xai_code(text: str) -> str:
    body = text or ""
    if not body.strip():
        return ""
    for pat in (XAI_SUBJECT_LINE, XAI_LABELED_DASH, XAI_SUBJECT_CODE_RE):
        for m in pat.finditer(body):
            raw = (m.group(1) or "").strip()
            if _looks_like_xai_code(raw):
                return raw.upper()
    for m in XAI_LABELED_PLAIN.finditer(body):
        raw = (m.group(1) or "").strip()
        if _looks_like_xai_code(raw) and not _is_domain_fragment(body, m.start(1), m.end(1), raw):
            return raw.upper()
    for m in XAI_DASH.finditer(body):
        raw = (m.group(1) or "").strip()
        if not _looks_like_xai_code(raw):
            continue
        if _is_domain_fragment(body, m.start(1), m.end(1), raw):
            continue
        return raw.upper()
    return ""


def extract_code(content: str) -> str:
    """Extract OpenAI 6-digit or Grok/xAI XXX-XXX codes from raw mail."""
    text = str(content or "")
    if not text:
        return ""

    looks_xai = bool(
        re.search(
            r"(?i)(?:noreply@x\.ai|\bx\.ai\b|spacexai|\bgrok\b|(?<![a-z])xai(?![a-z]))",
            text,
        )
    )

    openai_patterns = [
        r"enter this code:\s*(\d{6})",
        r"verification code to continue:\s*(\d{6})",
        r"Your (?:ChatGPT|OpenAI) code is\s*(\d{6})",
        r"输入此(?:临时)?验证码以继续[：:]\s*(\d{6})",
        r"(?i)(?:verification|security|login|sign[- ]?up) code[:\s]+(\d{6})",
        r"(?i)(?:ChatGPT|OpenAI).{0,40}code is[:\s]+(\d{6})",
    ]
    for pat in openai_patterns:
        found = re.findall(pat, text, flags=re.I)
        if found:
            return found[-1]

    xai = extract_xai_code(text)
    if xai:
        return xai
    if looks_xai:
        m = XAI_DASH.search(text)
        if m and _looks_like_xai_code(m.group(1)):
            return m.group(1).upper()

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
    m = re.search(r"([a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,})", raw, flags=re.I)
    return m.group(1).lower() if m else raw


def bearer_token(value: Optional[str]) -> str:
    raw = str(value or "").strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return raw


def token_matches(provided: Optional[str], expected: str) -> bool:
    expected = str(expected or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(bearer_token(provided), expected)


def _require(value: Optional[str], *more: Optional[str], expected: str) -> None:
    for item in (value, *more):
        if token_matches(item, expected):
            return
    raise HTTPException(status_code=401, detail="unauthorized")


def parse_webhook_payload(data: Dict[str, Any]) -> Tuple[str, str, str, str]:
    address = normalize_address(
        data.get("to_addr")
        or data.get("to")
        or data.get("recipient")
        or data.get("email")
        or data.get("address")
        or ""
    )
    sender = str(data.get("from_addr") or data.get("from") or data.get("sender") or "")
    subject = str(data.get("subject") or "")
    text = str(data.get("text") or data.get("body") or data.get("content") or "")
    html = str(data.get("html") or data.get("raw_html") or "")
    raw = str(data.get("raw_content") or data.get("raw") or "")
    raw_text = "\n".join(part for part in (subject, text, html, raw) if part)
    code = str(data.get("code") or "").strip() or extract_code(raw_text)
    return address, sender, code, raw_text


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), timeout=5)
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


async def _store(address: str, code: str, sender: str, raw_text: str) -> None:
    now = time.time()
    async with database_lock:
        with _connect() as conn:
            conn.execute("DELETE FROM email_codes WHERE received_at < ?", (now - TTL_SEC,))
            conn.execute(
                "INSERT INTO email_codes (address, code, sender, raw_text, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (address, code, sender, raw_text, now),
            )


async def _latest(address: str) -> Optional[Tuple[str, str, str]]:
    now = time.time()
    async with database_lock:
        with _connect() as conn:
            conn.execute("DELETE FROM email_codes WHERE received_at < ?", (now - TTL_SEC,))
            row = conn.execute(
                "SELECT code, sender, raw_text FROM email_codes "
                "WHERE address = ? ORDER BY received_at DESC LIMIT 1",
                (address,),
            ).fetchone()
            return row if row else None


async def _publish(address: str, code: str, sender: str, raw_text: str) -> int:
    await _store(address, code, sender, raw_text)
    payload = {"code": code, "from": sender, "email": address, "raw_text": raw_text}
    stale = []
    delivered = 0
    for socket in tuple(listeners.get(address, ())):
        try:
            await socket.send_json(payload)
            delivered += 1
        except Exception:
            stale.append(socket)
    for socket in stale:
        listeners[address].discard(socket)
    if not listeners.get(address):
        listeners.pop(address, None)
    return delivered


@app.on_event("startup")
async def startup():
    with _connect() as conn:
        pass


@app.get("/health")
@app.get("/api/email-bridge/health")
async def health():
    return {"status": "ok", "listeners": sum(len(v) for v in listeners.values()), "mode": "openai-cpa"}


async def _handle_webhook(
    request: Request,
    authorization: Optional[str] = None,
    x_webhook_token: Optional[str] = None,
    x_email_webhook_secret: Optional[str] = None,
    x_webhook_secret: Optional[str] = None,
):
    _require(
        authorization,
        x_webhook_token,
        x_email_webhook_secret,
        x_webhook_secret,
        expected=WEBHOOK_TOKEN,
    )
    body = await request.body()
    if len(body) > MAX_BODY:
        raise HTTPException(status_code=413, detail="invalid body")
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid payload")
    address, sender, code, raw_text = parse_webhook_payload(data)
    if not address or not code:
        return {"ok": True, "stored": False, "reason": "missing address or code"}
    delivered = await _publish(address, code, sender, raw_text or code)
    return {"ok": True, "stored": True, "email": address, "delivered": delivered}


@app.post("/api/webhook/email")
@app.post("/api/email-bridge/webhook")
@app.post("/webhook")
async def webhook(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_webhook_token: Optional[str] = Header(default=None),
    x_email_webhook_secret: Optional[str] = Header(default=None),
    x_webhook_secret: Optional[str] = Header(default=None),
):
    return await _handle_webhook(
        request,
        authorization,
        x_webhook_token,
        x_email_webhook_secret,
        x_webhook_secret,
    )


@app.get("/api/email-bridge/check/{address:path}")
@app.get("/check/{address:path}")
async def check(
    address: str,
    authorization: Optional[str] = Header(default=None),
    x_webhook_token: Optional[str] = Header(default=None),
    x_webhook_secret: Optional[str] = Header(default=None),
):
    _require(authorization, x_webhook_token, x_webhook_secret, expected=API_TOKEN)
    row = await _latest(normalize_address(unquote(address)))
    if not row:
        return {"code": None}
    return {"code": row[0], "from": row[1], "raw_text": row[2]}


async def _ws_handler(websocket: WebSocket, address: str) -> None:
    auth = (
        websocket.headers.get("authorization")
        or websocket.headers.get("x-webhook-secret")
        or websocket.query_params.get("token")
    )
    try:
        _require(auth, expected=API_TOKEN)
    except HTTPException:
        await websocket.close(code=4401)
        return

    address = normalize_address(unquote(address))
    if not address:
        await websocket.close(code=4400)
        return

    await websocket.accept()
    listeners[address].add(websocket)
    try:
        row = await _latest(address)
        if row:
            await websocket.send_json(
                {"code": row[0], "from": row[1], "email": address, "raw_text": row[2]}
            )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        listeners[address].discard(websocket)
        if not listeners.get(address):
            listeners.pop(address, None)


@app.websocket("/api/email-bridge/ws/{address:path}")
async def ws_bridge(websocket: WebSocket, address: str):
    await _ws_handler(websocket, address)


@app.websocket("/ws/{address:path}")
async def ws_legacy(websocket: WebSocket, address: str):
    await _ws_handler(websocket, address)
