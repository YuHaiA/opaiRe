from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

CONFIG = Path("/usr/local/etc/xray/config.json")
MANAGED_PREFIX = "panel_"


def clean_user(value: Optional[str]) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", str(value or "").strip())
    if not cleaned:
        cleaned = "tg_" + secrets.token_hex(4)
    return cleaned[:40]


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    action = payload.get("action") or "list"
    data = json.loads(CONFIG.read_text())
    inbound = next(
        (item for item in data.get("inbounds", []) if item.get("protocol") == "socks" and item.get("tag") == "tg-socks-in"),
        None,
    )
    if inbound is None:
        inbound = next((item for item in data.get("inbounds", []) if item.get("protocol") == "socks"), None)
    if inbound is None:
        raise SystemExit("tg socks inbound not found")

    settings = inbound.setdefault("settings", {})
    settings["auth"] = "password"
    accounts = settings.setdefault("accounts", [])
    changed = False

    if action == "add":
        user = clean_user(payload.get("user"))
        password = str(payload.get("password") or secrets.token_urlsafe(16))[:80]
        found = next((item for item in accounts if item.get("user") == user), None)
        if found:
            found["pass"] = password
        else:
            accounts.append({"user": user, "pass": password})
        changed = True
    elif action == "delete":
        user = clean_user(payload.get("user"))
        if len(accounts) <= 1:
            raise SystemExit("cannot delete the last tg account")
        new_accounts = [item for item in accounts if item.get("user") != user]
        if len(new_accounts) == len(accounts):
            raise SystemExit("tg account not found")
        settings["accounts"] = accounts = new_accounts
        changed = True
    elif action == "rotate":
        user = clean_user(payload.get("user"))
        found = next((item for item in accounts if item.get("user") == user), None)
        if not found:
            raise SystemExit("tg account not found")
        found["pass"] = str(payload.get("password") or secrets.token_urlsafe(16))[:80]
        changed = True
    elif action == "sync_panel":
        panel_accounts = []
        for item in payload.get("accounts", []) or []:
            user = clean_user(item.get("user"))
            if not user.startswith(MANAGED_PREFIX):
                continue
            panel_accounts.append({"user": user, "pass": str(item.get("password") or "")[:80]})
        accounts = [item for item in accounts if not str(item.get("user") or "").startswith(MANAGED_PREFIX)]
        accounts.extend(panel_accounts)
        settings["accounts"] = accounts
        changed = True
    elif action != "list":
        raise SystemExit("unknown action")

    if changed:
        backup = CONFIG.with_name(f"{CONFIG.name}.bak-tg-panel-{int(time.time())}")
        backup.write_text(CONFIG.read_text())
        CONFIG.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        subprocess.run(["systemctl", "restart", "xray"], check=True)

    visible_accounts = [item for item in accounts if str(item.get("user") or "").startswith(MANAGED_PREFIX)]
    print(json.dumps({"port": inbound.get("port"), "accounts": visible_accounts}, ensure_ascii=False))


if __name__ == "__main__":
    main()
