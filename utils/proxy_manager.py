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
V2RAYN_RESTART_WAIT_SEC = 4
V2RAYN_HIDE_WINDOW_ON_RESTART = True
V2RAYN_PRECHECK_ON_START = False
V2RAYN_PRECHECK_CACHE_MINUTES = 30
V2RAYN_PRECHECK_MAX_NODES = 12
V2RAYN_LIVE_POOL_LIMIT = 50
V2RAYN_SUBSCRIPTION_UPDATE_ENABLED = False
V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 0
V2RAYN_SUBSCRIPTION_UPDATE_COMMAND = ""
_v2rayn_invalid_index_ids = set()
_v2rayn_invalid_lock = threading.Lock()
_v2rayn_live_profiles = []
_v2rayn_live_lock = threading.Lock()
_v2rayn_precheck_lock = threading.Lock()
_v2rayn_last_precheck_at = 0.0
_v2rayn_last_subscription_update_at = 0.0
_v2rayn_runtime_signature = None
_v2raya_invalid_node_keys = set()
_v2raya_invalid_lock = threading.Lock()
_v2raya_live_nodes = []
_v2raya_live_lock = threading.Lock()
_v2raya_precheck_lock = threading.Lock()
_v2raya_last_precheck_at = 0.0
_v2raya_runtime_signature = None
POOL_MODE = False
FASTEST_MODE = False
PROXY_GROUP_NAME = "节点选择"
CLASH_SECRET = ""
NODE_BLACKLIST = []
_IS_IN_DOCKER = os.path.exists("/.dockerenv")
_global_switch_lock = threading.Lock()
_socket_restore_lock = threading.Lock()
_original_socket = socket.socket
_last_switch_time = 0
_last_v2rayn_core_restart_time = 0.0
_last_v2rayn_pressure_log_at = 0.0
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


def _count_local_proxy_active_connections(proxy_url=None) -> int:
    if os.name != "nt":
        return 0
    target_proxy = _get_v2rayn_inbound_proxy_url(proxy_url if proxy_url else LOCAL_PROXY_URL)
    parsed = urllib.parse.urlparse(target_proxy)
    port = parsed.port
    if not port:
        return 0
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "tcp"],
            capture_output=True,
            text=True,
            timeout=8,
            **_hidden_subprocess_kwargs(),
        )
        if result.returncode != 0:
            return 0
        count = 0
        marker = f":{port}"
        for line in (result.stdout or "").splitlines():
            text = line.strip()
            if not text.startswith("TCP"):
                continue
            parts = re.split(r"\s+", text)
            if len(parts) < 5:
                continue
            local_addr, remote_addr, state = parts[1], parts[2], parts[3].upper()
            if marker not in local_addr and marker not in remote_addr:
                continue
            if state in {"ESTABLISHED", "CLOSE_WAIT", "FIN_WAIT_1", "FIN_WAIT_2", "SYN_SENT", "SYN_RECEIVED"}:
                count += 1
        return count
    except Exception:
        return 0


def _wait_for_local_proxy_pressure_relief(proxy_url=None, threshold: int = 16, timeout_sec: float = 6.0) -> int:
    global _last_v2rayn_pressure_log_at
    if os.name != "nt":
        return 0
    start = time.time()
    last_count = _count_local_proxy_active_connections(proxy_url)
    if last_count <= threshold:
        return last_count
    while time.time() - start < timeout_sec:
        now = time.time()
        if now - _last_v2rayn_pressure_log_at >= 2.0:
            print(f"[{ts()}] [代理池] 本地代理活跃连接较多 ({last_count})，等待网络栈缓冲后再切换...")
            _last_v2rayn_pressure_log_at = now
        time.sleep(0.5)
        last_count = _count_local_proxy_active_connections(proxy_url)
        if last_count <= threshold:
            break
    return last_count


def format_docker_url(url: str) -> str:
    if not url or not isinstance(url, str):
        return url
    if _IS_IN_DOCKER:
        if "127.0.0.1" in url:
            return url.replace("127.0.0.1", "host.docker.internal")
        if "localhost" in url:
            return url.replace("localhost", "host.docker.internal")
    return url


def _normalize_v2raya_api_base_url(url: str) -> str:
    value = str(url or "").strip().rstrip("/")
    if value.endswith("/api"):
        return value[:-4]
    return value


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

    clash_conf = conf_data.get("clash_proxy_pool", {})
    ENABLE_NODE_SWITCH = bool(clash_conf.get("enable", False))
    PROXY_CLIENT_TYPE = str(clash_conf.get("client_type", "clash") or "clash").strip().lower()
    if PROXY_CLIENT_TYPE not in {"clash", "v2rayn", "v2raya"}:
        PROXY_CLIENT_TYPE = "clash"
    V2RAYA_PANEL_URL = _normalize_v2raya_api_base_url(
        clash_conf.get("v2raya_api_url", "") or clash_conf.get("v2raya_url", "")
    )
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
        V2RAYN_RESTART_WAIT_SEC = max(1, int(clash_conf.get("v2rayn_restart_wait_sec", 4)))
    except Exception:
        V2RAYN_RESTART_WAIT_SEC = 4
    V2RAYN_HIDE_WINDOW_ON_RESTART = bool(clash_conf.get("v2rayn_hide_window_on_restart", True))
    V2RAYN_PRECHECK_ON_START = False
    try:
        V2RAYN_PRECHECK_CACHE_MINUTES = max(0, int(clash_conf.get("v2rayn_precheck_cache_minutes", 30)))
    except Exception:
        V2RAYN_PRECHECK_CACHE_MINUTES = 30
    try:
        V2RAYN_PRECHECK_MAX_NODES = int(clash_conf.get("v2rayn_precheck_max_nodes", 12))
    except Exception:
        V2RAYN_PRECHECK_MAX_NODES = 12
    try:
        V2RAYN_LIVE_POOL_LIMIT = max(1, int(clash_conf.get("v2rayn_live_pool_limit", 50)))
    except Exception:
        V2RAYN_LIVE_POOL_LIMIT = 50
    V2RAYN_SUBSCRIPTION_UPDATE_ENABLED = bool(clash_conf.get("v2rayn_subscription_update_enabled", False))
    try:
        V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = max(0, int(clash_conf.get("v2rayn_subscription_update_interval_minutes", 0)))
    except Exception:
        V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES = 0
    V2RAYN_SUBSCRIPTION_UPDATE_COMMAND = str(clash_conf.get("v2rayn_subscription_update_command", "") or "").strip()
    POOL_MODE = bool(clash_conf.get("pool_mode", False))
    FASTEST_MODE = bool(clash_conf.get("fastest_mode", False))
    CLASH_API_URL = format_docker_url(clash_conf.get("api_url", "http://127.0.0.1:9090"))
    LOCAL_PROXY_URL = format_docker_url(clash_conf.get("test_proxy_url", "http://127.0.0.1:7890"))
    PROXY_GROUP_NAME = clash_conf.get("group_name", "节点选择")
    CLASH_SECRET = clash_conf.get("secret", "")
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


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def clean_for_log(text: str) -> str:
    emoji_pattern = re.compile(
        r"[\U0001F1E6-\U0001F1FF]|[\U0001F300-\U0001F6FF]|[\U0001F900-\U0001F9FF]|[\U00002600-\U000027BF]|[\uFE0F]"
    )
    return emoji_pattern.sub("", text).strip()


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


