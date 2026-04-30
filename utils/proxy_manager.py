import copy
import csv
import io
import json
import os
import random
import re
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests as std_requests
import yaml

CLASH_API_URL = ""
LOCAL_PROXY_URL = ""
ENABLE_NODE_SWITCH = False
PROXY_CLIENT_TYPE = "clash"
V2RAYA_PANEL_URL = ""
V2RAYA_USERNAME = ""
V2RAYA_PASSWORD = ""
V2RAYN_BASE_DIR = ""
V2RAYN_GUI_CONFIG_PATH = ""
V2RAYN_DB_PATH = ""
V2RAYN_EXE_PATH = ""
V2RAYN_RESTART_WAIT_SEC = 6
V2RAYN_HIDE_WINDOW_ON_RESTART = True
V2RAYN_PRECHECK_ON_START = False
V2RAYN_PRECHECK_CACHE_MINUTES = 30
V2RAYN_PRECHECK_MAX_NODES = 50
V2RAYN_LIVE_POOL_LIMIT = 50
V2RAYN_SUBSCRIPTION_UPDATE_ENABLED = False
V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 0
V2RAYN_SUBSCRIPTION_UPDATE_COMMAND = ""
POOL_MODE = False
FASTEST_MODE = False
PROXY_GROUP_NAME = "节点选择"
CLASH_SECRET = ""
NODE_BLACKLIST = []
_IS_IN_DOCKER = os.path.exists("/.dockerenv")
_global_switch_lock = threading.Lock()
_socket_restore_lock = threading.Lock()
_original_socket = socket.socket
_last_switch_time = 0.0
_last_switch_result_lock = threading.Lock()
_last_switch_result = {
    "ok": False,
    "client_type": "",
    "message": "",
    "target": "",
    "proxy_url": "",
    "at": 0.0,
}
_v2rayn_invalid_index_ids: set[str] = set()
_v2rayn_invalid_lock = threading.Lock()
_v2rayn_live_profiles: list[dict] = []
_v2rayn_live_lock = threading.Lock()
_v2rayn_precheck_lock = threading.Lock()
_v2rayn_last_precheck_at = 0.0
_v2rayn_last_subscription_update_at = 0.0
_v2rayn_runtime_signature = None
_v2raya_invalid_node_keys: set[str] = set()
_v2raya_invalid_lock = threading.Lock()
_v2raya_live_nodes: list[dict] = []
_v2raya_live_lock = threading.Lock()
_v2raya_precheck_lock = threading.Lock()
_v2raya_last_precheck_at = 0.0
_v2raya_runtime_signature = None
_v2raya_last_detected_proxy_url = ""
_v2raya_last_detected_proxy_source = ""
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)


def _hidden_subprocess_kwargs() -> dict:
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
        "startupinfo": startupinfo,
    }


def _call_with_original_socket(fn, *args, **kwargs):
    with _socket_restore_lock:
        current_socket = socket.socket
        socket.socket = _original_socket
        try:
            return fn(*args, **kwargs)
        finally:
            socket.socket = current_socket


def format_docker_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return url
    if _IS_IN_DOCKER:
        if "127.0.0.1" in url:
            return url.replace("127.0.0.1", "host.docker.internal")
        if "localhost" in url:
            return url.replace("localhost", "host.docker.internal")
    return url


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def clean_for_log(text: str) -> str:
    emoji_pattern = re.compile(
        r"[\U0001F1E6-\U0001F1FF]|[\U0001F300-\U0001F6FF]|[\U0001F900-\U0001F9FF]|[\U00002600-\U000027BF]|[\uFE0F]"
    )
    return emoji_pattern.sub("", str(text or "")).strip()


def _record_switch_result(ok: bool, client_type: str, message: str = "", target: str = "", proxy_url: str = "") -> None:
    with _last_switch_result_lock:
        _last_switch_result.update(
            {
                "ok": bool(ok),
                "client_type": str(client_type or "").strip(),
                "message": str(message or "").strip(),
                "target": str(target or "").strip(),
                "proxy_url": str(proxy_url or "").strip(),
                "at": time.time(),
            }
        )


def get_last_switch_result() -> dict:
    with _last_switch_result_lock:
        return dict(_last_switch_result)


def reload_proxy_config():
    global CLASH_API_URL, LOCAL_PROXY_URL, ENABLE_NODE_SWITCH, PROXY_CLIENT_TYPE
    global V2RAYA_PANEL_URL, V2RAYA_USERNAME, V2RAYA_PASSWORD
    global V2RAYN_BASE_DIR, V2RAYN_GUI_CONFIG_PATH, V2RAYN_DB_PATH, V2RAYN_EXE_PATH
    global V2RAYN_RESTART_WAIT_SEC, V2RAYN_HIDE_WINDOW_ON_RESTART, V2RAYN_PRECHECK_ON_START
    global V2RAYN_PRECHECK_CACHE_MINUTES, V2RAYN_PRECHECK_MAX_NODES, V2RAYN_LIVE_POOL_LIMIT
    global V2RAYN_SUBSCRIPTION_UPDATE_ENABLED, V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES
    global V2RAYN_SUBSCRIPTION_UPDATE_COMMAND, POOL_MODE, FASTEST_MODE, PROXY_GROUP_NAME
    global CLASH_SECRET, NODE_BLACKLIST, _v2rayn_runtime_signature, _v2raya_runtime_signature

    config_path = os.path.join(BASE_DIR, "data", "config.yaml")
    if not os.path.exists(config_path):
        print(f"[{ts()}] [WARNING] 配置文件 {config_path} 不存在，使用默认代理设置。")
        conf_data = {}
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            conf_data = yaml.safe_load(f) or {}

    clash_conf = conf_data.get("clash_proxy_pool", {}) if isinstance(conf_data.get("clash_proxy_pool"), dict) else {}
    ENABLE_NODE_SWITCH = bool(clash_conf.get("enable", False))
    PROXY_CLIENT_TYPE = str(clash_conf.get("client_type", "clash") or "clash").strip().lower()
    if PROXY_CLIENT_TYPE not in {"clash", "v2rayn", "v2raya"}:
        PROXY_CLIENT_TYPE = "clash"

    V2RAYA_PANEL_URL = str(
        clash_conf.get("v2raya_api_url", "") or clash_conf.get("v2raya_url", "") or ""
    ).strip().rstrip("/")
    if V2RAYA_PANEL_URL.endswith("/api"):
        V2RAYA_PANEL_URL = V2RAYA_PANEL_URL[:-4]
    V2RAYA_USERNAME = str(clash_conf.get("v2raya_username", "") or "").strip()
    V2RAYA_PASSWORD = str(clash_conf.get("v2raya_password", "") or "").strip()

    V2RAYN_BASE_DIR = str(clash_conf.get("v2rayn_base_dir", "") or "").strip()
    if V2RAYN_BASE_DIR:
        V2RAYN_GUI_CONFIG_PATH = os.path.join(V2RAYN_BASE_DIR, "guiConfigs", "guiNConfig.json")
        V2RAYN_DB_PATH = os.path.join(V2RAYN_BASE_DIR, "guiConfigs", "guiNDB.db")
        V2RAYN_EXE_PATH = os.path.join(V2RAYN_BASE_DIR, "v2rayN.exe")
    else:
        V2RAYN_GUI_CONFIG_PATH = ""
        V2RAYN_DB_PATH = ""
        V2RAYN_EXE_PATH = ""

    try:
        V2RAYN_RESTART_WAIT_SEC = max(1, int(clash_conf.get("v2rayn_restart_wait_sec", 6)))
    except Exception:
        V2RAYN_RESTART_WAIT_SEC = 6
    V2RAYN_HIDE_WINDOW_ON_RESTART = bool(clash_conf.get("v2rayn_hide_window_on_restart", True))
    V2RAYN_PRECHECK_ON_START = bool(clash_conf.get("v2rayn_precheck_on_start", False))
    try:
        V2RAYN_PRECHECK_CACHE_MINUTES = max(0, int(clash_conf.get("v2rayn_precheck_cache_minutes", 30)))
    except Exception:
        V2RAYN_PRECHECK_CACHE_MINUTES = 30
    try:
        V2RAYN_PRECHECK_MAX_NODES = max(0, int(clash_conf.get("v2rayn_precheck_max_nodes", 50)))
    except Exception:
        V2RAYN_PRECHECK_MAX_NODES = 50
    try:
        V2RAYN_LIVE_POOL_LIMIT = max(1, int(clash_conf.get("v2rayn_live_pool_limit", 50)))
    except Exception:
        V2RAYN_LIVE_POOL_LIMIT = 50
    V2RAYN_SUBSCRIPTION_UPDATE_ENABLED = bool(clash_conf.get("v2rayn_subscription_update_enabled", False))
    try:
        V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = max(
            0, int(clash_conf.get("v2rayn_subscription_update_interval_minutes", 0))
        )
    except Exception:
        V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 0
    V2RAYN_SUBSCRIPTION_UPDATE_COMMAND = str(clash_conf.get("v2rayn_subscription_update_command", "") or "").strip()

    POOL_MODE = bool(clash_conf.get("pool_mode", False))
    FASTEST_MODE = bool(clash_conf.get("fastest_mode", False))
    CLASH_API_URL = format_docker_url(str(clash_conf.get("api_url", "http://127.0.0.1:9090") or "").strip())
    raw_local_proxy = str(clash_conf.get("test_proxy_url", "") or "").strip()
    if not raw_local_proxy:
        raw_local_proxy = str(conf_data.get("default_proxy", "") or "").strip()
    if not raw_local_proxy and PROXY_CLIENT_TYPE == "clash":
        raw_local_proxy = "http://127.0.0.1:7890"
    LOCAL_PROXY_URL = format_docker_url(raw_local_proxy)
    PROXY_GROUP_NAME = str(clash_conf.get("group_name", "节点选择") or "节点选择")
    CLASH_SECRET = str(clash_conf.get("secret", "") or "").strip()
    NODE_BLACKLIST = clash_conf.get("blacklist", ["港", "HK", "台", "TW", "中国", "CN"])

    new_v2rayn_runtime_signature = (
        PROXY_CLIENT_TYPE,
        V2RAYN_BASE_DIR,
        V2RAYN_GUI_CONFIG_PATH,
        V2RAYN_DB_PATH,
        V2RAYN_EXE_PATH,
        V2RAYN_PRECHECK_ON_START,
        V2RAYN_PRECHECK_CACHE_MINUTES,
        V2RAYN_PRECHECK_MAX_NODES,
        V2RAYN_LIVE_POOL_LIMIT,
        tuple(str(x) for x in NODE_BLACKLIST),
    )
    if _v2rayn_runtime_signature != new_v2rayn_runtime_signature:
        _reset_v2rayn_runtime_state()
        _v2rayn_runtime_signature = new_v2rayn_runtime_signature

    new_v2raya_runtime_signature = (
        PROXY_CLIENT_TYPE,
        V2RAYA_PANEL_URL,
        V2RAYA_USERNAME,
        V2RAYA_PASSWORD,
        V2RAYN_PRECHECK_ON_START,
        V2RAYN_PRECHECK_CACHE_MINUTES,
        V2RAYN_PRECHECK_MAX_NODES,
        V2RAYN_LIVE_POOL_LIMIT,
        tuple(str(x) for x in NODE_BLACKLIST),
    )
    if _v2raya_runtime_signature != new_v2raya_runtime_signature:
        _reset_v2raya_runtime_state()
        _v2raya_runtime_signature = new_v2raya_runtime_signature

    print(f"[{ts()}] [系统] 代理管理模块配置已同步更新。当前模式: {PROXY_CLIENT_TYPE}")


def get_display_name(proxy_url: str) -> str:
    if not proxy_url:
        return "全局单机"
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        if parsed.port and 41000 < parsed.port <= 41050:
            return f"{parsed.port - 41000}号机"
        return f"端口:{parsed.port}"
    except Exception:
        return "未知通道"


def _resolve_local_proxy_url(proxy_url=None) -> str:
    raw_url = proxy_url if proxy_url else LOCAL_PROXY_URL
    return format_docker_url(str(raw_url or "").strip())


