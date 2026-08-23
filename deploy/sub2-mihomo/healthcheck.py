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
PROXY_HOST = os.environ.get("MIHOMO_PROXY_HOST", "127.0.0.1")
PROXY_PORT = int(os.environ.get("MIHOMO_PROXY_PORT", "7890"))
PROXY_TARGET = os.environ.get("MIHOMO_PROXY_TARGET", "http://127.0.0.1:9090/version")
TIMEOUT = float(os.environ.get("MIHOMO_HEALTH_TIMEOUT", "5"))
FAILURES_BEFORE_RESTART = int(os.environ.get("MIHOMO_HEALTH_FAILURES", "3"))
STATE = Path(os.environ.get("MIHOMO_HEALTH_STATE", "/run/sub2-mihomo-health.json"))


def service_ok() -> bool:
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def controller_ok() -> bool:
    request = urllib.request.Request(CONTROLLER, headers={"Connection": "close"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            response.read(128)
        return True
    except urllib.error.HTTPError as error:
        # A protected controller normally returns 401/403 without a secret;
        # that still proves the listener and HTTP stack are responsive.
        return error.code in {401, 403} or 200 <= error.code < 400
    except (OSError, urllib.error.URLError):
        return False


def proxy_ok() -> bool:
    """Verify that the mixed port accepts and completes an HTTP proxy request."""
    try:
        with socket.create_connection((PROXY_HOST, PROXY_PORT), timeout=TIMEOUT) as connection:
            request = (
                f"GET {PROXY_TARGET} HTTP/1.1\r\n"
                "Host: 127.0.0.1:9090\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            connection.sendall(request)
            response = connection.recv(256)
        status = response.split(b" ", 2)
        # A 4xx/5xx from Mihomo still proves that the proxy parser and
        # request lifecycle are alive (for example, an empty provider pool
        # legitimately returns 502). Only a timeout or malformed response
        # indicates a stuck listener.
        return len(status) >= 2 and status[0].startswith(b"HTTP/") and status[1].isdigit()
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
    checks = {
        "service": service_ok(),
        "controller": controller_ok(),
        "proxy": proxy_ok(),
    }
    if not checks["service"]:
        print(f"Mihomo service is inactive; restarting {SERVICE}")
        subprocess.run(["systemctl", "restart", SERVICE], check=False)
        save_failures(0)
        return 0
    healthy = all(checks.values())
    failures = 0 if healthy else load_failures() + 1
    save_failures(failures)
    if healthy:
        return 0
    if failures < FAILURES_BEFORE_RESTART:
        failed = ",".join(name for name, passed in checks.items() if not passed)
        print(f"Mihomo health check failed: {failed} ({failures}/{FAILURES_BEFORE_RESTART})")
        return 0
    failed = ",".join(name for name, passed in checks.items() if not passed)
    print(f"Mihomo unhealthy ({failed}) for {failures} checks; restarting {SERVICE}")
    subprocess.run(["systemctl", "restart", SERVICE], check=False)
    save_failures(0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
