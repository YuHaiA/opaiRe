#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mihomo subscription manager + simple Web panel (local-style UX)."""

from __future__ import annotations

import argparse
import atexit
import gzip
import ipaddress
import json
import os
import random
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import ProxyHandler, Request, build_opener, urlopen

import yaml

from v2ray_convert import detect_and_parse_subscription, proxies_to_provider_yaml


ROOT = Path(__file__).resolve().parent
BIN = ROOT / "bin" / ("mihomo.exe" if os.name == "nt" else "mihomo")
SERVICE_NAME = os.environ.get("MIHOMO_SERVICE", "sub2-mihomo")
PUBLIC_BASE = os.environ.get("MIHOMO_PUBLIC_BASE", "https://tupai.cyou/mihomo").rstrip("/")
MANAGED_BY_SYSTEMD = os.environ.get("MIHOMO_SYSTEMD", "1" if os.name != "nt" else "0") == "1"
PRESERVE_CONFIG = os.environ.get("MIHOMO_PRESERVE_CONFIG", "0") == "1"
PROXY_GROUP = os.environ.get("MIHOMO_PROXY_GROUP", "PROXY").strip() or "PROXY"
DASHBOARD_ENABLED = os.environ.get("MIHOMO_DASHBOARD_ENABLED", "1") != "0"
CONFIG = ROOT / "config.yaml"
PROVIDER = ROOT / "providers" / "subscription.yaml"
STATE_DIR = ROOT / "state"
SETTINGS_FILE = STATE_DIR / "settings.json"
SOURCE_FILE = STATE_DIR / "subscription.txt"
SECRET_FILE = STATE_DIR / "controller.secret"
PID_FILE = STATE_DIR / "mihomo.pid"
MANAGER_PID_FILE = STATE_DIR / "manager.pid"
DELAYS_FILE = STATE_DIR / "delays.json"
EGRESS_STATE_FILE = STATE_DIR / "egress-pool.json"
LOG_FILE = ROOT / "logs" / "mihomo.log"
ERR_FILE = ROOT / "logs" / "mihomo.err.log"
WEB_DIR = ROOT / "web"

DEFAULT_SETTINGS: dict[str, Any] = {
    "mixed_port": 7890,
    "socks_port": 7891,
    "controller_host": "127.0.0.1",
    "controller_port": 9090,
    "web_host": "127.0.0.1",
    "web_port": 19099,
    "allow_lan": True,
    "subscription_kind": "",
    "node_count": 0,
    "updated_at": "",
    "auto_update_minutes": 60,
    "node_test_minutes": 5,
    "egress_pool_enabled": True,
    "egress_count": 10,
    "egress_base_port": 7901,
    "egress_auto_rotate_enabled": True,
    "egress_rotate_minutes": 30,
    "egress_reuse_cooldown_minutes": 60,
    "max_accounts_per_egress": 2,
    "account_reconcile_minutes": 1,
    "sub2api_deploy_dir": "/home/ec2-user/sub2api-deploy",
    "sub2api_postgres_container": "sub2api-postgres",
    "public_base": "https://tupai.cyou/mihomo",
}

_CORE_LOCK = threading.RLock()
_POOL_LOCK = threading.RLock()
_HEALTH_LOCK = threading.Lock()
_CORE_PROCESS: subprocess.Popen[Any] | None = None

EGRESS_COUNT = 10
DEFAULT_MAX_ACCOUNTS_PER_EGRESS = 2
MAX_ACCOUNTS_PER_EGRESS_LIMIT = 20
NODE_TEST_TARGETS = (
    "https://api.x.ai/v1/models",
    "https://api.openai.com/v1/models",
)
EGRESS_IP_TEST_URL = "https://api.ipify.org?format=json"