def get_local_proxy_diagnostics(proxy_url=None) -> dict:
    target_proxy = _resolve_local_proxy_url(proxy_url)
    diagnostics = {
        "configured": bool(target_proxy),
        "target_proxy": target_proxy,
        "display_name": get_display_name(target_proxy),
        "scheme": "",
        "host": "",
        "port": None,
        "reachable": False,
        "error": "",
    }
    if not target_proxy:
        diagnostics["error"] = "未配置 test_proxy_url 或 default_proxy"
        return diagnostics
    try:
        parsed = urllib.parse.urlparse(target_proxy)
        diagnostics["scheme"] = str(parsed.scheme or "").lower()
        diagnostics["host"] = parsed.hostname or "127.0.0.1"
        default_port = 1080 if diagnostics["scheme"].startswith("socks5") else 8080
        diagnostics["port"] = parsed.port or default_port
    except Exception as e:
        diagnostics["error"] = f"代理地址解析失败: {e}"
        return diagnostics

    try:
        with _call_with_original_socket(
            socket.create_connection, (diagnostics["host"], diagnostics["port"]), 0.5
        ):
            diagnostics["reachable"] = True
    except Exception as e:
        diagnostics["error"] = str(e)
    return diagnostics


def _default_port_for_proxy_scheme(scheme: str) -> int:
    scheme = str(scheme or "").strip().lower()
    return 1080 if scheme.startswith("socks5") else 8080


def _build_proxy_url(host: str, port: int, scheme: str) -> str:
    normalized_host = str(host or "127.0.0.1").strip()
    normalized_port = int(port)
    normalized_scheme = "socks5h" if str(scheme or "").lower().startswith("socks5") else "http"
    return format_docker_url(f"{normalized_scheme}://{normalized_host}:{normalized_port}")


def _parse_proxy_url(proxy_url: str) -> dict:
    raw = str(proxy_url or "").strip()
    if not raw:
        return {"url": "", "scheme": "", "host": "", "port": None}
    try:
        parsed = urllib.parse.urlparse(raw)
        scheme = str(parsed.scheme or "").strip().lower()
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or _default_port_for_proxy_scheme(scheme)
        return {"url": format_docker_url(raw), "scheme": scheme, "host": host, "port": int(port)}
    except Exception:
        return {"url": format_docker_url(raw), "scheme": "", "host": "", "port": None}


def _set_runtime_default_proxy(proxy_url: str, source: str = "") -> str:
    global LOCAL_PROXY_URL, _v2raya_last_detected_proxy_url, _v2raya_last_detected_proxy_source
    normalized = format_docker_url(str(proxy_url or "").strip())
    if not normalized:
        return ""
    LOCAL_PROXY_URL = normalized
    _v2raya_last_detected_proxy_url = normalized
    _v2raya_last_detected_proxy_source = str(source or "").strip()
    try:
        from utils import config as cfg

        cfg.DEFAULT_PROXY = normalized
        if isinstance(getattr(cfg, "_c", None), dict):
            cfg._c["default_proxy"] = normalized
            clash_conf = cfg._c.get("clash_proxy_pool")
            if not isinstance(clash_conf, dict):
                clash_conf = {}
                cfg._c["clash_proxy_pool"] = clash_conf
            clash_conf["test_proxy_url"] = normalized
    except Exception:
        pass
    return normalized


def _parse_v2raya_runtime_inbounds(value, bucket: list[dict], ctx: str = "") -> None:
    if isinstance(value, dict):
        keys = {str(key or "").strip().lower() for key in value.keys()}
        inbound_hint = any(
            hint in keys
            for hint in {"inbound", "inbounds", "localport", "protocol", "mixed", "http", "socks", "listen"}
        ) or "inbound" in str(ctx or "").lower()
        raw_port = None
        for key in ["LocalPort", "localPort", "port", "listenPort"]:
            current = value.get(key)
            try:
                current_int = int(current)
            except Exception:
                continue
            if 0 < current_int < 65536:
                raw_port = current_int
                break
        raw_protocol = _first_v2raya_text(
            value.get("Protocol"),
            value.get("protocol"),
            value.get("type"),
            value.get("Type"),
            value.get("Inbound"),
            value.get("inbound"),
        ).lower()
        if inbound_hint and raw_port and raw_protocol:
            scheme = "socks5h" if "socks" in raw_protocol else "http"
            bucket.append(
                {
                    "url": _build_proxy_url("127.0.0.1", raw_port, scheme),
                    "source": "runtime_inbound",
                    "protocol": raw_protocol,
                    "port": raw_port,
                }
            )
        for key, child in value.items():
            _parse_v2raya_runtime_inbounds(child, bucket, ctx=f"{ctx}.{key}" if ctx else str(key or ""))
    elif isinstance(value, list):
        for item in value:
            _parse_v2raya_runtime_inbounds(item, bucket, ctx=ctx)


def _get_v2raya_runtime_proxy_candidates() -> list[dict]:
    if not V2RAYA_PANEL_URL:
        return []
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        payloads = []
        for endpoint, params in [
            ("touch", None),
            ("setting", None),
            ("outbounds", None),
            ("outbound", {"outbound": "proxy"}),
        ]:
            try:
                resp, payload, _ = _v2raya_request(session, "GET", endpoint, auth_values=auth_values, params=params)
                if resp is not None and resp.status_code < 400:
                    payloads.append(payload)
            except Exception:
                continue
        candidates = []
        for payload in payloads:
            _parse_v2raya_runtime_inbounds(_v2raya_unwrap_payload(payload), candidates)
        deduped = []
        seen = set()
        for item in candidates:
            url = str(item.get("url") or "").strip()
            if url and url not in seen:
                seen.add(url)
                deduped.append(item)
        return deduped
    except Exception:
        return []
    finally:
        session.close()


def _get_proxy_process_pid_map() -> dict[int, str]:
    hidden_kwargs = _hidden_subprocess_kwargs()
    try:
        proc = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=8,
            **hidden_kwargs,
        )
        if proc.returncode != 0:
            return {}
        pid_map = {}
        for row in csv.reader(io.StringIO(proc.stdout)):
            if len(row) < 2:
                continue
            name = str(row[0] or "").strip()
            try:
                pid = int(str(row[1] or "").replace(",", "").strip())
            except Exception:
                continue
            if re.search(r"(v2ray|xray|v2raya|clash|mihomo|sing)", name, re.IGNORECASE):
                pid_map[pid] = name
        return pid_map
    except Exception:
        return {}


def _iter_related_listener_candidates() -> list[dict]:
    hidden_kwargs = _hidden_subprocess_kwargs()
    pid_map = _get_proxy_process_pid_map()
    if not pid_map:
        return []
    panel_port = _parse_proxy_url(V2RAYA_PANEL_URL).get("port")
    try:
        proc = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=8,
            **hidden_kwargs,
        )
        if proc.returncode != 0:
            return []
    except Exception:
        return []

    candidates = []
    seen = set()
    for raw_line in str(proc.stdout or "").splitlines():
        line = raw_line.strip()
        if not line.startswith("TCP"):
            continue
        parts = re.split(r"\s+", line)
        if len(parts) < 5 or parts[3].upper() != "LISTENING":
            continue
        local_addr = parts[1]
        try:
            pid = int(parts[4])
        except Exception:
            continue
        if pid not in pid_map:
            continue
        if ":" not in local_addr:
            continue
        host_text, port_text = local_addr.rsplit(":", 1)
        try:
            port = int(port_text.strip().strip("]"))
        except Exception:
            continue
        if port == panel_port:
            continue
        host = host_text.strip().strip("[]")
        if host in {"0.0.0.0", "::", "::1", "127.0.0.1", "*"}:
            host = "127.0.0.1"
        signature = f"{pid}:{host}:{port}"
        if signature in seen:
            continue
        seen.add(signature)
        for scheme in ["http", "socks5h"]:
            candidates.append(
                {
                    "url": _build_proxy_url(host, port, scheme),
                    "source": f"listener:{pid_map[pid]}",
                    "port": port,
                    "process_name": pid_map[pid],
                    "pid": pid,
                    "scheme": scheme,
                }
            )
    return candidates


def discover_v2raya_local_proxy(preferred_url=None, validate: bool = True) -> dict:
    preferred = _resolve_local_proxy_url(preferred_url)
    candidates = []
    seen = set()

    def add_candidate(url: str, source: str, note: str = "") -> None:
        normalized = format_docker_url(str(url or "").strip())
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        diag = get_local_proxy_diagnostics(normalized)
        candidates.append(
            {
                "url": normalized,
                "source": str(source or "").strip(),
                "note": str(note or "").strip(),
                "reachable": bool(diag.get("reachable")),
                "diagnostics": diag,
            }
        )

    for raw in [preferred, LOCAL_PROXY_URL, _v2raya_last_detected_proxy_url]:
        if raw:
            add_candidate(raw, "configured")
            parsed = _parse_proxy_url(raw)
            if parsed.get("host") and parsed.get("port"):
                alternate_scheme = "socks5h" if parsed.get("scheme", "").startswith("http") else "http"
                add_candidate(_build_proxy_url(parsed["host"], parsed["port"], alternate_scheme), "configured_alt")

    for item in _get_v2raya_runtime_proxy_candidates():
        add_candidate(item.get("url"), item.get("source"), note=item.get("protocol", ""))
    for item in _iter_related_listener_candidates():
        add_candidate(item.get("url"), item.get("source"))

    selected = None
    if validate:
        for item in candidates:
            if not item.get("reachable"):
                continue
            if _test_proxy_liveness_once(item["url"], silent=True):
                selected = dict(item)
                break

    return {
        "configured_proxy": preferred,
        "detected_proxy": selected.get("url") if selected else "",
        "detected_source": selected.get("source") if selected else "",
        "reachable_candidate_count": sum(1 for item in candidates if item.get("reachable")),
        "candidates": candidates,
        "selected": selected,
    }


def align_v2raya_local_proxy(preferred_url=None, persist: bool = False) -> dict:
    result = discover_v2raya_local_proxy(preferred_url=preferred_url, validate=True)
    selected = result.get("selected") or {}
    detected_proxy = str(selected.get("url") or "").strip()
    if not detected_proxy:
        return {
            **result,
            "ok": False,
            "persisted": False,
            "message": "未发现可用的 v2rayA 本地代理端口，请先确认 v2rayA 已启动并已挂载代理入口。",
        }

    applied_proxy = _set_runtime_default_proxy(detected_proxy, source=selected.get("source", "detected"))
    persisted = False
    if persist:
        try:
            from utils import config as cfg

            new_config = copy.deepcopy(getattr(cfg, "_c", {}) or {})
            new_config["default_proxy"] = applied_proxy
            clash_conf = new_config.get("clash_proxy_pool")
            if not isinstance(clash_conf, dict):
                clash_conf = {}
                new_config["clash_proxy_pool"] = clash_conf
            clash_conf["test_proxy_url"] = applied_proxy
            cfg.reload_all_configs(new_config_dict=new_config)
            persisted = True
        except Exception as e:
            return {
                **result,
                "ok": False,
                "persisted": False,
                "applied_proxy": applied_proxy,
                "message": f"已接管运行态代理端口 {applied_proxy}，但写回配置文件失败: {e}",
            }

    return {
        **result,
        "ok": True,
        "persisted": persisted,
        "applied_proxy": applied_proxy,
        "message": (
            f"已自动识别并同步 v2rayA 本地代理端口为 {applied_proxy}，配置文件也已更新。"
            if persisted
            else f"已自动识别并接管当前运行态代理端口 {applied_proxy}。"
        ),
    }


