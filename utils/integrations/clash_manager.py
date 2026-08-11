import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.parse
from typing import Optional, Tuple, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
from uuid import uuid4

import docker
import requests
import yaml
import utils.config as cfg
from utils.clash_group_utils import resolve_group_name, strip_group_decorations
from utils.integrations.subscription_fetcher import fetch_subscription_text
BASE_PATH = os.path.join(os.getcwd(), "data", "mihomo-pool")
os.makedirs(BASE_PATH, exist_ok=True)

HOST_PROJECT_PATH = os.getenv("HOST_PROJECT_PATH", os.getcwd())
HOST_BASE_PATH = os.path.join(HOST_PROJECT_PATH, "data", "mihomo-pool")

IMAGE_NAME = "metacubex/mihomo:latest"
MANUAL_SUBSCRIPTION_PATH = os.path.join(BASE_PATH, "manual-subscription.txt")
MANUAL_CONFIG_PATH = os.path.join(BASE_PATH, "manual-config.yaml")
SINGLE_CORE_LOG_PATH = os.path.join(BASE_PATH, "mihomo-core.log")
SINGLE_CORE_PID_PATH = os.path.join(BASE_PATH, "mihomo-core.pid")

KNOWN_RUNTIME_MODES = {
    "docker_pool",
    "linux_single_core",
    "windows_single_core",
    "local_gui",
}


def _configured_runtime_mode() -> str:
    """Read explicit clash_proxy_pool.runtime_mode from config when present."""
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    mode = str(clash_conf.get("runtime_mode") or "").strip().lower()
    return mode if mode in KNOWN_RUNTIME_MODES else ""


def _is_proxy_group_meta(meta: dict) -> bool:
    if not isinstance(meta, dict):
        return False
    if isinstance(meta.get("all"), list):
        return True
    gtype = str(meta.get("type") or "").strip().lower()
    return gtype in {"selector", "url-test", "urltest", "fallback", "load-balance", "loadbalance", "relay"}


def _collect_groups_from_runtime(proxy_map: dict | None = None) -> list[dict]:
    """Build strategy-group list purely from live controller /proxies data."""
    groups = []
    source = proxy_map if isinstance(proxy_map, dict) else {}
    for name, meta in source.items():
        if not _is_proxy_group_meta(meta):
            continue
        nodes = meta.get("all") if isinstance(meta.get("all"), list) else []
        groups.append(
            {
                "name": str(name),
                "type": str(meta.get("type") or "N/A"),
                "nodes": list(nodes),
                "count": len(nodes),
                "current": str(meta.get("now") or ""),
            }
        )
    return groups


def _enrich_nodes_with_providers(base_url: str, secret: str, nodes: list) -> list:
    """Merge provider node names so provider-backed groups stay complete."""
    merged = []
    seen = set()
    for node in nodes or []:
        name = str(node or "").strip()
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    try:
        res = requests.get(
            f"{base_url}/providers/proxies",
            headers=_controller_headers(secret),
            timeout=5,
        )
        if res.status_code != 200:
            return merged
        payload = res.json() or {}
        providers = payload.get("providers") if isinstance(payload, dict) else {}
        if not isinstance(providers, dict):
            return merged
        for provider in providers.values():
            if not isinstance(provider, dict):
                continue
            for item in provider.get("proxies") or []:
                name = str(item.get("name") or "").strip() if isinstance(item, dict) else str(item or "").strip()
                if name and name not in seen:
                    seen.add(name)
                    merged.append(name)
    except Exception:
        return merged
    return merged



def get_client():
    try:
        return docker.from_env()
    except Exception as e:
        print(f"[{cfg.ts()}] [DOCKER] Docker 连接失败，非docker环境忽略该提示: {e}")
        return None


def _read_runtime_config() -> dict:
    config_path = os.path.join(os.getcwd(), "data", "config.yaml")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _persist_sub_url(url: str, subscription_id: str = "") -> None:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {})
    if not isinstance(clash_conf, dict):
        clash_conf = {}
    clash_conf["sub_url"] = str(url or "").strip()
    if subscription_id:
        clash_conf["selected_subscription_id"] = str(subscription_id).strip()
    clash_conf["sub_urls"] = _normalize_subscriptions(clash_conf.get("sub_urls", []), clash_conf["sub_url"])
    config_data["clash_proxy_pool"] = clash_conf
    cfg.reload_all_configs(new_config_dict=config_data)


def _normalize_subscriptions(raw_items, selected_url: str = "") -> list[dict]:
    items = []
    seen = set()
    source = raw_items if isinstance(raw_items, list) else []
    for item in source:
        if isinstance(item, str):
            url = item.strip()
            name = url
            item_id = uuid4().hex[:8]
        elif isinstance(item, dict):
            url = str(item.get("url") or "").strip()
            name = str(item.get("name") or item.get("label") or url or "未命名订阅").strip()
            item_id = str(item.get("id") or uuid4().hex[:8]).strip()
        else:
            continue
        if name == "当前订阅":
            continue
        if not url or url in seen:
            continue
        seen.add(url)
        items.append({"id": item_id, "name": name or url, "url": url})

    selected_url = str(selected_url or "").strip()
    if selected_url and selected_url not in seen:
        items.insert(0, {"id": uuid4().hex[:8], "name": "当前订阅", "url": selected_url})
    return items


def _normalize_single_subscription_url(url: str, resolved_url: str = "") -> str:
    explicit = str(resolved_url or "").strip()
    if explicit:
        return explicit
    raw = str(url or "").strip()
    parsed = urllib.parse.urlparse(raw)
    if parsed.scheme in {"http", "https"}:
        return raw
    return raw


