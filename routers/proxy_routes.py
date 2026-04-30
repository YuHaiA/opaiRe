import asyncio
import os
import subprocess
from typing import List, Optional

import yaml
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from global_state import engine, verify_token
from utils import core_engine, proxy_manager

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.yaml")
V2RAYA_RECOVER_SCRIPT_PATH = os.path.join(BASE_DIR, "recover_v2raya_panel.ps1")


class V2rayASwitchReq(BaseModel):
    node_id: str
    node_type: Optional[str] = "subscriptionServer"
    subscription_id: Optional[str] = ""
    node_name: Optional[str] = ""
    node_key: Optional[str] = ""


class V2rayNSwitchReq(BaseModel):
    index_id: str


class V2rayNIndexIdsReq(BaseModel):
    index_ids: List[str]


class V2rayANodeKeysReq(BaseModel):
    node_keys: List[str]


def _tail_output_lines(text: str, limit: int = 12) -> list[str]:
    lines = [str(line or "").strip() for line in str(text or "").splitlines() if str(line or "").strip()]
    if limit <= 0:
        return lines
    return lines[-limit:]


def _run_v2raya_recover_script(wait_seconds: int = 12) -> dict:
    if os.name != "nt":
        return {
            "ok": False,
            "returncode": -1,
            "error": "当前宿主机不是 Windows，无法执行 v2rayA PowerShell 恢复脚本。",
            "output": "",
            "output_tail": [],
        }

    if not os.path.exists(V2RAYA_RECOVER_SCRIPT_PATH):
        return {
            "ok": False,
            "returncode": -1,
            "error": "未找到 recover_v2raya_panel.ps1 恢复脚本。",
            "output": "",
            "output_tail": [],
        }

    command = [
        "powershell",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        V2RAYA_RECOVER_SCRIPT_PATH,
        "-ConfigPath",
        CONFIG_PATH,
        "-WaitSeconds",
        str(max(3, int(wait_seconds or 12))),
    ]

    try:
        completed = subprocess.run(
            command,
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        output = "\n".join(part for part in [(e.stdout or "").strip(), (e.stderr or "").strip()] if part).strip()
        return {
            "ok": False,
            "returncode": -1,
            "error": "执行 v2rayA 恢复脚本超时，请稍后重试。",
            "output": output,
            "output_tail": _tail_output_lines(output),
        }
    except Exception as e:
        return {
            "ok": False,
            "returncode": -1,
            "error": f"执行 v2rayA 恢复脚本失败: {e}",
            "output": "",
            "output_tail": [],
        }

    output = "\n".join(part for part in [(completed.stdout or "").strip(), (completed.stderr or "").strip()] if part).strip()
    return {
        "ok": completed.returncode == 0,
        "returncode": int(completed.returncode),
        "error": "" if completed.returncode == 0 else "v2rayA 恢复脚本执行失败。",
        "output": output,
        "output_tail": _tail_output_lines(output),
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
    if not raw or not os.path.exists(raw):
        return {}, ""
    try:
        env_map = {}
        with open(raw, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = str(raw_line or "").strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                env_map[key.strip()] = value.strip().strip("'\"")
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
    env_file = str(clash_conf.get("v2raya_env_file", "") or ("/etc/default/v2raya" if os.name != "nt" else "")).strip()
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
    runtime_default_proxy = str(getattr(core_engine.cfg, "DEFAULT_PROXY", "") or default_proxy).strip()
    proxy_alignment = proxy_manager.get_v2raya_proxy_alignment_snapshot(runtime_default_proxy if runtime_default_proxy else None)
    local_proxy = proxy_alignment.get("local_proxy") or proxy_manager.get_local_proxy_diagnostics(
        runtime_default_proxy if runtime_default_proxy else None
    )

    issues = []
    if not default_proxy:
        issues.append("未配置 default_proxy")
    elif not local_proxy.get("reachable"):
        listener_host = local_proxy.get("host") or "127.0.0.1"
        listener_port = local_proxy.get("port") or "UNKNOWN"
        issues.append(f"default_proxy 对应本地端口未监听: {listener_host}:{listener_port}")
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
        "default_proxy": default_proxy,
        "effective_proxy": runtime_default_proxy,
        "local_proxy": local_proxy,
        "proxy_alignment": proxy_alignment,
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


def _build_v2raya_duplicate_signature(node: dict) -> str:
    address = str(node.get("address") or "").strip().lower()
    port = str(node.get("port") or "").strip().lower()
    node_type = str(node.get("node_type") or "").strip().lower()
    if address or port:
        return f"{node_type}|{address}|{port}"
    return f"{node_type}|{str(node.get('name') or node.get('node_id') or '').strip().lower()}"


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

    duplicate_groups = []
    for signature, items in grouped.items():
        if len(items) <= 1:
            continue
        sorted_items = sorted(
            items,
            key=lambda node: (
                0 if node.get("is_current") else 1,
                0 if not node.get("is_invalid") else 1,
                float(node.get("latency_ms", float("inf"))) if isinstance(node.get("latency_ms"), (int, float)) else float("inf"),
                str(node.get("subscription_name") or ""),
                str(node.get("name") or node.get("node_id") or ""),
            ),
        )
        keep_key = str((sorted_items[0] or {}).get("key") or "")
        group_name = str(sorted_items[0].get("name") or sorted_items[0].get("address") or keep_key)
        duplicate_groups.append(
            {
                "signature": signature,
                "keep_key": keep_key,
                "count": len(sorted_items),
                "name": group_name,
                "keys": [str(item.get("key") or "") for item in sorted_items if item.get("key")],
            }
        )
        for item in items:
            item["duplicate_count"] = len(items)
            item["is_duplicate"] = str(item.get("key") or "") != keep_key

    annotated_nodes = [item for bucket in grouped.values() for item in bucket]
    annotated_nodes.sort(
        key=lambda item: (
            0 if item.get("is_current") else 1,
            0 if not item.get("is_invalid") else 1,
            float(item.get("latency_ms", float("inf"))) if isinstance(item.get("latency_ms"), (int, float)) else float("inf"),
            str(item.get("subscription_name") or ""),
            str(item.get("name") or item.get("node_id") or ""),
        )
    )
    return annotated_nodes, duplicate_groups, sorted(invalid_keys)


def _build_v2raya_nodes_response_data(snapshot: dict) -> dict:
    nodes = list(snapshot.get("nodes") or [])
    annotated_nodes, duplicate_groups, invalid_keys = _annotate_v2raya_nodes(nodes)
    return {
        **snapshot,
        "nodes": annotated_nodes,
        "duplicate_groups": duplicate_groups,
        "invalid_keys": invalid_keys,
        "duplicate_count": sum(max(0, int(group.get("count") or 0) - 1) for group in duplicate_groups),
        "invalid_count": len(invalid_keys),
        "runtime": _build_v2raya_runtime_snapshot(),
    }


@router.post("/api/proxy/v2rayn/precheck")
async def api_v2rayn_precheck(refresh_subscription: bool = Query(False), token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "请先停止当前运行的任务，再执行 v2rayN 批量测活。"}
    if proxy_manager.PROXY_CLIENT_TYPE != "v2rayn":
        return {"status": "error", "message": "当前代理客户端不是 v2rayN，无需执行该操作。"}

    default_proxy = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    summary = proxy_manager.refresh_v2rayn_live_pool(
        proxy_url=default_proxy if default_proxy else None,
        force=True,
        reason="manual",
        refresh_subscription=refresh_subscription,
    )
    live_profiles = summary.get("live_profiles", [])
    live_names = [p.get("remarks", "") for p in live_profiles[:8] if p.get("remarks")]
    return {
        "status": "success" if summary.get("live_count", 0) > 0 else "warning",
        "message": (
            f"v2rayN 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续只会在活节点池内切换。"
            if summary.get("live_count", 0) > 0
            else f"v2rayN 批量测活完成：0 / {summary['tested_count']} 存活，请检查订阅、出口地区或本地代理链路。"
        ),
        "tested_count": summary["tested_count"],
        "live_count": summary["live_count"],
        "dead_count": summary["dead_count"],
        "subscription_updated": summary.get("subscription_updated", False),
        "live_names": live_names,
    }


@router.get("/api/proxy/v2rayn/nodes")
async def api_v2rayn_nodes(include_invalid: bool = Query(True), token: str = Depends(verify_token)):
    if proxy_manager.PROXY_CLIENT_TYPE != "v2rayn":
        return {"status": "error", "message": "当前代理客户端不是 v2rayN，无需读取该节点列表。"}
    return {
        "status": "success",
        "message": "已直接读取 v2rayN 本地节点列表，无需重启 v2rayN。",
        **proxy_manager.get_v2rayn_profiles_snapshot(include_invalid=include_invalid),
    }


@router.post("/api/proxy/v2rayn/update_subscription")
async def api_v2rayn_update_subscription(token: str = Depends(verify_token)):
    ok, message = proxy_manager.run_v2rayn_subscription_update_only()
    return {"status": "success" if ok else "warning", "message": message}


@router.post("/api/proxy/v2rayn/switch")
async def api_v2rayn_switch(req: V2rayNSwitchReq, token: str = Depends(verify_token)):
    proxy_url = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    result = proxy_manager.switch_v2rayn_profile(req.index_id, proxy_url=proxy_url if proxy_url else None)
    snapshot = proxy_manager.get_v2rayn_profiles_snapshot(include_invalid=True)
    print(
        f"[{proxy_manager.ts()}] [{'SUCCESS' if result.get('ok') else 'WARNING'}] "
        f"[代理面板] {result.get('message') or 'v2rayN 节点切换完成。'}"
    )
    return {
        "status": "success" if result.get("ok") else "warning",
        "message": result.get("message") or "v2rayN 节点切换完成。",
        "data": snapshot,
    }


@router.post("/api/proxy/v2rayn/mark_invalid")
async def api_v2rayn_mark_invalid(req: V2rayNIndexIdsReq, token: str = Depends(verify_token)):
    index_ids = [str(item or "").strip() for item in (req.index_ids or []) if str(item or "").strip()]
    if not index_ids:
        return {"status": "warning", "message": "请至少选择一个 v2rayN 节点。"}
    changed = proxy_manager.set_v2rayn_profile_invalid_state(index_ids, invalid=True)
    data = proxy_manager.get_v2rayn_profiles_snapshot(include_invalid=True)
    return {
        "status": "success",
        "message": f"已标记 {len(changed)} 个 v2rayN 节点为失效，自动切点时会跳过它们。",
        "data": data,
    }


@router.post("/api/proxy/v2rayn/clear_invalid")
async def api_v2rayn_clear_invalid(token: str = Depends(verify_token)):
    proxy_manager.clear_v2rayn_invalid_index_ids()
    data = proxy_manager.get_v2rayn_profiles_snapshot(include_invalid=True)
    return {"status": "success", "message": "已清空 v2rayN 失效标记。", "data": data}


@router.post("/api/proxy/v2raya/precheck")
async def api_v2raya_precheck(token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "请先停止当前运行的任务，再执行 v2rayA 批量测活。"}
    if proxy_manager.PROXY_CLIENT_TYPE != "v2raya":
        return {"status": "error", "message": "当前代理客户端不是 v2rayA，无需执行该操作。"}

    default_proxy = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    summary = proxy_manager.refresh_v2raya_live_pool(proxy_url=default_proxy if default_proxy else None, force=True, reason="manual")
    live_nodes = summary.get("live_nodes", [])
    live_names = [p.get("name", "") for p in live_nodes[:8] if p.get("name")]
    return {
        "status": "success" if summary.get("live_count", 0) > 0 else "warning",
        "message": (
            f"v2rayA 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续只会在活节点池内切换。"
            if summary.get("live_count", 0) > 0
            else f"v2rayA 批量测活完成：0 / {summary['tested_count']} 存活，请检查面板登录态、节点出口或本地代理链路。"
        ),
        "tested_count": summary["tested_count"],
        "live_count": summary["live_count"],
        "dead_count": summary["dead_count"],
        "live_names": live_names,
    }


@router.post("/api/proxy/v2raya/test_current")
async def api_v2raya_test_current(token: str = Depends(verify_token)):
    proxy_url = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    if not proxy_url:
        return {"status": "error", "message": "当前未配置 default_proxy，无法检测 v2rayA 当前链路。"}
    ok = proxy_manager.test_proxy_liveness(proxy_url, silent=False)
    diagnostics = proxy_manager.get_local_proxy_diagnostics(proxy_url)
    return {
        "status": "success" if ok else "warning",
        "message": "v2rayA 当前代理链路可用。" if ok else "v2rayA 当前代理链路不可用，请检查 v2rayA 面板里的节点、订阅或本地代理端口。",
        "data": {
            "proxy_url": proxy_url,
            "client_type": proxy_manager.PROXY_CLIENT_TYPE,
            "local_proxy": diagnostics,
        },
    }


@router.post("/api/proxy/v2raya/align_proxy")
async def api_v2raya_align_proxy(persist: bool = Query(True), token: str = Depends(verify_token)):
    preferred_proxy = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    result = proxy_manager.align_v2raya_local_proxy(preferred_url=preferred_proxy, persist=persist)
    runtime = _build_v2raya_runtime_snapshot()
    return {
        "status": "success" if result.get("ok") else "warning",
        "message": result.get("message") or "v2rayA 本地代理端口对齐完成。",
        "data": {
            **result,
            "runtime": runtime,
        },
    }


@router.post("/api/proxy/v2raya/recover_panel")
async def api_v2raya_recover_panel(token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "请先停止当前运行的任务，再执行 v2rayA 面板恢复。"}

    result = await asyncio.to_thread(_run_v2raya_recover_script)
    runtime = _build_v2raya_runtime_snapshot()
    local_proxy = runtime.get("local_proxy") or {}

    if result.get("ok"):
        if local_proxy.get("reachable"):
            status = "success"
            message = "v2rayA 恢复脚本执行完成，本地代理端口已恢复监听。"
        else:
            listener_host = local_proxy.get("host") or "127.0.0.1"
            listener_port = local_proxy.get("port") or "UNKNOWN"
            status = "warning"
            message = f"v2rayA 恢复脚本已执行，但本地代理端口仍未监听: {listener_host}:{listener_port}"
    else:
        status = "error"
        message = result.get("error") or "执行 v2rayA 恢复脚本失败。"

    return {
        "status": status,
        "message": message,
        "data": {
            "runtime": runtime,
            "script": {
                "path": V2RAYA_RECOVER_SCRIPT_PATH,
                "returncode": result.get("returncode", -1),
                "output_tail": result.get("output_tail") or [],
            },
        },
    }


@router.post("/api/proxy/v2raya/inspect")
async def api_v2raya_inspect(token: str = Depends(verify_token)):
    data = _build_v2raya_runtime_snapshot()
    issues = data.get("issues", [])
    return {
        "status": "success" if not issues else "warning",
        "message": "v2rayA 环境检测通过。" if not issues else "v2rayA 环境检测完成，但仍有待确认项。",
        "data": data,
    }


@router.get("/api/proxy/v2raya/nodes")
async def api_v2raya_nodes(with_latency: bool = Query(False), token: str = Depends(verify_token)):
    try:
        snapshot = proxy_manager.get_v2raya_nodes_snapshot(with_latency=with_latency)
        data = _build_v2raya_nodes_response_data(snapshot)
        issues = (data.get("runtime") or {}).get("issues", [])
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
    proxy_url = getattr(core_engine.cfg, "DEFAULT_PROXY", None)
    node_payload = {
        "key": str(req.node_key or "").strip(),
        "node_id": str(req.node_id or "").strip(),
        "node_type": str(req.node_type or "subscriptionServer").strip(),
        "subscription_id": str(req.subscription_id or "").strip(),
        "name": str(req.node_name or req.node_id or "").strip(),
    }
    if not node_payload["node_id"]:
        return {"status": "warning", "message": "缺少节点 ID。"}
    result = proxy_manager.switch_v2raya_node_safely(node_payload, proxy_url=proxy_url if proxy_url else None)
    snapshot = result.get("snapshot") or proxy_manager.get_v2raya_nodes_snapshot(with_latency=False)
    data = _build_v2raya_nodes_response_data(snapshot)
    panel_message = result.get("message") or f"已请求切换到节点：{node_payload['name']}"
    print(
        f"[{proxy_manager.ts()}] [{'SUCCESS' if result.get('ok') else 'WARNING'}] "
        f"[代理面板] {panel_message}"
    )
    return {
        "status": "success" if result.get("ok") else "warning",
        "message": panel_message,
        "data": data,
    }


@router.post("/api/proxy/v2raya/mark_invalid")
async def api_v2raya_mark_invalid(req: V2rayANodeKeysReq, token: str = Depends(verify_token)):
    node_keys = [str(item or "").strip() for item in (req.node_keys or []) if str(item or "").strip()]
    if not node_keys:
        return {"status": "warning", "message": "请至少选择一个节点。"}
    changed = proxy_manager.set_v2raya_node_invalid_state(node_keys, invalid=True)
    data = _build_v2raya_nodes_response_data(proxy_manager.get_v2raya_nodes_snapshot(with_latency=False))
    return {
        "status": "success",
        "message": f"已标记 {len(changed)} 个节点为失效，自动切点时会跳过它们。",
        "data": data,
    }


@router.post("/api/proxy/v2raya/clear_invalid")
async def api_v2raya_clear_invalid(token: str = Depends(verify_token)):
    proxy_manager.clear_v2raya_invalid_node_keys()
    data = _build_v2raya_nodes_response_data(proxy_manager.get_v2raya_nodes_snapshot(with_latency=False))
    return {"status": "success", "message": "已清空 v2rayA 失效标记。", "data": data}


@router.post("/api/proxy/v2raya/dedupe")
async def api_v2raya_dedupe(token: str = Depends(verify_token)):
    data = _build_v2raya_nodes_response_data(proxy_manager.get_v2raya_nodes_snapshot(with_latency=False))
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
        return {"status": "success", "message": "当前没有检测到可移除的重复节点。", "data": data}
    proxy_manager.set_v2raya_node_invalid_state(duplicate_keys, invalid=True)
    data = _build_v2raya_nodes_response_data(proxy_manager.get_v2raya_nodes_snapshot(with_latency=False))
    return {
        "status": "success",
        "message": f"已将 {len(duplicate_keys)} 个重复节点标记为失效，后续自动切点会忽略它们。",
        "data": data,
    }