def get_v2raya_proxy_alignment_snapshot(preferred_url=None) -> dict:
    effective_proxy = _resolve_local_proxy_url(preferred_url)
    local_proxy = get_local_proxy_diagnostics(effective_proxy)
    snapshot = {
        "effective_proxy": effective_proxy,
        "local_proxy": local_proxy,
        "detected_proxy": _v2raya_last_detected_proxy_url,
        "detected_source": _v2raya_last_detected_proxy_source,
        "recommended_proxy": "",
        "candidate_count": 0,
        "reachable_candidate_count": 0,
    }
    if local_proxy.get("reachable"):
        return snapshot
    discovery = discover_v2raya_local_proxy(preferred_url=effective_proxy, validate=False)
    snapshot["candidate_count"] = len(discovery.get("candidates") or [])
    snapshot["reachable_candidate_count"] = int(discovery.get("reachable_candidate_count") or 0)
    if discovery.get("detected_proxy"):
        snapshot["detected_proxy"] = discovery.get("detected_proxy")
        snapshot["detected_source"] = discovery.get("detected_source")
        if discovery.get("detected_proxy") != effective_proxy:
            snapshot["recommended_proxy"] = discovery.get("detected_proxy")
    return snapshot


def get_api_url_for_proxy(proxy_url: str) -> str:
    if not POOL_MODE or not proxy_url:
        return CLASH_API_URL
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        port = parsed.port
        if port and 41000 < port <= 41050:
            api_port = port + 1000
            return format_docker_url(f"http://{parsed.hostname}:{api_port}")
    except Exception:
        pass
    return CLASH_API_URL


def _find_actual_group_name(proxies_data: dict, keyword: str) -> str:
    wanted = str(keyword or "").strip().lower()
    best_name = ""
    best_score = None
    for key, meta in (proxies_data or {}).items():
        if not isinstance(meta, dict) or not isinstance(meta.get("all"), list):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        score = [0, len(meta.get("all", []))]
        name_lower = name.lower()
        if wanted and name == keyword:
            score[0] = 100
        elif wanted and name_lower == wanted:
            score[0] = 95
        elif wanted and wanted in name_lower:
            score[0] = 90
        elif any(hint in name_lower for hint in ["chatgpt", "openai", "copilot", "claude", "anthropic", "ai"]):
            score[0] = 70
        score_key = tuple(score)
        if best_score is None or score_key > best_score:
            best_score = score_key
            best_name = name
    return best_name


def _test_proxy_liveness_once(proxy_url: str, silent: bool = False):
    target_proxy = format_docker_url(str(proxy_url or "").strip())
    if not target_proxy:
        if not silent:
            print(f"[{ts()}] [代理测活] 未配置可用的本地代理地址。")
        return False
    proxies = {"http": target_proxy, "https": target_proxy}
    display_name = get_display_name(target_proxy)

    loc = "UNKNOWN"
    latency = None
    try:
        res = _call_with_original_socket(
            std_requests.get,
            "https://cloudflare.com/cdn-cgi/trace",
            proxies=proxies,
            timeout=5,
        )
        if res.status_code == 200:
            latency = round(res.elapsed.total_seconds(), 2)
            for line in res.text.split("\n"):
                if line.startswith("loc="):
                    loc = line.split("=", 1)[1].strip()
                    break
            if loc in {"CN", "HK"}:
                if not silent:
                    print(f"[{ts()}] [代理测活] {display_name} 地区受限 ({loc})，弃用！")
                return False
    except Exception:
        pass

    try:
        from curl_cffi import requests as cffi_requests

        auth_resp = cffi_requests.get(
            "https://auth.openai.com/",
            proxies=proxies,
            timeout=8,
            verify=True,
            allow_redirects=False,
            impersonate="chrome110",
        )
        if auth_resp.status_code >= 500:
            if not silent:
                print(f"[{ts()}] [代理测活] {display_name} OpenAI 入口异常 (HTTP {auth_resp.status_code})，弃用！")
            return False
    except Exception as e:
        if not silent:
            print(f"[{ts()}] [代理测活] {display_name} OpenAI TLS 校验失败: {e}")
        return False

    if not silent:
        if latency is not None:
            print(f"[{ts()}] [代理测活] {display_name} 成功！地区 ({loc})，延迟: {latency:.2f}s")
        else:
            print(f"[{ts()}] [代理测活] {display_name} 成功！OpenAI 入口可用。")
    return True


def test_proxy_liveness(proxy_url=None, silent: bool = False):
    target_proxy = _resolve_local_proxy_url(proxy_url)
    if _test_proxy_liveness_once(target_proxy, silent=silent):
        return True
    if PROXY_CLIENT_TYPE != "v2raya":
        return False
    detected = discover_v2raya_local_proxy(preferred_url=target_proxy)
    selected = detected.get("selected") or {}
    selected_proxy = str(selected.get("url") or "").strip()
    if not selected_proxy or selected_proxy == target_proxy:
        return False
    _set_runtime_default_proxy(selected_proxy, source=selected.get("source", "detected"))
    if not silent:
        print(
            f"[{ts()}] [代理测活] v2rayA 自动改用检测到的本地代理端口: "
            f"{selected_proxy} ({selected.get('source') or 'unknown'})"
        )
    return _test_proxy_liveness_once(selected_proxy, silent=silent)


def _v2raya_text(value) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _first_v2raya_text(*values) -> str:
    for value in values:
        text = _v2raya_text(value)
        if text:
            return text
    return ""


def _v2raya_unwrap_payload(payload):
    if isinstance(payload, dict) and payload.get("data") is not None:
        return payload.get("data")
    return payload


def _extract_v2raya_token(payload) -> str:
    candidates = []
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict):
            candidates.extend(
                [
                    data.get("token"),
                    data.get("authorization"),
                    data.get("Authorization"),
                    data.get("access_token"),
                    data.get("accessToken"),
                    data.get("jwt"),
                ]
            )
        candidates.extend(
            [
                payload.get("token"),
                payload.get("authorization"),
                payload.get("Authorization"),
                payload.get("access_token"),
                payload.get("accessToken"),
                payload.get("jwt"),
            ]
        )
    for item in candidates:
        text = _v2raya_text(item)
        if text:
            return text
    return ""


def _v2raya_payload_ok(payload, status_code: int) -> bool:
    if status_code >= 400:
        return False
    if isinstance(payload, dict):
        if payload.get("success") is False or payload.get("ok") is False:
            return False
        code = payload.get("code")
        if isinstance(code, int) and code >= 400:
            return False
        message = _v2raya_text(payload.get("message")).lower()
        if "unauthorized" in message or "forbidden" in message:
            return False
    return True


def _v2raya_login(session) -> list[str]:
    if not V2RAYA_PANEL_URL:
        raise RuntimeError("未配置 v2rayA 面板地址")
    if not V2RAYA_USERNAME and not V2RAYA_PASSWORD:
        return [""]
    if not V2RAYA_USERNAME or not V2RAYA_PASSWORD:
        raise RuntimeError("v2rayA API 登录名和密码需要同时填写")
    resp = session.post(
        f"{V2RAYA_PANEL_URL}/api/login",
        headers={"Accept": "application/json, text/plain, */*"},
        json={"username": V2RAYA_USERNAME, "password": V2RAYA_PASSWORD},
        timeout=10,
    )
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if not _v2raya_payload_ok(payload, resp.status_code):
        message = _first_v2raya_text(
            payload.get("message") if isinstance(payload, dict) else "",
            resp.text,
            f"HTTP {resp.status_code}",
        )
        raise RuntimeError(f"登录 v2rayA API 失败: {message}")
    token = _extract_v2raya_token(payload)
    auth_values = [""]
    if token:
        auth_values.append(token)
        if not token.lower().startswith("bearer "):
            auth_values.append(f"Bearer {token}")
    deduped = []
    for item in auth_values:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _v2raya_request(session, method: str, path: str, auth_values=None, params=None, json_body=None):
    url = f"{V2RAYA_PANEL_URL}/api/{str(path or '').lstrip('/')}"
    auth_values = auth_values[:] if auth_values else [""]
    last_resp = None
    last_payload = None
    last_auth = ""
    for auth_value in auth_values:
        headers = {"Accept": "application/json, text/plain, */*"}
        if auth_value:
            headers["Authorization"] = auth_value
        resp = session.request(method, url, headers=headers, params=params, json=json_body, timeout=12)
        try:
            payload = resp.json()
        except Exception:
            payload = {"raw": resp.text}
        if resp.status_code != 401:
            return resp, payload, auth_value
        last_resp = resp
        last_payload = payload
        last_auth = auth_value
    return last_resp, last_payload, last_auth


def _append_v2raya_ref(refs: set[str], value) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, dict):
        for key in ["id", "ID", "Id", "name", "remarks", "alias", "address", "server", "host"]:
            if key in value:
                _append_v2raya_ref(refs, value.get(key))
        return
    if isinstance(value, list):
        for item in value:
            _append_v2raya_ref(refs, item)
        return
    text = _v2raya_text(value)
    if text:
        refs.add(text)