def get_subscription_state() -> dict:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    selected_url = str(clash_conf.get("sub_url") or "").strip()
    selected_subscription_id = str(clash_conf.get("selected_subscription_id") or "").strip()
    subscriptions = _normalize_subscriptions(clash_conf.get("sub_urls", []), selected_url)
    selected_id = ""
    matched = False
    if selected_url:
        for item in subscriptions:
            item["selected"] = item["url"] == selected_url
            if item["selected"]:
                selected_id = item["id"]
                matched = True
    if not matched and selected_subscription_id:
        for item in subscriptions:
            item["selected"] = item["id"] == selected_subscription_id
            if item["selected"]:
                selected_id = item["id"]
                matched = True
    if not matched:
        for item in subscriptions:
            item["selected"] = False
    return {
        "selected_id": selected_id,
        "selected_url": selected_url,
        "items": subscriptions,
    }


def add_subscription(name: str, url: str, make_selected: bool = False) -> tuple[bool, str]:
    url = str(url or "").strip()
    name = str(name or "").strip() or url
    if not url:
        return False, "订阅链接不能为空。"
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    subscriptions = _normalize_subscriptions(clash_conf.get("sub_urls", []), clash_conf.get("sub_url", ""))
    for item in subscriptions:
        if item["url"] == url:
            item["name"] = name
            if make_selected:
                clash_conf["sub_url"] = url
                clash_conf["selected_subscription_id"] = item["id"]
            clash_conf["sub_urls"] = subscriptions
            config_data["clash_proxy_pool"] = clash_conf
            cfg.reload_all_configs(new_config_dict=config_data)
            return True, "订阅已存在，已更新名称。"
    subscriptions.append({"id": uuid4().hex[:8], "name": name, "url": url})
    clash_conf["sub_urls"] = subscriptions
    if make_selected or not str(clash_conf.get("sub_url") or "").strip():
        clash_conf["sub_url"] = url
        clash_conf["selected_subscription_id"] = subscriptions[-1]["id"]
    config_data["clash_proxy_pool"] = clash_conf
    cfg.reload_all_configs(new_config_dict=config_data)
    return True, "订阅已添加。"


def delete_subscription(subscription_id: str) -> tuple[bool, str]:
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        return False, "订阅标识不能为空。"
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    selected_url = str(clash_conf.get("sub_url") or "").strip()
    subscriptions = _normalize_subscriptions(clash_conf.get("sub_urls", []), selected_url)
    removed = None
    remained = []
    for item in subscriptions:
        if item["id"] == sub_id:
            removed = item
        else:
            remained.append(item)
    if not removed:
        return False, "未找到要删除的订阅。"
    clash_conf["sub_urls"] = remained
    if str(clash_conf.get("selected_subscription_id") or "").strip() == removed["id"]:
        clash_conf["selected_subscription_id"] = remained[0]["id"] if remained else ""
    if selected_url == removed["url"]:
        clash_conf["sub_url"] = remained[0]["url"] if remained else ""
    config_data["clash_proxy_pool"] = clash_conf
    cfg.reload_all_configs(new_config_dict=config_data)
    return True, "订阅已删除。"


def select_subscription(subscription_id: str, target: str = "all", resolved_url: str = "") -> tuple[bool, str]:
    sub_id = str(subscription_id or "").strip()
    if not sub_id:
        return False, "订阅标识不能为空。"
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    subscriptions = _normalize_subscriptions(clash_conf.get("sub_urls", []), clash_conf.get("sub_url", ""))
    for item in subscriptions:
        if item["id"] == sub_id:
            final_url = _normalize_single_subscription_url(item.get("url", ""), resolved_url)
            if not final_url:
                return False, "订阅链接为空，无法切换。"
            item["url"] = final_url
            success, message = patch_and_update(final_url, target, item["id"])
            if success:
                clash_conf["sub_url"] = final_url
                clash_conf["selected_subscription_id"] = item["id"]
                clash_conf["sub_urls"] = subscriptions
                config_data["clash_proxy_pool"] = clash_conf
                cfg.reload_all_configs(new_config_dict=config_data)
                return True, f"已切换到订阅 [{item['name']}]，并同步刷新当前策略组。"
            return False, f"订阅已切换为 [{item['name']}]，但同步新策略组失败：{message}"
    return False, "未找到要选中的订阅。"


def _persist_tested_nodes(group_name: str, healthy_nodes: list[str]) -> None:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {})
    if not isinstance(clash_conf, dict):
        clash_conf = {}
    tested_map = clash_conf.get("tested_nodes", {})
    if not isinstance(tested_map, dict):
        tested_map = {}
    tested_map[str(group_name)] = healthy_nodes
    clash_conf["tested_nodes"] = tested_map
    config_data["clash_proxy_pool"] = clash_conf
    cfg.reload_all_configs(new_config_dict=config_data)


def clear_tested_nodes(group_name: str) -> tuple[bool, str]:
    try:
        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {})
        if not isinstance(clash_conf, dict):
            clash_conf = {}
        tested_map = clash_conf.get("tested_nodes", {})
        if isinstance(tested_map, dict):
            tested_map.pop(str(group_name), None)
        clash_conf["tested_nodes"] = tested_map if isinstance(tested_map, dict) else {}
        config_data["clash_proxy_pool"] = clash_conf
        cfg.reload_all_configs(new_config_dict=config_data)
        return True, f"已清空策略组 [{group_name}] 的有效节点池。"
    except Exception as e:
        return False, str(e)


def set_preferred_only_mode(enabled: bool) -> tuple[bool, str]:
    try:
        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {})
        clash_conf = clash_conf if isinstance(clash_conf, dict) else {}
        clash_conf["preferred_only_mode"] = bool(enabled)
        config_data["clash_proxy_pool"] = clash_conf
        cfg.reload_all_configs(new_config_dict=config_data)
        return True, "已开启仅用标优节点模式。" if enabled else "已恢复为全部候选节点模式。"
    except Exception as exc:
        return False, str(exc)


