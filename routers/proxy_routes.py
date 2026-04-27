import asyncio
import json
import os
import re
from typing import Any, List, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from global_state import engine, verify_token
from utils import core_engine
from utils import proxy_manager

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.yaml")


class V2rayASwitchReq(BaseModel):
    node_id: str
    node_type: Optional[str] = "subscriptionServer"
    subscription_id: Optional[str] = ""
    node_name: Optional[str] = ""


class V2rayANodeKeysReq(BaseModel):
    node_keys: List[str] = []


@router.post("/api/proxy/v2raya/precheck")
async def api_v2raya_precheck(token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "请先停止当前运行的任务，再执行 v2rayA 批量测活。"}
    if proxy_manager.PROXY_CLIENT_TYPE != "v2raya":
        return {"status": "error", "message": "当前代理客户端不是 v2rayA，无需执行该操作。"}

    default_proxy = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    summary = proxy_manager.refresh_v2raya_live_pool(
        proxy_url=default_proxy if default_proxy else None,
        force=True,
        reason="manual",
    )
    live_nodes = summary.get("live_nodes", [])
    live_names = [p.get("name", "") for p in live_nodes[:8] if p.get("name")]
    if summary.get("live_count", 0) > 0:
        return {
            "status": "success",
            "message": f"v2rayA 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续只会在活节点池内切换。",
            "tested_count": summary["tested_count"],
            "live_count": summary["live_count"],
            "dead_count": summary["dead_count"],
            "live_names": live_names,
        }
    return {
        "status": "warning",
        "message": f"v2rayA 批量测活完成：0 / {summary['tested_count']} 存活，请检查面板登录态、节点出口或本地代理链路。",
        "tested_count": summary["tested_count"],
        "live_count": summary["live_count"],
        "dead_count": summary["dead_count"],
        "live_names": live_names,
    }


def _read_current_yaml_config() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _build_path_status(path: str, expected: str = "any") -> dict:
    raw = str(path or "").strip()
    exists = os.path.exists(raw) if raw else False
    is_file = os.path.isfile(raw) if raw else False
    is_dir = os.path.isdir(raw) if raw else False
    executable = os.access(raw, os.X_OK) if raw and exists and not is_dir else False
    matches = exists
    if expected == "file":
        matches = is_file
    elif expected == "dir":
        matches = is_dir
    return {
        "path": raw,
        "exists": exists,
        "is_file": is_file,
        "is_dir": is_dir,
        "executable": executable,
        "matches": matches,
    }


def _read_simple_env_file(env_path: str) -> tuple[dict, str]:
    raw = str(env_path or "").strip()
    if not raw:
        return {}, ""
    if not os.path.exists(raw):
        return {}, ""
    try:
        env_map = {}
        with open(raw, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = str(raw_line or "").strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                value = value.strip().strip("'\"")
                env_map[key.strip()] = value
        return env_map, ""
    except Exception as e:
        return {}, str(e)


def _build_v2raya_runtime_snapshot() -> dict:
    config_data = _read_current_yaml_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}

    panel_url = str(clash_conf.get("v2raya_url", "") or "").strip()
    username = str(clash_conf.get("v2raya_username", "") or "").strip()
    password = str(clash_conf.get("v2raya_password", "") or "").strip()
    xray_bin = str(clash_conf.get("v2raya_xray_bin", "") or "").strip()
    assets_dir = str(clash_conf.get("v2raya_assets_dir", "") or "").strip()
    env_file = str(
        clash_conf.get("v2raya_env_file", "") or ("/etc/default/v2raya" if os.name != "nt" else "")
    ).strip()
    subscription_url = str(clash_conf.get("sub_url", "") or "").strip()
    default_proxy = str(config_data.get("default_proxy", "") or "").strip()

    xray_status = _build_path_status(xray_bin, expected="file")
    assets_status = _build_path_status(assets_dir, expected="dir")
    env_status = _build_path_status(env_file, expected="file")
    env_map, env_error = _read_simple_env_file(env_file)

    geoip_path = os.path.join(assets_dir, "geoip.dat") if assets_dir else ""
    geosite_path = os.path.join(assets_dir, "geosite.dat") if assets_dir else ""
    geoip_exists = os.path.exists(geoip_path) if geoip_path else False
    geosite_exists = os.path.exists(geosite_path) if geosite_path else False

    env_xray_bin = str(env_map.get("V2RAYA_V2RAY_BIN", "") or "").strip()
    env_assets_dir = str(env_map.get("V2RAYA_V2RAY_ASSETSDIR", "") or "").strip()

    issues = []
    if not default_proxy:
        issues.append("未配置 default_proxy")
    if not panel_url:
        issues.append("未配置 v2rayA 面板地址")
    if (username and not password) or (password and not username):
        issues.append("v2rayA API 登录名和密码需要同时填写")
    if xray_bin and not xray_status["matches"]:
        issues.append("v2rayA Xray 路径不存在或不是文件")
    if assets_dir and not assets_status["matches"]:
        issues.append("v2rayA geodata 目录不存在或不是目录")
    if assets_dir and assets_status["matches"] and (not geoip_exists or not geosite_exists):
        issues.append("geodata 目录缺少 geoip.dat 或 geosite.dat")
    if env_file and not env_status["matches"]:
        issues.append("v2rayA 环境文件不存在")
    if env_error:
        issues.append(f"读取 v2rayA 环境文件失败: {env_error}")

    return {
        "client_type": str(clash_conf.get("client_type", "") or "").strip(),
        "panel_url": panel_url,
        "subscription_url": subscription_url,
        "default_proxy": default_proxy,
        "os_name": os.name,
        "api_auth": {
            "username": username,
            "password_configured": bool(password),
        },
        "xray_bin": xray_status,
        "assets_dir": {
            **assets_status,
            "geoip_exists": geoip_exists,
            "geosite_exists": geosite_exists,
        },
        "env_file": {
            **env_status,
            "error": env_error,
            "values": {
                "V2RAYA_V2RAY_BIN": env_xray_bin,
                "V2RAYA_V2RAY_ASSETSDIR": env_assets_dir,
                "V2RAYA_LOG_LEVEL": str(env_map.get("V2RAYA_LOG_LEVEL", "") or "").strip(),
            },
            "matches": {
                "xray_bin": bool(xray_bin and env_xray_bin and xray_bin == env_xray_bin),
                "assets_dir": bool(assets_dir and env_assets_dir and assets_dir == env_assets_dir),
            },
        },
        "issues": issues,
    }