def _get_pool_index_from_proxy_url(proxy_url: str | None) -> int | None:
    target = proxy_url or LOCAL_PROXY_URL
    try:
        parsed = urllib.parse.urlparse(str(target))
        if parsed.port and 41000 < parsed.port <= 41050:
            return parsed.port - 41000
    except Exception:
        pass
    return 1 if POOL_MODE else None


def _get_clash_config_path(proxy_url: str | None = None) -> str:
    idx = _get_pool_index_from_proxy_url(proxy_url)
    base_dir = "/opt/mihomo-pool"
    if idx is not None:
        path = os.path.join(base_dir, f"config_{idx}", "config.yaml")
        if os.path.exists(path):
            return path
    fallback = os.path.join(base_dir, "config_1", "config.yaml")
    return fallback if os.path.exists(fallback) else ""


def _extract_default_route_groups(proxy_url: str | None = None) -> list[str]:
    config_path = _get_clash_config_path(proxy_url)
    if not config_path or not os.path.exists(config_path):
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        rules = data.get("rules") or []
        for raw in reversed(rules):
            if not isinstance(raw, str):
                continue
            parts = [str(x).strip().strip("'\"") for x in raw.split(",")]
            if len(parts) >= 2 and parts[0].upper() in {"MATCH", "FINAL"}:
                return [parts[1]]
    except Exception:
        pass
    return []


def _find_actual_group_name(proxies_data: dict, keyword: str) -> str:
    wanted = str(keyword or "").strip()
    wanted_lower = wanted.lower()
    ai_hints = ["chatgpt", "openai", "copilot", "claude", "anthropic", "ai"]
    best_name = ""
    best_score = None
    for key, meta in (proxies_data or {}).items():
        if not isinstance(meta, dict) or not isinstance(meta.get("all"), list):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        all_items = meta.get("all", [])
        leaf_count = 0
        child_group_count = 0
        for item in all_items:
            child_meta = proxies_data.get(str(item or "").strip())
            if isinstance(child_meta, dict) and isinstance(child_meta.get("all"), list):
                child_group_count += 1
            else:
                leaf_count += 1
        score = [0, 0, leaf_count, -child_group_count, len(all_items), -len(name)]
        if wanted and name == wanted:
            score[0] = 100
        elif wanted and wanted_lower == name.lower():
            score[0] = 95
        elif wanted and wanted_lower in name.lower():
            score[0] = 90
        elif any(hint in name.lower() for hint in ai_hints):
            score[0] = 70
        elif child_group_count == 0:
            score[0] = 50
        score_tuple = tuple(score)
        if best_score is None or score_tuple > best_score:
            best_score = score_tuple
            best_name = name
    return best_name


def _find_group_path(proxies_data: dict, start_group: str, target_group: str) -> list[str]:
    start = str(start_group or "").strip()
    target = str(target_group or "").strip()
    if not start or not target:
        return []
    if start == target:
        return [start]
    queue_items = [(start, [start])]
    visited = {start}
    while queue_items:
        current, path = queue_items.pop(0)
        meta = proxies_data.get(current)
        if not isinstance(meta, dict) or not isinstance(meta.get("all"), list):
            continue
        for raw in meta.get("all", []):
            child = str(raw or "").strip()
            if not child:
                continue
            if child == target:
                return path + [target]
            child_meta = proxies_data.get(child)
            if isinstance(child_meta, dict) and isinstance(child_meta.get("all"), list) and child not in visited:
                visited.add(child)
                queue_items.append((child, path + [child]))
    return []


def _ensure_default_route_alignment(api_url: str, headers: dict, proxies_data: dict, target_group: str, proxy_url: str | None = None) -> tuple[bool, list[dict], str]:
    default_groups = _extract_default_route_groups(proxy_url)
    if not default_groups or not target_group:
        return True, [], ""
    ops = []
    errors = []
    for root_group in default_groups:
        path = _find_group_path(proxies_data, root_group, target_group)
        if not path:
            errors.append(f"{root_group} 无法到达 {target_group}")
            continue
        for idx in range(len(path) - 1):
            parent = path[idx]
            child = path[idx + 1]
            current_now = str((proxies_data.get(parent) or {}).get("now") or "").strip()
            if current_now == child:
                ops.append({"group": parent, "select": child, "ok": True, "skipped": True})
                continue
            try:
                resp = std_requests.put(
                    f"{api_url}/proxies/{urllib.parse.quote(parent, safe='')}",
                    headers=headers,
                    json={"name": child},
                    timeout=5,
                )
                ok = resp.status_code == 204
                ops.append({"group": parent, "select": child, "ok": ok, "skipped": False, "status": resp.status_code})
                if ok:
                    parent_meta = proxies_data.get(parent)
                    if isinstance(parent_meta, dict):
                        parent_meta["now"] = child
                else:
                    errors.append(f"{parent} -> {child} HTTP {resp.status_code}")
            except Exception as e:
                ops.append({"group": parent, "select": child, "ok": False, "skipped": False, "error": str(e)})
                errors.append(f"{parent} -> {child}: {e}")
    return len(errors) == 0, ops, "；".join(errors)


def _describe_policy_state(proxies_data: dict, proxy_url: str | None = None) -> dict:
    actual_group_name = _find_actual_group_name(proxies_data, PROXY_GROUP_NAME)
    default_groups = _extract_default_route_groups(proxy_url)
    root_states = []
    route_aligned = True if default_groups else None
    for root_group in default_groups:
        meta = proxies_data.get(root_group) or {}
        root_now = str(meta.get("now") or "").strip()
        path = _find_group_path(proxies_data, root_group, actual_group_name) if actual_group_name else []
        aligned = bool(path) and all(str((proxies_data.get(path[idx]) or {}).get("now") or "").strip() == path[idx + 1] for idx in range(len(path) - 1))
        if route_aligned is not None:
            route_aligned = route_aligned and aligned
        root_states.append({"group": root_group, "now": root_now, "path": path, "aligned": aligned})
    return {
        "group_name": actual_group_name,
        "current_node": str((proxies_data.get(actual_group_name) or {}).get("now") or "").strip() if actual_group_name else "",
        "default_groups": default_groups,
        "root_states": root_states,
        "route_aligned": route_aligned,
    }