def clear_preferred_nodes(group_name: str) -> tuple[bool, str]:
    try:
        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {})
        clash_conf = clash_conf if isinstance(clash_conf, dict) else {}
        preferred_map = clash_conf.get("preferred_nodes", {})
        preferred_map = preferred_map if isinstance(preferred_map, dict) else {}
        target = strip_group_decorations(group_name)
        for key in list(preferred_map):
            normalized = strip_group_decorations(key)
            if key == group_name or (target and (target == normalized or target in normalized or normalized in target)):
                preferred_map.pop(key, None)
        clash_conf["preferred_nodes"] = preferred_map
        config_data["clash_proxy_pool"] = clash_conf
        cfg.reload_all_configs(new_config_dict=config_data)
        return True, f"已清空策略组 [{group_name}] 的标优节点池。"
    except Exception as exc:
        return False, str(exc)


def _is_real_proxy_node(proxy_map: dict, node_name: str) -> bool:
    name = str(node_name or "").strip()
    if not name or name.upper() in {"DIRECT", "REJECT", "REJECT-DROP", "PASS"}:
        return False
    meta = proxy_map.get(name) if isinstance(proxy_map, dict) else None
    if not isinstance(meta, dict):
        return True
    proxy_type = str(meta.get("type") or "").strip().lower()
    return proxy_type not in {"selector", "urltest", "fallback", "loadbalance", "relay", "direct", "reject"}


def set_preferred_node(group_name: str, proxy_name: str, enabled: bool = True, target: str = "all") -> tuple[bool, str]:
    group_name = str(group_name or "").strip()
    proxy_name = str(proxy_name or "").strip()
    if not group_name or not proxy_name:
        return False, "策略组和节点名称不能为空。"
    try:
        proxy_map = _fetch_controller_proxies(target)
        runtime_group = resolve_group_name(proxy_map, group_name)
        runtime_meta = proxy_map.get(runtime_group) if runtime_group else None
        if not isinstance(runtime_meta, dict):
            return False, f"未找到策略组 [{group_name}]。"
        if proxy_name not in [node for node in runtime_meta.get("all", []) if _is_real_proxy_node(proxy_map, node)]:
            return False, f"节点 [{proxy_name}] 不属于策略组 [{runtime_group or group_name}]。"

        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {})
        clash_conf = clash_conf if isinstance(clash_conf, dict) else {}
        preferred_map = clash_conf.get("preferred_nodes", {})
        preferred_map = preferred_map if isinstance(preferred_map, dict) else {}
        canonical_group = runtime_group or group_name
        current_nodes = preferred_map.get(canonical_group, [])
        current_nodes = current_nodes if isinstance(current_nodes, list) else []
        updated_nodes = [node for node in current_nodes if str(node) != proxy_name]
        if enabled:
            updated_nodes.append(proxy_name)
        preferred_map[canonical_group] = list(dict.fromkeys(updated_nodes)) if updated_nodes else []
        clash_conf["preferred_nodes"] = preferred_map
        config_data["clash_proxy_pool"] = clash_conf
        cfg.reload_all_configs(new_config_dict=config_data)
        action = "加入" if enabled else "移出"
        return True, f"已将节点 [{proxy_name}] {action}策略组 [{canonical_group}] 的标优节点池。"
    except Exception as exc:
        return False, str(exc)


def clear_evicted_nodes() -> tuple[bool, str]:
    try:
        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {})
        clash_conf = clash_conf if isinstance(clash_conf, dict) else {}
        clash_conf["evicted_nodes"] = []
        config_data["clash_proxy_pool"] = clash_conf
        cfg.reload_all_configs(new_config_dict=config_data)
        return True, "已清空拉黑节点池。"
    except Exception as exc:
        return False, str(exc)


def _build_requests_proxies() -> Optional[dict]:
    proxy_url = str(getattr(cfg, "DEFAULT_PROXY", "") or "").strip()
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}


def _extract_port_from_url(url: str, fallback: int) -> int:
    text = str(url or "").strip()
    if not text:
        return fallback
    try:
        if "://" not in text:
            text = f"http://{text}"
        parsed = urllib.parse.urlparse(text)
        return int(parsed.port or fallback)
    except Exception:
        return fallback

def _collect_groups_from_config(config_path: str) -> list[dict]:
    groups = []
    if not os.path.exists(config_path):
        return groups
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        for group in data.get("proxy-groups", []):
            groups.append(
                {
                    "name": group.get("name", "N/A"),
                    "count": len(group.get("proxies", [])),
                    "type": group.get("type", "N/A"),
                    "nodes": list(group.get("proxies", [])),
                    "current": "",
                }
            )
    except Exception:
        pass
    return groups


def _read_pid() -> Optional[int]:
    if not os.path.exists(SINGLE_CORE_PID_PATH):
        return None
    try:
        return int(open(SINGLE_CORE_PID_PATH, "r", encoding="utf-8").read().strip())
    except Exception:
        return None


