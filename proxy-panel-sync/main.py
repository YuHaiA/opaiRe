from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import subprocess
import time
from datetime import datetime
from calendar import monthrange
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "proxy_panel.db"
TOKEN_FILE = DATA_DIR / "admin_token.txt"
SOURCE_CLASH = Path("/var/www/proxy-subs/clash.yaml")
SOURCE_V2RAY = Path("/var/www/proxy-subs/v2ray.txt")
TG_TOOL_PATH = Path(__file__).resolve().with_name("tg_xray_tool.py")
DATA_DIR.mkdir(parents=True, exist_ok=True)

SERVER3_PREFIX = "server3-"
SERVER4_PREFIX = "server4-"
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"
TG_SERVERS = {
    "s3": {
        "name": "Server 3",
        "host": "dazhou.bond",
        "port": 18443,
        "ssh": None,
        "tool": str(TG_TOOL_PATH),
    },
    "s4": {
        "name": "Server 4",
        "host": "xh-ai.cyou",
        "port": 18444,
        "tool": "/home/opc/tg_xray_tool.py",
        "ssh": [
            "ssh",
            "-i",
            "/home/opc/.ssh/server4_reconcile_key",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "-o",
            "StrictHostKeyChecking=no",
            "opc@10.0.0.154",
        ],
    },
}

DISABLED_CLASH = {
    "proxies": [],
    "proxy-groups": [{"name": "Node Select", "type": "select", "proxies": ["DIRECT"]}],
    "rules": ["MATCH,DIRECT"],
}
DISABLED_V2RAY_TEXT = base64.b64encode(b"# disabled\n").decode("ascii")

app = FastAPI(title="Proxy Panel", docs_url="/docs")


class LoginReq(BaseModel):
    token: str


class AccountIn(BaseModel):
    id: Optional[str] = ""
    name: str
    enabled: bool = True
    quota_gb: float = 200
    used_gb_s3: float = 0
    used_gb_s4: float = 0
    traffic_reset_mode: str = "monthly"
    reset_day: int = 1
    slug: Optional[str] = ""
    notes: Optional[str] = ""


class IdReq(BaseModel):
    id: str


class UsageReq(BaseModel):
    id: str
    used_gb_s3: Optional[float] = None
    used_gb_s4: Optional[float] = None
    used_gb: Optional[float] = None


class TgAccountReq(BaseModel):
    id: Optional[str] = ""
    server: str
    user: Optional[str] = ""
    password: Optional[str] = ""
    enabled: bool = True
    quota_gb: float = 50
    used_gb: float = 0
    traffic_reset_mode: str = "monthly"
    reset_day: int = 1
    notes: Optional[str] = ""


class TgAccountDeleteReq(BaseModel):
    id: Optional[str] = ""
    server: str
    user: str


def admin_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
    return token


def require_auth(authorization: str = Header("")) -> None:
    if not authorization.startswith("Bearer ") or authorization.split(" ", 1)[1] != admin_token():
        raise HTTPException(status_code=401, detail="unauthorized")


def tg_server_config(server: str) -> dict[str, Any]:
    key = str(server or "").lower()
    if key not in TG_SERVERS:
        raise HTTPException(status_code=400, detail="unknown tg server")
    return TG_SERVERS[key]


def run_tg_xray(server: str, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = tg_server_config(server)
    body = json.dumps(payload)
    if cfg["ssh"]:
        cmd = [*cfg["ssh"], "sudo", "python3", str(cfg["tool"])]
    else:
        cmd = ["sudo", "python3", str(cfg["tool"])]
    result = subprocess.run(cmd, input=body, text=True, capture_output=True, timeout=30)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "tg account operation failed").strip()
        raise HTTPException(status_code=500, detail=detail[-500:])
    try:
        return json.loads(result.stdout)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"bad tg account response: {exc}") from exc


def normalize_panel_tg_user(value: str | None) -> str:
    cleaned = "".join(ch for ch in str(value or "").strip().lower() if ch.isalnum() or ch in "_-")
    if not cleaned:
        cleaned = secrets.token_hex(4)
    if not cleaned.startswith("panel_"):
        cleaned = "panel_" + cleaned
    return cleaned[:40]


def tg_account_available(account: dict[str, Any]) -> bool:
    if not bool(account.get("enabled")):
        return False
    quota = float(account.get("quota_gb") or 0)
    if quota <= 0:
        return True
    return float(account.get("used_gb") or 0) < quota