def _normalize_v2raya_panel_url(panel_url: str) -> str:
    raw = str(panel_url or "").strip().rstrip("/")
    if raw.endswith("/api"):
        raw = raw[:-4]
    return raw


def _stringify_v2raya(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _first_v2raya_text(*values: Any) -> str:
    for value in values:
        text = _stringify_v2raya(value)
        if text:
            return text
    return ""


def _v2raya_unwrap_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and payload.get("data") is not None:
        return payload.get("data")
    return payload


def _extract_v2raya_token(payload: Any) -> str:
    candidates: list[Any] = []
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
        text = _stringify_v2raya(item)
        if text:
            return text
    return ""


def _v2raya_payload_ok(payload: Any, status_code: int) -> bool:
    if status_code >= 400:
        return False
    if isinstance(payload, dict):
        if payload.get("success") is False or payload.get("ok") is False:
            return False
        code = payload.get("code")
        if isinstance(code, int) and code >= 400:
            return False
        message = _stringify_v2raya(payload.get("message")).lower()
        if "unauthorized" in message or "forbidden" in message:
            return False
    return True


def _build_v2raya_api_settings(config_data: dict | None = None) -> dict:
    config_data = config_data or _read_current_yaml_config()
    clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
    return {
        "panel_url": _normalize_v2raya_panel_url(clash_conf.get("v2raya_url", "")),
        "username": str(clash_conf.get("v2raya_username", "") or "").strip(),
        "password": str(clash_conf.get("v2raya_password", "") or "").strip(),
    }


def _build_v2raya_panel_candidates(panel_url: str) -> list[str]:
    base = _normalize_v2raya_panel_url(panel_url)
    if not base:
        return []

    candidates: list[str] = [base]
    try:
        parsed = urlsplit(base)
        hostname = (parsed.hostname or "").strip().lower()
        port = parsed.port
        if hostname and hostname not in {"127.0.0.1", "localhost", "::1"}:
            for local_host in ("127.0.0.1", "localhost"):
                netloc = f"{local_host}:{port}" if port else local_host
                local_url = urlunsplit((parsed.scheme or "http", netloc, parsed.path or "", "", ""))
                candidates.append(_normalize_v2raya_panel_url(local_url))
    except Exception:
        pass

    deduped: list[str] = []
    for item in candidates:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


async def _v2raya_request(
    client: httpx.AsyncClient,
    panel_url: str,
    method: str,
    path: str,
    *,
    auth_values: list[str] | None = None,
    params: dict | None = None,
    json_body: Any = None,
) -> tuple[httpx.Response | None, Any, str]:
    url = f"{panel_url}/api/{str(path or '').lstrip('/')}"
    headers_base = {"Accept": "application/json, text/plain, */*"}
    values = auth_values[:] if auth_values else [""]
    if not values:
        values = [""]
    last_resp = None
    last_payload = None
    last_auth = ""
    for auth_value in values:
        headers = dict(headers_base)
        if auth_value:
            headers["Authorization"] = auth_value
        try:
            resp = await client.request(method, url, headers=headers, params=params, json=json_body)
        except Exception as e:
            last_resp = None
            last_payload = {"error": str(e)}
            last_auth = auth_value
            continue
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


async def _v2raya_login(
    client: httpx.AsyncClient,
    panel_url: str,
    username: str,
    password: str,
) -> tuple[list[str], str]:
    username = str(username or "").strip()
    password = str(password or "").strip()
    if not username and not password:
        return [""], ""
    if not username or not password:
        raise RuntimeError("v2rayA API 登录名和密码需要同时填写。")
    try:
        resp = await client.post(
            f"{panel_url}/api/login",
            headers={"Accept": "application/json, text/plain, */*"},
            json={"username": username, "password": password},
        )
    except Exception as e:
        raise RuntimeError(f"登录 v2rayA API 失败: {e}") from e
    try:
        payload = resp.json()
    except Exception:
        payload = {"raw": resp.text}
    if resp.status_code >= 400 or not _v2raya_payload_ok(payload, resp.status_code):
        message = _first_v2raya_text(
            payload.get("message") if isinstance(payload, dict) else "",
            resp.text,
            f"HTTP {resp.status_code}",
        )
        raise RuntimeError(f"登录 v2rayA API 失败: {message}")
    token = _extract_v2raya_token(payload)
    values = [""]
    if token:
        values.append(token)
        if not token.lower().startswith("bearer "):
            values.append(f"Bearer {token}")
    deduped: list[str] = []
    for item in values:
        if item not in deduped:
            deduped.append(item)
    return deduped, token


async def _v2raya_login_any(
    client: httpx.AsyncClient,
    panel_url: str,
    username: str,
    password: str,
) -> tuple[str, list[str], str]:
    last_error: Exception | None = None
    for candidate in _build_v2raya_panel_candidates(panel_url):
        try:
            auth_values, token = await _v2raya_login(client, candidate, username, password)
            return candidate, auth_values, token
        except Exception as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("请先填写 v2rayA 面板地址。")


def _append_v2raya_ref(refs: set[str], value: Any) -> None:
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
    text = _stringify_v2raya(value)
    if text:
        refs.add(text)


def _collect_v2raya_current_refs(value: Any, refs: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lower_key = str(key or "").lower()
            if any(token in lower_key for token in ["current", "selected", "connected", "running", "active", "now"]):
                _append_v2raya_ref(refs, child)
            _collect_v2raya_current_refs(child, refs)
    elif isinstance(value, list):
        for item in value:
            _collect_v2raya_current_refs(item, refs)


def _build_v2raya_node_candidate(obj: dict, ctx: dict) -> dict | None:
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
        obj.get("host"),
        ctx.get("subscription_name"),
    )
    node_type = _first_v2raya_text(obj.get("_type"), obj.get("type"))
    if not node_type:
        node_type = "subscriptionServer" if subscription_id else "server"
    lower_type = node_type.lower()
    if lower_type == "subscription":
        return None
    if "sub" in lower_type and "server" in lower_type:
        node_type = "subscriptionServer"
    elif "server" in lower_type:
        node_type = "server"

    key = f"{node_type}:{subscription_id or '-'}:{node_id or name or address}"
    current_hint = any(bool(obj.get(key_name)) for key_name in ["isCurrent", "current", "selected", "connected", "active"])
    return {
        "key": key,
        "node_id": node_id or name or address,
        "node_type": node_type,
        "subscription_id": subscription_id,
        "subscription_name": subscription_name,
        "name": name or address or node_id,
        "address": address,
        "port": port,
        "_current_hint": current_hint,
        "latency_ms": None,
        "latency_source": "",
    }


def _walk_v2raya_nodes(value: Any, nodes: dict[str, dict], current_refs: set[str], ctx: dict | None = None) -> None:
    ctx = dict(ctx or {})
    if isinstance(value, dict):
        _collect_v2raya_current_refs(value, current_refs)
        raw_type = _first_v2raya_text(value.get("_type"), value.get("type")).lower()
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
        if raw_type == "subscription":
            next_ctx["subscription_id"] = _first_v2raya_text(
                value.get("id"),
                value.get("ID"),
                value.get("Id"),
                value.get("sub"),
                value.get("subId"),
                value.get("subid"),
                value.get("subscriptionId"),
                next_ctx.get("subscription_id"),
            )
            next_ctx["subscription_name"] = _first_v2raya_text(
                value.get("name"),
                value.get("remarks"),
                value.get("title"),
                value.get("host"),
                value.get("address"),
                next_ctx.get("subscription_name"),
            )
        container_name = _first_v2raya_text(value.get("name"), value.get("remarks"), value.get("title"))
        container_sub_id = _first_v2raya_text(value.get("sub"), value.get("subId"), value.get("subid"), value.get("subscriptionId"))
        if container_sub_id:
            next_ctx["subscription_id"] = container_sub_id
        if container_name and (not candidate or raw_type == "subscription"):
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


def _extract_v2raya_nodes(*sources: Any) -> list[dict]:
    nodes: dict[str, dict] = {}
    current_refs: set[str] = set()
    for source in sources:
        _walk_v2raya_nodes(_v2raya_unwrap_payload(source), nodes, current_refs)

    result: list[dict] = []
    for item in nodes.values():
        match_values = {
            _stringify_v2raya(item.get("node_id")),
            _stringify_v2raya(item.get("name")),
            _stringify_v2raya(item.get("address")),
        }
        if item.get("subscription_id"):
            match_values.add(f"{item['subscription_id']}:{item['node_id']}")
        item["is_current"] = bool(item.pop("_current_hint", False) or any(value in current_refs for value in match_values if value))
        result.append(item)
    return result


def _extract_v2raya_latency_ms(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if value < 0:
            return None
        return round(float(value), 1)
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
        return None
    if isinstance(value, list):
        for item in value:
            latency = _extract_v2raya_latency_ms(item)
            if latency is not None:
                return latency
    return None


def _build_v2raya_latency_params(node: dict) -> list[dict]:
    params_list: list[dict] = []
    base = {"id": node.get("node_id")}
    if node.get("subscription_id"):
        base["sub"] = node.get("subscription_id")
    for type_key in ["_type", "type"]:
        params = dict(base)
        params[type_key] = node.get("node_type")
        params_list.append(params)
    params_list.append(dict(base))
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in params_list:
        cleaned = {k: v for k, v in item.items() if _stringify_v2raya(v)}
        signature = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            deduped.append(cleaned)
    return deduped


async def _fetch_v2raya_node_latency(
    client: httpx.AsyncClient,
    panel_url: str,
    auth_values: list[str],
    node: dict,
) -> dict:
    result = dict(node)
    for endpoint in ["httpLatency", "pingLatency"]:
        for params in _build_v2raya_latency_params(node):
            resp, payload, _ = await _v2raya_request(
                client,
                panel_url,
                "GET",
                endpoint,
                auth_values=auth_values,
                params=params,
            )
            if resp is None or not _v2raya_payload_ok(payload, resp.status_code):
                continue
            latency_ms = _extract_v2raya_latency_ms(_v2raya_unwrap_payload(payload))
            if latency_ms is not None:
                result["latency_ms"] = latency_ms
                result["latency_source"] = endpoint
                return result
    return result


def _sort_v2raya_nodes(nodes: list[dict]) -> list[dict]:
    def _node_sort_key(item: dict):
        latency = item.get("latency_ms")
        latency_value = float(latency) if isinstance(latency, (int, float)) else 999999.0
        return (
            0 if item.get("is_current") else 1,
            latency_value,
            _first_v2raya_text(item.get("subscription_name"), ""),
            _first_v2raya_text(item.get("name"), item.get("address"), item.get("node_id")),
        )

    return sorted(nodes, key=_node_sort_key)


def _build_v2raya_duplicate_signature(node: dict) -> str:
    address = _first_v2raya_text(node.get("address"), "").lower()
    port = _first_v2raya_text(node.get("port"), "").lower()
    node_type = _first_v2raya_text(node.get("node_type"), "").lower()
    if address or port:
        return f"{node_type}|{address}|{port}"
    return f"{node_type}|{_first_v2raya_text(node.get('name'), node.get('node_id'), '').lower()}"


def _annotate_v2raya_nodes(nodes: list[dict]) -> tuple[list[dict], list[dict], list[str]]:
    invalid_keys = set(proxy_manager.get_v2raya_invalid_node_keys())
    grouped: dict[str, list[dict]] = {}
    for raw in nodes or []:
        item = dict(raw)
        signature = _build_v2raya_duplicate_signature(item)
        item["duplicate_signature"] = signature
        item["is_invalid"] = str(item.get("key") or "") in invalid_keys
        item["is_duplicate"] = False
        item["duplicate_count"] = 1
        grouped.setdefault(signature, []).append(item)

    duplicate_groups: list[dict] = []
    for signature, items in grouped.items():
        if len(items) <= 1:
            continue
        sorted_items = sorted(
            items,
            key=lambda node: (
                0 if node.get("is_current") else 1,
                0 if not node.get("is_invalid") else 1,
                float(node.get("latency_ms", float("inf"))) if isinstance(node.get("latency_ms"), (int, float)) else float("inf"),
                _first_v2raya_text(node.get("subscription_name"), ""),
                _first_v2raya_text(node.get("name"), node.get("node_id"), ""),
            ),
        )
        keep_key = str((sorted_items[0] or {}).get("key") or "")
        group_name = _first_v2raya_text(sorted_items[0].get("name"), sorted_items[0].get("address"), keep_key)
        duplicate_groups.append({
            "signature": signature,
            "keep_key": keep_key,
            "count": len(sorted_items),
            "name": group_name,
            "keys": [str(item.get("key") or "") for item in sorted_items if item.get("key")],
        })
        for item in items:
            item["duplicate_count"] = len(items)
            item["is_duplicate"] = str(item.get("key") or "") != keep_key

    annotated_nodes = [item for bucket in grouped.values() for item in bucket]
    return _sort_v2raya_nodes(annotated_nodes), duplicate_groups, sorted(invalid_keys)


async def _load_v2raya_nodes_snapshot(with_latency: bool = False) -> dict:
    config_data = _read_current_yaml_config()
    runtime = _build_v2raya_runtime_snapshot()
    settings = _build_v2raya_api_settings(config_data)
    panel_url = settings.get("panel_url", "")
    if not panel_url:
        return {
            "nodes": [],
            "runtime": runtime,
            "auth_configured": bool(settings.get("username") and settings.get("password")),
            "message": "请先填写 v2rayA 面板地址。",
        }

    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        resolved_panel_url, auth_values, token = await _v2raya_login_any(
            client, panel_url, settings.get("username", ""), settings.get("password", "")
        )
        touch_resp, touch_payload, _ = await _v2raya_request(client, resolved_panel_url, "GET", "touch", auth_values=auth_values)
        outbounds_resp, outbounds_payload, _ = await _v2raya_request(client, resolved_panel_url, "GET", "outbounds", auth_values=auth_values)
        outbound_resp, outbound_payload, _ = await _v2raya_request(
            client, resolved_panel_url, "GET", "outbound", auth_values=auth_values, params={"outbound": "proxy"}
        )

        if touch_resp is None or touch_resp.status_code >= 400:
            message = _first_v2raya_text(
                touch_payload.get("message") if isinstance(touch_payload, dict) else "",
                touch_payload.get("error") if isinstance(touch_payload, dict) else "",
                "读取 v2rayA 节点列表失败。",
            )
            raise RuntimeError(message)

        nodes = _extract_v2raya_nodes(touch_payload, outbounds_payload, outbound_payload)
        if with_latency and nodes:
            semaphore = asyncio.Semaphore(6)

            async def _worker(item: dict) -> dict:
                async with semaphore:
                    return await _fetch_v2raya_node_latency(client, panel_url, auth_values, item)

            nodes = list(await asyncio.gather(*[_worker(item) for item in nodes]))

        runtime["resolved_panel_url"] = resolved_panel_url
        return {
            "nodes": _sort_v2raya_nodes(nodes),
            "runtime": runtime,
            "auth_configured": bool(settings.get("username") and settings.get("password")),
            "auth_token_present": bool(token),
            "message": "v2rayA 节点列表已刷新。",
        }


def _build_v2raya_nodes_response_data(data: dict) -> dict:
    payload = dict(data or {})
    annotated_nodes, duplicate_groups, invalid_keys = _annotate_v2raya_nodes(payload.get("nodes") or [])
    payload["nodes"] = annotated_nodes
    payload["duplicate_groups"] = duplicate_groups
    payload["invalid_keys"] = invalid_keys
    payload["duplicate_count"] = sum(max(0, int(group.get("count") or 0) - 1) for group in duplicate_groups)
    payload["invalid_count"] = len(invalid_keys)
    return payload


def _build_v2raya_switch_payloads(req: V2rayASwitchReq) -> list[dict]:
    touch_payload = {
        "id": str(req.node_id or "").strip(),
        "_type": str(req.node_type or "subscriptionServer").strip(),
    }
    subscription_id = str(req.subscription_id or "").strip()
    if subscription_id:
        touch_payload["sub"] = subscription_id
    payloads = [
        dict(touch_payload),
        {"touch": dict(touch_payload)},
        {**touch_payload, "outbound": "proxy"},
        {"touch": dict(touch_payload), "outbound": "proxy"},
        {
            "id": str(req.node_id or "").strip(),
            "sub": subscription_id,
            "type": str(req.node_type or "subscriptionServer").strip(),
            "name": str(req.node_name or "").strip(),
        },
    ]
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in payloads:
        cleaned = {k: v for k, v in item.items() if v is not None and v != ""}
        signature = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            deduped.append(cleaned)
    return deduped


async def _load_v2raya_service_status() -> dict:
    config_data = _read_current_yaml_config()
    settings = _build_v2raya_api_settings(config_data)
    panel_url = settings.get("panel_url", "")
    runtime = _build_v2raya_runtime_snapshot()
    if not panel_url:
        return {
            "configured": False,
            "running": False,
            "panel_url": "",
            "runtime": runtime,
            "message": "请先填写 v2rayA 面板地址。",
        }
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        resolved_panel_url, auth_values, _ = await _v2raya_login_any(
            client, panel_url, settings.get("username", ""), settings.get("password", "")
        )
        resp, body, _ = await _v2raya_request(
            client,
            resolved_panel_url,
            "GET",
            "touch",
            auth_values=auth_values,
        )
        if resp is None or not _v2raya_payload_ok(body, resp.status_code):
            message = ""
            if isinstance(body, dict):
                message = _first_v2raya_text(body.get("message"), body.get("error"), message)
            raise RuntimeError(message or "读取 v2rayA 服务状态失败。")
        touch_data = _v2raya_unwrap_payload(body)
        if not isinstance(touch_data, dict):
            touch_data = {}
        running = bool(touch_data.get("running"))
        return {
            "configured": True,
            "running": running,
            "panel_url": resolved_panel_url,
            "runtime": runtime,
            "connected_server": touch_data.get("connectedServer"),
            "touch": touch_data,
            "message": "v2rayA 服务正在运行。" if running else "v2rayA 服务当前未运行。",
        }


@router.post("/api/proxy/v2raya/test_current")
async def api_v2raya_test_current(token: str = Depends(verify_token)):
    proxy_url = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    if not proxy_url:
        return {"status": "error", "message": "当前未配置 default_proxy，无法检测 v2rayA 当前链路。"}
    ok = proxy_manager.test_proxy_liveness(proxy_url, silent=False)
    return {
        "status": "success" if ok else "warning",
        "message": "v2rayA 当前代理链路可用。" if ok else "v2rayA 当前代理链路不可用，请检查 v2rayA 面板里的节点、订阅或本地代理端口。",
        "data": {
            "proxy_url": proxy_url,
            "client_type": proxy_manager.PROXY_CLIENT_TYPE,
        },
    }


@router.post("/api/proxy/v2raya/inspect")
async def api_v2raya_inspect(token: str = Depends(verify_token)):
    try:
        data = _build_v2raya_runtime_snapshot()
        issues = data.get("issues", [])
        return {
            "status": "success" if not issues else "warning",
            "message": "v2rayA 环境检测通过。" if not issues else "v2rayA 环境检测完成，但仍有待确认项。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"v2rayA 环境检测失败: {e}"}


@router.get("/api/proxy/v2raya/status")
async def api_v2raya_status(token: str = Depends(verify_token)):
    try:
        data = await _load_v2raya_service_status()
        if not data.get("configured"):
            return {"status": "warning", "message": data.get("message") or "请先填写 v2rayA 面板地址。", "data": data}
        return {
            "status": "success" if data.get("running") else "warning",
            "message": data.get("message") or ("v2rayA 服务正在运行。" if data.get("running") else "v2rayA 服务当前未运行。"),
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"读取 v2rayA 服务状态失败: {e}"}


@router.get("/api/proxy/v2raya/nodes")
async def api_v2raya_nodes(with_latency: bool = Query(False), token: str = Depends(verify_token)):
    try:
        service_status = await _load_v2raya_service_status()
        if not service_status.get("configured"):
            return {
                "status": "warning",
                "message": service_status.get("message") or "请先填写 v2rayA 面板地址。",
                "data": {"nodes": [], "runtime": service_status.get("runtime"), "service_status": service_status},
            }
        if not service_status.get("running"):
            return {
                "status": "warning",
                "message": "v2rayA 服务当前未运行，启动后才能读取节点。",
                "data": {"nodes": [], "runtime": service_status.get("runtime"), "service_status": service_status},
            }
        data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=with_latency))
        data["service_status"] = service_status
        runtime = data.get("runtime") or {}
        issues = runtime.get("issues", []) if isinstance(runtime, dict) else []
        status = "success" if not issues else "warning"
        if not data.get("nodes"):
            status = "warning"
        message = "v2rayA 节点列表已刷新。" if not with_latency else "v2rayA 节点延迟已刷新。"
        if not data.get("nodes"):
            message = data.get("message") or "暂未读取到 v2rayA 节点。"
        return {"status": status, "message": message, "data": data}
    except Exception as e:
        return {
            "status": "error",
            "message": f"读取 v2rayA 节点列表失败: {e}",
            "data": {"nodes": [], "runtime": _build_v2raya_runtime_snapshot()},
        }


@router.post("/api/proxy/v2raya/switch")
async def api_v2raya_switch(req: V2rayASwitchReq, token: str = Depends(verify_token)):
    try:
        settings = _build_v2raya_api_settings()
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resolved_panel_url, auth_values, _ = await _v2raya_login_any(
                client, panel_url, settings.get("username", ""), settings.get("password", "")
            )
            switch_ok = False
            last_message = ""
            for endpoint in ["connection", "outbound"]:
                for payload in _build_v2raya_switch_payloads(req):
                    resp, body, _ = await _v2raya_request(
                        client,
                        resolved_panel_url,
                        "POST",
                        endpoint,
                        auth_values=auth_values,
                        json_body=payload,
                    )
                    if resp is not None and _v2raya_payload_ok(body, resp.status_code):
                        switch_ok = True
                        break
                    if isinstance(body, dict):
                        last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
                if switch_ok:
                    break
            if not switch_ok:
                return {"status": "error", "message": last_message or "v2rayA 节点切换失败，请检查面板登录态或 API 兼容性。"}
        await asyncio.sleep(0.8)
        data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
        target_name = str(req.node_name or req.node_id or "").strip()
        return {
            "status": "success",
            "message": f"已请求切换到节点：{target_name}",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"切换 v2rayA 节点失败: {e}"}


@router.post("/api/proxy/v2raya/stop_service")
async def api_v2raya_stop_service(token: str = Depends(verify_token)):
    try:
        settings = _build_v2raya_api_settings()
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resolved_panel_url, auth_values, _ = await _v2raya_login_any(
                client, panel_url, settings.get("username", ""), settings.get("password", "")
            )
            resp, body, _ = await _v2raya_request(
                client,
                resolved_panel_url,
                "DELETE",
                "v2ray",
                auth_values=auth_values,
            )
            if resp is None or not _v2raya_payload_ok(body, resp.status_code):
                last_message = ""
                if isinstance(body, dict):
                    last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
                return {"status": "error", "message": last_message or "关闭 v2rayA 服务失败，请检查面板登录态或服务状态。"}
        await asyncio.sleep(0.8)
        data = await _load_v2raya_service_status()
        return {
            "status": "success",
            "message": "已关闭 v2rayA 服务。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"关闭 v2rayA 服务失败: {e}"}


@router.post("/api/proxy/v2raya/start_service")
async def api_v2raya_start_service(token: str = Depends(verify_token)):
    try:
        settings = _build_v2raya_api_settings()
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            resolved_panel_url, auth_values, _ = await _v2raya_login_any(
                client, panel_url, settings.get("username", ""), settings.get("password", "")
            )
            resp, body, _ = await _v2raya_request(
                client,
                resolved_panel_url,
                "POST",
                "v2ray",
                auth_values=auth_values,
            )
            if resp is None or not _v2raya_payload_ok(body, resp.status_code):
                last_message = ""
                if isinstance(body, dict):
                    last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
                return {"status": "error", "message": last_message or "启动 v2rayA 服务失败，请检查面板登录态或服务状态。"}
        await asyncio.sleep(1.0)
        data = await _load_v2raya_service_status()
        return {
            "status": "success",
            "message": "已启动 v2rayA 服务。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"启动 v2rayA 服务失败: {e}"}


@router.post("/api/proxy/v2raya/import_subscription")
async def api_v2raya_import_subscription(token: str = Depends(verify_token)):
    try:
        config_data = _read_current_yaml_config()
        settings = _build_v2raya_api_settings(config_data)
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        clash_conf = config_data.get("clash_proxy_pool", {}) if isinstance(config_data.get("clash_proxy_pool"), dict) else {}
        subscription_url = str(clash_conf.get("sub_url", "") or "").strip()
        if not subscription_url:
            return {"status": "error", "message": "请先填写订阅链接。"}
        async with httpx.AsyncClient(timeout=18.0, follow_redirects=True) as client:
            resolved_panel_url, auth_values, _ = await _v2raya_login_any(
                client, panel_url, settings.get("username", ""), settings.get("password", "")
            )
            resp, body, _ = await _v2raya_request(
                client,
                resolved_panel_url,
                "POST",
                "import",
                auth_values=auth_values,
                json_body={"url": subscription_url},
            )
            if resp is None or not _v2raya_payload_ok(body, resp.status_code):
                last_message = ""
                if isinstance(body, dict):
                    last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
                return {"status": "error", "message": last_message or "导入 v2rayA 订阅失败，请检查订阅链接或面板登录态。"}
        await asyncio.sleep(1.0)
        data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
        return {
            "status": "success",
            "message": "已提交 v2rayA 订阅导入/更新。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"导入 v2rayA 订阅失败: {e}"}


@router.post("/api/proxy/v2raya/delete_subscription")
async def api_v2raya_delete_subscription(req: V2rayASwitchReq, token: str = Depends(verify_token)):
    try:
        settings = _build_v2raya_api_settings()
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        subscription_id = str(req.subscription_id or req.node_id or "").strip()
        if not subscription_id:
            return {"status": "error", "message": "缺少订阅组 ID，无法删除。"}
        async with httpx.AsyncClient(timeout=18.0, follow_redirects=True) as client:
            resolved_panel_url, auth_values, _ = await _v2raya_login_any(
                client, panel_url, settings.get("username", ""), settings.get("password", "")
            )
            resp, body, _ = await _v2raya_request(
                client,
                resolved_panel_url,
                "DELETE",
                "subscription",
                auth_values=auth_values,
                json_body={"id": subscription_id, "_type": "subscription"},
            )
            if resp is None or not _v2raya_payload_ok(body, resp.status_code):
                last_message = ""
                if isinstance(body, dict):
                    last_message = _first_v2raya_text(body.get("message"), body.get("error"), last_message)
                return {"status": "error", "message": last_message or "删除 v2rayA 订阅组失败，请检查面板登录态。"}
        await asyncio.sleep(0.8)
        service_status = await _load_v2raya_service_status()
        if not service_status.get("running"):
            return {
                "status": "success",
                "message": "订阅组已删除；当前 v2rayA 未运行，节点列表保持为空。",
                "data": {"nodes": [], "runtime": service_status.get("runtime"), "service_status": service_status},
            }
        data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
        data["service_status"] = service_status
        return {
            "status": "success",
            "message": "已删除 v2rayA 订阅组。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"删除 v2rayA 订阅组失败: {e}"}


@router.post("/api/proxy/v2raya/mark_invalid")
async def api_v2raya_mark_invalid(req: V2rayANodeKeysReq, token: str = Depends(verify_token)):
    node_keys = [str(item or "").strip() for item in (req.node_keys or []) if str(item or "").strip()]
    if not node_keys:
        return {"status": "warning", "message": "请至少选择一个节点。"}
    changed = proxy_manager.set_v2raya_node_invalid_state(node_keys, invalid=True)
    data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
    return {
        "status": "success",
        "message": f"已标记 {len(changed)} 个节点为失效，自动切点时会跳过它们。",
        "data": data,
    }


@router.post("/api/proxy/v2raya/clear_invalid")
async def api_v2raya_clear_invalid(token: str = Depends(verify_token)):
    proxy_manager.clear_v2raya_invalid_node_keys()
    data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
    return {
        "status": "success",
        "message": "已清空 v2rayA 失效标记。",
        "data": data,
    }


@router.post("/api/proxy/v2raya/dedupe")
async def api_v2raya_dedupe(token: str = Depends(verify_token)):
    data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
    duplicate_groups = data.get("duplicate_groups") or []
    duplicate_keys: list[str] = []
    for group in duplicate_groups:
        keep_key = str(group.get("keep_key") or "")
        for node_key in group.get("keys") or []:
            text = str(node_key or "").strip()
            if text and text != keep_key:
                duplicate_keys.append(text)
    duplicate_keys = sorted(set(duplicate_keys))
    if not duplicate_keys:
        return {
            "status": "success",
            "message": "当前没有检测到可移除的重复节点。",
            "data": data,
        }
    proxy_manager.set_v2raya_node_invalid_state(duplicate_keys, invalid=True)
    data = _build_v2raya_nodes_response_data(await _load_v2raya_nodes_snapshot(with_latency=False))
    return {
        "status": "success",
        "message": f"已将 {len(duplicate_keys)} 个重复节点标记为失效，后续自动切点会忽略它们。",
        "data": data,
    }