def _is_pid_running(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _write_pid(pid: int) -> None:
    with open(SINGLE_CORE_PID_PATH, "w", encoding="utf-8") as f:
        f.write(str(pid))


def _stop_single_core() -> None:
    pid = _read_pid()
    if _is_pid_running(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1.0)
        except Exception:
            pass
        if _is_pid_running(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    if os.path.exists(SINGLE_CORE_PID_PATH):
        try:
            os.remove(SINGLE_CORE_PID_PATH)
        except Exception:
            pass


def _probe_local_ports(api_port: int, proxy_port: int, secret: str = "") -> bool:
    try:
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        res = requests.get(f"http://127.0.0.1:{api_port}/version", timeout=1.5, headers=headers)
        if res.status_code in {200, 401}:
            return True
    except Exception:
        pass
    try:
        with socket.create_connection(("127.0.0.1", proxy_port), 0.8):
            return True
    except Exception:
        return False


def _controller_headers(secret: str) -> dict:
    return {"Authorization": f"Bearer {secret}"} if secret else {}


def _get_local_controller() -> tuple[str, str]:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    api_port = _extract_port_from_url(clash_conf.get("api_url"), 9097)
    secret = str(clash_conf.get("secret") or "").strip()
    return f"http://127.0.0.1:{api_port}", secret


def _get_docker_controller(target: str) -> Tuple[Optional[str], str]:
    client = get_client()
    if not client:
        return None, ""
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    secret = str(clash_conf.get("secret") or "").strip()
    desired_name = "clash_1" if target in {"", "all", None} else f"clash_{target}"
    try:
        container = client.containers.get(desired_name)
    except Exception:
        return None, secret
    bindings = container.attrs.get("HostConfig", {}).get("PortBindings", {}) or {}
    port_bind = bindings.get("9090/tcp") or []
    if not port_bind:
        return None, secret
    host_port = port_bind[0].get("HostPort")
    if not host_port:
        return None, secret
    return f"http://127.0.0.1:{host_port}", secret


def _get_controller_endpoint(target: str = "all") -> Tuple[Optional[str], str]:
    mode = _detect_runtime_mode(get_client())
    if mode == "docker_pool":
        return _get_docker_controller(target)
    return _get_local_controller()


def _fetch_controller_proxies(target: str = "all") -> dict:
    base_url, secret = _get_controller_endpoint(target)
    if not base_url:
        raise RuntimeError("未找到可用的 Clash 控制接口。")
    res = requests.get(f"{base_url}/proxies", headers=_controller_headers(secret), timeout=5)
    res.raise_for_status()
    payload = res.json() or {}
    proxies = payload.get("proxies")
    if not isinstance(proxies, dict):
        raise RuntimeError("Clash 控制接口返回异常，缺少 proxies 数据。")
    return proxies


def _resolve_runtime_group_name(group_name: str, target: str = "all") -> Optional[str]:
    proxy_map = _fetch_controller_proxies(target)
    return resolve_group_name(proxy_map, group_name)


def _merge_runtime_groups(config_groups: list[dict], target: str = "all") -> list[dict]:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    tested_map = clash_conf.get("tested_nodes", {})
    if not isinstance(tested_map, dict):
        tested_map = {}

    proxy_map = {}
    base_url, secret = None, ""
    try:
        base_url, secret = _get_controller_endpoint(target)
        proxy_map = _fetch_controller_proxies(target)
    except Exception:
        proxy_map = {}

    groups = list(config_groups or [])
    if not groups and proxy_map:
        groups = _collect_groups_from_runtime(proxy_map)

    provider_names = None
    def _maybe_enrich(nodes: list) -> list:
        nonlocal provider_names
        values = [str(x or "").strip() for x in (nodes or []) if str(x or "").strip()]
        if not base_url:
            return values
        # Only pull provider metadata when the group looks provider-backed
        # (empty / only references other groups), not on every healthy full list.
        leaf_like = [n for n in values if n not in proxy_map or not _is_proxy_group_meta(proxy_map.get(n) or {})]
        if values and leaf_like:
            return values
        if provider_names is None:
            provider_names = _enrich_nodes_with_providers(base_url, secret, [])
        merged_nodes = []
        seen = set()
        for name in list(values) + list(provider_names or []):
            if name and name not in seen:
                seen.add(name)
                merged_nodes.append(name)
        return merged_nodes

    if not proxy_map:
        merged = []
        for group in groups:
            item = dict(group)
            healthy_nodes = tested_map.get(str(group.get("name", "")), [])
            if isinstance(healthy_nodes, list) and healthy_nodes:
                item["healthy_nodes"] = healthy_nodes
            merged.append(item)
        return merged

    merged = []
    seen_names = set()
    for group in groups:
        runtime_name = resolve_group_name(proxy_map, group.get("name", ""))
        runtime = proxy_map.get(runtime_name) if runtime_name else None
        item = dict(group)
        healthy_nodes = tested_map.get(str(group.get("name", "")), [])
        if isinstance(healthy_nodes, list) and healthy_nodes:
            item["healthy_nodes"] = healthy_nodes
        if isinstance(runtime, dict):
            nodes = runtime.get("all")
            if isinstance(nodes, list) and nodes:
                item["nodes"] = _maybe_enrich(list(nodes))
                item["count"] = len(item["nodes"])
            item["current"] = str(runtime.get("now") or "")
            if runtime.get("type"):
                item["type"] = runtime.get("type")
            if runtime_name:
                item["runtime_name"] = runtime_name
                seen_names.add(runtime_name)
        elif isinstance(item.get("nodes"), list):
            item["nodes"] = _maybe_enrich(item.get("nodes") or [])
            item["count"] = len(item["nodes"])
        merged.append(item)

    # Ensure live groups missing from local YAML still appear (shared external core).
    for name, meta in proxy_map.items():
        if name in seen_names or not _is_proxy_group_meta(meta):
            continue
        nodes = meta.get("all") if isinstance(meta.get("all"), list) else []
        nodes = _maybe_enrich(nodes)
        item = {
            "name": str(name),
            "type": str(meta.get("type") or "N/A"),
            "nodes": list(nodes),
            "count": len(nodes),
            "current": str(meta.get("now") or ""),
            "runtime_name": str(name),
        }
        healthy_nodes = tested_map.get(str(name), [])
        if isinstance(healthy_nodes, list) and healthy_nodes:
            item["healthy_nodes"] = healthy_nodes
        merged.append(item)
    return merged

def _apply_config_to_controller(config_path: str, target: str = "all") -> tuple[bool, str]:
    try:
        base_url, secret = _get_controller_endpoint(target)
        if not base_url:
            return False, "未找到可用的 Clash 控制接口。"
        res = requests.put(
            f"{base_url}/configs",
            headers=_controller_headers(secret),
            params={"force": "true"},
            json={"path": config_path},
            timeout=8,
        )
        if res.status_code not in {200, 204}:
            return False, f"HTTP {res.status_code} {res.text[:160]}"
        return True, "配置已热更新到当前 Clash 内核。"
    except Exception as e:
        return False, str(e)


def switch_proxy_group(group_name: str, proxy_name: str, target: str = "all") -> tuple[bool, str]:
    if not group_name or not proxy_name:
        return False, "策略组和目标节点不能为空。"
    try:
        base_url, secret = _get_controller_endpoint(target)
        if not base_url:
            return False, "未找到可用的 Clash 控制接口。"
        runtime_group_name = _resolve_runtime_group_name(group_name, target)
        if not runtime_group_name:
            return False, f"未找到策略组 [{group_name}]。"
        encoded_name = urllib.parse.quote(runtime_group_name, safe="")
        res = requests.put(
            f"{base_url}/proxies/{encoded_name}",
            headers=_controller_headers(secret),
            json={"name": proxy_name},
            timeout=8,
        )
        if res.status_code not in {200, 204}:
            return False, f"切换失败: HTTP {res.status_code} {res.text[:160]}"
        return True, f"已切换策略组 [{runtime_group_name}] 到节点 [{proxy_name}]"
    except Exception as e:
        return False, str(e)


def _is_nested_or_special_proxy(node_name: str, proxy_map: dict | None = None) -> bool:
    name = str(node_name or "").strip()
    if not name:
        return True
    upper = name.upper()
    if upper in {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE", "GLOBAL"}:
        return True
    meta = (proxy_map or {}).get(name)
    if isinstance(meta, dict):
        if isinstance(meta.get("all"), list):
            return True
        ptype = str(meta.get("type") or "").strip().lower()
        if ptype in {"direct", "reject", "rejectdrop", "pass", "compatible", "relay", "selector", "url-test", "urltest", "fallback", "load-balance", "loadbalance"}:
            return True
    return False


def _fetch_group_delay_map(
    base_url: str,
    secret: str,
    group_name: str,
    delay_url: str,
    timeout_ms: int = 6000,
) -> dict[str, int]:
    """Batch latency via Mihomo /group/{name}/delay.

    Provider-backed nodes often 404 on /proxies/{name}/delay; group delay is the
    reliable path used by the desktop shared-mihomo manager.
    """
    encoded = urllib.parse.quote(str(group_name or ""), safe="")
    res = requests.get(
        f"{base_url}/group/{encoded}/delay",
        headers=_controller_headers(secret),
        params={"timeout": int(timeout_ms), "url": delay_url},
        timeout=max(45.0, float(timeout_ms) / 1000.0 + 30.0),
    )
    if res.status_code != 200:
        raise RuntimeError(f"group delay HTTP {res.status_code}: {res.text[:160]}")
    payload = res.json() or {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, int] = {}
    for name, value in payload.items():
        try:
            delay = int(value)
        except (TypeError, ValueError):
            delay = 0
        out[str(name)] = delay if delay > 0 else 0
    return out


def test_group_latency(group_name: str, target: str = "all") -> Tuple[bool, Union[dict, str]]:
    if not group_name:
        return False, "策略组不能为空。"
    try:
        proxy_map = _fetch_controller_proxies(target)
        runtime_name = resolve_group_name(proxy_map, group_name)
        runtime = proxy_map.get(runtime_name) if runtime_name else None
        if not isinstance(runtime, dict):
            return False, f"未找到策略组 [{group_name}]。"
        nodes = runtime.get("all")
        if not isinstance(nodes, list) or not nodes:
            return False, f"策略组 [{group_name}] 没有可测速节点。"

        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
        # Keep empty test_proxy_url as "use default probe URL", not as mixed-port proxy.
        raw_test_url = str(clash_conf.get("test_proxy_url") or "").strip()
        if raw_test_url.startswith("http://") and (":789" in raw_test_url or raw_test_url.count(":") == 2):
            # Legacy misconfig sometimes put local mixed-port here; ignore it for delay URL.
            delay_url = "https://www.gstatic.com/generate_204"
        elif raw_test_url.startswith("http://") or raw_test_url.startswith("https://"):
            delay_url = raw_test_url
        else:
            delay_url = "https://www.gstatic.com/generate_204"
        timeout_ms = 6000
        try:
            timeout_ms = max(2000, int(clash_conf.get("delay_timeout_ms") or timeout_ms))
        except (TypeError, ValueError):
            timeout_ms = 6000

        base_url, secret = _get_controller_endpoint(target)
        if not base_url:
            return False, "未找到可用的 Clash 控制接口。"
        headers = _controller_headers(secret)

        # Candidate set: group members + provider leaves (shared-mihomo style).
        ordered_nodes: list[str] = []
        seen = set()
        for node in list(nodes) + _enrich_nodes_with_providers(base_url, secret, []):
            name = str(node or "").strip()
            if name and name not in seen:
                seen.add(name)
                ordered_nodes.append(name)
        if not ordered_nodes:
            return False, f"策略组 [{group_name}] 没有可测速节点。"

        results: dict[str, dict] = {}
        group_delay_error = ""
        try:
            delay_map = _fetch_group_delay_map(
                base_url,
                secret,
                runtime_name or group_name,
                delay_url,
                timeout_ms=timeout_ms,
            )
            for name, delay in delay_map.items():
                if delay > 0:
                    results[name] = {"status": "ok", "delay": int(delay), "via": "group"}
                else:
                    results[name] = {"status": "error", "message": "timeout", "via": "group"}
        except Exception as exc:
            group_delay_error = str(exc)

        def _probe_single(node_name: str):
            encoded = urllib.parse.quote(node_name, safe="")
            try:
                res = requests.get(
                    f"{base_url}/proxies/{encoded}/delay",
                    headers=headers,
                    params={"timeout": min(5000, timeout_ms), "url": delay_url},
                    timeout=max(8.0, min(12.0, timeout_ms / 1000.0 + 3.0)),
                )
                if res.status_code == 404:
                    return node_name, {"status": "error", "message": "HTTP 404 (provider 节点请用组测速)", "via": "node"}
                if res.status_code != 200:
                    return node_name, {"status": "error", "message": f"HTTP {res.status_code}", "via": "node"}
                payload = res.json() or {}
                delay = payload.get("delay")
                if isinstance(delay, (int, float)) and delay > 0:
                    return node_name, {"status": "ok", "delay": int(delay), "via": "node"}
                return node_name, {"status": "error", "message": "timeout", "via": "node"}
            except Exception as e:
                return node_name, {"status": "error", "message": str(e), "via": "node"}

        # Fallback only for real top-level proxies still missing a result.
        pending = []
        for name in ordered_nodes:
            if name in results:
                continue
            meta = proxy_map.get(name)
            if isinstance(meta, dict) and isinstance(meta.get("all"), list):
                results[name] = {"status": "skip", "message": "nested-group", "via": "skip"}
                continue
            if isinstance(meta, dict) and str(meta.get("type") or "").lower() in {"direct", "reject", "rejectdrop", "pass", "compatible"}:
                results[name] = {"status": "skip", "message": str(meta.get("type") or "special"), "via": "skip"}
                continue
            if isinstance(meta, dict):
                pending.append(name)
            else:
                # Provider-only node not returned by group delay this round.
                results[name] = {
                    "status": "error",
                    "message": group_delay_error or "group-delay miss",
                    "via": "group",
                }

        if pending:
            worker_count = max(1, min(12, len(pending)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(_probe_single, node) for node in pending]
                for future in as_completed(futures):
                    node_name, result = future.result()
                    results[node_name] = result

        if not results:
            return False, group_delay_error or f"策略组 [{group_name}] 测速未返回任何结果。"

        healthy_nodes = [
            node_name
            for node_name, result in sorted(
                results.items(),
                key=lambda item: item[1].get("delay", 10**9) if item[1].get("status") == "ok" else 10**9,
            )
            if result.get("status") == "ok" and not _is_nested_or_special_proxy(node_name, proxy_map)
        ]
        # Persist under both UI name and runtime name for switch/reload compatibility.
        _persist_tested_nodes(group_name, healthy_nodes)
        if runtime_name and runtime_name != group_name:
            _persist_tested_nodes(runtime_name, healthy_nodes)

        ok_count = sum(1 for item in results.values() if item.get("status") == "ok")
        return True, {
            "group_name": runtime_name or group_name,
            "test_url": delay_url,
            "method": "group_delay" if not group_delay_error else "node_fallback",
            "group_delay_error": group_delay_error,
            "total": len(ordered_nodes),
            "ok_count": ok_count,
            "healthy_count": len(healthy_nodes),
            "results": results,
            "healthy_nodes": healthy_nodes,
        }
    except Exception as e:
        return False, str(e)


def control_runtime(action: str) -> tuple[bool, str]:
    mode = _detect_runtime_mode(get_client())
    action = str(action or "").strip().lower()
    if action not in {"start", "stop", "restart"}:
        return False, "不支持的运行操作。"

    if mode == "windows_single_core":
        return False, "当前为 Windows 外部单核（共享代理）模式：请用桌面「mihomo共享代理」启停核心；本项目只读控制器、切换节点与测速，不会启动/停止/杀掉外部进程。"
    if mode == "local_gui":
        return False, "当前为本地 GUI 模式，请直接在本机 Clash/Mihomo 客户端中操作。"

    if mode == "linux_single_core":
        config_data = _read_runtime_config()
        clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
        proxy_url = str(config_data.get("default_proxy") or "").strip()
        api_url = str(clash_conf.get("api_url") or "").strip()
        secret = str(clash_conf.get("secret") or "").strip()
        externally_running = _probe_local_ports(
            _extract_port_from_url(api_url, 9097),
            _extract_port_from_url(proxy_url, 7897),
            secret,
        )
        if action == "stop":
            if not _is_pid_running(_read_pid()) and externally_running:
                return False, "检测到当前 Mihomo 由外部服务托管，网页无法直接停止它。"
            _stop_single_core()
            return True, "Linux 单核心 Mihomo 已停止。"
        if action == "restart":
            if not _is_pid_running(_read_pid()) and externally_running:
                return False, "检测到当前 Mihomo 由外部服务托管，请在系统服务中重启它。"
            _stop_single_core()
        ok, msg = _start_single_core()
        return ok, ("Linux 单核心 Mihomo 已启动。 " + msg) if action == "start" and ok else msg

    client = get_client()
    if not client:
        return False, "Docker 不可用，无法控制容器集群。"
    containers = client.containers.list(all=True, filters={"name": "clash_"})
    if not containers:
        return False, "当前没有可控制的 Clash 容器实例。"
    try:
        for container in containers:
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop()
            else:
                container.restart()
        return True, f"Docker Clash 实例已执行 {action} 操作。"
    except Exception as e:
        return False, str(e)


def _build_local_gui_status() -> dict:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    proxy_url = str(config_data.get("default_proxy") or "").strip()
    api_url = str(clash_conf.get("api_url") or "").strip()
    proxy_port = _extract_port_from_url(proxy_url, 7897)
    api_port = _extract_port_from_url(api_url, 9097)
    running = _probe_local_ports(api_port, proxy_port, str(clash_conf.get("secret") or "").strip())
    return {
        "mode": "local_gui",
        "subscriptions": get_subscription_state(),
        "instances": [
            {
                "name": "local-gui",
                "status": "running" if running else "external",
                "ports": f"{proxy_url or '-'} / {api_url or '-'}",
            }
        ],
        "groups": _merge_runtime_groups(_collect_groups_from_config(MANUAL_CONFIG_PATH)),
        "message": (
            "当前未检测到 Docker，已切换为本地 GUI 模式。网页仅保存订阅链接与 YAML 配置，不直接接管 GUI 进程。"
            + (" 已检测到本地 Clash/Mihomo 正在运行。" if running else " 暂未检测到本地 Clash/Mihomo 控制口或代理口。")
        ),
    }


def _build_single_core_status() -> dict:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    proxy_url = str(config_data.get("default_proxy") or "").strip()
    api_url = str(clash_conf.get("api_url") or "").strip()
    pid = _read_pid()
    secret = str(clash_conf.get("secret") or "").strip()
    running = _probe_local_ports(_extract_port_from_url(api_url, 9097), _extract_port_from_url(proxy_url, 7897), secret)
    return {
        "mode": "linux_single_core",
        "subscriptions": get_subscription_state(),
        "instances": [
            {
                "name": "mihomo-local",
                "status": "running" if running else "stopped",
                "ports": f"{proxy_url or '-'} / {api_url or '-'}",
                "pid": pid or "-",
            }
        ],
        "groups": _merge_runtime_groups(_collect_groups_from_config(MANUAL_CONFIG_PATH)),
        "message": "当前为 Linux 单核心模式。网页会直接写入 Mihomo 配置并重启本机内核。",
    }


def _build_windows_single_core_status() -> dict:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    proxy_url = str(config_data.get("default_proxy") or "").strip()
    api_url = str(clash_conf.get("api_url") or "").strip()
    secret = str(clash_conf.get("secret") or "").strip()
    running = _probe_local_ports(
        _extract_port_from_url(api_url, 9097),
        _extract_port_from_url(proxy_url, 7897),
        secret,
    )
    # Always prefer live controller groups for external shared core.
    # Local manual-config.yaml may be stale leftover from GUI/server modes.
    groups = _merge_runtime_groups([])
    return {
        "mode": "windows_single_core",
        "subscriptions": get_subscription_state(),
        "instances": [
            {
                "name": "shared-mihomo",
                "status": "running" if running else "external-offline",
                "ports": f"{proxy_url or '-'} / {api_url or '-'}",
            }
        ],
        "groups": groups,
        "message": (
            "当前为 Windows 外部单核（共享代理）模式：对接桌面 mihomo 共享代理控制器，"
            "可切换节点/测速/读状态，但不会改写其配置，也不会启动、停止或杀掉外部进程。"
            + (" 已检测到共享 Mihomo 正在运行。" if running else " 暂未检测到共享 Mihomo 控制口或代理口，请先启动桌面共享代理。")
        ),
    }


def _detect_runtime_mode(client) -> str:
    """Resolve Clash/Mihomo runtime mode.

    Priority:
    1) explicit clash_proxy_pool.runtime_mode
    2) auto: docker_pool / linux_single_core / local_gui

    Local Windows supports both:
    - windows_single_core: external shared mihomo (desktop project)
    - local_gui: Clash Verge / other GUI client
    Server modes remain:
    - linux_single_core
    - docker_pool
    """
    configured = _configured_runtime_mode()
    if configured in KNOWN_RUNTIME_MODES:
        return configured

    if client:
        return "docker_pool"
    if os.name != "nt" and shutil.which("mihomo"):
        return "linux_single_core"
    return "local_gui"


def _build_sample_container_config():
    return {"allow-lan": True, "mixed-port": 7890}


def _write_single_core_config(raw_yaml: dict) -> dict:
    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    mixed_port = _extract_port_from_url(config_data.get("default_proxy"), 7897)
    controller_port = _extract_port_from_url(clash_conf.get("api_url"), 9097)
    patched = dict(raw_yaml)
    patched.update(
        {
            "mixed-port": mixed_port,
            "allow-lan": True,
            "external-controller": f"127.0.0.1:{controller_port}",
        }
    )
    secret = str(clash_conf.get("secret") or "").strip()
    if secret:
        patched["secret"] = secret
    with open(MANUAL_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(patched, f, allow_unicode=True, sort_keys=False)
    return patched


def sync_single_core_runtime_from_saved_config() -> tuple[bool, str]:
    mode = _detect_runtime_mode(get_client())
    if mode != "linux_single_core":
        return True, "当前不是 Linux 单核心模式，无需同步 Clash 运行端口。"
    if not os.path.exists(MANUAL_CONFIG_PATH):
        return True, "当前未发现 manual-config.yaml，跳过单核心端口同步。"

    try:
        with open(MANUAL_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw_yaml = yaml.safe_load(f) or {}
        if not isinstance(raw_yaml, dict):
            return False, "manual-config.yaml 不是有效的 YAML 字典，无法同步端口。"
        _write_single_core_config(raw_yaml)
        ok, msg = _start_single_core()
        return ok, ("已按最新面板配置重建 Linux 单核心 Mihomo 运行端口。 " + msg) if ok else msg
    except Exception as e:
        return False, str(e)


def _start_single_core() -> tuple[bool, str]:
    mihomo_bin = shutil.which("mihomo")
    if not mihomo_bin:
        return False, "未找到 mihomo 可执行文件。请先在 Linux 服务器安装 mihomo。"
    if not os.path.exists(MANUAL_CONFIG_PATH):
        return False, "未找到 manual-config.yaml，无法启动 mihomo。"

    _stop_single_core()
    with open(SINGLE_CORE_LOG_PATH, "a", encoding="utf-8") as log_fp:
        proc = subprocess.Popen(
            [mihomo_bin, "-f", MANUAL_CONFIG_PATH],
            stdout=log_fp,
            stderr=log_fp,
            cwd=BASE_PATH,
            start_new_session=True,
        )
    _write_pid(proc.pid)

    config_data = _read_runtime_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    api_port = _extract_port_from_url(clash_conf.get("api_url"), 9097)
    secret = str(clash_conf.get("secret") or "").strip()
    last_error = ""
    for _ in range(12):
        time.sleep(0.5)
        try:
            headers = {"Authorization": f"Bearer {secret}"} if secret else {}
            res = requests.get(f"http://127.0.0.1:{api_port}/version", timeout=1.5, headers=headers)
            if res.status_code in {200, 401}:
                return True, "Mihomo 单核心已启动并可响应控制接口。"
            last_error = f"HTTP {res.status_code}"
        except Exception as e:
            last_error = str(e)
    return False, f"Mihomo 已尝试启动，但控制接口未就绪：{last_error}"


def get_pool_status():
    client = get_client()
    mode = _detect_runtime_mode(client)
    if mode == "windows_single_core":
        return _build_windows_single_core_status()
    if mode == "local_gui":
        return _build_local_gui_status()
    if mode == "linux_single_core":
        return _build_single_core_status()

    instances = []
    containers = client.containers.list(all=True, filters={"name": "clash_"})
    for c in containers:
        p_map = c.attrs.get("HostConfig", {}).get("PortBindings", {})
        ports = [f"{b[0]['HostPort']}->{p.split('/')[0]}" for p, b in p_map.items() if b]
        instances.append({"name": c.name, "status": c.status, "ports": ", ".join(ports)})
    instances.sort(key=lambda x: int(x["name"].split("_")[1]) if "_" in x["name"] else 999)
    return {
        "mode": "docker_pool",
        "subscriptions": get_subscription_state(),
        "instances": instances,
        "groups": _merge_runtime_groups(_collect_groups_from_config(os.path.join(BASE_PATH, "clash_1", "config.yaml"))),
        "message": "当前为 Docker 集群模式。网页可直接调度 Mihomo 容器实例。",
    }


def deploy_clash_pool(count):
    client = get_client()
    mode = _detect_runtime_mode(client)
    if mode == "windows_single_core":
        return False, "当前为 Windows 外部单核（共享代理）模式，无需同步 Docker 实例；订阅与核心由桌面共享代理维护。"
    if mode == "local_gui":
        return False, "当前未检测到 Docker。本地 Windows GUI 模式无需同步实例，请直接在本机 Clash/Mihomo 中导入订阅。"
    if mode == "linux_single_core":
        return True, "当前为 Linux 单核心模式，无需同步实例规模。"

    for c in client.containers.list(all=True, filters={"name": "clash_"}):
        try:
            if int(c.name.split("_")[1]) > count:
                c.remove(force=True)
        except Exception:
            pass

    for i in range(1, count + 1):
        name = f"clash_{i}"
        inst_dir = os.path.join(BASE_PATH, name)
        os.makedirs(inst_dir, exist_ok=True)
        cfg_file = os.path.join(inst_dir, "config.yaml")
        if not os.path.exists(cfg_file):
            with open(cfg_file, "w", encoding="utf-8") as f:
                yaml.dump(_build_sample_container_config(), f, allow_unicode=True, sort_keys=False)

        try:
            client.containers.get(name)
        except docker.errors.NotFound:
            client.containers.run(
                IMAGE_NAME,
                name=name,
                detach=True,
                restart_policy={"Name": "always"},
                ports={"7890/tcp": 41000 + i, "9090/tcp": 42000 + i},
                volumes={
                    os.path.join(HOST_BASE_PATH, name, "config.yaml"): {
                        "bind": "/root/.config/mihomo/config.yaml",
                        "mode": "rw",
                    }
                },
            )
    return True, f"成功同步 {count} 个实例"


def patch_and_update(url, target, subscription_id: str = ""):
    client = get_client()
    mode = _detect_runtime_mode(client)
    try:
        normalized_url = _normalize_single_subscription_url(url)
        parsed = urllib.parse.urlparse(normalized_url)
        if parsed.scheme not in {"http", "https"}:
            return False, "订阅链接不是完整的 http/https URL，无法在服务器端直接拉取。"
        proxies = _build_requests_proxies()
        fetch_result = fetch_subscription_text(normalized_url, proxies=proxies)
        if not fetch_result.ok:
            return False, fetch_result.message
        raw_text = fetch_result.text
        _persist_sub_url(normalized_url, subscription_id)
        os.makedirs(BASE_PATH, exist_ok=True)
        with open(MANUAL_SUBSCRIPTION_PATH, "w", encoding="utf-8") as f:
            f.write(raw_text)

        raw_yaml = yaml.safe_load(raw_text)
        if not isinstance(raw_yaml, dict):
            if mode == "windows_single_core":
                return True, "订阅链接已保存。当前为 Windows 外部单核（共享代理）模式，非 YAML 订阅请在共享代理控制台导入/更新。"
            if mode == "local_gui":
                return True, "订阅链接已保存，但内容不是 YAML。当前为本地 GUI 模式，请让 GUI 自己导入该订阅链接。"
            return False, "订阅内容不是 Clash/Mihomo YAML，无法直接下发到核心。请使用 YAML 订阅链接。"

        if mode == "windows_single_core":
            # Keep a local copy for reference only; never force-load into the external shared core.
            try:
                with open(MANUAL_CONFIG_PATH, "w", encoding="utf-8") as f:
                    yaml.dump(raw_yaml, f, allow_unicode=True, sort_keys=False)
            except Exception:
                pass
            return True, (
                "订阅内容已保存到本项目参考文件，但当前为 Windows 外部单核（共享代理）模式："
                "不会改写/热更新/重启桌面共享 Mihomo。请在共享代理控制台更新订阅；"
                "本面板继续用于节点切换、测速与状态读取。"
            )

        if mode == "local_gui":
            _write_single_core_config(raw_yaml)
            ok, apply_msg = _apply_config_to_controller(MANUAL_CONFIG_PATH, target)
            if ok:
                return True, "订阅已更新，并已热更新到本地 GUI Clash/Mihomo。"
            return True, "订阅链接已保存。检测到 YAML 配置，已写入 data/mihomo-pool/manual-config.yaml；但热更新 GUI 内核失败：" + apply_msg

        if mode == "linux_single_core":
            _write_single_core_config(raw_yaml)
            ok, msg = _start_single_core()
            return ok, ("订阅已更新并已下发到 Linux 单核心 Mihomo。 " + msg) if ok else msg

        conts = client.containers.list(all=True, filters={"name": "clash_"})
        indices = range(1, len(conts) + 1) if target == "all" else [int(target)]
        for i in indices:
            name = f"clash_{i}"
            patched = dict(raw_yaml)
            patched.update({"mixed-port": 7890, "allow-lan": True, "external-controller": "0.0.0.0:9090"})
            with open(os.path.join(BASE_PATH, name, "config.yaml"), "w", encoding="utf-8") as f:
                yaml.dump(patched, f, allow_unicode=True, sort_keys=False)
            try:
                client.containers.get(name).restart()
            except Exception:
                pass

        return True, "订阅已更新并应用补丁"
    except Exception as e:
        return False, str(e)