def test_proxy_liveness(proxy_url=None, silent: bool = False):
    raw_url = proxy_url if proxy_url else LOCAL_PROXY_URL
    target_proxy = format_docker_url(raw_url)
    proxies = {"http": target_proxy, "https": target_proxy}
    display_name = get_display_name(proxy_url if proxy_url else LOCAL_PROXY_URL)
    policy_state = {"group_name": "", "current_node": "", "default_groups": [], "root_states": [], "route_aligned": None}
    try:
        api_url = get_api_url_for_proxy(proxy_url)
        headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
        api_resp = std_requests.get(f"{api_url}/proxies", headers=headers, timeout=5)
        if api_resp.status_code == 200:
            policy_state = _describe_policy_state(api_resp.json().get("proxies", {}) or {}, proxy_url)
    except Exception:
        pass
    loc = "UNKNOWN"
    latency_str = "?"
    cf_ok = False
    try:
        res = std_requests.get("https://cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=5)
        if res.status_code == 200:
            cf_ok = True
            latency_str = f"{res.elapsed.total_seconds():.2f}s"
            for line in res.text.split("\n"):
                if line.startswith("loc="):
                    loc = line.split("=", 1)[1].strip()
                    break
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
    route_aligned = policy_state.get("route_aligned")
    if cf_ok and loc in {"CN", "HK"} and route_aligned is not False:
        if not silent:
            print(f"[{ts()}] [代理测活] {display_name} 地区受限 ({loc})，弃用！")
        return False
    business_group = str(policy_state.get("group_name") or "").strip()
    current_node = clean_for_log(str(policy_state.get("current_node") or "").strip())
    route_note = ""
    if route_aligned is False:
        route_parts = [f"{str(item.get('group') or '').strip()}={clean_for_log(str(item.get('now') or '').strip()) or '-'}" for item in policy_state.get("root_states") or []]
        route_note = f"；默认路由未对齐业务组，仅供参考 ({' / '.join(route_parts)})"
    elif route_aligned is True and policy_state.get("root_states"):
        route_parts = [f"{str(item.get('group') or '').strip()}={clean_for_log(str(item.get('now') or '').strip()) or '-'}" for item in policy_state.get("root_states") or []]
        route_note = f"；默认路由已对齐 ({' / '.join(route_parts)})"
    if cf_ok and not silent:
        business_note = f"；业务组[{business_group}]={current_node}" if business_group and current_node else ""
        print(f"[{ts()}] [代理测活] {display_name} 成功！地区 ({loc})，延迟: {latency_str}{business_note}{route_note}")
    elif not silent:
        business_note = f"业务组[{business_group}]={current_node}" if business_group and current_node else "OpenAI 入口可用"
        print(f"[{ts()}] [代理测活] {display_name} Cloudflare 观测失败，但 {business_note}，继续使用{route_note}")
    return True


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
            candidates.extend([
                data.get("token"),
                data.get("authorization"),
                data.get("Authorization"),
                data.get("access_token"),
                data.get("accessToken"),
                data.get("jwt"),
            ])
        candidates.extend([
            payload.get("token"),
            payload.get("authorization"),
            payload.get("Authorization"),
            payload.get("access_token"),
            payload.get("accessToken"),
            payload.get("jwt"),
        ])
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


def _v2raya_login(session: std_requests.Session) -> list[str]:
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
        message = _first_v2raya_text(payload.get("message") if isinstance(payload, dict) else "", resp.text, f"HTTP {resp.status_code}")
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


def _v2raya_request(session: std_requests.Session, method: str, path: str, auth_values=None, params=None, json_body=None):
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
    name = _first_v2raya_text(obj.get("name"), obj.get("remarks"), obj.get("ps"), obj.get("alias"), obj.get("title"))
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
        container_name = _first_v2raya_text(value.get("name"), value.get("remarks"), value.get("title"))
        container_sub_id = _first_v2raya_text(value.get("sub"), value.get("subId"), value.get("subid"), value.get("subscriptionId"))
        if container_sub_id:
            next_ctx["subscription_id"] = container_sub_id
        if container_name and not candidate:
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


def _fetch_v2raya_node_latency(session: std_requests.Session, auth_values: list[str], node: dict):
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


def _load_v2raya_nodes_snapshot(with_latency: bool = False) -> dict:
    if not V2RAYA_PANEL_URL:
        return {"nodes": [], "message": "请先填写 v2rayA 面板地址。"}
    session = std_requests.Session()
    try:
        auth_values = _v2raya_login(session)
        touch_resp, touch_payload, _ = _v2raya_request(session, "GET", "touch", auth_values=auth_values)
        outbounds_resp, outbounds_payload, _ = _v2raya_request(session, "GET", "outbounds", auth_values=auth_values)
        outbound_resp, outbound_payload, _ = _v2raya_request(session, "GET", "outbound", auth_values=auth_values, params={"outbound": "proxy"})
        if touch_resp is None or touch_resp.status_code >= 400:
            message = _first_v2raya_text(
                touch_payload.get("message") if isinstance(touch_payload, dict) else "",
                touch_payload.get("error") if isinstance(touch_payload, dict) else "",
                "读取 v2rayA 节点列表失败。",
            )
            raise RuntimeError(message)
        nodes = _extract_v2raya_nodes(touch_payload, outbounds_payload, outbound_payload)
        if with_latency and nodes:
            nodes = [_fetch_v2raya_node_latency(session, auth_values, item) for item in nodes]
        return {"nodes": _sort_v2raya_nodes(nodes), "message": "v2rayA 节点列表已刷新。"}
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
    snapshot = _load_v2raya_nodes_snapshot(with_latency=with_latency)
    nodes = snapshot.get("nodes") or []
    with _v2raya_invalid_lock:
        invalid_keys = set(_v2raya_invalid_node_keys)
    filtered = []
    for node in nodes:
        name = _v2raya_text(node.get("name"))
        if any(kw.upper() in name.upper() for kw in NODE_BLACKLIST):
            continue
        if not ignore_runtime_invalid and str(node.get("key") or "") in invalid_keys:
            continue
        filtered.append(dict(node))
    if not filtered and invalid_keys:
        with _v2raya_invalid_lock:
            _v2raya_invalid_node_keys.clear()
        return _list_v2raya_nodes(ignore_runtime_invalid=ignore_runtime_invalid, with_latency=with_latency)
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


def _switch_v2raya_via_api(node: dict) -> bool:
    if not V2RAYA_PANEL_URL:
        print(f"[{ts()}] [WARNING] v2rayA 模式未配置面板地址，改为仅校验当前代理链路。")
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
    if not _switch_v2raya_via_api(node):
        return False, None
    time.sleep(1.2)
    if not test_proxy_liveness(proxy_url):
        return False, None
    try:
        session = std_requests.Session()
        auth_values = _v2raya_login(session)
        with_latency = _fetch_v2raya_node_latency(session, auth_values, node)
        return True, with_latency.get("latency_ms")
    except Exception:
        return True, None
    finally:
        try:
            session.close()
        except Exception:
            pass


def _activate_v2raya_node_runtime(node: dict, proxy_url=None):
    if not _switch_v2raya_via_api(node):
        return False
    time.sleep(1.0)
    return True


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
            candidates = _list_v2raya_nodes(ignore_runtime_invalid=True, with_latency=False)
            if not candidates:
                print(f"[{ts()}] [ERROR] v2rayA 批量测活前未找到可用节点。")
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
                print(f"\n[{ts()}] [代理池] v2rayA 批量测活节点: [{clean_for_log(node.get('name') or node.get('address') or node.get('node_id') or 'UNKNOWN')}] ({idx}/{len(targets)})")
                print(f"[{ts()}] [代理池] 节点切换详情: old={current_key or 'UNKNOWN'} -> new={node.get('key')}")
                is_ok, latency_ms = _activate_v2raya_node(node, proxy_url)
                if is_ok:
                    node_with_latency = dict(node)
                    node_with_latency["latency_ms"] = latency_ms if latency_ms is not None else float("inf")
                    live_nodes.append(node_with_latency)
                    _mark_v2raya_node_valid(node.get("key"))
                    current_key = str(node.get("key") or "")
                    print(f"[{ts()}] [代理池] v2rayA 预检通过: [{clean_for_log(node.get('name') or node.get('address') or node.get('node_id') or 'UNKNOWN')}] | 延迟={latency_ms if latency_ms is not None else '?'}ms | 已纳入活节点池")
                else:
                    summary["dead_count"] += 1
                    _mark_v2raya_node_invalid(node.get("key"))
                    print(f"[{ts()}] [代理池] v2rayA 预检淘汰: [{clean_for_log(node.get('name') or node.get('address') or node.get('node_id') or 'UNKNOWN')}] | 链路不可用")
            live_nodes.sort(key=lambda item: (float(item.get("latency_ms", float("inf"))), str(item.get("name") or "")))
            if V2RAYN_LIVE_POOL_LIMIT > 0 and len(live_nodes) > V2RAYN_LIVE_POOL_LIMIT:
                print(f"[{ts()}] [代理池] v2rayA 活节点池按延迟排序后裁剪为前 {V2RAYN_LIVE_POOL_LIMIT} 个节点。")
                live_nodes = live_nodes[:V2RAYN_LIVE_POOL_LIMIT]
            _set_v2raya_live_nodes(live_nodes)
            summary["live_nodes"] = _get_v2raya_live_nodes()
            summary["live_count"] = len(summary["live_nodes"])
            summary["dead_count"] = max(summary["dead_count"], summary["tested_count"] - summary["live_count"])
            if summary["live_count"] > 0:
                print(f"\n[{ts()}] [SUCCESS] v2rayA 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续仅在活节点池内切换。")
            else:
                print(f"\n[{ts()}] [ERROR] v2rayA 批量测活完成：0 / {summary['tested_count']} 存活。")
            return summary
    except Exception as e:
        print(f"[{ts()}] [ERROR] v2rayA 批量测活异常: {e}")
        return summary


def _switch_v2raya_node(proxy_url=None):
    target_proxy = proxy_url if proxy_url else LOCAL_PROXY_URL
    display_name = get_display_name(target_proxy)
    if not V2RAYA_PANEL_URL:
        print(f"[{ts()}] [WARNING] v2rayA 模式未配置面板地址，改为仅校验当前代理链路: {display_name}")
        return test_proxy_liveness(proxy_url)
    if POOL_MODE:
        print(f"[{ts()}] [WARNING] v2rayA 模式暂不支持独享池模式，已忽略 pool_mode 配置。")
    try:
        current_nodes = _list_v2raya_nodes(ignore_runtime_invalid=True, with_latency=False)
        current_node = next((item for item in current_nodes if item.get("is_current")), None)
        current_key = str((current_node or {}).get("key") or "")
        if current_node:
            print(f"[{ts()}] [代理池] v2rayA 当前节点: [{clean_for_log(current_node.get('name') or current_node.get('address') or current_node.get('node_id') or 'UNKNOWN')}]")
        candidates = _list_v2raya_nodes()
        if not candidates:
            print(f"[{ts()}] [ERROR] v2rayA 过滤后无可用节点。")
            return False
        candidates = [dict(item) for item in candidates]
        random.shuffle(candidates)
        ordered = [item for item in candidates if item.get("key") != current_key] or candidates
        if len(ordered) == 1 and str((ordered[0] or {}).get("key") or "") == current_key:
            ordered = candidates
        max_retries = min(8, len(ordered))
        for idx, node in enumerate(ordered[:max_retries], 1):
            node_name = clean_for_log(node.get("name") or node.get("address") or node.get("node_id") or "UNKNOWN")
            print(f"\n[{ts()}] [代理池] v2rayA 尝试切换节点: [{node_name}] ({idx}/{max_retries})")
            print(f"[{ts()}] [代理池] 节点切换详情: old={current_key or 'UNKNOWN'} -> new={node.get('key')}")
            if _activate_v2raya_node_runtime(node, proxy_url):
                if test_proxy_liveness(proxy_url):
                    print(f"[{ts()}] [代理池] v2rayA 切换确认: 节点=[{node_name}] | 链路验证通过")
                    return True
                _mark_v2raya_node_invalid(node.get("key"))
                print(f"[{ts()}] [代理池] v2rayA 当前抽中节点验证失败，继续抽取下一节点...")
                continue
            _mark_v2raya_node_invalid(node.get("key"))
            print(f"[{ts()}] [代理池] v2rayA 节点切换失败，继续尝试下一节点...")
        print(f"\n[{ts()}] [ERROR] v2rayA 连续切换 {max_retries} 个节点后仍不可用。")
        return False
    except Exception as e:
        print(f"[{ts()}] [ERROR] v2rayA 自动切换异常: {e}")
        return False


def smart_switch_node(proxy_url=None):
    global _last_switch_time
    try:
        from utils import config as cfg
        if bool(getattr(cfg, "GLOBAL_STOP", False)):
            print(f"[{ts()}] [代理池] 已收到全局停止信号，跳过本次节点切换。")
            return False
    except Exception:
        pass
    if not ENABLE_NODE_SWITCH:
        return True
    with _global_switch_lock:
        cooldown = 10.0
        if PROXY_CLIENT_TYPE in {"v2rayn", "v2raya"}:
            cooldown = max(8.0, float(V2RAYN_RESTART_WAIT_SEC) + 4.0)
        if time.time() - _last_switch_time < cooldown:
            print(f"[{ts()}] [代理池] 其他线程刚完成切换，跳过本次请求...")
            return True
        if PROXY_CLIENT_TYPE == "v2rayn":
            success = _switch_v2rayn_node(proxy_url)
        elif PROXY_CLIENT_TYPE == "v2raya":
            success = _switch_v2raya_node(proxy_url)
        elif POOL_MODE and proxy_url:
            success = _do_smart_switch(proxy_url)
        else:
            success = _do_smart_switch(proxy_url)
        if success:
            _last_switch_time = time.time()
        return success


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

    scheme_map = {
        "socks": "socks5",
        "http": "http",
        "mixed": "http",
    }
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
    for item in [
        "https://www.gstatic.com/generate_204"
    ]:
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
    result = []
    with _v2rayn_invalid_lock:
        invalid_ids = set(_v2rayn_invalid_index_ids)
    for row in rows:
        remarks = str(row["Remarks"] or "").strip()
        if not remarks:
            continue
        if not ignore_runtime_invalid and str(row["IndexId"]) in invalid_ids:
            continue
        if any(kw.upper() in remarks.upper() for kw in NODE_BLACKLIST):
            continue
        result.append({
            "index_id": str(row["IndexId"]),
            "remarks": remarks,
            "address": str(row["Address"] or "").strip(),
            "port": row["Port"],
            "subid": str(row["Subid"] or "").strip(),
        })
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


def _write_v2rayn_selection(profile):
    cfg = _read_v2rayn_gui_config()
    if not cfg:
        return False
    cfg["IndexId"] = profile["index_id"]
    subid = str(profile.get("subid") or "").strip()
    if subid:
        cfg["SubIndexId"] = subid
    else:
        cfg.pop("SubIndexId", None)
    if V2RAYN_HIDE_WINDOW_ON_RESTART:
        ui_item = cfg.get("UiItem") or {}
        ui_item["AutoHideStartup"] = True
        cfg["UiItem"] = ui_item
    try:
        with open(V2RAYN_GUI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        return True
    except Exception as e:
        print(f"[{ts()}] [ERROR] 写入 v2rayN 当前节点失败: {e}")
        return False


def _get_v2rayn_process_ids() -> list[int]:
    if os.name != "nt":
        return []
    try:
        result = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH", "/FI", "IMAGENAME eq v2rayN.exe"],
            capture_output=True,
            text=True,
            timeout=10,
            **_hidden_subprocess_kwargs(),
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in (result.stdout or "").splitlines():
            line = line.strip().strip("\ufeff")
            if not line or line.startswith("INFO:"):
                continue
            if "v2rayN.exe" not in line:
                continue
            parts = [part.strip().strip('"') for part in line.split('","')]
            if len(parts) < 2:
                continue
            try:
                pids.append(int(parts[1]))
            except Exception:
                continue
        return sorted(set(pids))
    except Exception:
        return []


def _wait_for_v2rayn_exit(timeout_sec: float = 8.0) -> bool:
    if os.name != "nt":
        return True
    start = time.time()
    while time.time() - start < timeout_sec:
        if not _get_v2rayn_process_ids():
            return True
        time.sleep(0.25)
    still_running = _get_v2rayn_process_ids()
    if still_running:
        print(f"[{ts()}] [WARNING] v2rayN 旧进程未在 {timeout_sec}s 内完全退出: {still_running}")
        return False
    return True


def _wait_for_v2rayn_start(previous_pids: list[int] | None = None, timeout_sec: float = 8.0) -> tuple[bool, list[int]]:
    if os.name != "nt":
        return True, []
    prev = set(int(x) for x in (previous_pids or []))
    start = time.time()
    last_seen = []
    while time.time() - start < timeout_sec:
        current = _get_v2rayn_process_ids()
        last_seen = current
        if current and (not prev or any(pid not in prev for pid in current)):
            return True, current
        time.sleep(0.25)
    if last_seen:
        print(f"[{ts()}] [WARNING] v2rayN 启动后进程未发生变化，当前 PID: {last_seen}")
    else:
        print(f"[{ts()}] [WARNING] v2rayN 启动后未检测到 v2rayN.exe 进程。")
    return False, last_seen


def _launch_v2rayn(hidden: bool = True) -> bool:
    launch_kwargs = _hidden_subprocess_kwargs() if hidden else {}
    try:
        subprocess.Popen(
            [V2RAYN_EXE_PATH],
            cwd=V2RAYN_BASE_DIR if V2RAYN_BASE_DIR else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **launch_kwargs,
        )
        return True
    except Exception as e:
        mode = "隐藏窗口" if hidden else "普通窗口"
        print(f"[{ts()}] [WARNING] v2rayN 以{mode}启动失败: {e}")
    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", V2RAYN_EXE_PATH],
            cwd=V2RAYN_BASE_DIR if V2RAYN_BASE_DIR else None,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            **launch_kwargs,
        )
        print(f"[{ts()}] [代理池] v2rayN 已回退到 cmd/start 方式拉起 GUI。")
        return True
    except Exception as e:
        mode = "隐藏窗口" if hidden else "普通窗口"
        print(f"[{ts()}] [WARNING] v2rayN 以{mode}回退 cmd/start 启动仍失败: {e}")
        return False


def _restart_v2rayn():
    if not V2RAYN_EXE_PATH or not os.path.exists(V2RAYN_EXE_PATH):
        print(f"[{ts()}] [ERROR] 未找到 v2rayN.exe，请先配置 v2rayN 根目录。")
        return False
    hidden_kwargs = _hidden_subprocess_kwargs()
    previous_pids = _get_v2rayn_process_ids()
    for attempt in range(1, 3):
        try:
            subprocess.run(["taskkill", "/IM", "xray.exe", "/F"], capture_output=True, text=True, timeout=10, **hidden_kwargs)
            subprocess.run(["taskkill", "/IM", "v2rayN.exe", "/F"], capture_output=True, text=True, timeout=10, **hidden_kwargs)
        except Exception as e:
            print(f"[{ts()}] [WARNING] 结束 v2rayN/xray 进程时出现异常: {e}")

        _wait_for_v2rayn_exit(timeout_sec=max(3.0, min(10.0, float(V2RAYN_RESTART_WAIT_SEC))))
        time.sleep(0.6)

        launched = _launch_v2rayn(hidden=True)
        if not launched:
            launched = _launch_v2rayn(hidden=False)
        if not launched:
            print(f"[{ts()}] [WARNING] v2rayN 第 {attempt}/2 次重启未能成功发起。")
            continue

        started, current_pids = _wait_for_v2rayn_start(
            previous_pids=previous_pids,
            timeout_sec=max(4.0, min(12.0, float(V2RAYN_RESTART_WAIT_SEC) + 2.0)),
        )
        if started:
            print(f"[{ts()}] [代理池] v2rayN 已拉起，当前 PID: {current_pids}")
            return True

        previous_pids = current_pids or previous_pids
        print(f"[{ts()}] [WARNING] v2rayN 第 {attempt}/2 次重启后未确认启动成功，准备重试...")

    print(f"[{ts()}] [ERROR] 重启 v2rayN 失败：多次尝试后仍未检测到成功拉起。")
    return False


def _restart_v2rayn_core_only(proxy_url=None) -> bool:
    global _last_v2rayn_core_restart_time
    if os.name != "nt":
        return False
    gui_pids = _get_v2rayn_process_ids()
    if not gui_pids:
        return False
    now = time.time()
    if now - _last_v2rayn_core_restart_time < 3.0:
        time.sleep(3.0 - (now - _last_v2rayn_core_restart_time))
    hidden_kwargs = _hidden_subprocess_kwargs()
    try:
        subprocess.run(["taskkill", "/IM", "xray.exe", "/F"], capture_output=True, text=True, timeout=10, **hidden_kwargs)
    except Exception as e:
        print(f"[{ts()}] [WARNING] 仅重启 v2rayN 内核时结束 xray 失败: {e}")
    _last_v2rayn_core_restart_time = time.time()
    time.sleep(0.8)
    if _wait_for_local_proxy_ready(proxy_url, timeout_sec=max(4.0, float(V2RAYN_RESTART_WAIT_SEC) + 1.0)):
        print(f"[{ts()}] [代理池] v2rayN GUI 已在运行，已通过重启 xray 内核应用新节点。")
        return True
    print(f"[{ts()}] [WARNING] 仅重启 xray 内核未能恢复代理监听，回退到全量重启 v2rayN GUI。")
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


def _test_v2rayn_proxy_liveness(proxy_url=None, silent: bool = False, light: bool = False):
    raw_url = _get_v2rayn_inbound_proxy_url(proxy_url if proxy_url else LOCAL_PROXY_URL)
    target_proxy = format_docker_url(raw_url)
    proxies = {"http": target_proxy, "https": target_proxy}
    display_name = get_display_name(proxy_url if proxy_url else LOCAL_PROXY_URL)
    probe_urls = _get_v2rayn_probe_urls()
    last_error = None
    max_attempts = 1 if light else 2
    for attempt in range(max_attempts):
        probe_res = None
        probe_url = ""
        try:
            for probe_url in probe_urls:
                try:
                    probe_res = _call_with_original_socket(
                        std_requests.get,
                        probe_url,
                        proxies=proxies,
                        timeout=6.5,
                    )
                    if probe_res.status_code in (200, 204):
                        break
                    probe_res = None
                except Exception as exc:
                    last_error = exc
                    probe_res = None
            if probe_res is None:
                raise last_error or RuntimeError("all probe urls failed")
            if not light:
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
                        if not silent:
                            print(f"[{ts()}] [代理测活] {display_name} 成功！地区 ({loc})，基础探测延迟: {probe_res.elapsed.total_seconds():.2f}s | 探测URL={probe_url}")
                        return True, loc, round(float(probe_res.elapsed.total_seconds() * 1000), 1)
                except Exception:
                    pass
            if not silent:
                mode_desc = "轻量探测" if light else "基础探测"
                print(f"[{ts()}] [代理测活] {display_name} {mode_desc}成功，地区校验跳过。延迟: {probe_res.elapsed.total_seconds():.2f}s | 探测URL={probe_url}")
            return True, "UNKNOWN", round(float(probe_res.elapsed.total_seconds() * 1000), 1)
        except Exception as exc:
            last_error = exc
            if attempt == 0 and max_attempts > 1:
                if not silent:
                    print(f"[{ts()}] [代理测活] {display_name} 首次探测超时，等待链路稳定后重试一次...")
                time.sleep(1.0)
                continue
    if not silent:
        print(f"[{ts()}] [代理测活] {display_name} 链路中断或超时。{f' ({last_error})' if last_error else ''}")
    return False, None, None


def _activate_v2rayn_profile(profile, proxy_url=None):
    if not _write_v2rayn_selection(profile):
        return False, None, None
    if not (_restart_v2rayn_core_only(proxy_url) or _restart_v2rayn()):
        return False, None, None
    if not _wait_for_local_proxy_ready(proxy_url, timeout_sec=V2RAYN_RESTART_WAIT_SEC):
        return False, None, None
    time.sleep(0.8)
    print(f"[{ts()}] [代理池] v2rayN 节点 [{clean_for_log(profile['remarks'])}] 已生效，准备进入正式测活...")
    return _test_v2rayn_proxy_liveness(proxy_url)


def _activate_v2rayn_profile_runtime(profile, proxy_url=None):
    if not _write_v2rayn_selection(profile):
        return False
    if not (_restart_v2rayn_core_only(proxy_url) or _restart_v2rayn()):
        return False
    if not _wait_for_local_proxy_ready(proxy_url, timeout_sec=V2RAYN_RESTART_WAIT_SEC):
        return False
    time.sleep(0.8)
    print(f"[{ts()}] [代理池] v2rayN 节点 [{clean_for_log(profile['remarks'])}] 已切换生效，直接进入业务流程。")
    return True


def _reapply_current_v2rayn_profile(current_profile, proxy_url=None) -> bool:
    if not current_profile:
        return False
    print(f"[{ts()}] [代理池] v2rayN 先尝试重应用当前节点: [{clean_for_log(current_profile['remarks'])}]")
    if not _activate_v2rayn_profile_runtime(current_profile, proxy_url):
        print(f"[{ts()}] [代理池] v2rayN 当前节点重应用失败，准备切换其他节点。")
        return False
    if V2RAYN_PRECHECK_ON_START:
        _mark_v2rayn_profile_valid(current_profile["index_id"])
        print(f"[{ts()}] [代理池] v2rayN 当前节点重应用成功，继续沿用该节点。")
        return True
    is_ok, region, latency_ms = _test_v2rayn_proxy_liveness(proxy_url)
    if is_ok:
        print(f"[{ts()}] [代理池] v2rayN 当前节点重应用确认成功 | 出口地区={region or 'UNKNOWN'} | 延迟={latency_ms if latency_ms is not None else '?'}ms")
        return True
    print(f"[{ts()}] [代理池] v2rayN 当前节点重应用后仍不可用，准备切换其他节点。")
    _mark_v2rayn_profile_invalid(current_profile["index_id"])
    return False


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
        if V2RAYN_SUBSCRIPTION_UPDATE_ENABLED or force:
            print(f"[{ts()}] [WARNING] 已开启 v2rayN 订阅更新，但未配置更新命令，已跳过。")
        return False
    if not force:
        interval_sec = max(0, int(V2RAYN_SUBSCRIPTION_UPDATE_INTERVAL_MINUTES)) * 60
        if interval_sec <= 0:
            return False
        if _v2rayn_last_subscription_update_at > 0 and (time.time() - _v2rayn_last_subscription_update_at) < interval_sec:
            return False
    print(f"[{ts()}] [代理池] 正在执行 v2rayN 订阅更新命令...")
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
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        if proc.returncode != 0:
            err_msg = stderr.splitlines()[-1] if stderr else f"退出码 {proc.returncode}"
            print(f"[{ts()}] [WARNING] v2rayN 订阅更新失败: {err_msg}")
            return False
        _v2rayn_last_subscription_update_at = time.time()
        print(f"[{ts()}] [代理池] v2rayN 订阅更新完成{': ' + stdout.splitlines()[-1] if stdout else '。'}")
        return True
    except Exception as e:
        print(f"[{ts()}] [WARNING] v2rayN 订阅更新异常: {e}")
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
            print(f"[{ts()}] [ERROR] v2rayN 批量测活前未找到可用节点。")
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
        print(f"[{ts()}] [代理池] v2rayN 启动预检: 准备批量测活 {len(targets)} 个候选节点...")
        live_profiles = []
        for idx, profile in enumerate(targets, 1):
            summary["tested_count"] += 1
            print(f"\n[{ts()}] [代理池] v2rayN 批量测活节点: [{clean_for_log(profile['remarks'])}] ({idx}/{len(targets)})")
            print(f"[{ts()}] [代理池] 节点切换详情: old={current_id or 'UNKNOWN'} -> new={profile['index_id']}")
            is_ok, region, latency_ms = _activate_v2rayn_profile(profile, proxy_url)
            if is_ok:
                profile_with_latency = dict(profile)
                profile_with_latency["latency_ms"] = latency_ms if latency_ms is not None else float("inf")
                live_profiles.append(profile_with_latency)
                _mark_v2rayn_profile_valid(profile["index_id"])
                current_id = profile["index_id"]
                print(f"[{ts()}] [代理池] v2rayN 预检通过: [{clean_for_log(profile['remarks'])}] | 出口地区={region or 'UNKNOWN'} | 延迟={latency_ms if latency_ms is not None else '?'}ms | 已纳入活节点池")
            else:
                summary["dead_count"] += 1
                _mark_v2rayn_profile_invalid(profile["index_id"])
                print(f"[{ts()}] [代理池] v2rayN 预检淘汰: [{clean_for_log(profile['remarks'])}] | {'出口地区=' + region if region in {'CN', 'HK'} else '链路不可用'}")
        live_profiles.sort(key=lambda p: (float(p.get("latency_ms", float("inf"))), str(p.get("remarks") or "")))
        if V2RAYN_LIVE_POOL_LIMIT > 0 and len(live_profiles) > V2RAYN_LIVE_POOL_LIMIT:
            print(f"[{ts()}] [代理池] v2rayN 活节点池按延迟排序后裁剪为前 {V2RAYN_LIVE_POOL_LIMIT} 个节点。")
            live_profiles = live_profiles[:V2RAYN_LIVE_POOL_LIMIT]
        _set_v2rayn_live_profiles(live_profiles)
        summary["live_profiles"] = _get_v2rayn_live_profiles()
        summary["live_count"] = len(summary["live_profiles"])
        summary["dead_count"] = max(summary["dead_count"], summary["tested_count"] - summary["live_count"])
        if summary["live_count"] > 0:
            print(f"\n[{ts()}] [SUCCESS] v2rayN 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续仅在活节点池内切换。")
        else:
            print(f"\n[{ts()}] [ERROR] v2rayN 批量测活完成：0 / {summary['tested_count']} 存活。")
        return summary


def prepare_proxy_runtime(proxy_url=None, reason: str = "startup"):
    return {"tested_count": 0, "live_count": 0, "dead_count": 0, "live_profiles": [], "subscription_updated": False, "reason": reason}


def _switch_v2rayn_node(proxy_url=None):
    target_proxy = proxy_url if proxy_url else LOCAL_PROXY_URL
    display_name = get_display_name(target_proxy)
    if not V2RAYN_BASE_DIR:
        print(f"[{ts()}] [WARNING] v2rayN 模式未配置根目录，改为仅校验当前代理链路: {display_name}")
        return test_proxy_liveness(proxy_url)
    if POOL_MODE:
        print(f"[{ts()}] [WARNING] v2rayN 模式暂不支持独享池模式，已忽略 pool_mode 配置。")
    if FASTEST_MODE:
        print(f"[{ts()}] [WARNING] v2rayN 模式暂不支持延迟优选，将使用随机切点。")
    cfg = _read_v2rayn_gui_config()
    if not cfg:
        return False
    current_id = str(cfg.get("IndexId") or "").strip()
    current_profile = _get_v2rayn_profile_by_id(current_id)
    if current_profile:
        print(f"[{ts()}] [代理池] v2rayN 当前节点: [{clean_for_log(current_profile['remarks'])}] (IndexId={current_profile['index_id']})")
    elif current_id:
        print(f"[{ts()}] [代理池] v2rayN 当前节点 IndexId={current_id}")
    candidates = _list_v2rayn_profiles()
    if not candidates:
        print(f"[{ts()}] [ERROR] v2rayN 过滤后无可用节点。")
        return False
    candidates = [dict(p) for p in candidates]
    random.shuffle(candidates)
    ordered = [p for p in candidates if p["index_id"] != current_id] or candidates
    if len(ordered) == 1 and ordered[0]["index_id"] == current_id:
        ordered = candidates
    max_retries = min(8, len(ordered))
    for idx, profile in enumerate(ordered[:max_retries], 1):
        print(f"\n[{ts()}] [代理池] v2rayN 尝试切换节点: [{clean_for_log(profile['remarks'])}] ({idx}/{max_retries})")
        print(f"[{ts()}] [代理池] 节点切换详情: old={current_id or 'UNKNOWN'} -> new={profile['index_id']}")
        if _activate_v2rayn_profile_runtime(profile, proxy_url):
            is_ok, region, latency_ms = _test_v2rayn_proxy_liveness(proxy_url)
            if is_ok:
                print(f"[{ts()}] [代理池] v2rayN 切换确认: IndexId={profile['index_id']} | 节点=[{clean_for_log(profile['remarks'])}] | 出口地区={region or 'UNKNOWN'} | 延迟={latency_ms if latency_ms is not None else '?'}ms")
                return True
            _mark_v2rayn_profile_invalid(profile["index_id"])
            print(f"[{ts()}] [代理池] v2rayN 当前抽中节点验证失败，继续抽取下一节点...")
            continue
        _mark_v2rayn_profile_invalid(profile["index_id"])
        print(f"[{ts()}] [代理池] v2rayN 节点测活失败，继续尝试下一节点...")
    print(f"\n[{ts()}] [ERROR] v2rayN 连续切换 {max_retries} 个节点后仍不可用。")
    return False


def _do_smart_switch(proxy_url=None):
    if not ENABLE_NODE_SWITCH:
        return True
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    display_name = get_display_name(proxy_url)
    api_display = get_display_name(current_api_url).replace("号机", "号API")
    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code != 200:
            print(f"[{ts()}] [ERROR] 无法连接 Clash API ({api_display})，请检查容器状态。")
            return False
        proxies_data = resp.json().get("proxies", {})
        actual_group_name = _find_actual_group_name(proxies_data, PROXY_GROUP_NAME)
        if not actual_group_name:
            print(f"[{ts()}] [ERROR] {display_name} 找不到策略组关键词 '{PROXY_GROUP_NAME}'")
            return False
        safe_group_name = urllib.parse.quote(actual_group_name, safe="")
        current_node = str((proxies_data.get(actual_group_name, {}) or {}).get("now") or "").strip()
        all_nodes = proxies_data[actual_group_name].get("all", [])
        valid_nodes = []
        for n in all_nodes:
            node_name = str(n or "").strip()
            if not node_name or node_name == actual_group_name:
                continue
            node_meta = proxies_data.get(node_name, {})
            if isinstance(node_meta, dict) and "all" in node_meta:
                continue
            if any(kw.upper() in node_name.upper() for kw in NODE_BLACKLIST):
                continue
            valid_nodes.append(node_name)
        if not valid_nodes:
            print(f"[{ts()}] [ERROR] {display_name} 过滤后无可用节点，请检查黑名单。")
            return False
        if current_node and current_node in valid_nodes:
            print(f"[{ts()}] [代理池] {display_name} 先尝试重应用当前节点: [{clean_for_log(current_node)}]")
            reapply_resp = std_requests.put(
                f"{current_api_url}/proxies/{safe_group_name}",
                headers=headers,
                json={"name": current_node},
                timeout=5,
            )
            if reapply_resp.status_code == 204:
                proxies_data.setdefault(actual_group_name, {})["now"] = current_node
                aligned, _, align_error = _ensure_default_route_alignment(current_api_url, headers, proxies_data, actual_group_name, proxy_url)
                if not aligned and align_error:
                    print(f"[{ts()}] [代理池] {display_name} 当前节点重应用时默认路由自动对齐失败: {align_error}")
                time.sleep(1.0)
                if test_proxy_liveness(proxy_url):
                    print(f"[{ts()}] [代理池] {display_name} 当前节点重应用成功，继续沿用该节点。")
                    return True
                print(f"[{ts()}] [代理池] {display_name} 当前节点重应用后仍不可用，准备切换其他节点。")
        if FASTEST_MODE:
            print(f"\n[{ts()}] [代理池] {display_name} 开启优选模式，并发测速 {len(valid_nodes)} 个节点...")
            session = std_requests.Session()
            def trigger_delay(n):
                enc_n = urllib.parse.quote(n, safe="")
                try:
                    session.get(f"{current_api_url}/proxies/{enc_n}/delay?timeout=2000&url=http://www.gstatic.com/generate_204", headers=headers, timeout=2.5)
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
                        print(f"[{ts()}] [代理池] {display_name} 测速完成，最快节点: [{clean_for_log(best_node)}] ({min_delay}ms)")
                        switch_resp = std_requests.put(f"{current_api_url}/proxies/{safe_group_name}", headers=headers, json={"name": best_node}, timeout=5)
                        if switch_resp.status_code == 204:
                            proxies_data.setdefault(actual_group_name, {})["now"] = best_node
                            aligned, _, align_error = _ensure_default_route_alignment(current_api_url, headers, proxies_data, actual_group_name, proxy_url)
                            if not aligned and align_error:
                                print(f"[{ts()}] [代理池] {display_name} 默认路由自动对齐失败: {align_error}")
                            time.sleep(1)
                            if test_proxy_liveness(proxy_url):
                                return True
                            print(f"[{ts()}] [代理池] {display_name} 最快节点测活失败，回退到随机抽卡模式...")
            except Exception as e:
                print(f"[{ts()}] [代理池] {display_name} 优选模式异常: {e}，回退到随机抽卡模式...")
        max_retries = min(10, len(valid_nodes))
        random.shuffle(valid_nodes)
        for i, selected_node in enumerate(valid_nodes[:max_retries], start=1):
            print(f"\n[{ts()}] [代理池] {display_name} 尝试切换节点: [{clean_for_log(selected_node)}] ({i}/{max_retries})")
            switch_resp = std_requests.put(f"{current_api_url}/proxies/{safe_group_name}", headers=headers, json={"name": selected_node}, timeout=5)
            if switch_resp.status_code == 204:
                proxies_data.setdefault(actual_group_name, {})["now"] = selected_node
                aligned, _, align_error = _ensure_default_route_alignment(current_api_url, headers, proxies_data, actual_group_name, proxy_url)
                if not aligned and align_error:
                    print(f"[{ts()}] [代理池] {display_name} 默认路由自动对齐失败: {align_error}")
                time.sleep(1.5)
                if test_proxy_liveness(proxy_url):
                    return True
                print(f"[{ts()}] [代理池] {display_name} 测活失败，重新抽卡...")
            else:
                print(f"[{ts()}] [代理池] {display_name} 指令下发失败 (HTTP {switch_resp.status_code})。")
        print(f"\n[{ts()}] [代理池] {display_name} 连续 10 次抽卡均不可用！")
        return False
    except Exception as e:
        print(f"[{ts()}] [ERROR] {display_name} 切换节点异常: {e}")
        return False


reload_proxy_config()