def tg_row_to_account(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["quota_gb"] = round(float(item.get("quota_gb") or 0), 3)
    item["used_gb"] = round(float(item.get("used_gb") or 0), 3)
    item["traffic_reset_mode"] = normalize_traffic_reset_mode(item.get("traffic_reset_mode"))
    item["traffic_reset_label"] = "月重置" if item["traffic_reset_mode"] == "monthly" else "时间不限"
    item["remaining_gb"] = max(0.0, round(item["quota_gb"] - item["used_gb"], 3)) if item["quota_gb"] > 0 else 0.0
    item["usage_percent"] = 0 if item["quota_gb"] <= 0 else min(100, round(item["used_gb"] / item["quota_gb"] * 100, 1))
    item["available"] = tg_account_available(item)
    cfg = tg_server_config(item["server"])
    item["host"] = cfg["host"]
    item["port"] = cfg["port"]
    item["link"] = tg_socks_link(str(cfg["host"]), int(cfg["port"]), item["user"], item["password"])
    return item


def ensure_tg_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS tg_accounts (
        id TEXT PRIMARY KEY,
        server TEXT NOT NULL,
        user TEXT NOT NULL,
        password TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        quota_gb REAL NOT NULL,
        used_gb REAL NOT NULL DEFAULT 0,
        reset_day INTEGER NOT NULL,
        reset_cycle TEXT NOT NULL DEFAULT '',
        traffic_reset_mode TEXT NOT NULL DEFAULT 'monthly',
        notes TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL,
        UNIQUE(server, user)
    )"""
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tg_accounts)").fetchall()}
    additions = {
        "quota_gb": "ALTER TABLE tg_accounts ADD COLUMN quota_gb REAL NOT NULL DEFAULT 50",
        "used_gb": "ALTER TABLE tg_accounts ADD COLUMN used_gb REAL NOT NULL DEFAULT 0",
        "reset_day": "ALTER TABLE tg_accounts ADD COLUMN reset_day INTEGER NOT NULL DEFAULT 1",
        "reset_cycle": "ALTER TABLE tg_accounts ADD COLUMN reset_cycle TEXT NOT NULL DEFAULT ''",
        "traffic_reset_mode": "ALTER TABLE tg_accounts ADD COLUMN traffic_reset_mode TEXT NOT NULL DEFAULT 'monthly'",
        "notes": "ALTER TABLE tg_accounts ADD COLUMN notes TEXT NOT NULL DEFAULT ''",
    }
    for name, sql in additions.items():
        if name not in columns:
            conn.execute(sql)


def apply_tg_monthly_reset(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, reset_day, reset_cycle, traffic_reset_mode FROM tg_accounts").fetchall()
    now_ts = int(time.time())
    for row in rows:
        if normalize_traffic_reset_mode(row["traffic_reset_mode"]) != "monthly":
            continue
        reset_day = min(28, max(1, int(row["reset_day"] or 1)))
        cycle = current_reset_cycle(reset_day)
        if str(row["reset_cycle"] or "") != cycle:
            conn.execute(
                "UPDATE tg_accounts SET used_gb = 0, reset_cycle = ?, updated_at = ? WHERE id = ?",
                (cycle, now_ts, row["id"]),
            )
    conn.commit()


def list_tg_panel_accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    ensure_tg_tables(conn)
    apply_tg_monthly_reset(conn)
    rows = conn.execute("SELECT * FROM tg_accounts ORDER BY created_at ASC").fetchall()
    return [tg_row_to_account(row) for row in rows]


def sync_tg_xray_from_db(conn: sqlite3.Connection) -> None:
    accounts = list_tg_panel_accounts(conn)
    for server in TG_SERVERS:
        active = [
            {"user": item["user"], "password": item["password"]}
            for item in accounts
            if item["server"] == server and item["available"]
        ]
        run_tg_xray(server, {"action": "sync_panel", "accounts": active})


def tg_socks_link(host: str, port: int, user: str, password: str) -> str:
    return f"tg://socks?server={host}&port={port}&user={quote(user)}&pass={quote(password)}"


def list_tg_servers() -> list[dict[str, Any]]:
    conn = db()
    panel_accounts = list_tg_panel_accounts(conn)
    conn.close()
    result = []
    for key, cfg in TG_SERVERS.items():
        port = int(cfg["port"])
        accounts = [item for item in panel_accounts if item["server"] == key]
        result.append(
            {
                "server": key,
                "name": cfg["name"],
                "host": cfg["host"],
                "port": port,
                "accounts": accounts,
            }
        )
    return result


def new_id() -> str:
    return "acct_" + secrets.token_hex(5)


def new_slug() -> str:
    return "".join(secrets.choice(SLUG_ALPHABET) for _ in range(6))


def normalize_slug(value: str) -> str:
    cleaned = "".join(ch for ch in str(value or "").strip().lower() if ch in SLUG_ALPHABET)
    if len(cleaned) < 4:
        return new_slug()
    return cleaned[:7]


def current_reset_cycle(reset_day: int) -> str:
    now = datetime.now()
    year = now.year
    month = now.month
    if now.day < reset_day:
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return f"{year:04d}-{month:02d}"


def next_reset_timestamp(reset_day: int) -> int:
    now = datetime.now()
    day = min(28, max(1, int(reset_day or 1)))
    year = now.year
    month = now.month
    last_day = monthrange(year, month)[1]
    target_day = min(day, last_day)
    target = datetime(year, month, target_day)
    if now >= target:
        month += 1
        if month == 13:
            month = 1
            year += 1
        last_day = monthrange(year, month)[1]
        target_day = min(day, last_day)
        target = datetime(year, month, target_day)
    return int(target.timestamp())


def normalize_traffic_reset_mode(value: Optional[str]) -> str:
    return "unlimited_time" if value == "unlimited_time" else "monthly"


def is_monthly_reset_account(account: dict[str, Any]) -> bool:
    return normalize_traffic_reset_mode(account.get("traffic_reset_mode")) == "monthly"


def subscription_userinfo_headers(account: dict[str, Any]) -> dict[str, str]:
    quota_gb = max(0.0, float(account.get("quota_gb") or 0))
    used_gb = max(0.0, float(account.get("used_gb") or 0))
    total_bytes = int(round(quota_gb * 1024 * 1024 * 1024))
    used_bytes = int(round(used_gb * 1024 * 1024 * 1024))
    return {
        "Subscription-Userinfo": (
            f"upload=0; download={used_bytes}; total={total_bytes}; expire={account_expire_timestamp(account)}"
        ),
        "profile-web-page-url": "https://dazhou.bond/proxy-panel/",
    }


def format_gb(value: float) -> str:
    rounded = round(max(0.0, float(value or 0)), 3)
    return f"{rounded:g}"


def next_reset_label(account: dict[str, Any]) -> str:
    if not is_monthly_reset_account(account):
        return "不限期"
    stamp = next_reset_timestamp(int(account.get("reset_day") or 1))
    return datetime.fromtimestamp(stamp).strftime("%m-%d")


def account_expire_timestamp(account: dict[str, Any]) -> int:
    if not is_monthly_reset_account(account):
        # Common subscription clients treat 0 as no expiration.
        return 0
    return next_reset_timestamp(int(account.get("reset_day") or 1))


def v2ray_usage_node(account: dict[str, Any]) -> str:
    used = format_gb(account.get("used_gb") or 0)
    quota = format_gb(account.get("quota_gb") or 0)
    remaining = format_gb(account.get("remaining_gb") or 0)
    title = f"\u6d41\u91cf {used}/{quota}GB | \u5269\u4f59 {remaining}GB | \u91cd\u7f6e {next_reset_label(account)}"
    payload = {
        "v": "2",
        "ps": title,
        "add": "127.0.0.1",
        "port": "9",
        "id": "00000000-0000-0000-0000-000000000000",
        "aid": "0",
        "scy": "auto",
        "net": "tcp",
        "type": "none",
        "host": "",
        "path": "",
        "tls": "",
        "sni": "",
    }
    encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    return f"vmess://{encoded}"


def encode_v2ray_lines(lines: list[str]) -> str:
    return base64.b64encode("\n".join(lines).encode("utf-8")).decode("ascii")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        enabled INTEGER NOT NULL,
        quota_gb REAL NOT NULL,
        used_gb REAL NOT NULL DEFAULT 0,
        used_gb_s3 REAL NOT NULL DEFAULT 0,
        used_gb_s4 REAL NOT NULL DEFAULT 0,
        reset_day INTEGER NOT NULL,
        reset_cycle TEXT NOT NULL DEFAULT '',
        traffic_reset_mode TEXT NOT NULL DEFAULT 'monthly',
        slug TEXT UNIQUE NOT NULL,
        notes TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
    )"""
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "used_gb_s3" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN used_gb_s3 REAL NOT NULL DEFAULT 0")
    if "used_gb_s4" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN used_gb_s4 REAL NOT NULL DEFAULT 0")
    if "reset_cycle" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN reset_cycle TEXT NOT NULL DEFAULT ''")
    if "traffic_reset_mode" not in columns:
        conn.execute("ALTER TABLE accounts ADD COLUMN traffic_reset_mode TEXT NOT NULL DEFAULT 'monthly'")
    rows = conn.execute("SELECT id, used_gb, used_gb_s3, used_gb_s4 FROM accounts").fetchall()
    for row in rows:
        used_total = float(row["used_gb"] or 0)
        used_s3 = float(row["used_gb_s3"] or 0)
        used_s4 = float(row["used_gb_s4"] or 0)
        if used_total > 0 and used_s3 == 0 and used_s4 == 0:
            half = round(used_total / 2.0, 3)
            conn.execute(
                "UPDATE accounts SET used_gb_s3 = ?, used_gb_s4 = ? WHERE id = ?",
                (half, max(0.0, round(used_total - half, 3)), row["id"]),
            )
    conn.commit()
    return conn


def apply_monthly_reset(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, reset_day, reset_cycle, traffic_reset_mode FROM accounts").fetchall()
    now_ts = int(time.time())
    for row in rows:
        if normalize_traffic_reset_mode(row["traffic_reset_mode"]) != "monthly":
            continue
        reset_day = min(28, max(1, int(row["reset_day"] or 1)))
        cycle = current_reset_cycle(reset_day)
        if str(row["reset_cycle"] or "") != cycle:
            conn.execute(
                "UPDATE accounts SET used_gb = 0, used_gb_s3 = 0, used_gb_s4 = 0, reset_cycle = ?, updated_at = ? WHERE id = ?",
                (cycle, now_ts, row["id"]),
            )
    conn.commit()


def per_server_quota_gb(account: dict[str, Any]) -> float:
    quota = float(account.get("quota_gb") or 0)
    return 0.0 if quota <= 0 else round(quota / 2.0, 3)


def server_available(account: dict[str, Any], server_key: str) -> bool:
    if not bool(account.get("enabled")):
        return False
    limit = per_server_quota_gb(account)
    if limit <= 0:
        return True
    used_value = float(account.get(f"used_gb_{server_key}") or 0)
    return used_value < limit


def account_available(account: dict[str, Any]) -> bool:
    return server_available(account, "s3") or server_available(account, "s4")


def row_to_account(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["enabled"] = bool(item["enabled"])
    item["traffic_reset_mode"] = normalize_traffic_reset_mode(item.get("traffic_reset_mode"))
    item["traffic_reset_label"] = "月重置" if item["traffic_reset_mode"] == "monthly" else "时间不限"
    item["used_gb_s3"] = round(float(item.get("used_gb_s3") or 0), 3)
    item["used_gb_s4"] = round(float(item.get("used_gb_s4") or 0), 3)
    item["used_gb"] = round(item["used_gb_s3"] + item["used_gb_s4"], 3)
    item["quota_scope"] = "split_evenly_per_server"
    item["per_server_quota_gb"] = per_server_quota_gb(item)
    item["remaining_gb_s3"] = max(0.0, round(item["per_server_quota_gb"] - item["used_gb_s3"], 3))
    item["remaining_gb_s4"] = max(0.0, round(item["per_server_quota_gb"] - item["used_gb_s4"], 3))
    item["remaining_gb"] = round(item["remaining_gb_s3"] + item["remaining_gb_s4"], 3)
    item["usage_percent"] = (
        0 if float(item["quota_gb"] or 0) <= 0 else min(100, round(item["used_gb"] / float(item["quota_gb"]) * 100, 1))
    )
    item["server3_available"] = server_available(item, "s3")
    item["server4_available"] = server_available(item, "s4")
    item["published"] = item["server3_available"] or item["server4_available"]
    item["links"] = {
        "clash": f"/subs/{item['slug']}/clash.yaml",
        "v2ray": f"/subs/{item['slug']}/v2ray.txt",
    }
    return item


def ensure_default() -> None:
    conn = db()
    apply_monthly_reset(conn)
    count = conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if count == 0:
        now = int(time.time())
        conn.execute(
            """INSERT INTO accounts
            (id, name, enabled, quota_gb, used_gb, used_gb_s3, used_gb_s4, reset_day, reset_cycle, traffic_reset_mode, slug, notes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), "owner", 1, 200, 0, 0, 0, 1, current_reset_cycle(1), "monthly", new_slug(), "Default owner account", now, now),
        )
        conn.commit()
    conn.close()


def list_accounts() -> list[dict[str, Any]]:
    ensure_default()
    conn = db()
    apply_monthly_reset(conn)
    rows = conn.execute("SELECT * FROM accounts ORDER BY created_at ASC").fetchall()
    conn.close()
    return [row_to_account(row) for row in rows]


def find_account_by_slug(slug: str) -> Optional[dict[str, Any]]:
    conn = db()
    apply_monthly_reset(conn)
    row = conn.execute("SELECT * FROM accounts WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return row_to_account(row) if row else None


def load_clash_template() -> dict[str, Any]:
    if not SOURCE_CLASH.exists():
        return DISABLED_CLASH
    try:
        return yaml.safe_load(SOURCE_CLASH.read_text(encoding="utf-8")) or DISABLED_CLASH
    except Exception:
        return DISABLED_CLASH


def load_v2ray_template_lines() -> list[str]:
    if not SOURCE_V2RAY.exists():
        return []
    try:
        raw = base64.b64decode(SOURCE_V2RAY.read_text(encoding="utf-8").strip()).decode("utf-8", errors="ignore")
    except Exception:
        return []
    return [line.strip() for line in raw.splitlines() if line.strip()]


def line_belongs_to_server3(line: str) -> bool:
    lower = line.lower()
    return "#server3-" in lower or "@dazhou.bond:" in lower


def line_belongs_to_server4(line: str) -> bool:
    lower = line.lower()
    return "#server4-" in lower or "@xh-ai.cyou:" in lower


def filter_clash_template(account: dict[str, Any]) -> dict[str, Any]:
    if not account_available(account):
        return DISABLED_CLASH
    template = load_clash_template()
    proxies = []
    for proxy in template.get("proxies", []) or []:
        name = str(proxy.get("name") or "")
        if name.startswith(SERVER3_PREFIX) and account["server3_available"]:
            proxies.append(proxy)
        elif name.startswith(SERVER4_PREFIX) and account["server4_available"]:
            proxies.append(proxy)
    if not proxies:
        return DISABLED_CLASH
    allowed = {str(proxy.get("name") or "") for proxy in proxies}
    groups = []
    for group in template.get("proxy-groups", []) or []:
        item = dict(group)
        original = group.get("proxies", []) or []
        item["proxies"] = [name for name in original if name in allowed or name == "DIRECT"]
        if not item["proxies"]:
            item["proxies"] = ["DIRECT"]
        groups.append(item)
    return {
        "proxies": proxies,
        "proxy-groups": groups,
        "rules": template.get("rules", ["MATCH,DIRECT"]),
    }


def filter_v2ray_text(account: dict[str, Any]) -> str:
    usage_node = v2ray_usage_node(account)
    if not account_available(account):
        return encode_v2ray_lines([usage_node])
    kept = []
    for line in load_v2ray_template_lines():
        if line_belongs_to_server3(line) and account["server3_available"]:
            kept.append(line)
        elif line_belongs_to_server4(line) and account["server4_available"]:
            kept.append(line)
        elif not line_belongs_to_server3(line) and not line_belongs_to_server4(line):
            kept.append(line)
    kept.append(usage_node)
    if not kept:
        return encode_v2ray_lines([usage_node])
    return encode_v2ray_lines(kept)


def sync_summary() -> dict[str, Any]:
    clash_mtime = int(SOURCE_CLASH.stat().st_mtime) if SOURCE_CLASH.exists() else 0
    v2ray_mtime = int(SOURCE_V2RAY.stat().st_mtime) if SOURCE_V2RAY.exists() else 0
    return {
        "clash_template_ready": SOURCE_CLASH.exists(),
        "v2ray_template_ready": SOURCE_V2RAY.exists(),
        "clash_template_mtime": clash_mtime,
        "v2ray_template_mtime": v2ray_mtime,
        "quota_mode": "split_evenly_per_server",
    }


@app.post("/api/login")
def login(req: LoginReq):
    if req.token != admin_token():
        raise HTTPException(status_code=401, detail="bad token")
    return {"status": "success", "token": admin_token()}


@app.get("/api/state")
def state(authorization: str = Header("")):
    require_auth(authorization)
    accounts = list_accounts()
    return {
        "status": "success",
        "accounts": accounts,
        "summary": {
            "accounts": len(accounts),
            "enabled": sum(1 for a in accounts if a["enabled"]),
            "published": sum(1 for a in accounts if a["published"]),
        },
        "sync": sync_summary(),
        "tg_servers": list_tg_servers(),
    }


@app.post("/api/accounts")
def save_account(req: AccountIn, authorization: str = Header("")):
    require_auth(authorization)
    now = int(time.time())
    item_id = req.id or new_id()
    slug = normalize_slug(req.slug or new_slug())
    reset_day = min(28, max(1, int(req.reset_day or 1)))
    traffic_reset_mode = normalize_traffic_reset_mode(req.traffic_reset_mode)
    used_s3 = max(0.0, float(req.used_gb_s3 or 0))
    used_s4 = max(0.0, float(req.used_gb_s4 or 0))
    conn = db()
    apply_monthly_reset(conn)
    old = conn.execute("SELECT created_at FROM accounts WHERE id = ?", (item_id,)).fetchone()
    created_at = int(old["created_at"]) if old else now
    conn.execute(
        """INSERT OR REPLACE INTO accounts
        (id, name, enabled, quota_gb, used_gb, used_gb_s3, used_gb_s4, reset_day, reset_cycle, traffic_reset_mode, slug, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            req.name[:80],
            int(req.enabled),
            max(0.0, float(req.quota_gb or 0)),
            round(used_s3 + used_s4, 3),
            used_s3,
            used_s4,
            reset_day,
            current_reset_cycle(reset_day),
            traffic_reset_mode,
            slug,
            (req.notes or "")[:500],
            created_at,
            now,
        ),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": "saved", "accounts": list_accounts(), "sync": sync_summary()}


@app.post("/api/accounts/delete")
def delete_account(req: IdReq, authorization: str = Header("")):
    require_auth(authorization)
    conn = db()
    conn.execute("DELETE FROM accounts WHERE id = ?", (req.id,))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "deleted", "accounts": list_accounts(), "sync": sync_summary()}


@app.post("/api/accounts/rotate")
def rotate_account(req: IdReq, authorization: str = Header("")):
    require_auth(authorization)
    conn = db()
    conn.execute("UPDATE accounts SET slug = ?, updated_at = ? WHERE id = ?", (new_slug(), int(time.time()), req.id))
    conn.commit()
    conn.close()
    return {"status": "success", "message": "rotated", "accounts": list_accounts(), "sync": sync_summary()}


@app.post("/api/accounts/usage")
def usage(req: UsageReq, authorization: str = Header("")):
    require_auth(authorization)
    conn = db()
    apply_monthly_reset(conn)
    row = conn.execute("SELECT used_gb_s3, used_gb_s4 FROM accounts WHERE id = ?", (req.id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="account not found")
    used_s3 = float(row["used_gb_s3"] or 0)
    used_s4 = float(row["used_gb_s4"] or 0)
    if req.used_gb_s3 is not None:
        used_s3 = max(0.0, float(req.used_gb_s3))
    if req.used_gb_s4 is not None:
        used_s4 = max(0.0, float(req.used_gb_s4))
    if req.used_gb is not None and req.used_gb_s3 is None and req.used_gb_s4 is None:
        total = max(0.0, float(req.used_gb))
        used_s3 = round(total / 2.0, 3)
        used_s4 = round(total - used_s3, 3)
    conn.execute(
        "UPDATE accounts SET used_gb = ?, used_gb_s3 = ?, used_gb_s4 = ?, updated_at = ? WHERE id = ?",
        (round(used_s3 + used_s4, 3), used_s3, used_s4, int(time.time()), req.id),
    )
    conn.commit()
    conn.close()
    return {"status": "success", "message": "usage updated", "accounts": list_accounts(), "sync": sync_summary()}


@app.get("/api/tg-accounts")
def tg_accounts(authorization: str = Header("")):
    require_auth(authorization)
    return {"status": "success", "tg_servers": list_tg_servers()}


@app.post("/api/tg-accounts")
def save_tg_account(req: TgAccountReq, authorization: str = Header("")):
    require_auth(authorization)
    server = str(req.server or "").lower()
    tg_server_config(server)
    now = int(time.time())
    item_id = req.id or "tg_" + secrets.token_hex(5)
    user = normalize_panel_tg_user(req.user)
    password = str(req.password or secrets.token_urlsafe(16))[:80]
    reset_day = min(28, max(1, int(req.reset_day or 1)))
    traffic_reset_mode = normalize_traffic_reset_mode(req.traffic_reset_mode)
    conn = db()
    ensure_tg_tables(conn)
    apply_tg_monthly_reset(conn)
    old = conn.execute("SELECT created_at, password FROM tg_accounts WHERE id = ?", (item_id,)).fetchone()
    if not old:
        old = conn.execute("SELECT created_at, password FROM tg_accounts WHERE server = ? AND user = ?", (server, user)).fetchone()
    created_at = int(old["created_at"]) if old else now
    if not req.password and old:
        password = str(old["password"])
    conn.execute(
        """INSERT OR REPLACE INTO tg_accounts
        (id, server, user, password, enabled, quota_gb, used_gb, reset_day, reset_cycle, traffic_reset_mode, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            item_id,
            server,
            user,
            password,
            int(req.enabled),
            max(0.0, float(req.quota_gb or 0)),
            max(0.0, float(req.used_gb or 0)),
            reset_day,
            current_reset_cycle(reset_day),
            traffic_reset_mode,
            (req.notes or "")[:500],
            created_at,
            now,
        ),
    )
    conn.commit()
    sync_tg_xray_from_db(conn)
    conn.close()
    return {"status": "success", "message": "tg account saved", "tg_servers": list_tg_servers()}


@app.post("/api/tg-accounts/rotate")
def rotate_tg_account(req: TgAccountDeleteReq, authorization: str = Header("")):
    require_auth(authorization)
    server = str(req.server or "").lower()
    user = normalize_panel_tg_user(req.user)
    conn = db()
    ensure_tg_tables(conn)
    row = conn.execute("SELECT id FROM tg_accounts WHERE server = ? AND user = ?", (server, user)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="tg account not found")
    conn.execute(
        "UPDATE tg_accounts SET password = ?, updated_at = ? WHERE id = ?",
        (secrets.token_urlsafe(16), int(time.time()), row["id"]),
    )
    conn.commit()
    sync_tg_xray_from_db(conn)
    conn.close()
    return {"status": "success", "message": "tg account rotated", "tg_servers": list_tg_servers()}


@app.post("/api/tg-accounts/delete")
def delete_tg_account(req: TgAccountDeleteReq, authorization: str = Header("")):
    require_auth(authorization)
    server = str(req.server or "").lower()
    user = normalize_panel_tg_user(req.user)
    conn = db()
    ensure_tg_tables(conn)
    conn.execute("DELETE FROM tg_accounts WHERE server = ? AND user = ?", (server, user))
    conn.commit()
    sync_tg_xray_from_db(conn)
    conn.close()
    return {"status": "success", "message": "tg account deleted", "tg_servers": list_tg_servers()}


@app.get("/api/sync")
def sync_state(authorization: str = Header("")):
    require_auth(authorization)
    return {"status": "success", "sync": sync_summary(), "accounts": list_accounts(), "tg_servers": list_tg_servers()}


def _resolve_account_or_404(slug: str) -> dict[str, Any]:
    acct = find_account_by_slug(slug)
    if not acct:
        raise HTTPException(status_code=404, detail="not found")
    return acct


@app.get("/sub/{slug}/clash.yaml")
@app.get("/subs/{slug}/clash.yaml")
def sub_clash(slug: str):
    acct = _resolve_account_or_404(slug)
    return PlainTextResponse(
        yaml.safe_dump(filter_clash_template(acct), allow_unicode=True, sort_keys=False),
        media_type="text/yaml",
        headers=subscription_userinfo_headers(acct),
    )


@app.get("/sub/{slug}/v2ray.txt")
@app.get("/subs/{slug}/v2ray.txt")
def sub_v2ray(slug: str):
    acct = _resolve_account_or_404(slug)
    return PlainTextResponse(filter_v2ray_text(acct), media_type="text/plain", headers=subscription_userinfo_headers(acct))


@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "app" / "index.html").read_text(encoding="utf-8")