def normalized_settings(value: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    if value:
        settings.update(value)
    settings["egress_count"] = EGRESS_COUNT
    for key, default, minimum, maximum in (
        ("auto_update_minutes", 60, 0, 10080),
        ("node_test_minutes", 5, 0, 1440),
        ("egress_base_port", 7901, 1024, 65526),
        ("egress_rotate_minutes", 30, 0, 10080),
        ("egress_reuse_cooldown_minutes", 60, 0, 1440),
        ("max_accounts_per_egress", DEFAULT_MAX_ACCOUNTS_PER_EGRESS, 1, MAX_ACCOUNTS_PER_EGRESS_LIMIT),
        ("account_reconcile_minutes", 1, 0, 1440),
    ):
        try:
            number = int(settings.get(key, default))
        except (TypeError, ValueError):
            number = default
        settings[key] = min(max(number, minimum), maximum)
    settings["egress_pool_enabled"] = bool(settings.get("egress_pool_enabled", True))
    settings["egress_auto_rotate_enabled"] = bool(settings.get("egress_auto_rotate_enabled", True))
    return settings


class ManagerError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def load_settings() -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if SETTINGS_FILE.exists():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update(loaded)
        except Exception:
            pass
    return normalized_settings(settings)


def save_settings(settings: dict[str, Any]) -> None:
    atomic_write(SETTINGS_FILE, json.dumps(normalized_settings(settings), ensure_ascii=False, indent=2) + "\n")


def egress_group_name(index: int) -> str:
    return f"EGRESS-{index:02d}"


def egress_listener_name(index: int) -> str:
    return f"sub2-egress-{index:02d}"


def egress_proxy_name(index: int) -> str:
    return f"mihomo-egress-{index:02d}"


def load_egress_state() -> dict[str, Any]:
    if EGRESS_STATE_FILE.exists():
        try:
            value = json.loads(EGRESS_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                return value
        except Exception:
            pass
    return {
        "cursor": 0,
        "last_rotated_at": "",
        "assignments": {},
        "exit_ips": {},
        "node_last_used_at": {},
        "ip_last_used_at": {},
    }


def save_egress_state(state: dict[str, Any]) -> None:
    atomic_write(EGRESS_STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def _state_map(state: dict[str, Any], key: str) -> dict[str, str]:
    value = state.get(key)
    if not isinstance(value, dict):
        value = {}
        state[key] = value
    return value


def _recent_history_values(
    history: dict[str, str], cooldown_minutes: int, *, now: datetime | None = None
) -> set[str]:
    if cooldown_minutes <= 0:
        return set()
    now = now or datetime.now(timezone.utc).astimezone()
    cutoff = now - timedelta(minutes=cooldown_minutes)
    recent: set[str] = set()
    for value, raw_timestamp in history.items():
        try:
            timestamp = datetime.fromisoformat(str(raw_timestamp))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            if timestamp >= cutoff:
                recent.add(str(value))
        except (TypeError, ValueError):
            continue
    return recent


def _record_egress_usage(
    state: dict[str, Any], node: str, exit_ip: str, *, timestamp: str | None = None
) -> None:
    timestamp = timestamp or utc_now()
    if node:
        _state_map(state, "node_last_used_at")[node] = timestamp
    if exit_ip:
        _state_map(state, "ip_last_used_at")[exit_ip] = timestamp


def _prune_egress_history(state: dict[str, Any], cooldown_minutes: int) -> None:
    keep_minutes = max(cooldown_minutes * 2, 1440)
    cutoff = datetime.now(timezone.utc).astimezone() - timedelta(minutes=keep_minutes)
    for key in ("node_last_used_at", "ip_last_used_at"):
        history = _state_map(state, key)
        retained: dict[str, str] = {}
        for value, raw_timestamp in history.items():
            try:
                timestamp = datetime.fromisoformat(str(raw_timestamp))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                if timestamp >= cutoff:
                    retained[str(value)] = str(raw_timestamp)
            except (TypeError, ValueError):
                continue
        state[key] = retained


def controller_secret() -> str:
    # Prefer live config secret so systemd core and panel stay in sync.
    if CONFIG.exists():
        try:
            doc = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
            value = str(doc.get("secret") or "").strip()
            if value:
                if not SECRET_FILE.exists() or SECRET_FILE.read_text(encoding="utf-8").strip() != value:
                    atomic_write(SECRET_FILE, value + "\n")
                return value
        except Exception:
            pass
    if SECRET_FILE.exists():
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    cred = ROOT / "CREDENTIALS.txt"
    if cred.exists():
        for line in cred.read_text(encoding="utf-8").splitlines():
            if line.startswith("controller_secret="):
                value = line.split("=", 1)[1].strip()
                if value:
                    atomic_write(SECRET_FILE, value + "\n")
                    return value
    value = secrets.token_urlsafe(32)
    atomic_write(SECRET_FILE, value + "\n")
    return value


def config_document(settings: dict[str, Any]) -> dict[str, Any]:
    secret = controller_secret()
    allow_lan = bool(settings.get("allow_lan", True))
    groups = [
        {
            "name": "STICKY",
            "type": "fallback",
            "use": ["subscription"],
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "lazy": True,
        },
        {
            "name": "AUTO-URLTEST",
            "type": "url-test",
            "use": ["subscription"],
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "tolerance": 50,
            "lazy": True,
        },
        {
            "name": "AUTO-BALANCE",
            "type": "load-balance",
            "strategy": "round-robin",
            "use": ["subscription"],
            "url": "https://www.gstatic.com/generate_204",
            "interval": 300,
            "lazy": True,
        },
        {
            "name": "PROXY",
            "type": "select",
            "use": ["subscription"],
            "proxies": ["STICKY", "AUTO-URLTEST", "AUTO-BALANCE"],
        },
    ]
    listeners: list[dict[str, Any]] = []
    if bool(settings.get("egress_pool_enabled", True)):
        base_port = int(settings.get("egress_base_port") or 7901)
        for index in range(1, EGRESS_COUNT + 1):
            group = egress_group_name(index)
            groups.append({"name": group, "type": "select", "use": ["subscription"]})
            listeners.append(
                {
                    "name": egress_listener_name(index),
                    "type": "mixed",
                    "port": base_port + index - 1,
                    "listen": "0.0.0.0" if allow_lan else "127.0.0.1",
                    "proxy": group,
                }
            )

    document = {
        "mixed-port": int(settings["mixed_port"]),
        "socks-port": int(settings.get("socks_port") or 7891),
        "allow-lan": allow_lan,
        "bind-address": "*" if allow_lan else "127.0.0.1",
        "mode": "rule",
        "log-level": "warning",
        "ipv6": False,
        "find-process-mode": "off",
        "external-controller": f"{settings['controller_host']}:{int(settings['controller_port'])}",
        "secret": secret,
        "external-ui": "ui",
        "unified-delay": True,
        "tcp-concurrent": True,
        "geo-auto-update": False,
        "profile": {"store-selected": True, "store-fake-ip": False},
        "proxy-providers": {
            "subscription": {
                "type": "file",
                "path": "providers/subscription.yaml",
                "health-check": {
                    "enable": True,
                    "url": "https://www.gstatic.com/generate_204",
                    "interval": 600,
                    "lazy": True,
                },
            }
        },
        "proxy-groups": groups,
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "MATCH,PROXY",
        ],
    }
    if listeners:
        document["listeners"] = listeners
    return document


def write_config(settings: dict[str, Any] | None = None) -> None:
    settings = settings or load_settings()
    content = yaml.safe_dump(config_document(settings), allow_unicode=True, sort_keys=False)
    atomic_write(CONFIG, content)


def sync_config(settings: dict[str, Any] | None = None) -> None:
    if PRESERVE_CONFIG:
        if not CONFIG.exists():
            raise ManagerError(f"保留配置模式下未找到 Mihomo 配置: {CONFIG}")
        return
    write_config(settings)


def ensure_layout() -> dict[str, Any]:
    for path in (STATE_DIR, PROVIDER.parent, LOG_FILE.parent, WEB_DIR):
        path.mkdir(parents=True, exist_ok=True)
    legacy = ROOT / "providers" / "sub.yaml"
    if legacy.exists() and not PROVIDER.exists():
        PROVIDER.write_bytes(legacy.read_bytes())
    settings = load_settings()
    if PUBLIC_BASE:
        settings["public_base"] = PUBLIC_BASE
    if not PROVIDER.exists():
        atomic_write(PROVIDER, "proxies: []\n")
    sync_config(settings)
    save_settings(settings)
    return settings



def mask_source(source: str) -> str:
    source = (source or "").strip()
    if not source:
        return "未配置"
    if "\n" in source or "\r" in source:
        return f"本地分享链接（{len([line for line in source.splitlines() if line.strip()])} 行）"
    try:
        parsed = urlparse(source)
    except Exception:
        return "已配置"
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}/***"
    return f"已配置（长度 {len(source)}）"


def fetch_subscription(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "clash-verge/v2.3.1",
            "Accept": "text/yaml,text/plain,application/octet-stream,*/*",
        },
    )
    try:
        with urlopen(request, timeout=35) as response:
            data = response.read()
            if str(response.headers.get("Content-Encoding", "")).lower() == "gzip":
                data = gzip.decompress(data)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ManagerError(f"订阅下载失败: {exc}") from exc
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def validate_config() -> str:
    if not BIN.exists():
        raise ManagerError(f"未找到 Mihomo 核心: {BIN}")
    try:
        result = subprocess.run(
            [str(BIN), "-t", "-d", str(ROOT), "-f", str(CONFIG)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagerError("Mihomo 配置校验超过 60 秒，已取消本次操作") from exc
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0:
        raise ManagerError("Mihomo 配置校验失败: " + output[-1200:].strip())
    return output.strip()


def update_subscription(source: str | None = None) -> dict[str, Any]:
    ensure_layout()
    if source is None:
        source = SOURCE_FILE.read_text(encoding="utf-8").strip()
    source = (source or "").strip()
    if not source:
        raise ManagerError("请先填写订阅 URL 或 V2Ray 分享链接")

    raw = fetch_subscription(source) if source.startswith(("http://", "https://")) and "\n" not in source else source
    parsed = detect_and_parse_subscription(raw)
    proxies = parsed.get("proxies") or []
    if not proxies:
        raise ManagerError(f"未识别到可用节点（类型: {parsed.get('kind') or 'unknown'}）")

    previous_provider = PROVIDER.read_bytes() if PROVIDER.exists() else None
    previous_source = SOURCE_FILE.read_text(encoding="utf-8") if SOURCE_FILE.exists() else ""
    settings = load_settings()
    updated_settings = dict(settings)
    try:
        atomic_write(PROVIDER, proxies_to_provider_yaml(proxies))
        atomic_write(SOURCE_FILE, source + ("\n" if not source.endswith("\n") else ""))
        updated_settings.update(
            {
                "subscription_kind": parsed.get("kind") or "unknown",
                "node_count": len(proxies),
                "updated_at": utc_now(),
            }
        )
        sync_config(updated_settings)
        validation = validate_config()
        save_settings(updated_settings)
        atomic_write(DELAYS_FILE, json.dumps({"tested_at": "", "rows": {}}, ensure_ascii=False))
    except Exception:
        if previous_provider is None:
            PROVIDER.unlink(missing_ok=True)
        else:
            PROVIDER.write_bytes(previous_provider)
        atomic_write(SOURCE_FILE, previous_source)
        save_settings(settings)
        sync_config(settings)
        raise

    reloaded = False
    if controller_online():
        try:
            reload_core()
            if bool(updated_settings.get("egress_pool_enabled", True)):
                test_nodes(repair=True)
            reloaded = True
        except Exception:
            reloaded = False
    return {
        "ok": True,
        "kind": updated_settings["subscription_kind"],
        "count": updated_settings["node_count"],
        "updated_at": updated_settings["updated_at"],
        "sample": parsed.get("sample") or [],
        "reloaded": reloaded,
        "validation": validation[-300:],
    }


def controller_base(settings: dict[str, Any] | None = None) -> str:
    settings = settings or load_settings()
    return f"http://{settings['controller_host']}:{int(settings['controller_port'])}"


def controller_request(path: str, *, method: str = "GET", payload: Any = None, timeout: float = 5.0) -> Any:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        controller_base() + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {controller_secret()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:300]
        raise ManagerError(f"Mihomo API {exc.code}: {text}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ManagerError(f"无法连接 Mihomo 控制器: {exc}") from exc


def controller_online() -> bool:
    try:
        controller_request("/version", timeout=1.5)
        return True
    except Exception:
        return False


def reload_core() -> dict[str, Any]:
    sync_config()
    validate_config()
    return controller_request("/configs?force=true", method="PUT", payload={"path": str(CONFIG)}, timeout=10)


def owned_process() -> subprocess.Popen[Any] | None:
    """Return only the Mihomo process created by this manager instance."""
    global _CORE_PROCESS
    process = _CORE_PROCESS
    if process is None:
        return None
    if process.poll() is None:
        return process
    _CORE_PROCESS = None
    PID_FILE.unlink(missing_ok=True)
    return None


def owned_pid() -> int | None:
    if MANAGED_BY_SYSTEMD:
        return service_main_pid()
    process = owned_process()
    return process.pid if process is not None else None


def terminate_owned_process(process: subprocess.Popen[Any]) -> None:
    """Stop the explicit child handle without scanning or killing unrelated processes."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _ctl(*args: str, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    """Talk to mihomo via thin root helper (preferred) or raw systemctl."""
    helper = ROOT / "mihomoctl"
    commands: list[list[str]] = []
    if helper.exists():
        commands.append(["sudo", "-n", str(helper), *args])
        commands.append([str(helper), *args])
    # fallback raw systemctl mapping
    if args and args[0] in {"start", "stop", "restart", "is-active"}:
        commands.append(["systemctl", args[0], SERVICE_NAME])
        commands.append(["sudo", "-n", "systemctl", args[0], SERVICE_NAME])
    elif args and args[0] == "pid":
        commands.append(["systemctl", "show", "-p", "MainPID", "--value", SERVICE_NAME])
        commands.append(["sudo", "-n", "systemctl", "show", "-p", "MainPID", "--value", SERVICE_NAME])
    elif args and args[0] == "logs":
        n = args[1] if len(args) > 1 else "80"
        commands.append(["journalctl", "-u", SERVICE_NAME, "-n", str(n), "--no-pager"])
        commands.append(["sudo", "-n", "journalctl", "-u", SERVICE_NAME, "-n", str(n), "--no-pager"])
    last: subprocess.CompletedProcess[str] | None = None
    for cmd in commands:
        try:
            last = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except Exception as exc:
            last = subprocess.CompletedProcess(cmd, 1, "", str(exc))
            continue
        if last.returncode == 0 or args[:1] == ["is-active"]:
            return last
        err = (last.stderr or "") + (last.stdout or "")
        if "Permission denied" in err or "Interactive authentication required" in err:
            continue
        # try next candidate on failure
    assert last is not None
    return last


def service_active() -> bool:
    if not MANAGED_BY_SYSTEMD:
        return False
    try:
        result = _ctl("is-active", timeout=5)
        return result.returncode == 0 and result.stdout.strip() == "active"
    except Exception:
        return False


def service_main_pid() -> int | None:
    if not MANAGED_BY_SYSTEMD:
        return None
    try:
        result = _ctl("pid", timeout=5)
        pid = int((result.stdout or "0").strip() or "0")
        return pid if pid > 0 else None
    except Exception:
        return None


def start_core() -> dict[str, Any]:
    global _CORE_PROCESS
    ensure_layout()
    with _CORE_LOCK:
        if controller_online():
            return {
                "ok": True,
                "already_running": True,
                "pid": service_main_pid() or owned_pid(),
                "owned": False if MANAGED_BY_SYSTEMD else owned_process() is not None,
            }

        if MANAGED_BY_SYSTEMD:
            sync_config()
            validate_config()
            result = _ctl("start")
            if result.returncode != 0:
                detail = ((result.stderr or "") + (result.stdout or "")).strip()
                raise ManagerError(f"systemctl 启动失败: {detail or result.returncode}")
            deadline = time.time() + 15
            while time.time() < deadline:
                if controller_online():
                    return {
                        "ok": True,
                        "pid": service_main_pid(),
                        "already_running": False,
                        "owned": False,
                        "via": "systemd",
                    }
                time.sleep(0.35)
            raise ManagerError(f"Mihomo 控制器 15 秒内未就绪，请查看 journalctl -u {SERVICE_NAME}")

        validate_config()
        if not BIN.exists():
            raise ManagerError(f"未找到 Mihomo 核心: {BIN}")

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        out = LOG_FILE.open("ab")
        err = ERR_FILE.open("ab")
        try:
            process = subprocess.Popen(
                [str(BIN), "-d", str(ROOT), "-f", str(CONFIG)],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
            )
            _CORE_PROCESS = process
        finally:
            out.close()
            err.close()
        atomic_write(PID_FILE, f"{process.pid}\n")

        deadline = time.time() + 15
        while time.time() < deadline:
            if process.poll() is not None:
                _CORE_PROCESS = None
                PID_FILE.unlink(missing_ok=True)
                tail = tail_logs(40)
                raise ManagerError(f"Mihomo 启动失败，退出码 {process.returncode}\n{tail}")
            if controller_online():
                return {"ok": True, "pid": process.pid, "already_running": False, "owned": True}
            time.sleep(0.35)
        terminate_owned_process(process)
        _CORE_PROCESS = None
        PID_FILE.unlink(missing_ok=True)
        raise ManagerError("Mihomo 控制器 15 秒内未就绪，已停止本次启动的核心，请查看日志")


def stop_core() -> dict[str, Any]:
    global _CORE_PROCESS
    with _CORE_LOCK:
        if MANAGED_BY_SYSTEMD:
            if not service_active() and not controller_online():
                return {"ok": True, "already_stopped": True, "via": "systemd"}
            result = _ctl("stop")
            if result.returncode != 0:
                detail = ((result.stderr or "") + (result.stdout or "")).strip()
                raise ManagerError(f"systemctl 停止失败: {detail or result.returncode}")
            deadline = time.time() + 10
            while time.time() < deadline and controller_online():
                time.sleep(0.2)
            return {"ok": True, "stopped": True, "via": "systemd"}

        process = owned_process()
        if process is None:
            if controller_online():
                raise ManagerError("核心不是由当前管理器启动，已拒绝跨进程强制结束")
            PID_FILE.unlink(missing_ok=True)
            return {"ok": True, "already_stopped": True}
        terminate_owned_process(process)
        _CORE_PROCESS = None
        PID_FILE.unlink(missing_ok=True)
        return {"ok": True, "stopped": True, "pid": process.pid}


def select_proxy(name: str, group: str = "PROXY") -> dict[str, Any]:
    if not name:
        raise ManagerError("节点名称不能为空")
    controller_request(f"/proxies/{quote(group, safe='')}", method="PUT", payload={"name": name})
    return {"ok": True, "group": group, "name": name}


def probe_egress_ip(index: int, timeout: float = 8.0) -> str:
    if index < 1 or index > EGRESS_COUNT:
        raise ManagerError(f"出口编号必须在 1-{EGRESS_COUNT} 之间")
    settings = load_settings()
    port = int(settings["egress_base_port"]) + index - 1
    proxy_url = f"http://127.0.0.1:{port}"
    opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    request = Request(EGRESS_IP_TEST_URL, headers={"User-Agent": "sub2-mihomo/1.0"})
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = response.read(512).decode("utf-8", errors="replace").strip()
        value = json.loads(payload)
        exit_ip = str(value.get("ip") or "").strip() if isinstance(value, dict) else ""
        parsed = ipaddress.ip_address(exit_ip)
        if not parsed.is_global:
            raise ValueError("not a public address")
        return str(parsed)
    except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
        raise ManagerError(f"出口 {index:02d} 公网 IP 探测失败") from exc


def probe_current_egress_ips() -> dict[str, str]:
    results = {egress_group_name(index): "" for index in range(1, EGRESS_COUNT + 1)}
    with ThreadPoolExecutor(max_workers=EGRESS_COUNT) as executor:
        futures = {
            executor.submit(probe_egress_ip, index): index
            for index in range(1, EGRESS_COUNT + 1)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[egress_group_name(index)] = future.result()
            except ManagerError:
                pass
    return results


def load_delay_cache() -> dict[str, Any]:
    if not DELAYS_FILE.exists():
        return {"tested_at": "", "rows": {}}
    try:
        value = json.loads(DELAYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tested_at": "", "rows": {}}
    return value if isinstance(value, dict) else {"tested_at": "", "rows": {}}


def cached_healthy_node_names(names: list[str] | None = None) -> list[str]:
    names = names if names is not None else provider_node_names()
    cache = load_delay_cache()
    rows = cache.get("rows") if isinstance(cache.get("rows"), dict) else {}
    healthy: list[str] = []
    for name in names:
        row = rows.get(name)
        if not isinstance(row, dict) or row.get("ok") is not True:
            continue
        try:
            delay = int(row.get("delay") or 0)
        except (TypeError, ValueError):
            delay = 0
        if delay > 0:
            healthy.append(name)
    return healthy


def node_test_due(settings: dict[str, Any] | None = None) -> bool:
    settings = settings or load_settings()
    minutes = int(settings.get("node_test_minutes") or 0)
    if minutes <= 0:
        return False
    tested_at = str(load_delay_cache().get("tested_at") or "")
    if not tested_at:
        return True
    try:
        tested = datetime.fromisoformat(tested_at)
        age = datetime.now(tested.tzinfo or timezone.utc) - tested
        return age.total_seconds() >= minutes * 60
    except Exception:
        return True


def provider_node_names() -> list[str]:
    data = controller_request("/providers/proxies", timeout=10)
    providers = data.get("providers") if isinstance(data, dict) else {}
    providers = providers if isinstance(providers, dict) else {}
    preferred = providers.get("subscription")
    selected = preferred if isinstance(preferred, dict) else None
    candidates = [selected] if selected is not None else [p for p in providers.values() if isinstance(p, dict)]
    names: list[str] = []
    seen: set[str] = set()
    for provider in candidates:
        for item in provider.get("proxies") or []:
            name = str(item.get("name") or "") if isinstance(item, dict) else ""
            if name and name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key.strip()] = value
    return values


def sub2api_psql(sql: str, *, timeout: float = 30.0) -> str:
    settings = load_settings()
    deploy_dir = Path(str(settings.get("sub2api_deploy_dir") or ""))
    env = _parse_env_file(deploy_dir / ".env")
    password = env.get("POSTGRES_PASSWORD", "")
    if not password:
        raise ManagerError("未能从 Sub2API .env 读取数据库密码")
    container = str(settings.get("sub2api_postgres_container") or "sub2api-postgres")
    command = [
        "docker", "exec", "-i", "-e", f"PGPASSWORD={password}", container,
        "psql", "-X", "-v", "ON_ERROR_STOP=1", "-U", env.get("POSTGRES_USER", "sub2api"),
        "-d", env.get("POSTGRES_DB", "sub2api"), "-At",
    ]
    try:
        result = subprocess.run(
            command,
            input=sql,
            cwd=str(deploy_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ManagerError(f"连接 Sub2API 数据库失败: {exc}") from exc
    if result.returncode != 0:
        raise ManagerError("Sub2API 数据库操作失败: " + (result.stderr or result.stdout)[-800:].strip())
    return result.stdout


def sub2api_json_rows(query: str) -> list[dict[str, Any]]:
    output = sub2api_psql(query.rstrip().rstrip(";") + ";\n")
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def ensure_sub2api_egress_proxies() -> list[dict[str, Any]]:
    settings = load_settings()
    base_port = int(settings["egress_base_port"])
    statements = ["BEGIN;"]
    for index in range(1, EGRESS_COUNT + 1):
        name = egress_proxy_name(index)
        port = base_port + index - 1
        statements.append(
            "INSERT INTO proxies (name, protocol, host, port, status, fallback_mode) "
            f"SELECT '{name}', 'http', '172.20.0.1', {port}, 'active', 'none' "
            f"WHERE NOT EXISTS (SELECT 1 FROM proxies WHERE name='{name}' AND deleted_at IS NULL);"
        )
        statements.append(
            f"UPDATE proxies SET protocol='http', host='172.20.0.1', port={port}, "
            f"status='active', fallback_mode='none', updated_at=now() WHERE name='{name}' AND deleted_at IS NULL;"
        )
    statements.append("COMMIT;")
    sub2api_psql("\n".join(statements))
    names = ",".join(f"'{egress_proxy_name(i)}'" for i in range(1, EGRESS_COUNT + 1))
    return sub2api_json_rows(
        "SELECT json_build_object('id',id,'name',name,'port',port,'status',status) "
        f"FROM proxies WHERE deleted_at IS NULL AND name IN ({names}) ORDER BY name"
    )


def _timestamp_is_future(value: Any) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        now = datetime.now(parsed.tzinfo or timezone.utc)
        return parsed > now
    except Exception:
        return False


def _account_healthy(account: dict[str, Any]) -> bool:
    if str(account.get("status") or "") != "active":
        return False
    if _timestamp_is_future(account.get("temp_unschedulable_until")):
        return False
    expires_at = account.get("expires_at")
    if expires_at:
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
            if parsed <= datetime.now(parsed.tzinfo or timezone.utc):
                return False
        except Exception:
            pass
    return True


def reconcile_accounts() -> dict[str, Any]:
    """Keep ten fixed egress rows and the configured schedulable Grok account capacity on each."""
    with _POOL_LOCK:
        max_accounts_per_egress = int(load_settings()["max_accounts_per_egress"])
        proxies = ensure_sub2api_egress_proxies()
        if len(proxies) != EGRESS_COUNT:
            raise ManagerError(f"固定出口创建不完整: {len(proxies)}/{EGRESS_COUNT}")
        proxy_by_id = {int(row["id"]): row for row in proxies}
        slots = {int(row["id"]): [] for row in proxies}
        accounts = sub2api_json_rows(
            "SELECT json_build_object("
            "'id',id,'name',name,'status',status,'schedulable',schedulable,'proxy_id',proxy_id,"
            "'extra',extra,'last_used_at',last_used_at,'temp_unschedulable_until',temp_unschedulable_until,"
            "'expires_at',expires_at) FROM accounts "
            "WHERE deleted_at IS NULL AND platform='grok' ORDER BY last_used_at NULLS FIRST, id"
        )
        selected: dict[int, int] = {}
        candidates: list[dict[str, Any]] = []
        externally_disabled: set[int] = set()

        for account in accounts:
            account_id = int(account["id"])
            extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
            managed = bool(extra.get("mihomo_pool_managed"))
            standby = bool(extra.get("mihomo_pool_standby"))
            proxy_id = int(account["proxy_id"]) if account.get("proxy_id") is not None else None
            healthy = _account_healthy(account)
            if managed and not standby and not bool(account.get("schedulable")):
                externally_disabled.add(account_id)
                continue
            if healthy and bool(account.get("schedulable")) and proxy_id in slots and len(slots[proxy_id]) < max_accounts_per_egress:
                slots[proxy_id].append(account)
                selected[account_id] = proxy_id
                continue
            if healthy and (bool(account.get("schedulable")) or (managed and standby)):
                candidates.append(account)

        candidate_index = 0
        while candidate_index < len(candidates):
            available = [proxy_id for proxy_id, bound in slots.items() if len(bound) < max_accounts_per_egress]
            if not available:
                break
            proxy_id = min(available, key=lambda value: (len(slots[value]), proxy_by_id[value]["name"]))
            account = candidates[candidate_index]
            candidate_index += 1
            account_id = int(account["id"])
            slots[proxy_id].append(account)
            selected[account_id] = proxy_id

        candidate_ids = {int(account["id"]) for account in candidates}
        changed_ids: list[int] = []
        managed_account_count = 0
        statements = ["BEGIN;"]
        for account in accounts:
            account_id = int(account["id"])
            extra = account.get("extra") if isinstance(account.get("extra"), dict) else {}
            already_managed = bool(extra.get("mihomo_pool_managed"))
            target_proxy = selected.get(account_id)
            old_proxy = int(account["proxy_id"]) if account.get("proxy_id") is not None else None
            old_schedulable = bool(account.get("schedulable"))
            if account_id in externally_disabled:
                target_schedulable = False
                standby = False
                disabled = True
            elif target_proxy is not None:
                target_schedulable = True
                standby = False
                disabled = False
            else:
                target_schedulable = False
                standby = True
                disabled = False
            should_manage = already_managed or target_proxy is not None or account_id in candidate_ids
            if not should_manage and account_id not in externally_disabled:
                continue
            managed_account_count += 1
            marker_changed = (
                extra.get("mihomo_pool_managed") is not True
                or extra.get("mihomo_pool_standby") is not standby
                or bool(extra.get("mihomo_pool_externally_disabled")) is not disabled
            )
            if old_proxy != target_proxy or old_schedulable != target_schedulable or marker_changed:
                changed_ids.append(account_id)
                proxy_sql = "NULL" if target_proxy is None else str(target_proxy)
                statements.append(
                    "UPDATE accounts SET "
                    f"proxy_id={proxy_sql}, schedulable={'true' if target_schedulable else 'false'}, "
                    "extra=jsonb_set(jsonb_set(jsonb_set(COALESCE(extra,'{}'::jsonb),"
                    "'{mihomo_pool_managed}','true'::jsonb,true),"
                    f"'{{mihomo_pool_standby}}','{'true' if standby else 'false'}'::jsonb,true),"
                    f"'{{mihomo_pool_externally_disabled}}','{'true' if disabled else 'false'}'::jsonb,true), "
                    f"updated_at=now() WHERE id={account_id};"
                )
        if changed_ids:
            payload = json.dumps({"account_ids": changed_ids}, separators=(",", ":"))
            statements.append(
                "INSERT INTO scheduler_outbox (event_type, payload) "
                f"VALUES ('account_bulk_changed', '{payload}'::jsonb);"
            )
        statements.append("COMMIT;")
        sub2api_psql("\n".join(statements), timeout=60)

        summary_rows = []
        for proxy in proxies:
            proxy_id = int(proxy["id"])
            bound = slots[proxy_id]
            summary_rows.append(
                {
                    "id": proxy_id,
                    "name": proxy["name"],
                    "port": int(proxy["port"]),
                    "account_count": len(bound),
                    "accounts": [{"id": int(item["id"]), "name": item.get("name") or ""} for item in bound],
                }
            )
        state = load_egress_state()
        state["accounts_reconciled_at"] = utc_now()
        state["account_summary"] = summary_rows
        state["standby_accounts"] = max(0, managed_account_count - len(selected) - len(externally_disabled))
        state["externally_disabled_accounts"] = len(externally_disabled)
        save_egress_state(state)
        return {
            "ok": True,
            "egress_count": EGRESS_COUNT,
            "online_accounts": len(selected),
            "standby_accounts": state["standby_accounts"],
            "externally_disabled_accounts": len(externally_disabled),
            "changed_accounts": len(changed_ids),
            "rows": summary_rows,
        }


def current_egress_assignments(state: dict[str, Any] | None = None) -> dict[str, str]:
    state = state or load_egress_state()
    saved = state.get("assignments") if isinstance(state.get("assignments"), dict) else {}
    assignments: dict[str, str] = {}
    try:
        response = controller_request("/proxies", timeout=10)
        proxies = response.get("proxies") if isinstance(response, dict) else {}
        proxies = proxies if isinstance(proxies, dict) else {}
        for index in range(1, EGRESS_COUNT + 1):
            group = egress_group_name(index)
            detail = proxies.get(group) if isinstance(proxies.get(group), dict) else {}
            assignments[group] = str(detail.get("now") or saved.get(group) or "")
    except Exception:
        assignments = {
            egress_group_name(index): str(saved.get(egress_group_name(index)) or "")
            for index in range(1, EGRESS_COUNT + 1)
        }
    return assignments


def _select_unique_egress_candidate(
    *,
    index: int,
    current: str,
    current_ip: str,
    healthy_names: list[str],
    state: dict[str, Any],
    reserved_nodes: set[str],
    reserved_ips: set[str],
    start: int,
    cooldown_minutes: int,
) -> tuple[str, str, int]:
    group = egress_group_name(index)
    recent_nodes = _recent_history_values(_state_map(state, "node_last_used_at"), cooldown_minutes)
    recent_ips = _recent_history_values(_state_map(state, "ip_last_used_at"), cooldown_minutes)
    if current:
        recent_nodes.add(current)
    if current_ip:
        recent_ips.add(current_ip)

    attempted = 0
    for offset in range(len(healthy_names)):
        candidate_index = (start + offset) % len(healthy_names)
        candidate = healthy_names[candidate_index]
        if candidate in reserved_nodes or candidate in recent_nodes:
            continue
        attempted += 1
        select_proxy(candidate, group)
        try:
            exit_ip = probe_egress_ip(index)
        except ManagerError:
            continue
        if exit_ip in reserved_ips or exit_ip in recent_ips:
            continue
        return candidate, exit_ip, (candidate_index + 1) % len(healthy_names)

    if current:
        select_proxy(current, group)
    if attempted == 0:
        raise ManagerError("没有未占用且不在冷却期的健康节点")
    raise ManagerError("健康候选节点的公网 IP 均重复、处于冷却期或探测失败")


def _restore_egress_assignments(assignments: dict[str, str]) -> None:
    for group, node in assignments.items():
        if node:
            try:
                select_proxy(node, group)
            except Exception:
                pass


def repair_unhealthy_egresses(healthy_names: list[str] | None = None) -> dict[str, Any]:
    with _POOL_LOCK:
        healthy_names = healthy_names if healthy_names is not None else cached_healthy_node_names()
        if len(healthy_names) < EGRESS_COUNT:
            raise ManagerError(f"测速可用节点不足 {EGRESS_COUNT} 个，当前仅 {len(healthy_names)} 个")
        healthy_set = set(healthy_names)
        state = load_egress_state()
        live_assignments = current_egress_assignments(state)
        live_ips = probe_current_egress_ips()
        if not any(live_ips.values()):
            raise ManagerError("公网 IP 探测暂不可用，已保留当前固定出口")
        settings = load_settings()
        cooldown_minutes = int(settings["egress_reuse_cooldown_minutes"])

        try:
            cursor = int(state.get("cursor") or 0) % len(healthy_names)
        except (TypeError, ValueError):
            cursor = random.randrange(len(healthy_names))
        retained: dict[str, tuple[str, str]] = {}
        reserved_nodes: set[str] = set()
        reserved_ips: set[str] = set()
        for index in range(1, EGRESS_COUNT + 1):
            group = egress_group_name(index)
            current = live_assignments.get(group) or ""
            exit_ip = live_ips.get(group) or ""
            if (
                current in healthy_set
                and current not in reserved_nodes
                and exit_ip
                and exit_ip not in reserved_ips
            ):
                retained[group] = (current, exit_ip)
                reserved_nodes.add(current)
                reserved_ips.add(exit_ip)

        changed_groups = [
            egress_group_name(index)
            for index in range(1, EGRESS_COUNT + 1)
            if egress_group_name(index) not in retained
        ]
        timestamp = utc_now()
        for group in changed_groups:
            _record_egress_usage(
                state,
                live_assignments.get(group) or "",
                live_ips.get(group) or "",
                timestamp=timestamp,
            )

        assignments: dict[str, str] = {}
        exit_ips: dict[str, str] = {}
        switched = 0
        try:
            for index in range(1, EGRESS_COUNT + 1):
                group = egress_group_name(index)
                if group in retained:
                    node, exit_ip = retained[group]
                    assignments[group] = node
                    exit_ips[group] = exit_ip
                    continue
                replacement, exit_ip, cursor = _select_unique_egress_candidate(
                    index=index,
                    current=live_assignments.get(group) or "",
                    current_ip=live_ips.get(group) or "",
                    healthy_names=healthy_names,
                    state=state,
                    reserved_nodes=reserved_nodes,
                    reserved_ips=reserved_ips,
                    start=cursor,
                    cooldown_minutes=cooldown_minutes,
                )
                assignments[group] = replacement
                exit_ips[group] = exit_ip
                reserved_nodes.add(replacement)
                reserved_ips.add(exit_ip)
                _record_egress_usage(state, replacement, exit_ip, timestamp=timestamp)
                switched += 1
        except Exception:
            _restore_egress_assignments(live_assignments)
            raise
        state["cursor"] = cursor
        state["assignments"] = assignments
        state["exit_ips"] = exit_ips
        state["last_health_repaired_at"] = utc_now()
        state["last_health_switched"] = switched
        _prune_egress_history(state, cooldown_minutes)
        save_egress_state(state)
        return {
            "ok": True,
            "count": EGRESS_COUNT,
            "switched": switched,
            "unique_exit_ips": len(set(exit_ips.values())),
            "assignments": assignments,
        }


def rotation_healthy_node_names() -> list[str]:
    if not controller_online():
        raise ManagerError("请先启动 Mihomo 核心")
    provider_names = provider_node_names()
    healthy_names = cached_healthy_node_names(provider_names)
    if len(healthy_names) < EGRESS_COUNT or node_test_due():
        test_nodes(repair=False)
        healthy_names = cached_healthy_node_names(provider_names)
    if len(healthy_names) < EGRESS_COUNT:
        raise ManagerError(f"测速可用节点不足 {EGRESS_COUNT} 个，当前仅 {len(healthy_names)} 个")
    return healthy_names


def rotate_egress(index: int) -> dict[str, Any]:
    if index < 1 or index > EGRESS_COUNT:
        raise ManagerError(f"出口编号必须在 1-{EGRESS_COUNT} 之间")
    healthy_names = rotation_healthy_node_names()
    with _POOL_LOCK:
        state = load_egress_state()
        assignments = current_egress_assignments(state)
        live_ips = probe_current_egress_ips()
        group = egress_group_name(index)
        current = assignments.get(group) or ""
        current_ip = live_ips.get(group) or ""
        other_ips = [
            live_ips.get(egress_group_name(other)) or ""
            for other in range(1, EGRESS_COUNT + 1)
            if other != index
        ]
        if not all(other_ips) or len(set(other_ips)) != EGRESS_COUNT - 1:
            raise ManagerError("其他固定出口的公网 IP 无法确认唯一，请先执行目标站测活自动修复")
        occupied = {node for name, node in assignments.items() if name != group and node}
        occupied_ips = set(other_ips)
        cooldown_minutes = int(load_settings()["egress_reuse_cooldown_minutes"])
        try:
            start = (healthy_names.index(current) + 1) % len(healthy_names)
        except ValueError:
            try:
                start = int(state.get("cursor") or 0) % len(healthy_names)
            except (TypeError, ValueError):
                start = 0
        timestamp = utc_now()
        _record_egress_usage(state, current, current_ip, timestamp=timestamp)
        replacement, exit_ip, cursor = _select_unique_egress_candidate(
            index=index,
            current=current,
            current_ip=current_ip,
            healthy_names=healthy_names,
            state=state,
            reserved_nodes=occupied,
            reserved_ips=occupied_ips,
            start=start,
            cooldown_minutes=cooldown_minutes,
        )
        assignments[group] = replacement
        live_ips[group] = exit_ip
        _record_egress_usage(state, replacement, exit_ip, timestamp=timestamp)
        state["assignments"] = assignments
        state["exit_ips"] = live_ips
        state["cursor"] = cursor
        state["last_manual_switched_at"] = timestamp
        _prune_egress_history(state, cooldown_minutes)
        save_egress_state(state)
        return {
            "ok": True,
            "index": index,
            "group": group,
            "port": int(load_settings()["egress_base_port"]) + index - 1,
            "previous": current,
            "node": replacement,
            "healthy_nodes": len(healthy_names),
            "unique_exit_ips": len(set(live_ips.values())),
        }


def rotate_egresses() -> dict[str, Any]:
    healthy_names = rotation_healthy_node_names()
    with _POOL_LOCK:
        state = load_egress_state()
        live_assignments = current_egress_assignments(state)
        live_ips = probe_current_egress_ips()
        if any(live_assignments.values()) and not any(live_ips.values()):
            raise ManagerError("公网 IP 探测暂不可用，已取消本次轮换")
        cooldown_minutes = int(load_settings()["egress_reuse_cooldown_minutes"])
        try:
            cursor = int(state.get("cursor") or 0) % len(healthy_names)
        except (TypeError, ValueError):
            cursor = random.randrange(len(healthy_names))
        timestamp = utc_now()
        for index in range(1, EGRESS_COUNT + 1):
            group = egress_group_name(index)
            _record_egress_usage(
                state,
                live_assignments.get(group) or "",
                live_ips.get(group) or "",
                timestamp=timestamp,
            )
        assignments: dict[str, str] = {}
        exit_ips: dict[str, str] = {}
        reserved_nodes: set[str] = set()
        reserved_ips: set[str] = set()
        try:
            for index in range(1, EGRESS_COUNT + 1):
                group = egress_group_name(index)
                replacement, exit_ip, cursor = _select_unique_egress_candidate(
                    index=index,
                    current=live_assignments.get(group) or "",
                    current_ip=live_ips.get(group) or "",
                    healthy_names=healthy_names,
                    state=state,
                    reserved_nodes=reserved_nodes,
                    reserved_ips=reserved_ips,
                    start=cursor,
                    cooldown_minutes=cooldown_minutes,
                )
                assignments[group] = replacement
                exit_ips[group] = exit_ip
                reserved_nodes.add(replacement)
                reserved_ips.add(exit_ip)
                _record_egress_usage(state, replacement, exit_ip, timestamp=timestamp)
        except Exception:
            _restore_egress_assignments(live_assignments)
            raise
        state["cursor"] = cursor
        state["assignments"] = assignments
        state["exit_ips"] = exit_ips
        state["last_rotated_at"] = timestamp
        _prune_egress_history(state, cooldown_minutes)
        save_egress_state(state)
        return {
            "ok": True,
            "count": EGRESS_COUNT,
            "healthy_nodes": len(healthy_names),
            "unique_exit_ips": len(set(exit_ips.values())),
            "last_rotated_at": state["last_rotated_at"],
            "assignments": assignments,
        }


def save_runtime_settings(payload: dict[str, Any]) -> dict[str, Any]:
    settings = load_settings()
    previous_capacity = int(settings["max_accounts_per_egress"])
    for key in (
        "auto_update_minutes",
        "node_test_minutes",
        "egress_rotate_minutes",
        "egress_reuse_cooldown_minutes",
        "max_accounts_per_egress",
        "account_reconcile_minutes",
    ):
        if key in payload:
            settings[key] = payload[key]
    if "egress_auto_rotate_enabled" in payload:
        settings["egress_auto_rotate_enabled"] = payload["egress_auto_rotate_enabled"] is True
    settings["egress_pool_enabled"] = True
    settings = normalized_settings(settings)
    save_settings(settings)
    result: dict[str, Any] = {"ok": True, "settings": public_settings(settings)}
    if int(settings["max_accounts_per_egress"]) != previous_capacity:
        result["accounts"] = reconcile_accounts()
    return result


def public_settings(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or load_settings()
    return {
        "auto_update_minutes": int(settings["auto_update_minutes"]),
        "node_test_minutes": int(settings["node_test_minutes"]),
        "egress_pool_enabled": True,
        "egress_count": EGRESS_COUNT,
        "egress_base_port": int(settings["egress_base_port"]),
        "egress_auto_rotate_enabled": bool(settings["egress_auto_rotate_enabled"]),
        "egress_rotate_minutes": int(settings["egress_rotate_minutes"]),
        "egress_reuse_cooldown_minutes": int(settings["egress_reuse_cooldown_minutes"]),
        "max_accounts_per_egress": int(settings["max_accounts_per_egress"]),
        "account_reconcile_minutes": int(settings["account_reconcile_minutes"]),
    }


def test_nodes(*, repair: bool = True) -> dict[str, Any]:
    if not controller_online():
        raise ManagerError("请先启动 Mihomo 核心")
    with _HEALTH_LOCK:
        names = provider_node_names()
        if not names:
            raise ManagerError("订阅中没有可测速节点")
        timeout_ms = 6000
        delay_maps: list[dict[str, Any]] = []
        for test_url in NODE_TEST_TARGETS:
            query = urlencode({"url": test_url, "timeout": timeout_ms})
            data = controller_request(
                f"/group/{quote(PROXY_GROUP, safe='')}/delay?{query}",
                timeout=max(45.0, timeout_ms / 1000.0 + 30.0),
            )
            delay_maps.append(data if isinstance(data, dict) else {})
        rows: dict[str, dict[str, Any]] = {}
        alive_delays: list[int] = []
        for name in names:
            delays: list[int] = []
            for delay_map in delay_maps:
                try:
                    delays.append(int(delay_map.get(name) or 0))
                except (TypeError, ValueError):
                    delays.append(0)
            ok = bool(delays) and all(delay > 0 for delay in delays)
            delay = max(delays, default=0) if ok else 0
            rows[name] = {"ok": ok, "delay": delay if ok else 0}
            if ok:
                alive_delays.append(delay)
        tested_at = utc_now()
        atomic_write(
            DELAYS_FILE,
            json.dumps({"tested_at": tested_at, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
        )
    result = {
        "ok": True,
        "total": len(names),
        "alive": len(alive_delays),
        "failed": len(names) - len(alive_delays),
        "best_delay": min(alive_delays) if alive_delays else 0,
        "tested_at": tested_at,
    }
    if repair and len(alive_delays) >= EGRESS_COUNT:
        repaired = repair_unhealthy_egresses([name for name in names if rows[name]["ok"]])
        result["switched"] = int(repaired["switched"])
    return result


def proxy_snapshot() -> dict[str, Any]:
    if not controller_online():
        return {"running": False, "current": "", "nodes": [], "version": ""}
    version = controller_request("/version")
    groups = controller_request("/proxies")
    proxies = groups.get("proxies") if isinstance(groups, dict) else {}
    proxies = proxies if isinstance(proxies, dict) else {}
    group = proxies.get(PROXY_GROUP) if isinstance(proxies.get(PROXY_GROUP), dict) else {}
    names = group.get("all") if isinstance(group.get("all"), list) else []
    delay_cache = load_delay_cache()
    cached_rows = delay_cache.get("rows") if isinstance(delay_cache.get("rows"), dict) else {}
    nodes: list[dict[str, Any]] = []
    for name in names[:1000]:
        item = proxies.get(name) if isinstance(proxies.get(name), dict) else {}
        history = item.get("history") if isinstance(item.get("history"), list) else []
        delay = 0
        if history and isinstance(history[-1], dict):
            try:
                delay = int(history[-1].get("delay") or 0)
            except Exception:
                delay = 0
        cached = cached_rows.get(name) if isinstance(cached_rows.get(name), dict) else None
        if delay <= 0 and cached is not None:
            try:
                delay = int(cached.get("delay") or 0)
            except Exception:
                delay = 0
        nodes.append(
            {
                "name": name,
                "type": item.get("type") or "",
                "delay": delay,
                "alive": cached.get("ok") if cached is not None else None,
            }
        )
    return {
        "running": True,
        "current": group.get("now") or "",
        "nodes": nodes,
        "version": version.get("version") if isinstance(version, dict) else "",
        "tested_at": delay_cache.get("tested_at") or "",
    }


def egress_snapshot() -> list[dict[str, Any]]:
    settings = load_settings()
    base_port = int(settings["egress_base_port"])
    capacity = int(settings["max_accounts_per_egress"])
    pool_state = load_egress_state()
    account_rows = pool_state.get("account_summary") if isinstance(pool_state.get("account_summary"), list) else []
    accounts_by_name = {
        str(row.get("name") or ""): row for row in account_rows if isinstance(row, dict)
    }
    proxies: dict[str, Any] = {}
    if controller_online():
        try:
            result = controller_request("/proxies")
            proxies = result.get("proxies") if isinstance(result, dict) and isinstance(result.get("proxies"), dict) else {}
        except Exception:
            proxies = {}
    rows: list[dict[str, Any]] = []
    for index in range(1, EGRESS_COUNT + 1):
        group = egress_group_name(index)
        detail = proxies.get(group) if isinstance(proxies.get(group), dict) else {}
        proxy_name = egress_proxy_name(index)
        account_row = accounts_by_name.get(proxy_name, {})
        rows.append(
            {
                "index": index,
                "name": proxy_name,
                "group": group,
                "port": base_port + index - 1,
                "node": detail.get("now") or (pool_state.get("assignments") or {}).get(group, ""),
                "account_count": int(account_row.get("account_count") or 0),
                "accounts": account_row.get("accounts") if isinstance(account_row.get("accounts"), list) else [],
                "capacity": capacity,
            }
        )
    return rows


def tail_logs(lines: int = 80) -> str:
    chunks: list[str] = []
    if MANAGED_BY_SYSTEMD:
        try:
            result = _ctl("logs", str(lines), timeout=8)
            if result.stdout and result.stdout.strip():
                chunks.append("--- journalctl ---\n" + result.stdout.strip())
        except Exception:
            pass
    for label, path in (("mihomo.log", LOG_FILE), ("mihomo.err.log", ERR_FILE)):
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        except Exception:
            continue
        if content:
            chunks.append(f"--- {label} ---\n" + "\n".join(content))
    return "\n".join(chunks)[-30000:]



def status_payload() -> dict[str, Any]:
    settings = load_settings()
    source = SOURCE_FILE.read_text(encoding="utf-8").strip() if SOURCE_FILE.exists() else ""
    proxy = proxy_snapshot()
    pid = owned_pid()
    public_base = str(settings.get("public_base") or PUBLIC_BASE or "").rstrip("/")
    mixed = int(settings["mixed_port"])
    pool_state = load_egress_state()
    return {
        "ok": True,
        "running": proxy["running"],
        "pid": pid,
        "managed": True if MANAGED_BY_SYSTEMD else pid is not None,
        "version": proxy["version"],
        "current": proxy["current"],
        "nodes": proxy["nodes"],
        "tested_at": proxy.get("tested_at") or "",
        "node_count": int(settings.get("node_count") or 0),
        "subscription_kind": settings.get("subscription_kind") or "",
        "source_masked": mask_source(source),
        "updated_at": settings.get("updated_at") or "",
        "settings": public_settings(settings),
        "egresses": egress_snapshot(),
        "last_rotated_at": pool_state.get("last_rotated_at") or "",
        "accounts_reconciled_at": pool_state.get("accounts_reconciled_at") or "",
        "standby_accounts": int(pool_state.get("standby_accounts") or 0),
        "externally_disabled_accounts": int(pool_state.get("externally_disabled_accounts") or 0),
        "mixed_port": mixed,
        "proxy_url": f"http://127.0.0.1:{mixed}",
        "socks_url": f"socks5://127.0.0.1:{mixed}",
        "docker_proxy_url": f"http://172.20.0.1:{mixed}",
        "controller": controller_base(settings),
        "dashboard_url": ((public_base + "/ui/") if public_base else (controller_base(settings) + "/ui/")) if DASHBOARD_ENABLED else "",
        "web_url": public_base + "/" if public_base else f"http://{settings['web_host']}:{int(settings['web_port'])}",
    }



class ManagerHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class WebHandler(BaseHTTPRequestHandler):
    server_version = "MihomoSharedManager/1.0"

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            length = 0
        if length <= 0 or length > 2 * 1024 * 1024:
            return {}
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            target = WEB_DIR / "index.html"
        else:
            relative = path.lstrip("/")
            target = (WEB_DIR / relative).resolve()
            if WEB_DIR.resolve() not in target.parents:
                self.send_error(403)
                return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(target.suffix.lower(), "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/status":
            try:
                self._json(status_payload())
            except Exception as exc:
                self._json({"ok": False, "error": str(exc)}, 500)
            return
        if path == "/api/logs":
            self._json({"ok": True, "logs": tail_logs()})
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        body = self._read_json()
        try:
            if path == "/api/subscription":
                result = update_subscription(str(body.get("source") or ""))
            elif path == "/api/update":
                result = update_subscription()
            elif path == "/api/start":
                result = start_core()
            elif path == "/api/stop":
                result = stop_core()
            elif path == "/api/reload":
                result = reload_core()
            elif path == "/api/select":
                result = select_proxy(str(body.get("name") or ""), str(body.get("group") or PROXY_GROUP))
            elif path == "/api/test":
                result = test_nodes()
            elif path == "/api/settings":
                result = save_runtime_settings(body)
            elif path == "/api/egress/rotate":
                if body.get("index") is None:
                    result = rotate_egresses()
                else:
                    try:
                        index = int(body["index"])
                    except (TypeError, ValueError) as exc:
                        raise ManagerError("出口编号无效") from exc
                    result = rotate_egress(index)
            elif path == "/api/egress/reconcile":
                result = reconcile_accounts()
            elif path == "/api/shutdown":
                self._json({"ok": True, "message": "管理器正在关闭"})
                threading.Thread(target=self.server.shutdown, name="manager-shutdown", daemon=True).start()
                return
            else:
                self._json({"ok": False, "error": "not found"}, 404)
                return
            self._json(result)
        except ManagerError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except Exception as exc:
            self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, 500)

    def log_message(self, format: str, *args: Any) -> None:
        return


def auto_update_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(60):
        settings = load_settings()
        minutes = int(settings.get("auto_update_minutes") or 0)
        if minutes <= 0 or not SOURCE_FILE.exists() or not SOURCE_FILE.read_text(encoding="utf-8").strip():
            continue
        try:
            updated = datetime.fromisoformat(str(settings.get("updated_at") or ""))
            age = datetime.now(updated.tzinfo or timezone.utc) - updated
            if age.total_seconds() < minutes * 60:
                continue
        except Exception:
            pass

        try:
            update_subscription()
        except Exception:
            pass


def egress_rotate_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        settings = load_settings()
        minutes = int(settings.get("egress_rotate_minutes") or 0)
        if not bool(settings.get("egress_auto_rotate_enabled")) or minutes <= 0 or not controller_online():
            continue
        state = load_egress_state()
        try:
            rotated = datetime.fromisoformat(str(state.get("last_rotated_at") or ""))
            age = datetime.now(rotated.tzinfo or timezone.utc) - rotated
            if age.total_seconds() < minutes * 60:
                continue
        except Exception:
            pass
        try:
            rotate_egresses()
        except Exception:
            pass


def node_health_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        settings = load_settings()
        if not controller_online() or not node_test_due(settings):
            continue
        try:
            test_nodes(repair=True)
        except Exception:
            pass


def account_reconcile_loop(stop_event: threading.Event) -> None:
    while not stop_event.wait(30):
        settings = load_settings()
        minutes = int(settings.get("account_reconcile_minutes") or 0)
        if minutes <= 0:
            continue
        state = load_egress_state()
        try:
            reconciled = datetime.fromisoformat(str(state.get("accounts_reconciled_at") or ""))
            age = datetime.now(reconciled.tzinfo or timezone.utc) - reconciled
            if age.total_seconds() < minutes * 60:
                continue
        except Exception:
            pass
        try:
            reconcile_accounts()
        except Exception:
            pass


def manager_request(path: str, *, timeout: float = 8.0) -> dict[str, Any]:
    settings = load_settings()
    url = f"http://{settings['web_host']}:{int(settings['web_port'])}{path}"
    request = Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ManagerError(f"无法连接共享代理管理器: {exc}") from exc
    result = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(result, dict) or result.get("ok") is False:
        raise ManagerError(str(result.get("error") if isinstance(result, dict) else "管理器响应无效"))
    return result


def serve(*, autostart: bool = False, open_browser: bool = False) -> int:
    settings = ensure_layout()
    if autostart and int(settings.get("node_count") or 0) > 0:
        try:
            start_core()
        except Exception as exc:
            print(f"[!] Mihomo autostart failed: {exc}", flush=True)
    host = str(settings["web_host"])
    port = int(settings["web_port"])
    try:
        server = ManagerHTTPServer((host, port), WebHandler)
    except OSError as exc:
        raise ManagerError(f"Web 端口 {host}:{port} 无法监听，管理器可能已经运行: {exc}") from exc
    atomic_write(MANAGER_PID_FILE, f"{os.getpid()}\n")
    atexit.register(lambda: MANAGER_PID_FILE.unlink(missing_ok=True))
    stop_event = threading.Event()
    updater = threading.Thread(target=auto_update_loop, args=(stop_event,), name="subscription-auto-update", daemon=True)
    health_checker = threading.Thread(target=node_health_loop, args=(stop_event,), name="node-auto-test", daemon=True)
    rotator = threading.Thread(target=egress_rotate_loop, args=(stop_event,), name="egress-auto-rotate", daemon=True)
    reconciler = threading.Thread(target=account_reconcile_loop, args=(stop_event,), name="account-pool-reconcile", daemon=True)
    updater.start()
    health_checker.start()
    rotator.start()
    reconciler.start()
    web_url = f"http://{host}:{port}"
    print(f"[*] Web control: {web_url}", flush=True)
    print("[*] 此窗口是共享代理管理器；按 Ctrl+C 可安全停止核心并退出。", flush=True)
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(web_url)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        server.server_close()
        if not MANAGED_BY_SYSTEMD:
            try:
                stop_core()
            except Exception as exc:
                print(f"[!] 退出时停止 Mihomo 失败: {exc}", flush=True)
        MANAGER_PID_FILE.unlink(missing_ok=True)
    return 0


def configure_console_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    configure_console_output()
    parser = argparse.ArgumentParser(description="Shared Mihomo manager")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    serve_parser = sub.add_parser("serve")
    serve_parser.add_argument("--autostart", action="store_true")
    serve_parser.add_argument("--open", action="store_true", dest="open_browser")
    update_parser = sub.add_parser("update")
    update_parser.add_argument("--source", default="")
    sub.add_parser("start")
    sub.add_parser("stop")
    sub.add_parser("reload")
    sub.add_parser("status")
    sub.add_parser("shutdown")
    sub.add_parser("open")
    args = parser.parse_args(argv)
    command = args.command or "serve"
    try:
        if command == "init":
            settings = ensure_layout()
            print(json.dumps({"ok": True, "settings": settings}, ensure_ascii=False))
        elif command == "serve":
            return serve(
                autostart=bool(getattr(args, "autostart", False)),
                open_browser=bool(getattr(args, "open_browser", False)),
            )
        elif command == "update":
            source = str(getattr(args, "source", "") or "").strip() or None
            print(json.dumps(update_subscription(source), ensure_ascii=False))
        elif command == "start":
            print(json.dumps(manager_request("/api/start"), ensure_ascii=False))
        elif command == "stop":
            print(json.dumps(manager_request("/api/stop"), ensure_ascii=False))
        elif command == "reload":
            print(json.dumps(reload_core(), ensure_ascii=False))
        elif command == "status":
            print(json.dumps(status_payload(), ensure_ascii=False))
        elif command == "shutdown":
            print(json.dumps(manager_request("/api/shutdown"), ensure_ascii=False))
        elif command == "open":
            settings = load_settings()
            webbrowser.open(f"http://{settings['web_host']}:{int(settings['web_port'])}")
        return 0
    except ManagerError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
