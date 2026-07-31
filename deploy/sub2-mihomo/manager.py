#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Mihomo subscription manager + simple Web panel (local-style UX)."""

from __future__ import annotations

import argparse
import atexit
import gzip
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

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
    "public_base": "https://tupai.cyou/mihomo",
}

_CORE_LOCK = threading.RLock()
_CORE_PROCESS: subprocess.Popen[Any] | None = None


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
    settings = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            loaded = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update(loaded)
        except Exception:
            pass
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    atomic_write(SETTINGS_FILE, json.dumps(settings, ensure_ascii=False, indent=2) + "\n")


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
    return {
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
        "proxy-groups": [
            {
                # fallback sticks to the first alive node; switch only after health-check failure.
                # Same sticky behavior as Server1 /opt/cpa-mihomo CPA-STABLE.
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
        ],
        "rules": [
            "DOMAIN-SUFFIX,local,DIRECT",
            "IP-CIDR,127.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,10.0.0.0/8,DIRECT,no-resolve",
            "IP-CIDR,172.16.0.0/12,DIRECT,no-resolve",
            "IP-CIDR,192.168.0.0/16,DIRECT,no-resolve",
            "MATCH,PROXY",
        ],
    }


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


def load_delay_cache() -> dict[str, Any]:
    if not DELAYS_FILE.exists():
        return {"tested_at": "", "rows": {}}
    try:
        value = json.loads(DELAYS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tested_at": "", "rows": {}}
    return value if isinstance(value, dict) else {"tested_at": "", "rows": {}}


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


def test_nodes() -> dict[str, Any]:
    if not controller_online():
        raise ManagerError("请先启动 Mihomo 核心")
    names = provider_node_names()
    if not names:
        raise ManagerError("订阅中没有可测速节点")
    test_url = "https://accounts.x.ai/sign-up"
    timeout_ms = 6000
    query = urlencode({"url": test_url, "timeout": timeout_ms})
    data = controller_request(
        f"/group/{quote(PROXY_GROUP, safe='')}/delay?{query}",
        timeout=max(45.0, timeout_ms / 1000.0 + 30.0),
    )
    delays = data if isinstance(data, dict) else {}
    rows: dict[str, dict[str, Any]] = {}
    alive_delays: list[int] = []
    for name in names:
        try:
            delay = int(delays.get(name) or 0)
        except (TypeError, ValueError):
            delay = 0
        ok = delay > 0
        rows[name] = {"ok": ok, "delay": delay if ok else 0}
        if ok:
            alive_delays.append(delay)
    tested_at = utc_now()
    atomic_write(
        DELAYS_FILE,
        json.dumps({"tested_at": tested_at, "rows": rows}, ensure_ascii=False, indent=2) + "\n",
    )
    return {
        "ok": True,
        "total": len(names),
        "alive": len(alive_delays),
        "failed": len(names) - len(alive_delays),
        "best_delay": min(alive_delays) if alive_delays else 0,
        "tested_at": tested_at,
    }


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
    updater.start()
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