def _collect_v2raya_current_refs(value, refs: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower_key = str(key or "").lower()
            if any(token in lower_key for token in ["current", "selected", "connected", "running", "active", "now"]):
                _append_v2raya_ref(refs, child)
            _collect_v2raya_current_refs(child, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_v2raya_current_refs(item, refs)


def _build_v2raya_node_candidate(obj: dict, ctx: dict):
    node_id = _first_v2raya_text(obj.get("id"), obj.get("ID"), obj.get("Id"), obj.get("index"), obj.get("idx"))
    name = _first_v2raya_text(
        obj.get("name"),
        obj.get("remarks"),
        obj.get("ps"),
        obj.get("alias"),
        obj.get("title"),
        obj.get("host"),
    )
    address = _first_v2raya_text(obj.get("address"), obj.get("server"), obj.get("host"), obj.get("add"))
    port = _first_v2raya_text(obj.get("port"))
    has_children = any(isinstance(obj.get(key), list) and obj.get(key) for key in ["servers", "children", "items", "nodes", "serverList"])
    if has_children and not address and not port:
        return None
    if not node_id and not name:
        return None
    if not name and not address:
        return None
    subscription_id = _first_v2raya_text(
        obj.get("sub"),
        obj.get("subId"),
        obj.get("subid"),
        obj.get("subscriptionId"),
        ctx.get("subscription_id"),
    )
    subscription_name = _first_v2raya_text(
        obj.get("subscriptionName"),
        obj.get("subName"),
        obj.get("group"),
        ctx.get("subscription_name"),
    )
    node_type = _first_v2raya_text(obj.get("_type"), obj.get("type"))
    if not node_type:
        node_type = "subscriptionServer" if subscription_id else "server"
    lower_type = node_type.lower()
    if "sub" in lower_type and "server" in lower_type:
        node_type = "subscriptionServer"
    elif "server" in lower_type:
        node_type = "server"
    key = f"{node_type}:{subscription_id or '-'}:{node_id or name or address}"
    return {
        "key": key,
        "node_id": node_id or name or address,
        "node_type": node_type,
        "subscription_id": subscription_id,
        "subscription_name": subscription_name,
        "name": name or address or node_id,
        "address": address,
        "port": port,
        "_current_hint": any(bool(obj.get(field)) for field in ["isCurrent", "current", "selected", "connected", "active"]),
        "latency_ms": None,
        "latency_source": "",
    }


def _walk_v2raya_nodes(value, nodes: dict[str, dict], current_refs: set[str], ctx=None) -> None:
    ctx = dict(ctx or {})
    if isinstance(value, dict):
        _collect_v2raya_current_refs(value, current_refs)
        candidate = _build_v2raya_node_candidate(value, ctx)
        if candidate:
            existing = nodes.get(candidate["key"])
            if existing:
                if not existing.get("subscription_name") and candidate.get("subscription_name"):
                    existing["subscription_name"] = candidate["subscription_name"]
                existing["_current_hint"] = bool(existing.get("_current_hint") or candidate.get("_current_hint"))
            else:
                nodes[candidate["key"]] = candidate
        next_ctx = dict(ctx)
        container_name = _first_v2raya_text(value.get("name"), value.get("remarks"), value.get("title"), value.get("host"))
        container_sub_id = _first_v2raya_text(value.get("sub"), value.get("subId"), value.get("subid"), value.get("subscriptionId"))
        if container_sub_id:
            next_ctx["subscription_id"] = container_sub_id
        if candidate and str(candidate.get("node_type") or "").lower() == "subscription":
            if candidate.get("node_id") and not next_ctx.get("subscription_id"):
                next_ctx["subscription_id"] = candidate["node_id"]
            if candidate.get("name"):
                next_ctx["subscription_name"] = candidate["name"]
        elif container_name and not candidate:
            next_ctx["subscription_name"] = container_name
        for key, child in value.items():
            child_ctx = dict(next_ctx)
            lower_key = str(key or "").lower()
            if lower_key in {"servers", "serverlist", "nodes", "children", "items"} and container_name and not child_ctx.get("subscription_name"):
                child_ctx["subscription_name"] = container_name
            _walk_v2raya_nodes(child, nodes, current_refs, child_ctx)
    elif isinstance(value, list):
        for item in value:
            _walk_v2raya_nodes(item, nodes, current_refs, ctx)


def _is_v2raya_switchable_node(node: dict) -> bool:
    node_type = _v2raya_text(node.get("node_type")).lower()
    if "subscription" in node_type and "server" not in node_type:
        return False
    if node.get("subscription_id") or node.get("address"):
        return True
    return "server" in node_type or not node_type


def _extract_v2raya_nodes(*sources) -> list[dict]:
    nodes = {}
    current_refs = set()
    for source in sources:
        _walk_v2raya_nodes(_v2raya_unwrap_payload(source), nodes, current_refs)
    result = []
    for item in nodes.values():
        match_values = {
            _v2raya_text(item.get("node_id")),
            _v2raya_text(item.get("name")),
            _v2raya_text(item.get("address")),
        }
        if item.get("subscription_id"):
            match_values.add(f"{item['subscription_id']}:{item['node_id']}")
        item["is_current"] = bool(item.pop("_current_hint", False) or any(value in current_refs for value in match_values if value))
        item["is_switchable"] = _is_v2raya_switchable_node(item)
        result.append(item)
    return result


def _extract_v2raya_latency_ms(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 1) if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        matched = re.search(r"(\d+(?:\.\d+)?)\s*ms", text, re.IGNORECASE)
        if matched:
            return round(float(matched.group(1)), 1)
        if re.fullmatch(r"\d+(?:\.\d+)?", text):
            return round(float(text), 1)
        return None
    if isinstance(value, dict):
        for key in ["latency", "delay", "ping", "httpLatency", "value", "ms"]:
            if key in value:
                latency = _extract_v2raya_latency_ms(value.get(key))
                if latency is not None:
                    return latency
        for child in value.values():
            latency = _extract_v2raya_latency_ms(child)
            if latency is not None:
                return latency
    if isinstance(value, list):
        for item in value:
            latency = _extract_v2raya_latency_ms(item)
            if latency is not None:
                return latency
    return None


def _build_v2raya_latency_params(node: dict) -> list[dict]:
    params_list = []
    base = {"id": node.get("node_id")}
    if node.get("subscription_id"):
        base["sub"] = node.get("subscription_id")
    for type_key in ["_type", "type"]:
        params = dict(base)
        params[type_key] = node.get("node_type")
        params_list.append(params)
    params_list.append(dict(base))
    deduped = []
    seen = set()
    for item in params_list:
        cleaned = {k: v for k, v in item.items() if _v2raya_text(v)}
        signature = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            deduped.append(cleaned)
    return deduped


def _fetch_v2raya_node_latency(session, auth_values: list[str], node: dict):
    result = dict(node)
    for endpoint in ["httpLatency", "pingLatency"]:
        for params in _build_v2raya_latency_params(node):
            resp, payload, _ = _v2raya_request(session, "GET", endpoint, auth_values=auth_values, params=params)
            if resp is None or not _v2raya_payload_ok(payload, resp.status_code):
                continue
            latency_ms = _extract_v2raya_latency_ms(_v2raya_unwrap_payload(payload))
            if latency_ms is not None:
                result["latency_ms"] = latency_ms
                result["latency_source"] = endpoint
                return result
    return result


def _get_v2raya_runtime_status(session, auth_values: list[str]) -> dict:
    status = {"running": None, "active_outbound": "", "outbounds": []}
    try:
        touch_resp, touch_payload, _ = _v2raya_request(session, "GET", "touch", auth_values=auth_values)
        if touch_resp is not None and touch_resp.status_code < 400:
            touch_data = _v2raya_unwrap_payload(touch_payload)
            if isinstance(touch_data, dict):
                running = touch_data.get("running")
                if isinstance(running, bool):
                    status["running"] = running
    except Exception:
        pass
    try:
        outbound_resp, outbound_payload, _ = _v2raya_request(
            session, "GET", "outbound", auth_values=auth_values, params={"outbound": "proxy"}
        )
        if outbound_resp is not None and outbound_resp.status_code < 400:
            outbound_data = _v2raya_unwrap_payload(outbound_payload)
            if isinstance(outbound_data, dict):
                setting = outbound_data.get("setting")
                if isinstance(setting, dict):
                    status["active_outbound"] = _first_v2raya_text(setting.get("type"), setting.get("outbound"))
    except Exception:
        pass
    try:
        outbounds_resp, outbounds_payload, _ = _v2raya_request(session, "GET", "outbounds", auth_values=auth_values)
        if outbounds_resp is not None and outbounds_resp.status_code < 400:
            outbounds_data = _v2raya_unwrap_payload(outbounds_payload)
            if isinstance(outbounds_data, dict):
                values = outbounds_data.get("outbounds")
                if isinstance(values, list):
                    status["outbounds"] = [str(item).strip() for item in values if str(item).strip()]
    except Exception:
        pass
    return status


def _log_v2raya_proxy_unavailable(node: dict, proxy_url=None) -> None:
    node_name = clean_for_log(node.get("name") or node.get("address") or node.get("node_id") or "UNKNOWN")
    proxy_diag = get_local_proxy_diagnostics(proxy_url)
    parts = [f"node={node_name}"]
    if proxy_diag.get("target_proxy"):
        parts.append(f"proxy={proxy_diag['target_proxy']}")
    if proxy_diag.get("host") and proxy_diag.get("port") is not None:
        listener = "up" if proxy_diag.get("reachable") else "down"
        parts.append(f"listener={proxy_diag['host']}:{proxy_diag['port']}({listener})")
    elif proxy_diag.get("error"):
        parts.append(proxy_diag["error"])

    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        runtime_status = _get_v2raya_runtime_status(session, auth_values)
        if runtime_status.get("running") is not None:
            parts.append(f"running={runtime_status['running']}")
        if runtime_status.get("active_outbound"):
            parts.append(f"active_outbound={runtime_status['active_outbound']}")
        if runtime_status.get("outbounds"):
            parts.append(f"outbounds={','.join(runtime_status['outbounds'])}")
    except Exception as e:
        parts.append(f"runtime_check_failed={e}")
    finally:
        session.close()

    if proxy_diag.get("error") and not proxy_diag.get("reachable"):
        parts.append(f"socket_error={proxy_diag['error']}")
    print(
        f"[{ts()}] [代理池] v2rayA 节点已切换，但本地代理出口不可用："
        f"{' | '.join(str(item) for item in parts if item)}"
    )


def _sort_v2raya_nodes(nodes: list[dict]) -> list[dict]:
    return sorted(
        nodes,
        key=lambda item: (
            0 if item.get("is_current") else 1,
            float(item.get("latency_ms")) if isinstance(item.get("latency_ms"), (int, float)) else float("inf"),
            _first_v2raya_text(item.get("subscription_name"), ""),
            _first_v2raya_text(item.get("name"), item.get("address"), item.get("node_id")),
        ),
    )


def _build_v2raya_subscription_summaries(nodes: list[dict], raw_nodes: list[dict] | None = None) -> list[dict]:
    groups: dict[str, dict] = {}

    def ensure_group(key: str, subscription_id: str = "", subscription_name: str = "", address: str = "") -> dict:
        entry = groups.get(key)
        if not entry:
            entry = {
                "id": str(subscription_id or key),
                "host": str(subscription_name or address or subscription_id or key),
                "address": str(address or ""),
                "node_count": 0,
                "current_count": 0,
                "best_latency": None,
            }
            groups[key] = entry
            return entry
        if subscription_id and not entry.get("id"):
            entry["id"] = str(subscription_id)
        if subscription_name and (not entry.get("host") or entry.get("host") == entry.get("id")):
            entry["host"] = str(subscription_name)
        if address and not entry.get("address"):
            entry["address"] = str(address)
        return entry

    for item in raw_nodes or []:
        node_type = _v2raya_text(item.get("node_type")).lower()
        if "subscription" not in node_type or "server" in node_type:
            continue
        subscription_id = _first_v2raya_text(item.get("subscription_id"), item.get("node_id"), item.get("name"))
        subscription_name = _first_v2raya_text(item.get("name"), item.get("address"), item.get("node_id"))
        key = _first_v2raya_text(subscription_id, subscription_name)
        if not key:
            continue
        ensure_group(key, subscription_id=subscription_id, subscription_name=subscription_name, address=_first_v2raya_text(item.get("address")))

    for item in nodes:
        subscription_id = _first_v2raya_text(item.get("subscription_id"))
        subscription_name = _first_v2raya_text(item.get("subscription_name"))
        key = _first_v2raya_text(subscription_id, subscription_name)
        if not key:
            continue
        entry = ensure_group(key, subscription_id=subscription_id, subscription_name=subscription_name)
        entry["node_count"] += 1
        if item.get("is_current"):
            entry["current_count"] += 1
        latency_ms = item.get("latency_ms")
        if isinstance(latency_ms, (int, float)):
            if entry["best_latency"] is None or float(latency_ms) < float(entry["best_latency"]):
                entry["best_latency"] = round(float(latency_ms), 1)

    return sorted(
        groups.values(),
        key=lambda item: (
            _first_v2raya_text(item.get("host"), item.get("address"), item.get("id")),
            _first_v2raya_text(item.get("id"), ""),
        ),
    )


def get_v2raya_nodes_snapshot(with_latency: bool = False) -> dict:
    if not V2RAYA_PANEL_URL:
        return {"nodes": [], "subscriptions": [], "message": "请先填写 v2rayA 面板地址。"}
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        touch_resp, touch_payload, _ = _v2raya_request(session, "GET", "touch", auth_values=auth_values)
        _, outbounds_payload, _ = _v2raya_request(session, "GET", "outbounds", auth_values=auth_values)
        _, outbound_payload, _ = _v2raya_request(session, "GET", "outbound", auth_values=auth_values, params={"outbound": "proxy"})
        if touch_resp is None or touch_resp.status_code >= 400:
            message = _first_v2raya_text(
                touch_payload.get("message") if isinstance(touch_payload, dict) else "",
                touch_payload.get("error") if isinstance(touch_payload, dict) else "",
                "读取 v2rayA 节点列表失败。",
            )
            raise RuntimeError(message)
        raw_nodes = _extract_v2raya_nodes(touch_payload, outbounds_payload, outbound_payload)
        nodes = [item for item in raw_nodes if item.get("is_switchable", True)]
        if with_latency and nodes:
            nodes = [_fetch_v2raya_node_latency(session, auth_values, item) for item in nodes]
        return {
            "nodes": _sort_v2raya_nodes(nodes),
            "subscriptions": _build_v2raya_subscription_summaries(nodes, raw_nodes),
            "message": "v2rayA 节点列表已刷新。",
        }
    finally:
        session.close()


def _reset_v2raya_runtime_state():
    global _v2raya_last_precheck_at
    with _v2raya_invalid_lock:
        _v2raya_invalid_node_keys.clear()
    with _v2raya_live_lock:
        _v2raya_live_nodes.clear()
    _v2raya_last_precheck_at = 0.0


def _set_v2raya_live_nodes(nodes):
    global _v2raya_last_precheck_at
    with _v2raya_live_lock:
        _v2raya_live_nodes.clear()
        _v2raya_live_nodes.extend([dict(item) for item in nodes])
    _v2raya_last_precheck_at = time.time()


def _get_v2raya_live_nodes():
    with _v2raya_live_lock:
        return [dict(item) for item in _v2raya_live_nodes]


def _store_v2raya_live_nodes(nodes):
    cleaned = []
    seen = set()
    for raw in nodes or []:
        item = dict(raw or {})
        key = str(item.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    cleaned.sort(
        key=lambda item: (
            float(item.get("latency_ms")) if isinstance(item.get("latency_ms"), (int, float)) else float("inf"),
            str(item.get("name") or item.get("address") or item.get("node_id") or ""),
        )
    )
    _set_v2raya_live_nodes(cleaned)


def _remember_v2raya_live_node(node: dict):
    node_key = str((node or {}).get("key") or "").strip()
    if not node_key:
        return
    live_nodes = [item for item in _get_v2raya_live_nodes() if str(item.get("key") or "").strip() != node_key]
    live_nodes.append(dict(node))
    _store_v2raya_live_nodes(live_nodes)


def _remove_v2raya_live_node(node_key: str):
    if not node_key:
        return
    with _v2raya_live_lock:
        _v2raya_live_nodes[:] = [item for item in _v2raya_live_nodes if item.get("key") != str(node_key)]


def _mark_v2raya_node_invalid(node_key: str):
    if not node_key:
        return
    with _v2raya_invalid_lock:
        _v2raya_invalid_node_keys.add(str(node_key))
    _remove_v2raya_live_node(node_key)


def _mark_v2raya_node_valid(node_key: str):
    if not node_key:
        return
    with _v2raya_invalid_lock:
        _v2raya_invalid_node_keys.discard(str(node_key))


def get_v2raya_invalid_node_keys():
    with _v2raya_invalid_lock:
        return sorted(str(item) for item in _v2raya_invalid_node_keys)


def is_v2raya_node_invalid(node_key: str) -> bool:
    target = str(node_key or "").strip()
    if not target:
        return False
    with _v2raya_invalid_lock:
        return target in _v2raya_invalid_node_keys


def clear_v2raya_invalid_node_keys():
    global _v2raya_last_precheck_at
    with _v2raya_invalid_lock:
        _v2raya_invalid_node_keys.clear()
    _v2raya_last_precheck_at = 0.0


def set_v2raya_node_invalid_state(node_keys, invalid: bool = True):
    changed = []
    for raw_key in node_keys or []:
        node_key = str(raw_key or "").strip()
        if not node_key:
            continue
        if invalid:
            _mark_v2raya_node_invalid(node_key)
        else:
            _mark_v2raya_node_valid(node_key)
        changed.append(node_key)
    return changed


def _list_v2raya_nodes(ignore_runtime_invalid: bool = False, with_latency: bool = False):
    snapshot = get_v2raya_nodes_snapshot(with_latency=with_latency)
    nodes = snapshot.get("nodes") or []
    with _v2raya_invalid_lock:
        invalid_keys = set(_v2raya_invalid_node_keys)
    filtered = []
    for node in nodes:
        name = _v2raya_text(node.get("name"))
        if any(str(kw).upper() in name.upper() for kw in NODE_BLACKLIST):
            continue
        if not ignore_runtime_invalid and str(node.get("key") or "") in invalid_keys:
            continue
        filtered.append(dict(node))
    return filtered


def _should_run_v2raya_precheck(force: bool = False) -> bool:
    if force:
        return True
    if not V2RAYN_PRECHECK_ON_START:
        return False
    live_nodes = _get_v2raya_live_nodes()
    if not live_nodes:
        return True
    if V2RAYN_PRECHECK_CACHE_MINUTES <= 0:
        return False
    return (time.time() - _v2raya_last_precheck_at) >= (V2RAYN_PRECHECK_CACHE_MINUTES * 60)


def _build_v2raya_switch_payloads(node: dict) -> list[dict]:
    touch_payload = {
        "id": str(node.get("node_id") or "").strip(),
        "_type": str(node.get("node_type") or "subscriptionServer").strip(),
    }
    subscription_id = str(node.get("subscription_id") or "").strip()
    if subscription_id:
        touch_payload["sub"] = subscription_id
    payloads = [
        dict(touch_payload),
        {"touch": dict(touch_payload)},
        {**touch_payload, "outbound": "proxy"},
        {"touch": dict(touch_payload), "outbound": "proxy"},
        {
            "id": str(node.get("node_id") or "").strip(),
            "sub": subscription_id,
            "type": str(node.get("node_type") or "subscriptionServer").strip(),
            "name": str(node.get("name") or "").strip(),
        },
    ]
    deduped = []
    seen = set()
    for item in payloads:
        cleaned = {}
        for k, v in item.items():
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            cleaned[k] = v
        signature = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            deduped.append(cleaned)
    return deduped


def switch_v2raya_node(node: dict) -> bool:
    if not V2RAYA_PANEL_URL:
        print(f"[{ts()}] [WARNING] v2rayA 模式未配置面板地址。")
        return False
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        last_message = ""
        for endpoint in ["connection", "outbound"]:
            for payload in _build_v2raya_switch_payloads(node):
                resp, body, _ = _v2raya_request(session, "POST", endpoint, auth_values=auth_values, json_body=payload)
                if resp is not None and _v2raya_payload_ok(body, resp.status_code):
                    return True
                if isinstance(body, dict):
                    last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
        if last_message:
            print(f"[{ts()}] [代理池] v2rayA 节点切换失败: {last_message}")
        return False
    except Exception as e:
        print(f"[{ts()}] [代理池] v2rayA 节点切换异常: {e}")
        return False
    finally:
        session.close()


def _activate_v2raya_node(node: dict, proxy_url=None):
    if not switch_v2raya_node(node):
        return False, None
    time.sleep(1.2)
    if not test_proxy_liveness(proxy_url, silent=True):
        _log_v2raya_proxy_unavailable(node, proxy_url)
        return False, None
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        with_latency = _fetch_v2raya_node_latency(session, auth_values, node)
        return True, with_latency.get("latency_ms")
    except Exception:
        return True, None
    finally:
        session.close()


def _activate_v2raya_node_runtime(node: dict, proxy_url=None):
    if not switch_v2raya_node(node):
        return False
    time.sleep(1.0)
    return True


def _find_v2raya_node(snapshot: dict, node: dict) -> dict | None:
    requested_key = _first_v2raya_text(node.get("key"))
    requested_id = _first_v2raya_text(node.get("node_id"))
    requested_type = _first_v2raya_text(node.get("node_type"), "subscriptionServer")
    requested_sub = _first_v2raya_text(node.get("subscription_id"))
    for item in snapshot.get("nodes") or []:
        if requested_key and str(item.get("key") or "").strip() == requested_key:
            return dict(item)
    for item in snapshot.get("nodes") or []:
        if str(item.get("node_id") or "").strip() != requested_id:
            continue
        if requested_sub and str(item.get("subscription_id") or "").strip() != requested_sub:
            continue
        item_type = _first_v2raya_text(item.get("node_type"), "subscriptionServer")
        if requested_type and item_type != requested_type:
            continue
        return dict(item)
    return None


def _preflight_v2raya_node(node: dict) -> tuple[bool, float | None, str]:
    if not V2RAYA_PANEL_URL:
        return False, None, "当前未配置 v2rayA 面板地址。"
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        probed = _fetch_v2raya_node_latency(session, auth_values, node)
        latency_ms = probed.get("latency_ms")
        if isinstance(latency_ms, (int, float)):
            return True, round(float(latency_ms), 1), ""
        return False, None, "目标节点未通过 v2rayA 面板延迟预检，已取消切换。"
    except Exception as e:
        return False, None, f"v2rayA 节点预检异常: {e}"
    finally:
        session.close()


def _recover_v2raya_node(previous_node: dict | None, proxy_url=None, exclude_keys=None) -> tuple[bool, dict | None]:
    excluded = {str(item or "").strip() for item in (exclude_keys or []) if str(item or "").strip()}
    candidates = []
    if previous_node and str(previous_node.get("key") or "").strip() not in excluded:
        candidates.append(dict(previous_node))
    for item in _get_v2raya_live_nodes():
        key = str(item.get("key") or "").strip()
        if not key or key in excluded or is_v2raya_node_invalid(key):
            continue
        candidates.append(dict(item))

    seen = set()
    for node in candidates:
        key = str(node.get("key") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        if not _activate_v2raya_node_runtime(node, proxy_url=proxy_url):
            continue
        if test_proxy_liveness(proxy_url, silent=True):
            _mark_v2raya_node_valid(key)
            _remember_v2raya_live_node(node)
            return True, node
        _mark_v2raya_node_invalid(key)
    return False, None


def switch_v2raya_node_safely(node: dict, proxy_url=None) -> dict:
    requested = dict(node or {})
    requested_id = _first_v2raya_text(requested.get("node_id"))
    if not requested_id:
        return {"ok": False, "message": "缺少 v2rayA 节点 ID。"}
    if not V2RAYA_PANEL_URL:
        return {"ok": False, "message": "当前未配置 v2rayA 面板地址。"}

    with _global_switch_lock:
        snapshot = get_v2raya_nodes_snapshot(with_latency=False)
        target = _find_v2raya_node(snapshot, requested)
        if not target:
            return {"ok": False, "message": "未在当前 v2rayA 节点列表中找到目标节点。", "snapshot": snapshot}

        target_key = str(target.get("key") or "").strip()
        target_name = clean_for_log(target.get("name") or target.get("address") or target.get("node_id") or requested_id)
        if target.get("is_current"):
            return {
                "ok": True,
                "node": target,
                "snapshot": snapshot,
                "message": f"当前已经是该节点：{target_name}",
            }
        if is_v2raya_node_invalid(target_key):
            return {
                "ok": False,
                "node": target,
                "snapshot": snapshot,
                "message": f"节点 {target_name} 已被标记为失效。请先清空失效标记或重新批量测活后再切换。",
            }

        current_node = next((dict(item) for item in (snapshot.get("nodes") or []) if item.get("is_current")), None)
        preflight_ok, latency_ms, preflight_message = _preflight_v2raya_node(target)
        if not preflight_ok:
            _mark_v2raya_node_invalid(target_key)
            refreshed_snapshot = get_v2raya_nodes_snapshot(with_latency=False)
            return {
                "ok": False,
                "node": target,
                "snapshot": refreshed_snapshot,
                "message": f"{preflight_message} 节点 {target_name} 已自动标记为失效。",
            }

        if not switch_v2raya_node(target):
            refreshed_snapshot = get_v2raya_nodes_snapshot(with_latency=False)
            return {
                "ok": False,
                "node": target,
                "snapshot": refreshed_snapshot,
                "message": f"v2rayA 面板拒绝切换到节点 {target_name}，请检查登录态或接口兼容性。",
            }

        time.sleep(1.2)
        if test_proxy_liveness(proxy_url, silent=True):
            target["latency_ms"] = latency_ms
            _mark_v2raya_node_valid(target_key)
            _remember_v2raya_live_node(target)
            refreshed_snapshot = get_v2raya_nodes_snapshot(with_latency=False)
            return {
                "ok": True,
                "node": target,
                "snapshot": refreshed_snapshot,
                "latency_ms": latency_ms,
                "message": (
                    f"已切换到 v2rayA 节点：{target_name}"
                    + (f" ({latency_ms}ms)" if latency_ms is not None else "")
                ),
            }

        _log_v2raya_proxy_unavailable(target, proxy_url)
        _mark_v2raya_node_invalid(target_key)
        recovered, recovered_node = _recover_v2raya_node(current_node, proxy_url=proxy_url, exclude_keys={target_key})
        refreshed_snapshot = get_v2raya_nodes_snapshot(with_latency=False)
        if recovered and recovered_node:
            recovered_name = clean_for_log(
                recovered_node.get("name") or recovered_node.get("address") or recovered_node.get("node_id") or "UNKNOWN"
            )
            return {
                "ok": False,
                "node": target,
                "recovered_node": recovered_node,
                "snapshot": refreshed_snapshot,
                "message": (
                    f"节点 {target_name} 切换后本地代理链路未恢复，已自动标记为失效，"
                    f"并回滚到 {recovered_name}。"
                ),
            }
        return {
            "ok": False,
            "node": target,
            "snapshot": refreshed_snapshot,
            "message": (
                f"节点 {target_name} 切换后本地代理链路未恢复，已自动标记为失效；"
                "自动回滚也失败了，请手动到 v2rayA 面板恢复节点。"
            ),
        }


def refresh_v2raya_live_pool(proxy_url=None, force: bool = False, reason: str = "startup"):
    summary = {"tested_count": 0, "live_count": 0, "dead_count": 0, "live_nodes": [], "reason": reason}
    if PROXY_CLIENT_TYPE != "v2raya":
        return summary
    if not V2RAYA_PANEL_URL:
        print(f"[{ts()}] [WARNING] v2rayA 模式未配置面板地址，无法执行批量测活。")
        return summary
    try:
        with _v2raya_precheck_lock:
            cached_live = _get_v2raya_live_nodes()
            if not _should_run_v2raya_precheck(force=force):
                summary["tested_count"] = len(cached_live)
                summary["live_count"] = len(cached_live)
                summary["live_nodes"] = cached_live
                return summary

            candidates = _list_v2raya_nodes(ignore_runtime_invalid=False, with_latency=False)
            if not candidates:
                print(f"[{ts()}] [ERROR] v2rayA 批量测活前未找到可用节点，请先清空失效标记或刷新节点列表。")
                _set_v2raya_live_nodes([])
                return summary

            current_node = next((item for item in candidates if item.get("is_current")), None)
            remaining = [item for item in candidates if item.get("key") != (current_node or {}).get("key")]
            random.shuffle(remaining)
            max_nodes = V2RAYN_PRECHECK_MAX_NODES
            if max_nodes > 0:
                slots = max(0, max_nodes - (1 if current_node else 0))
                targets = ([current_node] if current_node else []) + remaining[:slots]
            else:
                targets = ([current_node] if current_node else []) + remaining

            print(f"[{ts()}] [代理池] v2rayA 启动预检: 准备批量测活 {len(targets)} 个候选节点...")
            live_nodes = []
            current_key = str((current_node or {}).get("key") or "")
            for idx, node in enumerate(targets, 1):
                summary["tested_count"] += 1
                node_name = clean_for_log(node.get("name") or node.get("address") or node.get("node_id") or "UNKNOWN")
                print(f"\n[{ts()}] [代理池] v2rayA 批量测活节点: [{node_name}] ({idx}/{len(targets)})")
                print(f"[{ts()}] [代理池] 节点切换详情: old={current_key or 'UNKNOWN'} -> new={node.get('key')}")
                is_ok, latency_ms = _activate_v2raya_node(node, proxy_url)
                if is_ok:
                    node_with_latency = dict(node)
                    node_with_latency["latency_ms"] = latency_ms if latency_ms is not None else float("inf")
                    live_nodes.append(node_with_latency)
                    _mark_v2raya_node_valid(node.get("key"))
                    current_key = str(node.get("key") or "")
                else:
                    summary["dead_count"] += 1
                    _mark_v2raya_node_invalid(node.get("key"))

            live_nodes.sort(key=lambda item: (float(item.get("latency_ms", float("inf"))), str(item.get("name") or "")))
            if V2RAYN_LIVE_POOL_LIMIT > 0 and len(live_nodes) > V2RAYN_LIVE_POOL_LIMIT:
                live_nodes = live_nodes[:V2RAYN_LIVE_POOL_LIMIT]
            _store_v2raya_live_nodes(live_nodes)
            summary["live_nodes"] = _get_v2raya_live_nodes()
            summary["live_count"] = len(summary["live_nodes"])
            summary["dead_count"] = max(summary["dead_count"], summary["tested_count"] - summary["live_count"])
            return summary
    except Exception as e:
        print(f"[{ts()}] [ERROR] v2rayA 批量测活异常: {e}")
        return summary


def _switch_v2raya_node(proxy_url=None):
    target_proxy = proxy_url if proxy_url else LOCAL_PROXY_URL
    display_name = get_display_name(target_proxy)
    if not V2RAYA_PANEL_URL:
        print(f"[{ts()}] [WARNING] v2rayA 模式未配置面板地址，改为仅校验当前代理链路: {display_name}")
        ok = test_proxy_liveness(proxy_url)
        _record_switch_result(ok, "v2raya", f"v2rayA 未配置面板地址，沿用当前链路 {display_name}", display_name, target_proxy)
        return ok
    if POOL_MODE:
        print(f"[{ts()}] [WARNING] v2rayA 模式暂不支持独享池模式，已忽略 pool_mode 配置。")
    try:
        current_nodes = _list_v2raya_nodes(ignore_runtime_invalid=True, with_latency=False)
        current_node = next((item for item in current_nodes if item.get("is_current")), None)
        current_key = str((current_node or {}).get("key") or "")
        if V2RAYN_PRECHECK_ON_START:
            candidates = refresh_v2raya_live_pool(proxy_url, force=False, reason="switch").get("live_nodes") or _list_v2raya_nodes()
        else:
            candidates = _list_v2raya_nodes()
        if not candidates:
            if V2RAYN_PRECHECK_ON_START:
                rebuilt = refresh_v2raya_live_pool(proxy_url, force=True, reason="rebuild_after_pool_empty")
                candidates = rebuilt.get("live_nodes") or _list_v2raya_nodes()
                if not candidates:
                    _record_switch_result(False, "v2raya", "v2rayA 活节点池为空，无法切换节点。", "", target_proxy)
                    return False
            else:
                _record_switch_result(False, "v2raya", "v2rayA 节点列表为空，无法切换节点。", "", target_proxy)
                return False
        candidates = [dict(item) for item in candidates]
        random.shuffle(candidates)
        ordered = [item for item in candidates if item.get("key") != current_key] or candidates
        max_retries = min(8, len(ordered))
        for node in ordered[:max_retries]:
            target_name = clean_for_log(node.get("name") or node.get("node_id") or node.get("address") or "未命名节点")
            if _activate_v2raya_node_runtime(node, proxy_url):
                if V2RAYN_PRECHECK_ON_START:
                    _mark_v2raya_node_valid(node.get("key"))
                    _record_switch_result(True, "v2raya", f"已切换到 v2rayA 节点：{target_name}", target_name, target_proxy)
                    return True
                if test_proxy_liveness(proxy_url, silent=True):
                    _record_switch_result(True, "v2raya", f"已切换到 v2rayA 节点：{target_name}", target_name, target_proxy)
                    return True
                _log_v2raya_proxy_unavailable(node, proxy_url)
                _mark_v2raya_node_invalid(node.get("key"))
                _record_switch_result(False, "v2raya", f"已尝试切换到 v2rayA 节点 {target_name}，但链路未恢复。", target_name, target_proxy)
                continue
            _mark_v2raya_node_invalid(node.get("key"))
            _record_switch_result(False, "v2raya", f"切换 v2rayA 节点失败：{target_name}", target_name, target_proxy)
        _record_switch_result(False, "v2raya", "v2rayA 多个候选节点切换均失败。", "", target_proxy)
        return False
    except Exception as e:
        _record_switch_result(False, "v2raya", f"v2rayA 切换异常: {e}", "", target_proxy)
        print(f"[{ts()}] [ERROR] v2rayA 自动切换异常: {e}")
        return False


def _read_v2rayn_gui_config():
    if not V2RAYN_GUI_CONFIG_PATH or not os.path.exists(V2RAYN_GUI_CONFIG_PATH):
        print(f"[{ts()}] [ERROR] v2rayN 配置文件不存在，请检查 v2rayN 根目录。")
        return None
    try:
        with open(V2RAYN_GUI_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[{ts()}] [ERROR] 读取 v2rayN 配置失败: {e}")
        return None


def _get_v2rayn_inbound_proxy_url(preferred_url=None) -> str:
    raw = str(preferred_url or "").strip()
    cfg = _read_v2rayn_gui_config() or {}
    inbounds = cfg.get("Inbound") or []
    if not isinstance(inbounds, list) or not inbounds:
        return raw
    inbound = inbounds[0] if isinstance(inbounds[0], dict) else {}
    local_port = inbound.get("LocalPort")
    protocol = str(inbound.get("Protocol") or "").strip().lower()
    if not local_port or protocol not in {"socks", "http", "mixed"}:
        return raw
    scheme_map = {"socks": "socks5", "http": "http", "mixed": "http"}
    expected_scheme = scheme_map.get(protocol, "http")
    try:
        parsed = urllib.parse.urlparse(raw) if raw else None
    except Exception:
        parsed = None
    if parsed and parsed.hostname and parsed.port:
        host = parsed.hostname
        port = parsed.port
    else:
        host = "127.0.0.1"
        port = int(local_port)
    if port == int(local_port):
        return f"{expected_scheme}://{host}:{port}"
    return raw


def _get_v2rayn_ping_test_url() -> str:
    cfg = _read_v2rayn_gui_config() or {}
    speed_item = cfg.get("SpeedTestItem") or {}
    url = str(speed_item.get("SpeedPingTestUrl") or "").strip()
    return url or "https://www.google.com/generate_204"


def _get_v2rayn_probe_urls() -> list[str]:
    urls = []
    primary = _get_v2rayn_ping_test_url()
    if primary:
        urls.append(primary)
    for item in ["https://www.gstatic.com/generate_204"]:
        if item not in urls:
            urls.append(item)
    return urls


def _reset_v2rayn_runtime_state():
    global _v2rayn_last_precheck_at, _v2rayn_last_subscription_update_at
    with _v2rayn_invalid_lock:
        _v2rayn_invalid_index_ids.clear()
    with _v2rayn_live_lock:
        _v2rayn_live_profiles.clear()
    _v2rayn_last_precheck_at = 0.0
    _v2rayn_last_subscription_update_at = 0.0


def _set_v2rayn_live_profiles(profiles):
    global _v2rayn_last_precheck_at
    with _v2rayn_live_lock:
        _v2rayn_live_profiles.clear()
        _v2rayn_live_profiles.extend([dict(p) for p in profiles])
    _v2rayn_last_precheck_at = time.time()


def _get_v2rayn_live_profiles():
    with _v2rayn_live_lock:
        return [dict(p) for p in _v2rayn_live_profiles]


def _remove_v2rayn_live_profile(index_id: str):
    if not index_id:
        return
    with _v2rayn_live_lock:
        _v2rayn_live_profiles[:] = [p for p in _v2rayn_live_profiles if p.get("index_id") != str(index_id)]


def _list_v2rayn_profiles(ignore_runtime_invalid: bool = False):
    if not V2RAYN_DB_PATH or not os.path.exists(V2RAYN_DB_PATH):
        print(f"[{ts()}] [ERROR] v2rayN 数据库不存在，请检查 v2rayN 根目录。")
        return []
    try:
        conn = sqlite3.connect(V2RAYN_DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT IndexId, Remarks, Address, Port, Subid FROM ProfileItem").fetchall()
        conn.close()
    except Exception as e:
        print(f"[{ts()}] [ERROR] 读取 v2rayN 节点列表失败: {e}")
        return []
    with _v2rayn_invalid_lock:
        invalid_ids = set(_v2rayn_invalid_index_ids)
    result = []
    for row in rows:
        remarks = str(row["Remarks"] or "").strip()
        if not remarks:
            continue
        if not ignore_runtime_invalid and str(row["IndexId"]) in invalid_ids:
            continue
        if any(str(kw).upper() in remarks.upper() for kw in NODE_BLACKLIST):
            continue
        result.append(
            {
                "index_id": str(row["IndexId"]),
                "remarks": remarks,
                "address": str(row["Address"] or "").strip(),
                "port": row["Port"],
                "subid": str(row["Subid"] or "").strip(),
            }
        )
    if not result and invalid_ids:
        with _v2rayn_invalid_lock:
            _v2rayn_invalid_index_ids.clear()
        return _list_v2rayn_profiles(ignore_runtime_invalid=ignore_runtime_invalid)
    return result


def _get_v2rayn_profile_by_id(index_id: str):
    if not index_id or not V2RAYN_DB_PATH or not os.path.exists(V2RAYN_DB_PATH):
        return None
    try:
        conn = sqlite3.connect(V2RAYN_DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT IndexId, Remarks, Address, Port, Subid FROM ProfileItem WHERE IndexId = ?",
            (str(index_id),),
        ).fetchone()
        conn.close()
    except Exception:
        return None
    if not row:
        return None
    return {
        "index_id": str(row["IndexId"]),
        "remarks": str(row["Remarks"] or "").strip(),
        "address": str(row["Address"] or "").strip(),
        "port": row["Port"],
        "subid": str(row["Subid"] or "").strip(),
    }


def _mark_v2rayn_profile_invalid(index_id: str):
    if not index_id:
        return
    with _v2rayn_invalid_lock:
        _v2rayn_invalid_index_ids.add(str(index_id))
    _remove_v2rayn_live_profile(index_id)


def _mark_v2rayn_profile_valid(index_id: str):
    if not index_id:
        return
    with _v2rayn_invalid_lock:
        _v2rayn_invalid_index_ids.discard(str(index_id))


def get_v2rayn_invalid_index_ids():
    with _v2rayn_invalid_lock:
        return sorted(str(item) for item in _v2rayn_invalid_index_ids)


def clear_v2rayn_invalid_index_ids():
    global _v2rayn_last_precheck_at
    with _v2rayn_invalid_lock:
        _v2rayn_invalid_index_ids.clear()
    _v2rayn_last_precheck_at = 0.0


def set_v2rayn_profile_invalid_state(index_ids, invalid: bool = True):
    changed = []
    for raw_id in index_ids or []:
        index_id = str(raw_id or "").strip()
        if not index_id:
            continue
        if invalid:
            _mark_v2rayn_profile_invalid(index_id)
        else:
            _mark_v2rayn_profile_valid(index_id)
        changed.append(index_id)
    return changed


def get_v2rayn_profiles_snapshot(include_invalid: bool = True):
    profiles = _list_v2rayn_profiles(ignore_runtime_invalid=include_invalid)
    runtime_cfg = _read_v2rayn_gui_config() or {}
    current_id = str(runtime_cfg.get("IndexId") or "").strip()
    live_ids = {str(item.get("index_id") or "").strip() for item in _get_v2rayn_live_profiles()}
    with _v2rayn_invalid_lock:
        invalid_ids = set(str(item) for item in _v2rayn_invalid_index_ids)
    result = []
    for item in profiles:
        profile = dict(item)
        index_id = str(profile.get("index_id") or "").strip()
        profile["is_current"] = bool(index_id and index_id == current_id)
        profile["is_live"] = bool(index_id and index_id in live_ids)
        profile["is_invalid"] = bool(index_id and index_id in invalid_ids)
        result.append(profile)
    result.sort(
        key=lambda item: (
            0 if item.get("is_current") else 1,
            0 if item.get("is_live") else 1,
            1 if item.get("is_invalid") else 0,
            str(item.get("remarks") or ""),
        )
    )
    return {
        "current_index_id": current_id,
        "total_count": len(result),
        "live_count": len([item for item in result if item.get("is_live")]),
        "invalid_count": len([item for item in result if item.get("is_invalid")]),
        "nodes": result,
    }


def _write_v2rayn_selection(profile):
    cfg = _read_v2rayn_gui_config()
    if not cfg:
        return False
    cfg["IndexId"] = profile["index_id"]
    cfg.pop("SubIndexId", None)
    if V2RAYN_HIDE_WINDOW_ON_RESTART:
        ui_item = cfg.get("UiItem") or {}
        ui_item["AutoHideStartup"] = True
        cfg["UiItem"] = ui_item
    try:
        with open(V2RAYN_GUI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[{ts()}] [ERROR] 写入 v2rayN 当前节点失败: {e}")
        return False


def _restart_v2rayn():
    if not V2RAYN_EXE_PATH or not os.path.exists(V2RAYN_EXE_PATH):
        print(f"[{ts()}] [ERROR] 未找到 v2rayN.exe，请先配置 v2rayN 根目录。")
        return False
    hidden_kwargs = _hidden_subprocess_kwargs()
    try:
        subprocess.run(["taskkill", "/IM", "xray.exe", "/F"], capture_output=True, text=True, **hidden_kwargs)
        subprocess.run(["taskkill", "/IM", "v2rayN.exe", "/F"], capture_output=True, text=True, **hidden_kwargs)
        time.sleep(0.8)
        subprocess.Popen(
            [V2RAYN_EXE_PATH],
            cwd=V2RAYN_BASE_DIR if V2RAYN_BASE_DIR else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **hidden_kwargs,
        )
        return True
    except Exception as e:
        print(f"[{ts()}] [ERROR] 重启 v2rayN 失败: {e}")
        return False


def _wait_for_local_proxy_ready(proxy_url=None, timeout_sec=None):
    target_proxy = _get_v2rayn_inbound_proxy_url(proxy_url if proxy_url else LOCAL_PROXY_URL)
    parsed = urllib.parse.urlparse(target_proxy)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if not port:
        return False
    timeout_limit = max(3, int(timeout_sec or V2RAYN_RESTART_WAIT_SEC))
    start = time.time()
    while time.time() - start < timeout_limit:
        try:
            with _call_with_original_socket(socket.create_connection, (host, port), 0.8):
                return True
        except Exception:
            time.sleep(0.25)
    print(f"[{ts()}] [WARNING] v2rayN 本地代理端口 {host}:{port} 在 {timeout_limit}s 内未恢复监听。")
    return False


def _test_v2rayn_proxy_liveness(proxy_url=None, silent: bool = False):
    raw_url = _get_v2rayn_inbound_proxy_url(proxy_url if proxy_url else LOCAL_PROXY_URL)
    target_proxy = format_docker_url(raw_url)
    proxies = {"http": target_proxy, "https": target_proxy}
    display_name = get_display_name(proxy_url if proxy_url else LOCAL_PROXY_URL)
    probe_urls = _get_v2rayn_probe_urls()
    last_error = None
    for attempt in range(2):
        probe_res = None
        probe_url = ""
        try:
            for probe_url in probe_urls:
                try:
                    probe_res = _call_with_original_socket(std_requests.get, probe_url, proxies=proxies, timeout=6.5)
                    if probe_res.status_code in (200, 204):
                        break
                    probe_res = None
                except Exception as exc:
                    last_error = exc
                    probe_res = None
            if probe_res is None:
                raise last_error or RuntimeError("all probe urls failed")
            try:
                trace_res = _call_with_original_socket(
                    std_requests.get,
                    "https://cloudflare.com/cdn-cgi/trace",
                    proxies=proxies,
                    timeout=4.0,
                )
                if trace_res.status_code == 200:
                    loc = "UNKNOWN"
                    for line in trace_res.text.split("\n"):
                        if line.startswith("loc="):
                            loc = line.split("=")[1].strip()
                    if loc in {"CN", "HK"}:
                        if not silent:
                            print(f"[{ts()}] [代理测活] {display_name} 地区受限 ({loc})，立即切换下一节点。")
                        return False, loc, None
                    return True, loc, round(float(probe_res.elapsed.total_seconds() * 1000), 1)
            except Exception:
                pass
            return True, "UNKNOWN", round(float(probe_res.elapsed.total_seconds() * 1000), 1)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1.0)
                continue
    if not silent:
        print(f"[{ts()}] [代理测活] {display_name} 链路中断或超时。{f' ({last_error})' if last_error else ''}")
    return False, None, None


def _activate_v2rayn_profile(profile, proxy_url=None):
    if not _write_v2rayn_selection(profile):
        return False, None, None
    if not _restart_v2rayn():
        return False, None, None
    if not _wait_for_local_proxy_ready(proxy_url, timeout_sec=V2RAYN_RESTART_WAIT_SEC):
        return False, None, None
    time.sleep(0.8)
    return _test_v2rayn_proxy_liveness(proxy_url)


def _activate_v2rayn_profile_runtime(profile, proxy_url=None):
    if not _write_v2rayn_selection(profile):
        return False
    if not _restart_v2rayn():
        return False
    if not _wait_for_local_proxy_ready(proxy_url, timeout_sec=V2RAYN_RESTART_WAIT_SEC):
        return False
    time.sleep(0.8)
    return True


def switch_v2rayn_profile(index_id: str, proxy_url=None) -> dict:
    selected_id = str(index_id or "").strip()
    if not selected_id:
        return {"ok": False, "message": "缺少 v2rayN 节点 IndexId。"}
    if not V2RAYN_BASE_DIR:
        return {"ok": False, "message": "当前未配置 v2rayN 根目录。"}

    profile = _get_v2rayn_profile_by_id(selected_id)
    if not profile:
        return {"ok": False, "message": f"未找到 IndexId={selected_id} 对应的 v2rayN 节点。"}

    with _global_switch_lock:
        _mark_v2rayn_profile_valid(selected_id)
        ok, loc, latency_ms = _activate_v2rayn_profile(profile, proxy_url=proxy_url)
        if not ok:
            _mark_v2rayn_profile_invalid(selected_id)
            return {
                "ok": False,
                "profile": profile,
                "message": f"已尝试切换到 {profile['remarks']}，但本地链路未恢复或测活失败，已自动标记为失效。",
            }

    return {
        "ok": True,
        "profile": profile,
        "location": loc,
        "latency_ms": latency_ms,
        "message": (
            f"已切换到 v2rayN 节点：{profile['remarks']}"
            + (f" ({latency_ms}ms / {loc or 'UNKNOWN'})" if latency_ms is not None else "")
        ),
    }


def _should_run_v2rayn_precheck(force: bool = False) -> bool:
    if force:
        return True
    if not V2RAYN_PRECHECK_ON_START:
        return False
    live_profiles = _get_v2rayn_live_profiles()
    if not live_profiles:
        return True
    if V2RAYN_PRECHECK_CACHE_MINUTES <= 0:
        return False
    return (time.time() - _v2rayn_last_precheck_at) >= (V2RAYN_PRECHECK_CACHE_MINUTES * 60)


def _run_v2rayn_subscription_update(force: bool = False) -> bool:
    global _v2rayn_last_subscription_update_at
    if PROXY_CLIENT_TYPE != "v2rayn":
        return False
    if not V2RAYN_SUBSCRIPTION_UPDATE_ENABLED and not force:
        return False
    if not V2RAYN_SUBSCRIPTION_UPDATE_COMMAND:
        return False
    if not force:
        interval_sec = max(0, int(V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES)) * 60
        if interval_sec <= 0:
            return False
        if _v2rayn_last_subscription_update_at > 0 and (time.time() - _v2rayn_last_subscription_update_at) < interval_sec:
            return False
    try:
        proc = subprocess.run(
            V2RAYN_SUBSCRIPTION_UPDATE_COMMAND,
            cwd=V2RAYN_BASE_DIR if V2RAYN_BASE_DIR else None,
            capture_output=True,
            text=True,
            timeout=300,
            shell=True,
            **_hidden_subprocess_kwargs(),
        )
        if proc.returncode != 0:
            return False
        _v2rayn_last_subscription_update_at = time.time()
        return True
    except Exception:
        return False


def run_v2rayn_subscription_update_only() -> tuple[bool, str]:
    if PROXY_CLIENT_TYPE != "v2rayn":
        return False, "当前代理客户端不是 v2rayN，无需执行该操作。"
    if not V2RAYN_BASE_DIR:
        return False, "当前未配置 v2rayN 根目录。"
    if not V2RAYN_SUBSCRIPTION_UPDATE_COMMAND:
        return False, "当前未配置 v2rayN 订阅更新命令。"
    if _run_v2rayn_subscription_update(force=True):
        global _v2rayn_last_precheck_at
        _v2rayn_last_precheck_at = 0.0
        return True, "v2rayN 订阅更新已完成，下次切换节点时会自动重筛活节点池。"
    return False, "v2rayN 订阅更新失败，请检查本地 v2rayN 状态或更新脚本。"


def refresh_v2rayn_live_pool(proxy_url=None, force: bool = False, reason: str = "startup", refresh_subscription: bool = False):
    summary = {"tested_count": 0, "live_count": 0, "dead_count": 0, "live_profiles": [], "subscription_updated": False, "reason": reason}
    if PROXY_CLIENT_TYPE != "v2rayn":
        return summary
    if not V2RAYN_BASE_DIR:
        print(f"[{ts()}] [WARNING] v2rayN 模式未配置根目录，无法执行批量测活。")
        return summary
    with _v2rayn_precheck_lock:
        summary["subscription_updated"] = _run_v2rayn_subscription_update(force=refresh_subscription)
        if summary["subscription_updated"]:
            force = True
        cached_live = _get_v2rayn_live_profiles()
        if not _should_run_v2rayn_precheck(force=force):
            summary["tested_count"] = len(cached_live)
            summary["live_count"] = len(cached_live)
            summary["live_profiles"] = cached_live
            return summary
        gui_cfg = _read_v2rayn_gui_config() or {}
        current_id = str(gui_cfg.get("IndexId") or "").strip()
        candidates = _list_v2rayn_profiles(ignore_runtime_invalid=True)
        if not candidates:
            _set_v2rayn_live_profiles([])
            return summary
        current_profile = None
        remaining = []
        for profile in candidates:
            if profile["index_id"] == current_id and current_profile is None:
                current_profile = profile
            else:
                remaining.append(profile)
        random.shuffle(remaining)
        max_nodes = V2RAYN_PRECHECK_MAX_NODES
        if max_nodes > 0:
            slots = max(0, max_nodes - (1 if current_profile else 0))
            targets = ([current_profile] if current_profile else []) + remaining[:slots]
        else:
            targets = ([current_profile] if current_profile else []) + remaining
        live_profiles = []
        for profile in targets:
            summary["tested_count"] += 1
            is_ok, _, latency_ms = _activate_v2rayn_profile(profile, proxy_url)
            if is_ok:
                profile_with_latency = dict(profile)
                profile_with_latency["latency_ms"] = latency_ms if latency_ms is not None else float("inf")
                live_profiles.append(profile_with_latency)
                _mark_v2rayn_profile_valid(profile["index_id"])
                current_id = profile["index_id"]
            else:
                summary["dead_count"] += 1
                _mark_v2rayn_profile_invalid(profile["index_id"])
        live_profiles.sort(key=lambda p: (float(p.get("latency_ms", float("inf"))), str(p.get("remarks") or "")))
        if V2RAYN_LIVE_POOL_LIMIT > 0 and len(live_profiles) > V2RAYN_LIVE_POOL_LIMIT:
            live_profiles = live_profiles[:V2RAYN_LIVE_POOL_LIMIT]
        _set_v2rayn_live_profiles(live_profiles)
        summary["live_profiles"] = _get_v2rayn_live_profiles()
        summary["live_count"] = len(summary["live_profiles"])
        summary["dead_count"] = max(summary["dead_count"], summary["tested_count"] - summary["live_count"])
        return summary


def prepare_proxy_runtime(proxy_url=None, reason: str = "startup"):
    if ENABLE_NODE_SWITCH and PROXY_CLIENT_TYPE == "v2rayn" and V2RAYN_PRECHECK_ON_START:
        return refresh_v2rayn_live_pool(proxy_url, force=False, reason=reason)
    if ENABLE_NODE_SWITCH and PROXY_CLIENT_TYPE == "v2raya" and V2RAYN_PRECHECK_ON_START:
        return refresh_v2raya_live_pool(proxy_url, force=False, reason=reason)
    return {"tested_count": 0, "live_count": 0, "dead_count": 0, "live_profiles": [], "subscription_updated": False, "reason": reason}


def _switch_v2rayn_node(proxy_url=None):
    target_proxy = proxy_url if proxy_url else LOCAL_PROXY_URL
    display_name = get_display_name(target_proxy)
    if not V2RAYN_BASE_DIR:
        print(f"[{ts()}] [WARNING] v2rayN 模式未配置根目录，改为仅校验当前代理链路: {display_name}")
        ok = test_proxy_liveness(proxy_url)
        _record_switch_result(ok, "v2rayn", f"v2rayN 未配置根目录，沿用当前链路 {display_name}", display_name, target_proxy)
        return ok
    cfg = _read_v2rayn_gui_config()
    if not cfg:
        _record_switch_result(False, "v2rayn", "读取 v2rayN 配置失败，无法切换节点。", "", target_proxy)
        return False
    current_id = str(cfg.get("IndexId") or "").strip()
    if V2RAYN_PRECHECK_ON_START:
        candidates = refresh_v2rayn_live_pool(proxy_url, force=False, reason="switch").get("live_profiles") or _list_v2rayn_profiles()
    else:
        candidates = _list_v2rayn_profiles()
        if not candidates:
            if V2RAYN_PRECHECK_ON_START:
                rebuilt = refresh_v2rayn_live_pool(proxy_url, force=True, reason="rebuild_after_pool_empty", refresh_subscription=True)
                candidates = rebuilt.get("live_profiles") or _list_v2rayn_profiles()
                if not candidates:
                    _record_switch_result(False, "v2rayn", "v2rayN 活节点池为空，无法切换节点。", "", target_proxy)
                    return False
            else:
                _record_switch_result(False, "v2rayn", "v2rayN 节点列表为空，无法切换节点。", "", target_proxy)
                return False
    candidates = [dict(p) for p in candidates]
    random.shuffle(candidates)
    ordered = [p for p in candidates if p["index_id"] != current_id] or candidates
    max_retries = min(8, len(ordered))
    for profile in ordered[:max_retries]:
        target_name = clean_for_log(profile.get("remarks") or profile.get("address") or profile.get("index_id") or "未命名节点")
        if _activate_v2rayn_profile_runtime(profile, proxy_url):
            if V2RAYN_PRECHECK_ON_START:
                _mark_v2rayn_profile_valid(profile["index_id"])
                _record_switch_result(True, "v2rayn", f"已切换到 v2rayN 节点：{target_name}", target_name, target_proxy)
                return True
            is_ok, _, _ = _test_v2rayn_proxy_liveness(proxy_url, silent=True)
            if is_ok:
                _record_switch_result(True, "v2rayn", f"已切换到 v2rayN 节点：{target_name}", target_name, target_proxy)
                return True
            _mark_v2rayn_profile_invalid(profile["index_id"])
            _record_switch_result(False, "v2rayn", f"已尝试切换到 v2rayN 节点 {target_name}，但链路未恢复。", target_name, target_proxy)
            continue
        _mark_v2rayn_profile_invalid(profile["index_id"])
        _record_switch_result(False, "v2rayn", f"切换 v2rayN 节点失败：{target_name}", target_name, target_proxy)
    _record_switch_result(False, "v2rayn", "v2rayN 多个候选节点切换均失败。", "", target_proxy)
    return False


def smart_switch_node(proxy_url=None):
    global _last_switch_time
    if not ENABLE_NODE_SWITCH:
        _record_switch_result(True, PROXY_CLIENT_TYPE, "当前未启用自动切点，继续沿用现有链路。", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
        return True
    if PROXY_CLIENT_TYPE == "v2rayn":
        return _switch_v2rayn_node(proxy_url)
    if PROXY_CLIENT_TYPE == "v2raya":
        return _switch_v2raya_node(proxy_url)

    if POOL_MODE and proxy_url:
        return _do_smart_switch(proxy_url)

    with _global_switch_lock:
        if time.time() - _last_switch_time < 10:
            print(f"[{ts()}] [代理池] 其他线程刚完成切换，跳过本次请求...")
            _record_switch_result(True, PROXY_CLIENT_TYPE, "其他线程刚完成切换，本次沿用最新链路。", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
            return True
        success = _do_smart_switch(proxy_url)
        if success:
            _last_switch_time = time.time()
        return success


def _do_smart_switch(proxy_url=None):
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    display_name = get_display_name(proxy_url)
    api_display = get_display_name(current_api_url).replace("号机", "号API")
    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code != 200:
            _record_switch_result(False, "clash", f"无法连接 Clash API ({api_display})", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
            print(f"[{ts()}] [ERROR] 无法连接 Clash API ({api_display})，请检查容器状态。")
            return False
        proxies_data = resp.json().get("proxies", {})
        actual_group_name = _find_actual_group_name(proxies_data, PROXY_GROUP_NAME)
        if not actual_group_name:
            _record_switch_result(False, "clash", f"{display_name} 找不到策略组关键词 '{PROXY_GROUP_NAME}'", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
            print(f"[{ts()}] [ERROR] {display_name} 找不到策略组关键词 '{PROXY_GROUP_NAME}'")
            return False
        safe_group_name = urllib.parse.quote(actual_group_name, safe="")
        all_nodes = proxies_data.get(actual_group_name, {}).get("all", [])
        valid_nodes = []
        for n in all_nodes:
            node_name = str(n or "").strip()
            if not node_name or node_name == actual_group_name:
                continue
            node_meta = proxies_data.get(node_name, {})
            if isinstance(node_meta, dict) and "all" in node_meta:
                continue
            if any(str(kw).upper() in node_name.upper() for kw in NODE_BLACKLIST):
                continue
            valid_nodes.append(node_name)
        if not valid_nodes:
            _record_switch_result(False, "clash", f"{display_name} 过滤后无可用节点，请检查黑名单。", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
            print(f"[{ts()}] [ERROR] {display_name} 过滤后无可用节点，请检查黑名单。")
            return False

        if FASTEST_MODE:
            session = std_requests.Session()
            def trigger_delay(n):
                enc_n = urllib.parse.quote(n, safe="")
                try:
                    session.get(
                        f"{current_api_url}/proxies/{enc_n}/delay?timeout=2000&url=http://www.gstatic.com/generate_204",
                        headers=headers,
                        timeout=2.5,
                    )
                except Exception:
                    pass
            with ThreadPoolExecutor(max_workers=min(10, len(valid_nodes))) as executor:
                executor.map(trigger_delay, valid_nodes)
            session.close()
            time.sleep(1.5)
            try:
                resp2 = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
                if resp2.status_code == 200:
                    p_data = resp2.json().get("proxies", {})
                    best_node = None
                    min_delay = float("inf")
                    for n in valid_nodes:
                        history = p_data.get(n, {}).get("history", [])
                        if history:
                            delay = history[-1].get("delay", 0)
                            if 0 < delay < min_delay:
                                min_delay = delay
                                best_node = n
                    if best_node:
                        switch_resp = std_requests.put(
                            f"{current_api_url}/proxies/{safe_group_name}",
                            headers=headers,
                            json={"name": best_node},
                            timeout=5,
                        )
                        if switch_resp.status_code == 204:
                            time.sleep(1.0)
                            if test_proxy_liveness(proxy_url, silent=True):
                                target_name = clean_for_log(best_node)
                                _record_switch_result(True, "clash", f"已切换到 Clash 节点：{target_name}", target_name, proxy_url if proxy_url else LOCAL_PROXY_URL)
                                return True
            except Exception:
                pass

        random.shuffle(valid_nodes)
        max_retries = min(10, len(valid_nodes))
        for selected_node in valid_nodes[:max_retries]:
            switch_resp = std_requests.put(
                f"{current_api_url}/proxies/{safe_group_name}",
                headers=headers,
                json={"name": selected_node},
                timeout=5,
            )
            if switch_resp.status_code == 204:
                time.sleep(1.5)
                if test_proxy_liveness(proxy_url, silent=True):
                    target_name = clean_for_log(selected_node)
                    _record_switch_result(True, "clash", f"已切换到 Clash 节点：{target_name}", target_name, proxy_url if proxy_url else LOCAL_PROXY_URL)
                    return True
        _record_switch_result(False, "clash", f"{display_name} 候选节点切换后链路仍不可用。", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
        return False
    except Exception as e:
        _record_switch_result(False, "clash", f"{display_name} 切换节点异常: {e}", "", proxy_url if proxy_url else LOCAL_PROXY_URL)
        print(f"[{ts()}] [ERROR] {display_name} 切换节点异常: {e}")
        return False


reload_proxy_config()
