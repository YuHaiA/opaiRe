#!/usr/bin/env python3
"""Recover Mihomo when its process is alive but its controller is unresponsive."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


SERVICE = os.environ.get("MIHOMO_SERVICE", "sub2-mihomo")
CONTROLLER = os.environ.get("MIHOMO_CONTROLLER", "http://127.0.0.1:9090/version")
TIMEOUT = float(os.environ.get("MIHOMO_HEALTH_TIMEOUT", "5"))
FAILURES_BEFORE_RESTART = int(os.environ.get("MIHOMO_HEALTH_FAILURES", "3"))
STATE = Path(os.environ.get("MIHOMO_HEALTH_STATE", "/run/sub2-mihomo-health.json"))


def controller_ok() -> bool:
    request = urllib.request.Request(CONTROLLER, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read(128)
        return True
    except urllib.error.HTTPError:
        # A protected controller normally returns 401/403 without a secret;
        # that still proves the listener and HTTP stack are responsive.
        return True
    except (OSError, urllib.error.URLError):
        return False


def listener_ok() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 7890), timeout=TIMEOUT):
            return True
    except OSError:
        return False


def load_failures() -> int:
    try:
        return max(0, int(json.loads(STATE.read_text(encoding="utf-8")).get("failures", 0)))
    except (OSError, ValueError, TypeError):
        return 0


def save_failures(value: int) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps({"failures": value, "checked_at": int(time.time())}), encoding="utf-8")
    os.replace(temporary, STATE)


def main() -> int:
    healthy = controller_ok() and listener_ok()
    failures = 0 if healthy else load_failures() + 1
    save_failures(failures)
    if healthy:
        return 0
    if failures < FAILURES_BEFORE_RESTART:
        print(f"Mihomo health check failed ({failures}/{FAILURES_BEFORE_RESTART})")
        return 0
    print(f"Mihomo unhealthy for {failures} checks; restarting {SERVICE}")
    subprocess.run(["systemctl", "restart", SERVICE], check=False)
    save_failures(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
