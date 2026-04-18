import os
import time
import json
import secrets
import re
import random
import asyncio
import traceback
import threading
import sys
import subprocess
import shutil
import shlex
import urllib.parse
import zipfile
import yaml
import httpx
from fastapi import APIRouter, Depends, Header, Query, Request, WebSocket, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from typing import Any, List, Optional

from cloudflare import Cloudflare
from utils import core_engine, db_manager
from utils.config import reload_all_configs
from utils.integrations.sub2api_client import Sub2APIClient
from utils.integrations.tg_notifier import send_tg_msg_async
from utils.email_providers.gmail_oauth_handler import GmailOAuthHandler
from utils import proxy_manager

from global_state import VALID_TOKENS, CLUSTER_NODES, NODE_COMMANDS, cluster_lock, log_history, engine, verify_token, worker_status
import utils.config as cfg

router = APIRouter()

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.yaml")
START_SCRIPT_PATH = os.path.join(BASE_DIR, "start.ps1")
STOP_SCRIPT_PATH = os.path.join(BASE_DIR, "stop.ps1")
GMAIL_CLIENT_SECRETS = os.path.join(BASE_DIR, "data", "credentials.json")
GMAIL_TOKEN_PATH = os.path.join(BASE_DIR, "data", "token.json")
GMAIL_VERIFIER_PATH = os.path.join(BASE_DIR, "data", "temp_verifier.txt")
GITHUB_UPDATE_REPO = "YuHaiA/opaiRe"
CLASH_POOL_ROOT = "/opt/mihomo-pool"
CLASH_POOL_ENV_PATH = os.path.join(CLASH_POOL_ROOT, "pool.env")
CLASH_POOL_UPDATE_SCRIPT = os.path.join(CLASH_POOL_ROOT, "update_pool.sh")
CLASH_POOL_STATUS_SCRIPT = os.path.join(CLASH_POOL_ROOT, "status_pool.sh")

class DummyArgs:
    def __init__(self, proxy=None, once=False):
        self.proxy = proxy
        self.once = once


class ExportReq(BaseModel): emails: list[str]


class DeleteReq(BaseModel): emails: list[str]


class LoginData(BaseModel): password: str


class CFSyncExistingReq(BaseModel): sub_domains: str; api_email: str; api_key: str


class LuckMailBulkBuyReq(BaseModel): quantity: int; auto_tag: bool; config: dict


class SMSPriceReq(BaseModel): service: str = "openai"


class GmailExchangeReq(BaseModel): code: str


class CloudAccountItem(BaseModel): id: str; type: str


class CloudActionReq(BaseModel): accounts: List[CloudAccountItem]; action: str


class ClusterUploadAccountsReq(BaseModel): node_name: str; secret: str; accounts: list


class ClusterReportReq(BaseModel): node_name: str; secret: str; stats: dict; logs: list


class ClusterControlReq(BaseModel): node_name: str; action: str


class ClashPoolUpdateReq(BaseModel): sub_url: str


class V2rayASwitchReq(BaseModel):
    node_id: str
    node_type: Optional[str] = "subscriptionServer"
    subscription_id: Optional[str] = ""
    node_name: Optional[str] = ""


class ProjectUpdateReq(BaseModel):
    restart_after_update: bool = False


class DownloadUpdatePackageReq(BaseModel):
    version: str
    download_url: str


class MigrateUpdatePackageReq(BaseModel):
    version: str
    cleanup_zip: bool = True
    cleanup_other_versions: bool = False


class ExtResultReq(BaseModel):
    status: str
    task_id: Optional[str] = ""
    email: Optional[str] = ""
    password: Optional[str] = ""
    error_msg: Optional[str] = ""
    token_data: Optional[str] = ""
    callback_url: Optional[str] = ""
    code_verifier: Optional[str] = ""
    expected_state: Optional[str] = ""
    error_type: Optional[str] = "failed"


# ==========================================
# 辅助函数
# ==========================================
def get_web_password():
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                c = yaml.safe_load(f) or {}
                return str(c.get("web_password", "admin")).strip()
    except Exception:
        pass
    return "admin"


def _normalize_proxy_input_for_save(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = f"http://{text}"
    return text


def _normalize_proxy_input_list_for_save(raw_value) -> list[str]:
    if isinstance(raw_value, str):
        raw_items = [line.strip() for line in raw_value.splitlines() if line.strip()]
    elif isinstance(raw_value, list):
        raw_items = raw_value
    else:
        raw_items = []
    cleaned = []
    for item in raw_items:
        normalized = _normalize_proxy_input_for_save(item)
        if normalized:
            cleaned.append(normalized)
    return cleaned


def _build_http_dynamic_proxy_runtime() -> dict:
    enabled = bool(getattr(cfg, "HTTP_DYNAMIC_PROXY_ENABLE", False))
    configured_pool_size = int(getattr(cfg, "HTTP_DYNAMIC_PROXY_POOL_SIZE", 0) or 0)
    source_list = getattr(cfg, "HTTP_DYNAMIC_PROXY_LIST", []) or []
    default_proxy = str(getattr(cfg, "DEFAULT_PROXY", "") or "").strip()
    clash_pool_active = bool(getattr(cfg, "_clash_enable", False) and getattr(cfg, "_clash_pool_mode", False))

    queue_items = []
    try:
        with cfg.PROXY_QUEUE.mutex:
            queue_items = list(cfg.PROXY_QUEUE.queue)
    except Exception:
        queue_items = []

    actual_queue_channels = len([item for item in queue_items if item])
    using_default_fallback = enabled and not source_list and bool(default_proxy)
    invalid_empty = enabled and not source_list and not default_proxy
    single_source = (len(source_list) == 1) or using_default_fallback
    queue_owner = "clash" if clash_pool_active else ("http_dynamic" if enabled else "default")
    loaded_channels = actual_queue_channels if enabled and queue_owner == "http_dynamic" else 0
    single_source_cloned = enabled and single_source and loaded_channels > 1

    mode = "disabled"
    message = "HTTP 动态代理池未启用"
    if enabled:
        if queue_owner == "clash":
            mode = "shadowed_by_clash"
            message = "HTTP 动态代理池已开启，但当前 Clash 独享池优先级更高，动态代理池未进入运行队列"
        elif invalid_empty:
            mode = "invalid_empty"
            message = "已开启，但未填写 proxy_list 且未配置 default_proxy，运行时不会装载任何动态通道"
        elif using_default_fallback:
            mode = "fallback_default_proxy"
            message = "未填写动态代理列表，当前回退使用 default_proxy 构建动态通道队列"
        elif len(source_list) == 1:
            mode = "single_source_cloned"
            message = "单条动态代理已按通道数复制为多个并发工作位，适合按连接/会话轮换出口的网关"
        elif len(source_list) > 1:
            mode = "multi_source_round_robin"
            message = "多条动态代理已按通道数轮询装载到运行队列"
        else:
            mode = "unknown"
            message = "当前运行态已启用，但未识别到明确的动态代理来源"

    return {
        "enabled": enabled,
        "queue_owner": queue_owner,
        "configured_pool_size": configured_pool_size,
        "source_count": len(source_list),
        "loaded_channels": loaded_channels,
        "using_default_fallback": using_default_fallback,
        "single_source_cloned": single_source_cloned,
        "mode": mode,
        "queue_ready": bool(enabled and queue_owner == "http_dynamic" and loaded_channels > 0 and not invalid_empty),
        "error": "HTTP 动态代理池已开启，但当前没有任何可装载的动态代理通道" if invalid_empty else "",
        "message": message,
    }


def _read_clash_pool_env() -> dict:
    """读取宿主机 Mihomo 代理池的环境文件。"""
    if not os.path.exists(CLASH_POOL_ENV_PATH):
        raise FileNotFoundError(f"未找到 {CLASH_POOL_ENV_PATH}")
    env_map = {}
    with open(CLASH_POOL_ENV_PATH, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            env_map[key] = value
    return env_map


def _run_git_command(args: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git"] + args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            cwd=BASE_DIR,
        )
        return proc.returncode, (proc.stdout or "").strip()
    except FileNotFoundError:
        return 127, "git_not_found"


def _safe_extract_zip(zip_path: str, target_dir: str) -> None:
    os.makedirs(target_dir, exist_ok=True)
    target_real = os.path.realpath(target_dir)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            member_name = str(member.filename or "")
            if not member_name or member_name.endswith("/"):
                continue
            destination = os.path.realpath(os.path.join(target_dir, member_name))
            if not destination.startswith(target_real + os.sep) and destination != target_real:
                raise ValueError(f"压缩包包含非法路径: {member_name}")
        zf.extractall(target_dir)


def _get_updates_root() -> str:
    return os.path.join(BASE_DIR, "updates")


def _sanitize_update_version(version: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]", "_", str(version or "").strip())


def _get_update_paths(version: str) -> dict:
    safe_version = _sanitize_update_version(version)
    updates_root = _get_updates_root()
    version_root = os.path.join(updates_root, safe_version)
    package_dir = os.path.join(version_root, "package")
    extract_dir = os.path.join(version_root, "source")
    zip_path = os.path.join(package_dir, f"{safe_version}.zip")
    marker_path = os.path.join(version_root, ".download_complete")
    return {
        "version": str(version or "").strip(),
        "safe_version": safe_version,
        "updates_root": updates_root,
        "version_root": version_root,
        "package_dir": package_dir,
        "extract_dir": extract_dir,
        "zip_path": zip_path,
        "marker_path": marker_path,
    }


def _list_downloaded_updates() -> list[dict]:
    updates_root = _get_updates_root()
    if not os.path.isdir(updates_root):
        return []
    result = []
    for name in os.listdir(updates_root):
        version_root = os.path.join(updates_root, name)
        if not os.path.isdir(version_root):
            continue
        paths = _get_update_paths(name)
        marker_exists = os.path.exists(paths["marker_path"])
        extract_exists = os.path.isdir(paths["extract_dir"])
        zip_exists = os.path.isfile(paths["zip_path"])
        mtime = 0.0
        try:
            mtime = os.path.getmtime(version_root)
        except Exception:
            mtime = 0.0
        result.append({
            "version": name,
            "version_root": version_root,
            "package_dir": paths["package_dir"],
            "extract_dir": paths["extract_dir"],
            "zip_path": paths["zip_path"],
            "marker_exists": marker_exists,
            "extract_exists": extract_exists,
            "zip_exists": zip_exists,
            "mtime": mtime,
        })
    result.sort(key=lambda item: item.get("mtime", 0), reverse=True)
    return result


def _copy_directory_contents(src_dir: str, dest_dir: str, exclude_names: set[str] | None = None) -> tuple[int, int]:
    exclude_names = exclude_names or set()
    copied_files = 0
    copied_dirs = 0
    for root, dirs, files in os.walk(src_dir):
        dirs[:] = [item for item in dirs if item not in exclude_names]
        rel_root = os.path.relpath(root, src_dir)
        target_root = dest_dir if rel_root == "." else os.path.join(dest_dir, rel_root)
        os.makedirs(target_root, exist_ok=True)
        copied_dirs += 1
        for filename in files:
            if filename in exclude_names:
                continue
            src_path = os.path.join(root, filename)
            dest_path = os.path.join(target_root, filename)
            shutil.copy2(src_path, dest_path)
            copied_files += 1
    return copied_files, copied_dirs


def _build_project_update_status(fetch_remote: bool = True) -> dict:
    status = {
        "git_available": False,
        "is_git_repo": False,
        "branch": "",
        "is_main_branch": False,
        "dirty_files": [],
        "dirty_count": 0,
        "local_head": "",
        "remote_head": "",
        "merge_base": "",
        "needs_update": False,
        "fast_forward": False,
        "can_update": False,
        "message": "",
    }

    code, output = _run_git_command(["--version"])
    if code != 0:
        status["message"] = "当前环境未安装 Git，请使用左侧的普通用户更新流程。"
        return status
    status["git_available"] = True

    code, output = _run_git_command(["rev-parse", "--is-inside-work-tree"])
    if code != 0 or output.lower() != "true":
        status["message"] = "当前目录不是 Git 工作区，无法执行项目内更新。"
        return status
    status["is_git_repo"] = True

    code, branch = _run_git_command(["branch", "--show-current"])
    if code == 0:
        status["branch"] = branch.strip()
    status["is_main_branch"] = status["branch"] == "main"

    code, dirty_output = _run_git_command(["status", "--porcelain"])
    dirty_lines = [line.rstrip() for line in dirty_output.splitlines() if line.strip()] if code == 0 else []
    status["dirty_files"] = dirty_lines
    status["dirty_count"] = len(dirty_lines)

    if fetch_remote:
        fetch_code, fetch_output = _run_git_command(["fetch", "origin"], timeout=120)
        if fetch_code != 0:
            status["message"] = f"无法同步远端信息：{fetch_output or 'git fetch origin 失败'}"
            return status

    code, local_head = _run_git_command(["rev-parse", "HEAD"])
    if code == 0:
        status["local_head"] = local_head.strip()
    code, remote_head = _run_git_command(["rev-parse", "origin/main"])
    if code != 0:
        status["message"] = "未找到 origin/main，请先确认当前仓库已配置 origin 并完成首次拉取。"
        return status
    status["remote_head"] = remote_head.strip()
    code, merge_base = _run_git_command(["merge-base", "HEAD", "origin/main"])
    if code == 0:
        status["merge_base"] = merge_base.strip()

    local_head = status["local_head"]
    remote_head = status["remote_head"]
    merge_base = status["merge_base"]

    if not status["is_main_branch"]:
        status["message"] = f"当前分支是 {status['branch'] or '未知'}，仅支持在 main 分支上执行项目内更新。"
        return status
    if status["dirty_count"] > 0:
        status["message"] = f"当前工作区有 {status['dirty_count']} 处未提交修改，请先提交或清理后再更新。"
        return status
    if local_head == remote_head:
        status["message"] = "当前项目已经和 origin/main 同步，无需更新。"
        status["can_update"] = False
        status["needs_update"] = False
        return status
    if merge_base == local_head and remote_head and remote_head != local_head:
        status["needs_update"] = True
        status["fast_forward"] = True
        status["can_update"] = True
        status["message"] = "检测到 origin/main 有新提交，可执行 fast-forward 更新。"
        return status
    if merge_base == remote_head and local_head != remote_head:
        status["message"] = "当前本地 main 领先于 origin/main，不适合执行自动更新。"
        return status

    status["message"] = "当前本地与 origin/main 已分叉，自动更新已拦截，请手动处理 Git 冲突。"
    return status


def _write_clash_pool_env(env_map: dict) -> None:
    """回写代理池配置，只覆盖关键环境项并保留其余扩展字段。"""
    primary_keys = ["COUNT", "SUB_URL", "SECRET", "IMAGE"]
    lines = []
    for key in primary_keys:
        if key in env_map:
            lines.append(f"{key}={shlex.quote(str(env_map[key]))}")
    for key, value in env_map.items():
        if key not in primary_keys:
            lines.append(f"{key}={shlex.quote(str(value))}")
    with open(CLASH_POOL_ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _run_clash_pool_script(script_path: str, timeout: int = 300) -> tuple[int, str]:
    """在容器内执行宿主机代理池脚本，并返回退出码与输出。"""
    proc = subprocess.run(
        ["bash", script_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        cwd=CLASH_POOL_ROOT if os.path.isdir(CLASH_POOL_ROOT) else None,
    )
    return proc.returncode, proc.stdout or ""


def _get_clash_pool_status_output() -> str:
    if not os.path.exists(CLASH_POOL_STATUS_SCRIPT):
        return ""
    try:
        _, output = _run_clash_pool_script(CLASH_POOL_STATUS_SCRIPT, timeout=20)
        return output.strip()
    except Exception as e:
        return f"状态读取失败: {e}"


def _get_clash_pool_group_candidates(env_map: dict | None = None) -> tuple[list[dict], str]:
    """通过 Mihomo controller API 读取当前真实策略组。

    这样前端在订阅更新后可以直接展示“现在到底有哪些策略组可选”，
    避免用户手动猜 group_name。
    """
    try:
        env_map = env_map or _read_clash_pool_env()
        secret = str(env_map.get("SECRET") or "").strip()
        count = int(env_map.get("COUNT") or 1)
        api_port = 42001 if count > 0 else 42001
        url = f"http://host.docker.internal:{api_port}/proxies"
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        resp = httpx.get(url, headers=headers, timeout=15.0)
        if resp.status_code != 200:
            return [], f"读取 Clash API 失败: HTTP {resp.status_code}"
        data = resp.json()
        proxies = data.get("proxies") or {}
        groups = []
        for name, meta in proxies.items():
            if not isinstance(meta, dict):
                continue
            all_items = meta.get("all")
            now_name = meta.get("now")
            if not isinstance(all_items, list):
                continue
            groups.append({
                "name": str(name),
                "current": str(now_name or ""),
                "node_count": len(all_items),
            })
        groups.sort(key=lambda x: (-int(x.get("node_count") or 0), x.get("name") or ""))
        return groups, ""
    except Exception as e:
        return [], f"读取策略组失败: {e}"


def _sanitize_clash_sub_url(sub_url: str) -> str:
    value = str(sub_url or "").strip().strip("'\"")
    return re.sub(r"\s+", "", value)


def _replace_query_param(url: str, key: str, value: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    items = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    out = []
    replaced = False
    for k, v in items:
        if k == key:
            if not replaced:
                out.append((k, value))
                replaced = True
            continue
        out.append((k, v))
    if not replaced:
        out.append((key, value))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(out, doseq=True)))


def _build_clash_sub_url_candidates(sub_url: str) -> list[str]:
    normalized = _sanitize_clash_sub_url(sub_url)
    if not normalized:
        return []
    candidates = [normalized]
    parsed = urllib.parse.urlsplit(normalized)
    query_map = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    current_flag = str(query_map.get("flag") or "").strip().lower()

    if current_flag != "mihomo":
        candidates.append(_replace_query_param(normalized, "flag", "mihomo"))
    if not current_flag:
        candidates.append(_replace_query_param(normalized, "flag", "clash-meta"))
        candidates.append(_replace_query_param(normalized, "flag", "clash"))

    seen = set()
    ordered = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _classify_sub_payload(text: str) -> str:
    body = str(text or "").strip()
    if not body:
        return "empty"
    lowered = body[:256].lower()
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return "html"
    if any(token in body for token in ["proxy-groups:", "proxy-providers:", "\nproxies:", "\nrules:", "mixed-port:"]):
        return "yaml"
    compact = re.sub(r"\s+", "", body)
    if "://" in body and any(proto in body for proto in ["ss://", "vmess://", "vless://", "trojan://", "hysteria://", "hy2://", "tuic://"]):
        return "raw-uri"
    if len(compact) > 128 and re.fullmatch(r"[A-Za-z0-9+/=_-]+", compact or ""):
        return "base64"
    return "unknown"


def _probe_clash_sub_url(sub_url: str) -> dict:
    result = {
        "url": sub_url,
        "ok": False,
        "reason": "",
        "http_status": None,
        "payload_kind": "",
        "proxy_count": 0,
        "provider_count": 0,
        "group_count": 0,
        "group_names": [],
        "tls_insecure_fallback": False,
    }
    last_error = ""

    for verify_tls in (True, False):
        if verify_tls is False and result["http_status"] is not None:
            break
        try:
            resp = httpx.get(
                sub_url,
                timeout=25.0,
                follow_redirects=True,
                verify=verify_tls,
                headers={"User-Agent": "openai-cpa/subscription-probe"},
            )
            result["http_status"] = resp.status_code
            if verify_tls is False:
                result["tls_insecure_fallback"] = True
            if resp.status_code != 200:
                result["reason"] = f"HTTP {resp.status_code}"
                return result

            text = resp.text or ""
            result["payload_kind"] = _classify_sub_payload(text)
            if result["payload_kind"] in {"base64", "raw-uri"}:
                result["reason"] = "返回的是通用订阅串，不是 Mihomo/Clash YAML"
                return result
            if result["payload_kind"] == "html":
                result["reason"] = "返回的是 HTML 页面，不是订阅配置"
                return result
            if result["payload_kind"] == "empty":
                result["reason"] = "订阅内容为空"
                return result

            try:
                data = yaml.safe_load(text)
            except Exception as e:
                result["reason"] = f"YAML 解析失败: {e}"
                return result

            if not isinstance(data, dict):
                result["reason"] = "订阅返回内容不是 YAML 字典结构"
                return result

            proxies = data.get("proxies") or []
            proxy_providers = data.get("proxy-providers") or {}
            groups = data.get("proxy-groups") or []

            if isinstance(proxies, list):
                result["proxy_count"] = len(proxies)
            elif isinstance(proxies, dict):
                result["proxy_count"] = len(proxies)

            if isinstance(proxy_providers, dict):
                result["provider_count"] = len(proxy_providers)

            if isinstance(groups, list):
                result["group_count"] = len(groups)
                result["group_names"] = [
                    str(item.get("name") or "").strip()
                    for item in groups
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]

            if result["group_count"] <= 0:
                result["reason"] = "订阅未包含任何策略组"
                return result
            if result["proxy_count"] <= 0 and result["provider_count"] <= 0:
                result["reason"] = "订阅中未包含任何节点或代理提供器"
                return result

            result["ok"] = True
            if result["tls_insecure_fallback"]:
                result["reason"] = "已使用 TLS 非校验回退探测成功"
            return result
        except Exception as e:
            last_error = str(e)
            if verify_tls is False:
                break
            continue

    result["reason"] = last_error or "订阅探测失败"
    return result


def _resolve_clash_sub_url(sub_url: str) -> tuple[dict | None, list[dict]]:
    probes = []
    for candidate in _build_clash_sub_url_candidates(sub_url):
        probe = _probe_clash_sub_url(candidate)
        probes.append(probe)
        if probe.get("ok"):
            return probe, probes
    return None, probes


def _get_clash_pool_api_urls(env_map: dict | None = None) -> list[str]:
    env_map = env_map or _read_clash_pool_env()
    try:
        count = max(1, int(env_map.get("COUNT") or 1))
    except Exception:
        count = 1
    return [f"http://host.docker.internal:{42000 + i}" for i in range(1, count + 1)]


def _get_clash_pool_config_path(env_map: dict | None = None) -> str:
    env_map = env_map or _read_clash_pool_env()
    try:
        count = max(1, int(env_map.get("COUNT") or 1))
    except Exception:
        count = 1
    for idx in range(1, count + 1):
        path = os.path.join(CLASH_POOL_ROOT, f"config_{idx}", "config.yaml")
        if os.path.exists(path):
            return path
    return os.path.join(CLASH_POOL_ROOT, "config_1", "config.yaml")


def _extract_default_route_groups(env_map: dict | None = None) -> list[str]:
    try:
        config_path = _get_clash_pool_config_path(env_map)
        if not os.path.exists(config_path):
            return []
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


def _find_actual_group_name(proxies: dict, keyword: str) -> str:
    wanted = str(keyword or "").strip()
    wanted_lower = wanted.lower()
    ai_hints = ["chatgpt", "openai", "copilot", "claude", "anthropic", "ai"]
    fallback_name = ""
    fallback_score = None
    for key, meta in proxies.items():
        if not isinstance(meta, dict):
            continue
        all_items = meta.get("all")
        if not isinstance(all_items, list):
            continue
        name = str(key or "").strip()
        if not name:
            continue
        leaf_count = 0
        child_group_count = 0
        for item in all_items:
            child = str(item or "").strip()
            if not child:
                continue
            child_meta = proxies.get(child)
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

        if wanted and any(wanted_lower in str(item or "").strip().lower() for item in all_items):
            score[1] += 5
        if any(hint in name.lower() for hint in ai_hints):
            score[1] += 3

        score_tuple = tuple(score)
        if fallback_score is None or score_tuple > fallback_score:
            fallback_score = score_tuple
            fallback_name = name
    return fallback_name


def _find_group_path(proxies: dict, start_group: str, target_group: str) -> list[str]:
    start = str(start_group or "").strip()
    target = str(target_group or "").strip()
    if not start or not target:
        return []
    if start == target:
        return [start]

    queue_items: list[tuple[str, list[str]]] = [(start, [start])]
    visited = {start}

    while queue_items:
        current, path = queue_items.pop(0)
        meta = proxies.get(current)
        if not isinstance(meta, dict):
            continue
        all_items = meta.get("all")
        if not isinstance(all_items, list):
            continue
        for raw in all_items:
            child = str(raw or "").strip()
            if not child:
                continue
            if child == target:
                return path + [target]
            child_meta = proxies.get(child)
            if isinstance(child_meta, dict) and isinstance(child_meta.get("all"), list) and child not in visited:
                visited.add(child)
                queue_items.append((child, path + [child]))
    return []


def _filter_assignable_nodes(proxies: dict, group_name: str, blacklist: list[str]) -> list[str]:
    group_meta = proxies.get(group_name) if isinstance(proxies, dict) else None
    all_nodes = group_meta.get("all", []) if isinstance(group_meta, dict) else []
    valid_nodes = []
    for raw in all_nodes:
        node_name = str(raw or "").strip()
        if not node_name or node_name == group_name:
            continue
        node_meta = proxies.get(node_name, {})
        if isinstance(node_meta, dict) and isinstance(node_meta.get("all"), list):
            continue
        upper_name = node_name.upper()
        if any(str(flag or "").strip().upper() in upper_name for flag in blacklist):
            continue
        valid_nodes.append(node_name)
    return valid_nodes


def _align_default_route_group(api_url: str, headers: dict, proxies_payload: dict, default_group: str, target_group: str) -> tuple[list[dict], str]:
    path = _find_group_path(proxies_payload, default_group, target_group)
    if not path:
        return [], f"默认路由组 {default_group} 无法到达 {target_group}"
    if len(path) < 2:
        return [], ""

    ops = []
    for idx in range(len(path) - 1):
        parent = path[idx]
        child = path[idx + 1]
        try:
            resp = httpx.put(
                f"{api_url}/proxies/{urllib.parse.quote(parent, safe='')}",
                headers=headers,
                json={"name": child},
                timeout=8.0,
            )
            if resp.status_code == 204:
                ops.append({"group": parent, "select": child, "ok": True})
            else:
                ops.append({"group": parent, "select": child, "ok": False, "status": resp.status_code})
        except Exception as e:
            ops.append({"group": parent, "select": child, "ok": False, "error": str(e)})
    failed = [x for x in ops if not x.get("ok")]
    if failed:
        return ops, f"默认路由组对齐失败 {len(failed)} 项"
    return ops, ""


def _sync_clash_group_name(actual_group_name: str) -> dict:
    actual = str(actual_group_name or "").strip()
    if not actual:
        return {"updated": False, "before": "", "after": ""}

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            conf = yaml.safe_load(f) or {}
        clash_conf = conf.setdefault("clash_proxy_pool", {})
        before = str(clash_conf.get("group_name") or "").strip()
        if before == actual:
            return {"updated": False, "before": before, "after": actual}
        clash_conf["group_name"] = actual
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(conf, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        try:
            reload_all_configs()
        except Exception:
            pass
        return {"updated": True, "before": before, "after": actual}
    except Exception as e:
        return {"updated": False, "before": "", "after": actual, "error": str(e)}


def _rollback_clash_pool_update(previous_env: dict) -> tuple[int, str]:
    _write_clash_pool_env(previous_env)
    return _run_clash_pool_script(CLASH_POOL_UPDATE_SCRIPT, timeout=420)


def _spread_clash_pool_nodes(env_map: dict | None = None) -> tuple[list[dict], str]:
    """订阅更新后，为每个 Mihomo 实例尽量分配不同节点，避免全都落在同一出口。"""
    try:
        env_map = env_map or _read_clash_pool_env()
        secret = str(env_map.get("SECRET") or "").strip()
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        api_urls = _get_clash_pool_api_urls(env_map)
        group_keyword = str(getattr(cfg, "_c", {}).get("clash_proxy_pool", {}).get("group_name", "") or "").strip()
        blacklist = getattr(cfg, "_c", {}).get("clash_proxy_pool", {}).get("blacklist", []) or []
        default_route_groups = _extract_default_route_groups(env_map)
        if not isinstance(blacklist, list):
            blacklist = []

        proxies_payload = None
        group_name = ""
        last_err = ""

        for _ in range(20):
            try:
                resp = httpx.get(f"{api_urls[0]}/proxies", headers=headers, timeout=8.0)
                if resp.status_code == 200:
                    proxies_payload = resp.json().get("proxies") or {}
                    group_name = _find_actual_group_name(proxies_payload, group_keyword)
                    if group_name:
                        break
                    last_err = f"未找到策略组关键词: {group_keyword or '（空）'}"
                else:
                    last_err = f"HTTP {resp.status_code}"
            except Exception as e:
                last_err = str(e)
            time.sleep(1.0)

        if not isinstance(proxies_payload, dict) or not group_name:
            return [], f"策略组分流失败: {last_err or '未读取到代理信息'}"

        valid_nodes = _filter_assignable_nodes(proxies_payload, group_name, blacklist)
        if not valid_nodes:
            return [], f"策略组 {group_name} 下无可分配节点（可能被黑名单过滤空）"

        random.shuffle(valid_nodes)
        assigned = []
        encoded_group = urllib.parse.quote(group_name, safe="")
        for idx, api_url in enumerate(api_urls):
            node_name = valid_nodes[idx % len(valid_nodes)]
            try:
                switch_resp = httpx.put(
                    f"{api_url}/proxies/{encoded_group}",
                    headers=headers,
                    json={"name": node_name},
                    timeout=8.0,
                )
                if switch_resp.status_code == 204:
                    align_ops = []
                    align_error = ""
                    for root_group in default_route_groups:
                        ops, err = _align_default_route_group(api_url, headers, proxies_payload, root_group, group_name)
                        if ops:
                            align_ops.extend(ops)
                        if err and not align_error:
                            align_error = err
                    assigned.append({
                        "api": api_url,
                        "group": group_name,
                        "node": node_name,
                        "ok": True if not align_error else False,
                        "route_align": align_ops,
                        "route_group": default_route_groups,
                        "route_error": align_error
                    })
                else:
                    assigned.append({"api": api_url, "group": group_name, "node": node_name, "ok": False, "status": switch_resp.status_code})
            except Exception as e:
                assigned.append({"api": api_url, "group": group_name, "node": node_name, "ok": False, "error": str(e)})

        failed = [x for x in assigned if not x.get("ok")]
        if failed:
            return assigned, f"策略组分流部分失败，共 {len(failed)} 个实例未成功切换"
        return assigned, ""
    except Exception as e:
        return [], f"策略组分流异常: {e}"


def _inspect_clash_pool_runtime(env_map: dict | None = None) -> tuple[dict, str]:
    try:
        env_map = env_map or _read_clash_pool_env()
        secret = str(env_map.get("SECRET") or "").strip()
        headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        api_urls = _get_clash_pool_api_urls(env_map)
        default_route_groups = _extract_default_route_groups(env_map)
        group_keyword = str(getattr(cfg, "_c", {}).get("clash_proxy_pool", {}).get("group_name", "") or "").strip()

        runtime = {
            "group_keyword": group_keyword,
            "actual_group_name": "",
            "default_route_groups": default_route_groups,
            "effective_sub_url": str(env_map.get("SUB_URL") or "").strip(),
            "instance_total": len(api_urls),
            "instance_ok_count": 0,
            "aligned_count": 0,
            "all_aligned": None,
            "instances": [],
        }
        errors = []

        for idx, api_url in enumerate(api_urls, start=1):
            item = {
                "slot": idx,
                "api": api_url,
                "ok": False,
                "group": "",
                "current_node": "",
                "route_aligned": None,
                "route_states": [],
                "error": "",
            }
            try:
                resp = httpx.get(f"{api_url}/proxies", headers=headers, timeout=8.0)
                if resp.status_code != 200:
                    item["error"] = f"HTTP {resp.status_code}"
                    errors.append(f"{idx}号机 {item['error']}")
                    runtime["instances"].append(item)
                    continue

                proxies_payload = resp.json().get("proxies") or {}
                actual_group_name = _find_actual_group_name(proxies_payload, group_keyword)
                current_node = str((proxies_payload.get(actual_group_name) or {}).get("now") or "").strip() if actual_group_name else ""
                route_aligned = True if default_route_groups and actual_group_name else None
                route_states = []

                for root_group in default_route_groups:
                    root_meta = proxies_payload.get(root_group) or {}
                    root_now = str(root_meta.get("now") or "").strip()
                    path = _find_group_path(proxies_payload, root_group, actual_group_name) if actual_group_name else []
                    aligned = bool(path) and all(
                        str((proxies_payload.get(path[path_idx]) or {}).get("now") or "").strip() == path[path_idx + 1]
                        for path_idx in range(len(path) - 1)
                    )
                    if route_aligned is not None:
                        route_aligned = route_aligned and aligned
                    route_states.append({
                        "group": root_group,
                        "now": root_now,
                        "path": path,
                        "aligned": aligned,
                    })

                item.update({
                    "ok": True,
                    "group": actual_group_name,
                    "current_node": current_node,
                    "route_aligned": route_aligned,
                    "route_states": route_states,
                })
                if actual_group_name and not runtime["actual_group_name"]:
                    runtime["actual_group_name"] = actual_group_name
                runtime["instance_ok_count"] += 1
                if route_aligned is True:
                    runtime["aligned_count"] += 1
            except Exception as e:
                item["error"] = str(e)
                errors.append(f"{idx}号机 {e}")
            runtime["instances"].append(item)

        if default_route_groups:
            runtime["all_aligned"] = runtime["aligned_count"] == runtime["instance_ok_count"] and runtime["instance_ok_count"] > 0

        return runtime, "；".join(errors[:5])
    except Exception as e:
        return {}, f"读取 Clash 运行态失败: {e}"

def parse_cpa_usage_to_details(raw_usage: dict) -> dict:
    details = {"is_cpa": True}
    try:
        payload = raw_usage
        if "body" in raw_usage and isinstance(raw_usage["body"], str):
            try:
                payload = json.loads(raw_usage["body"])
            except:
                pass
        details["cpa_plan_type"] = str(payload.get("plan_type", "未知")).upper()
        total = payload.get("total_granted") or payload.get("hard_limit_usd") or payload.get("total")
        used = payload.get("total_used") or payload.get("total_usage") or payload.get("used")
        if total is not None and used is not None:
            total_val = float(total)
            used_val = float(used)
            details["cpa_total"] = f"${total_val:.2f}"
            details["cpa_remaining"] = f"${max(0.0, total_val - used_val):.2f}"
        else:
            details["cpa_total"] = "100%"
            details["cpa_remaining"] = "未知"

        rate_limit = payload.get("rate_limit", {})
        if isinstance(rate_limit, dict):
            primary = rate_limit.get("primary_window", {})
            if primary:
                p_remain = primary.get("remaining_percent")
                if p_remain is None and primary.get("used_percent") is not None:
                    p_remain = 100.0 - float(primary.get("used_percent"))
                details["cpa_primary_remain_pct"] = round(float(p_remain if p_remain is not None else 100.0), 1)

        code_review = payload.get("code_review_rate_limit", {})
        if isinstance(code_review, dict):
            c_primary = code_review.get("primary_window", {})
            if c_primary:
                c_remain = c_primary.get("remaining_percent")
                if c_remain is None and c_primary.get("used_percent") is not None:
                    c_remain = 100.0 - float(c_primary.get("used_percent"))
                details["cpa_codex_remain_pct"] = round(float(c_remain if c_remain is not None else 100.0), 1)

        details["cpa_used_percent"] = round(100.0 - details.get("cpa_primary_remain_pct", 100.0), 1)
        return details
    except Exception as e:
        print(f"[DEBUG] 解析CPA用量异常: {e}")
    details["cpa_total"] = "0.00";
    details["cpa_remaining"] = "0.00";
    details["cpa_used_percent"] = 0.0;
    details["cpa_plan_type"] = "未知"
    return details

@router.get("/")
async def get_dashboard():
    version = "1.0.0"
    js_path = os.path.join(BASE_DIR, "static", "js", "app.js")
    try:
        if os.path.exists(js_path):
            with open(js_path, "r", encoding="utf-8") as f:
                match = re.search(r"appVersion:\s*['\"]([^'\"]+)['\"]", f.read())
                if match: version = match.group(1)
    except Exception:
        pass

    html_path = os.path.join(BASE_DIR, "index.html")
    if not os.path.exists(html_path): return HTMLResponse(content="<h1>找不到 index.html</h1>", status_code=404)

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content.replace("__VER__", version),
                        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@router.post("/api/login")
async def login(data: LoginData):
    if data.password == get_web_password():
        token = secrets.token_hex(16)
        VALID_TOKENS.add(token)
        return {"status": "success", "token": token}
    return {"status": "error", "message": "密码错误"}


@router.get("/api/status")
async def get_status(token: str = Depends(verify_token)):
    ext_running = bool(getattr(core_engine.cfg, "REG_MODE", "protocol") == "extension" and core_engine.run_stats.get("ext_is_running"))
    return {"is_running": engine.is_running() or ext_running}


@router.get("/api/system/web_process_info")
async def get_web_process_info(token: str = Depends(verify_token)):
    return {
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "listen_url": "http://127.0.0.1:8000",
        "project_root": BASE_DIR,
        "start_script_path": START_SCRIPT_PATH,
        "stop_script_path": STOP_SCRIPT_PATH,
        "start_command": f'powershell -ExecutionPolicy Bypass -File "{START_SCRIPT_PATH}"',
        "stop_command": f'powershell -ExecutionPolicy Bypass -File "{STOP_SCRIPT_PATH}"',
    }

@router.post("/api/start")
async def start_task(token: str = Depends(verify_token)):
    if engine.is_running(): return {"status": "error", "message": "任务已经在运行中！"}
    try:
        reload_all_configs()
    except Exception as e:
        print(f"[{core_engine.ts()}] [警告] 启动重载提示: {e}")

    if getattr(core_engine.cfg, 'REG_MODE', 'protocol') == 'extension':
        return {"status": "error", "message": "当前为古法插件模式，请使用前端【古法】模式和浏览器插件启动。"}

    default_proxy = getattr(core_engine.cfg, 'DEFAULT_PROXY', None)
    args = DummyArgs(proxy=default_proxy if default_proxy else None)
    core_engine.run_stats.update({"success": 0, "failed": 0, "retries": 0, "pwd_blocked": 0, "phone_verify": 0, "start_time": time.time(), "ext_is_running": False})
    if getattr(core_engine.cfg, 'ENABLE_CPA_MODE', False):
        core_engine.run_stats["target"] = 0
        engine.start_cpa(args)
        return {"status": "success", "message": "启动成功：已自动识别并开启 [CPA 智能仓管模式]"}
    elif getattr(core_engine.cfg, 'ENABLE_SUB2API_MODE', False):
        engine.start_sub2api(args)
        return {"status": "success", "message": "启动成功：已自动识别并开启 [Sub2API 仓管模式]"}
    else:
        core_engine.run_stats["target"] = core_engine.cfg.NORMAL_TARGET_COUNT
        engine.start_normal(args)
        return {"status": "success", "message": "启动成功：已自动识别并开启 [常规量产模式]"}


@router.post("/api/stop")
async def stop_task(token: str = Depends(verify_token)):
    if not engine.is_running(): return {"status": "warning", "message": "当前没有运行的任务"}
    stats = core_engine.run_stats
    elapsed_time = round(time.time() - stats["start_time"], 1) if stats["start_time"] > 0 else 0
    total_attempts = stats["success"] + stats["failed"]
    success_rate = round((stats["success"] / total_attempts * 100), 2) if total_attempts > 0 else 0.0
    avg_time = round(elapsed_time / stats["success"], 1) if stats["success"] > 0 else 0.0
    target_str = stats["target"] if stats["target"] > 0 else "∞"
    template_str = getattr(core_engine.cfg, 'TG_BOT', {}).get("template_stop", "🛑 停止：成功 {success}/{target}")
    pwd_blocked = stats["pwd_blocked"] if stats["pwd_blocked"] > 0 else 0
    phone_blocked = stats["phone_verify"] if stats["phone_verify"] > 0 else 0

    try:
        msg = template_str.format(success_rate=success_rate, success=stats['success'], target=target_str,
                                  failed=stats['failed'], retries=stats['retries'], elapsed_time=elapsed_time,
                                  pwd_blocked=pwd_blocked, phone_verify=phone_blocked, avg_time=avg_time)
    except Exception:
        msg = f"⚠️ TG 模板渲染出错：未知的变量格式。\n请检查配置面板中的模板变量是否正确填写。"

    asyncio.create_task(send_tg_msg_async(msg))
    engine.stop()
    return {"status": "success", "message": "已发送停止指令，正在安全退出..."}


@router.get("/api/stats")
async def get_stats(token: str = Depends(verify_token)):
    stats = core_engine.run_stats
    current_reg_mode = getattr(core_engine.cfg, 'REG_MODE', 'protocol')
    ext_running = bool(current_reg_mode == 'extension' and stats.get("ext_is_running"))
    is_running = engine.is_running() or ext_running

    if is_running:
        elapsed = round(time.time() - stats["start_time"], 1) if stats.get("start_time", 0) > 0 else 0
        stats["_frozen_elapsed"] = elapsed
    else:
        elapsed = stats.get("_frozen_elapsed", 0)

    total_attempts = stats["success"] + stats["failed"]
    success_rate = round((stats["success"] / total_attempts * 100), 2) if total_attempts > 0 else 0.0
    avg_time = round(elapsed / stats["success"], 1) if stats["success"] > 0 else 0.0

    progress_pct = 0
    if stats["target"] > 0:
        progress_pct = min(100, round((stats["success"] / stats["target"]) * 100, 1))
    elif stats["success"] > 0:
        progress_pct = 100

    if current_reg_mode == 'extension':
        current_mode = "插件托管 (古法)"
    else:
        current_mode = "CPA 仓管" if getattr(core_engine.cfg, 'ENABLE_CPA_MODE', False) else (
            "Sub2Api 仓管" if getattr(core_engine.cfg, 'ENABLE_SUB2API_MODE', False) else "常规量产")

    return {
        "success": stats["success"], "failed": stats["failed"], "retries": stats["retries"],
        "pwd_blocked": stats.get("pwd_blocked", 0), "phone_verify": stats.get("phone_verify", 0),
        "total": total_attempts, "target": stats["target"] if stats["target"] > 0 else "∞",
        "success_rate": f"{success_rate}%", "elapsed": f"{elapsed}s", "avg_time": f"{avg_time}s",
        "progress_pct": f"{progress_pct}%", "is_running": is_running, "mode": current_mode
    }


@router.post("/api/start_check")
async def start_check_api(token: str = Depends(verify_token)):
    if engine.is_running(): return {"code": 400, "message": "系统正在运行中，请先停止主任务！"}
    default_proxy = getattr(core_engine.cfg, 'DEFAULT_PROXY', None)
    engine.start_check(DummyArgs(proxy=default_proxy if default_proxy else None))
    return {"code": 200, "message": "独立测活指令已下发！"}


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
    if summary.get("live_count", 0) > 0:
        return {
            "status": "success",
            "message": f"v2rayN 批量测活完成：存活 {summary['live_count']} / {summary['tested_count']}，后续只会在活节点池内切换。",
            "tested_count": summary["tested_count"],
            "live_count": summary["live_count"],
            "dead_count": summary["dead_count"],
            "subscription_updated": summary.get("subscription_updated", False),
            "live_names": live_names,
        }
    return {
        "status": "warning",
        "message": f"v2rayN 批量测活完成：0 / {summary['tested_count']} 存活，请检查订阅、出口地区或本地代理链路。",
        "tested_count": summary["tested_count"],
        "live_count": summary["live_count"],
        "dead_count": summary["dead_count"],
        "subscription_updated": summary.get("subscription_updated", False),
        "live_names": live_names,
    }


@router.post("/api/proxy/v2rayn/update_subscription")
async def api_v2rayn_update_subscription(token: str = Depends(verify_token)):
    ok, message = proxy_manager.run_v2rayn_subscription_update_only()
    return {
        "status": "success" if ok else "warning",
        "message": message,
    }


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
    text = str(value).strip()
    return text


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
        message = _first_v2raya_text(payload.get("message") if isinstance(payload, dict) else "", resp.text, f"HTTP {resp.status_code}")
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
        auth_values, token = await _v2raya_login(client, panel_url, settings.get("username", ""), settings.get("password", ""))
        touch_resp, touch_payload, _ = await _v2raya_request(client, panel_url, "GET", "touch", auth_values=auth_values)
        outbounds_resp, outbounds_payload, _ = await _v2raya_request(client, panel_url, "GET", "outbounds", auth_values=auth_values)
        outbound_resp, outbound_payload, _ = await _v2raya_request(client, panel_url, "GET", "outbound", auth_values=auth_values, params={"outbound": "proxy"})

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

        return {
            "nodes": _sort_v2raya_nodes(nodes),
            "runtime": runtime,
            "auth_configured": bool(settings.get("username") and settings.get("password")),
            "auth_token_present": bool(token),
            "message": "v2rayA 节点列表已刷新。",
        }


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
        cleaned = {k: v for k, v in item.items() if v not in {None, ""}}
        signature = json.dumps(cleaned, sort_keys=True, ensure_ascii=False)
        if signature not in seen:
            seen.add(signature)
            deduped.append(cleaned)
    return deduped


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


@router.get("/api/proxy/v2raya/nodes")
async def api_v2raya_nodes(with_latency: bool = Query(False), token: str = Depends(verify_token)):
    try:
        data = await _load_v2raya_nodes_snapshot(with_latency=with_latency)
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
        return {"status": "error", "message": f"读取 v2rayA 节点列表失败: {e}", "data": {"nodes": [], "runtime": _build_v2raya_runtime_snapshot()}}


@router.post("/api/proxy/v2raya/switch")
async def api_v2raya_switch(req: V2rayASwitchReq, token: str = Depends(verify_token)):
    try:
        settings = _build_v2raya_api_settings()
        panel_url = settings.get("panel_url", "")
        if not panel_url:
            return {"status": "error", "message": "请先填写 v2rayA 面板地址。"}
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            auth_values, _ = await _v2raya_login(client, panel_url, settings.get("username", ""), settings.get("password", ""))
            switch_ok = False
            last_message = ""
            for endpoint in ["connection", "outbound"]:
                for payload in _build_v2raya_switch_payloads(req):
                    resp, body, _ = await _v2raya_request(
                        client,
                        panel_url,
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
        data = await _load_v2raya_nodes_snapshot(with_latency=False)
        target_name = str(req.node_name or req.node_id or "").strip()
        return {
            "status": "success",
            "message": f"已请求切换到节点：{target_name}",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"切换 v2rayA 节点失败: {e}"}


@router.get("/api/ext/generate_task")
def ext_generate_task(token: str = Depends(verify_token)):
    from utils.email_providers.mail_service import mask_email, get_email_and_token, clear_sticky_domain
    from utils.register import _generate_password, generate_random_user_info, generate_oauth_url
    import utils.config as cfg_local

    print(f"[{cfg_local.ts()}] [INFO] 正在进行插件古法注册模式，请稍后...")
    try:
        cfg_local.GLOBAL_STOP = False
        clear_sticky_domain()

        email = None
        email_jwt = None
        for _ in range(3):
            print(f"[{cfg_local.ts()}] [INFO] 正在进行邮箱创建...")
            email, email_jwt = get_email_and_token(proxies=None)
            if email:
                break
            time.sleep(1.5)

        if not email:
            return {"status": "error", "message": "邮箱获取超时或暂无库存，请稍候"}

        user_info = generate_random_user_info()
        password = _generate_password()
        oauth_reg = generate_oauth_url()
        print(f"[{cfg_local.ts()}] [INFO] （{mask_email(email)}）下发古法任务数据 (昵称: {user_info['name']})...")

        name_parts = user_info['name'].split(' ')
        return {
            "status": "success",
            "task_data": {
                "email": email,
                "email_jwt": email_jwt,
                "password": password,
                "firstName": name_parts[0] if len(name_parts) > 0 else "John",
                "lastName": name_parts[1] if len(name_parts) > 1 else "Doe",
                "birthday": user_info['birthdate'],
                "registerUrl": oauth_reg.auth_url,
                "code_verifier": oauth_reg.code_verifier,
                "expected_state": oauth_reg.state
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"任务生成失败: {str(e)}"}


@router.get("/api/ext/get_mail_code")
def ext_get_mail_code(email: str, email_jwt: str = "", type: str = "signup", max_attempts: int = 20, token: str = Depends(verify_token)):
    from utils.email_providers.mail_service import get_oai_code
    try:
        code = get_oai_code(email, jwt=email_jwt, proxies=None, max_attempts=max_attempts)
        if code:
            return {"status": "success", "code": code}
        return {"status": "pending"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post("/api/ext/submit_result")
def ext_submit_result(req: ExtResultReq, token: str = Depends(verify_token)):
    from utils.register import submit_callback_url

    if req.status == "success":
        token_json = req.token_data
        if not token_json and req.callback_url:
            try:
                token_json = submit_callback_url(
                    callback_url=req.callback_url,
                    expected_state=req.expected_state or "",
                    code_verifier=req.code_verifier or ""
                )
            except Exception as e:
                print(f"[{core_engine.ts()}] [ERROR] 古法模式换取 Token 失败: {e}")
                return {"status": "error", "message": "Token 换取失败"}

        if not token_json:
            return {"status": "error", "message": "插件未返回有效 Token 数据"}

        db_manager.save_account_to_db(req.email, req.password, token_json)
        core_engine.run_stats['success'] = core_engine.run_stats.get('success', 0) + 1
        return {"status": "success", "message": "战利品已入库"}

    core_engine.run_stats['failed'] = core_engine.run_stats.get('failed', 0) + 1
    if req.error_type == 'phone_verify':
        core_engine.run_stats['phone_verify'] = core_engine.run_stats.get('phone_verify', 0) + 1
    elif req.error_type == 'pwd_blocked':
        core_engine.run_stats['pwd_blocked'] = core_engine.run_stats.get('pwd_blocked', 0) + 1
    return {"status": "success", "message": "异常统计已录入看板"}


@router.post("/api/ext/heartbeat")
def ext_heartbeat(worker_id: str, token: str = Depends(verify_token)):
    worker_status[worker_id] = time.time()
    return {"status": "success", "message": "ok"}


@router.get("/api/ext/check_node")
def check_node_status(worker_id: str, token: str = Depends(verify_token)):
    last_seen = worker_status.get(worker_id)
    if not last_seen:
        return {"status": "success", "online": False, "reason": "never_connected"}
    is_online = (time.time() - last_seen) < 15
    return {"status": "success", "online": is_online, "last_seen": last_seen}


@router.post("/api/ext/reset_stats")
def ext_reset_stats(token: str = Depends(verify_token)):
    core_engine.run_stats.update({
        "success": 0,
        "failed": 0,
        "retries": 0,
        "pwd_blocked": 0,
        "phone_verify": 0,
        "start_time": time.time(),
        "target": getattr(core_engine.cfg, 'NORMAL_TARGET_COUNT', 0),
        "ext_is_running": True
    })
    return {"status": "success"}


@router.post("/api/ext/stop")
def ext_stop(token: str = Depends(verify_token)):
    core_engine.run_stats["ext_is_running"] = False
    return {"status": "success"}


@router.post("/api/system/restart")
async def restart_system(token: str = Depends(verify_token)):
    try:
        if engine.is_running(): engine.stop()

        def _do_restart():
            time.sleep(1.5)
            print(f"[{core_engine.ts()}] [系统] 🔄 正在执行重启命令...")
            try:
                sys.stdout.flush()
                sys.stderr.flush()
                subprocess.Popen([sys.executable] + sys.argv)
                os._exit(0)
            except Exception as e:
                print(f"[{core_engine.ts()}] [系统] ❌ 重启失败: {e}")
                os._exit(1)

        threading.Thread(target=_do_restart, daemon=True).start()
        return {"status": "success", "message": "指令已下发，系统即将重启..."}
    except Exception as e:
        return {"status": "error", "message": f"重启异常: {str(e)}"}


@router.get("/api/system/project_update_status")
async def project_update_status(token: str = Depends(verify_token)):
    try:
        data = _build_project_update_status(fetch_remote=True)
        level = "success" if data.get("can_update") else ("warning" if data.get("is_git_repo") else "error")
        return {
            "status": level,
            "message": data.get("message") or "项目更新状态已读取。",
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": f"读取项目更新状态失败: {e}"}


@router.post("/api/system/update_project")
async def update_project(req: ProjectUpdateReq, token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "当前有任务正在运行，请先停止任务后再更新当前项目。"}
    try:
        status = _build_project_update_status(fetch_remote=True)
        if not status.get("can_update"):
            return {
                "status": "warning",
                "message": status.get("message") or "当前不满足自动更新条件。",
                "data": status,
            }

        code, output = _run_git_command(["pull", "--ff-only", "origin", "main"], timeout=180)
        if code != 0:
            return {
                "status": "error",
                "message": f"项目更新失败：{output or 'git pull --ff-only origin main 执行失败'}",
                "data": status,
            }

        refreshed = _build_project_update_status(fetch_remote=False)
        message = "当前项目代码已更新到最新 main。"
        if req.restart_after_update:
            def _do_restart_after_update():
                time.sleep(1.2)
                print(f"[{core_engine.ts()}] [系统] 🔄 项目更新完成，准备自动重启...")
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                    subprocess.Popen([sys.executable] + sys.argv)
                    os._exit(0)
                except Exception as restart_error:
                    print(f"[{core_engine.ts()}] [系统] ❌ 更新后重启失败: {restart_error}")
                    os._exit(1)

            threading.Thread(target=_do_restart_after_update, daemon=True).start()
            message = "当前项目代码已更新，系统即将自动重启。"
        return {
            "status": "success",
            "message": message,
            "output": output,
            "data": refreshed,
        }
    except Exception as e:
        return {"status": "error", "message": f"更新当前项目失败: {e}"}


@router.post("/api/system/download_update_package")
async def download_update_package(req: DownloadUpdatePackageReq, token: str = Depends(verify_token)):
    try:
        version = str(req.version or "").strip()
        download_url = str(req.download_url or "").strip()
        if not version or not download_url:
            return {"status": "error", "message": "缺少版本号或下载地址，无法下载更新包。"}

        paths = _get_update_paths(version)
        safe_version = paths["safe_version"]
        version_root = paths["version_root"]
        package_dir = paths["package_dir"]
        extract_dir = paths["extract_dir"]
        zip_path = paths["zip_path"]
        marker_path = paths["marker_path"]

        if os.path.exists(marker_path) and os.path.isdir(extract_dir):
            return {
                "status": "success",
                "message": f"更新包已存在：{extract_dir}",
                "data": {
                    "version": version,
                    "version_root": version_root,
                    "package_dir": package_dir,
                    "extract_dir": extract_dir,
                    "zip_path": zip_path,
                    "download_url": download_url,
                    "already_exists": True,
                },
            }

        os.makedirs(package_dir, exist_ok=True)
        os.makedirs(extract_dir, exist_ok=True)

        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            async with client.stream("GET", download_url, headers={"User-Agent": f"opaiRe/{version}"}) as resp:
                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "message": f"下载更新包失败 (HTTP {resp.status_code})",
                        "data": {"download_url": download_url, "version": version},
                    }
                with open(zip_path, "wb") as f:
                    async for chunk in resp.aiter_bytes():
                        if chunk:
                            f.write(chunk)

        _safe_extract_zip(zip_path, extract_dir)
        with open(marker_path, "w", encoding="utf-8") as f:
            f.write(version + "\n")

        return {
            "status": "success",
            "message": f"更新包已下载并解压到：{extract_dir}",
            "data": {
                "version": version,
                "version_root": version_root,
                "package_dir": package_dir,
                "extract_dir": extract_dir,
                "zip_path": zip_path,
                "download_url": download_url,
                "already_exists": False,
            },
        }
    except Exception as e:
        return {"status": "error", "message": f"下载更新包失败: {e}"}


@router.get("/api/system/update_packages")
async def update_packages(token: str = Depends(verify_token)):
    try:
        return {
            "status": "success",
            "message": "本地更新包列表已读取。",
            "data": {
                "packages": _list_downloaded_updates(),
                "updates_root": _get_updates_root(),
            },
        }
    except Exception as e:
        return {"status": "error", "message": f"读取本地更新包列表失败: {e}"}


@router.post("/api/system/migrate_update_package")
async def migrate_update_package(req: MigrateUpdatePackageReq, token: str = Depends(verify_token)):
    if engine.is_running():
        return {"status": "warning", "message": "当前有任务正在运行，请先停止任务后再迁移配置。"}
    try:
        paths = _get_update_paths(req.version)
        extract_dir = paths["extract_dir"]
        if not os.path.isdir(extract_dir):
            return {"status": "error", "message": "目标更新目录不存在，请先下载并解压该版本。"}

        src_data_dir = os.path.join(BASE_DIR, "data")
        if not os.path.isdir(src_data_dir):
            return {"status": "error", "message": "当前项目没有 data 目录，无法迁移配置。"}

        dest_data_dir = os.path.join(extract_dir, "data")
        os.makedirs(dest_data_dir, exist_ok=True)
        copied_files, copied_dirs = _copy_directory_contents(src_data_dir, dest_data_dir, exclude_names={"web_console.pid"})

        removed_paths = []
        if req.cleanup_zip and os.path.isfile(paths["zip_path"]):
            os.remove(paths["zip_path"])
            removed_paths.append(paths["zip_path"])
            if os.path.isdir(paths["package_dir"]) and not os.listdir(paths["package_dir"]):
                os.rmdir(paths["package_dir"])
                removed_paths.append(paths["package_dir"])

        if req.cleanup_other_versions:
            current_root = os.path.realpath(paths["version_root"])
            updates_root = os.path.realpath(paths["updates_root"])
            for item in _list_downloaded_updates():
                other_root = os.path.realpath(str(item.get("version_root") or ""))
                if not other_root or other_root == current_root:
                    continue
                if not other_root.startswith(updates_root + os.sep):
                    continue
                shutil.rmtree(other_root, ignore_errors=False)
                removed_paths.append(other_root)

        return {
            "status": "success",
            "message": f"已把当前 data 目录迁移到：{dest_data_dir}",
            "data": {
                "version": req.version,
                "extract_dir": extract_dir,
                "dest_data_dir": dest_data_dir,
                "copied_files": copied_files,
                "copied_dirs": copied_dirs,
                "removed_paths": removed_paths,
            },
        }
    except Exception as e:
        return {"status": "error", "message": f"迁移更新包配置失败: {e}"}

@router.get("/api/config")
async def get_config(token: str = Depends(verify_token)):
    config_data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    if isinstance(config_data.get("sub2api_mode"), dict):
        config_data["sub2api_mode"].pop("min_remaining_weekly_percent", None)
    config_data["web_password"] = config_data.get("web_password", "admin")
    if "local_microsoft" not in config_data:
        config_data["local_microsoft"] = {
            "enable_fission": False,
            "master_email": "",
            "client_id": "",
            "refresh_token": "",
            "pool_fission": False
        }
    config_data["http_dynamic_proxy_runtime"] = _build_http_dynamic_proxy_runtime()
    return config_data


@router.post("/api/config")
async def save_config(new_config: dict, token: str = Depends(verify_token)):
    try:
        new_config.pop("http_dynamic_proxy_runtime", None)
        current_config = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    current_config = yaml.safe_load(f) or {}
            except Exception:
                current_config = {}
        if isinstance(new_config.get("sub2api_mode"), dict):
            new_config["sub2api_mode"].pop("min_remaining_weekly_percent", None)
        if "default_proxy" in new_config:
            new_config["default_proxy"] = _normalize_proxy_input_for_save(new_config.get("default_proxy", ""))
        clash_proxy_pool = new_config.get("clash_proxy_pool")
        if isinstance(clash_proxy_pool, dict):
            clash_proxy_pool["client_type"] = str(clash_proxy_pool.get("client_type", "clash") or "clash").strip().lower()
            if clash_proxy_pool["client_type"] not in {"clash", "v2rayn", "v2raya"}:
                clash_proxy_pool["client_type"] = "clash"
            for field in [
                "v2raya_url",
                "v2raya_username",
                "v2raya_password",
                "v2raya_xray_bin",
                "v2raya_assets_dir",
                "v2raya_env_file",
                "v2rayn_base_dir",
            ]:
                if field in clash_proxy_pool:
                    clash_proxy_pool[field] = str(clash_proxy_pool.get(field, "") or "").strip()
        http_dynamic_proxy = new_config.get("http_dynamic_proxy")
        if isinstance(http_dynamic_proxy, dict):
            try:
                http_dynamic_proxy["pool_size"] = max(1, int(http_dynamic_proxy.get("pool_size", 1) or 1))
            except Exception:
                http_dynamic_proxy["pool_size"] = 1
            normalized_dynamic_list = _normalize_proxy_input_list_for_save(http_dynamic_proxy.get("proxy_list", []))
            http_dynamic_proxy["proxy_list"] = normalized_dynamic_list
            if bool(http_dynamic_proxy.get("enable", False)) and not normalized_dynamic_list and not str(new_config.get("default_proxy", "") or "").strip():
                return {"status": "error", "message": "HTTP 动态代理池已开启，但动态代理列表为空且全局默认代理也为空，请至少填写一项。"}
        http_dynamic_proxy = new_config.get("http_dynamic_proxy")
        auto_notes = []
        if isinstance(clash_proxy_pool, dict) and isinstance(http_dynamic_proxy, dict):
            old_clash = current_config.get("clash_proxy_pool", {}) if isinstance(current_config.get("clash_proxy_pool", {}), dict) else {}
            old_http = current_config.get("http_dynamic_proxy", {}) if isinstance(current_config.get("http_dynamic_proxy", {}), dict) else {}

            old_clash_active = bool(old_clash.get("enable", False))
            new_clash_active = bool(clash_proxy_pool.get("enable", False))
            old_http_active = bool(old_http.get("enable", False))
            new_http_active = bool(http_dynamic_proxy.get("enable", False))

            clash_just_enabled = new_clash_active and not old_clash_active
            http_just_enabled = new_http_active and not old_http_active

            if clash_just_enabled and new_http_active:
                http_dynamic_proxy["enable"] = False
                auto_notes.append("已自动关闭 HTTP 动态代理池")
            elif http_just_enabled and new_clash_active:
                clash_proxy_pool["enable"] = False
                auto_notes.append("已自动关闭 Clash 智能切点")

        with core_engine.cfg.CONFIG_FILE_LOCK:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.dump(new_config, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        try:
            reload_all_configs()
        except Exception:
            pass
        final_message = "✅ 配置已成功保存！"
        if auto_notes:
            final_message += "（" + "；".join(auto_notes) + "）"
        return {"status": "success", "message": final_message}
    except Exception as e:
        return {"status": "error", "message": f"❌ 保存失败: {str(e)}"}


@router.get("/api/clash_pool/info")
def get_clash_pool_info(token: str = Depends(verify_token)):
    """返回当前 Clash 订阅、自助更新状态和实际探测到的策略组。"""
    try:
        env_map = _read_clash_pool_env()
        group_candidates, group_error = _get_clash_pool_group_candidates(env_map)
        runtime_status, runtime_error = _inspect_clash_pool_runtime(env_map)
        return {
            "status": "success",
            "data": {
                "sub_url": env_map.get("SUB_URL", ""),
                "effective_sub_url": env_map.get("SUB_URL", ""),
                "count": env_map.get("COUNT", ""),
                "image": env_map.get("IMAGE", ""),
                "status_output": _get_clash_pool_status_output(),
                "group_candidates": group_candidates,
                "group_error": group_error,
                "runtime_status": runtime_status,
                "runtime_error": runtime_error,
            }
        }
    except Exception as e:
        return {"status": "error", "message": f"读取 Clash 订阅信息失败: {e}"}


@router.post("/api/clash_pool/update_subscription")
def update_clash_pool_subscription(req: ClashPoolUpdateReq, token: str = Depends(verify_token)):
    """更新订阅链接并执行代理池刷新脚本。"""
    try:
        sub_url = _sanitize_clash_sub_url(req.sub_url)
        if not sub_url:
            return {"status": "error", "message": "订阅链接不能为空"}
        if not os.path.exists(CLASH_POOL_UPDATE_SCRIPT):
            return {"status": "error", "message": f"未找到更新脚本: {CLASH_POOL_UPDATE_SCRIPT}"}

        resolved_probe, probe_history = _resolve_clash_sub_url(sub_url)
        if not resolved_probe:
            reason = "；".join(
                f"{item.get('url')} -> {item.get('reason') or '失败'}"
                for item in probe_history
            ) or "未找到可用的 Mihomo/Clash 订阅入口"
            return {
                "status": "error",
                "message": f"订阅探测失败：{reason}",
                "probe_history": probe_history,
            }

        effective_sub_url = str(resolved_probe.get("url") or sub_url).strip()
        env_map = _read_clash_pool_env()
        previous_env = dict(env_map)
        env_map["SUB_URL"] = effective_sub_url
        _write_clash_pool_env(env_map)

        code, output = _run_clash_pool_script(CLASH_POOL_UPDATE_SCRIPT, timeout=420)
        tail_lines = "\n".join((output or "").strip().splitlines()[-80:])
        status_output = _get_clash_pool_status_output()
        group_candidates, group_error = _get_clash_pool_group_candidates(env_map)
        assigned_nodes, assign_error = _spread_clash_pool_nodes(env_map)

        should_rollback = bool(code != 0 or (not assigned_nodes and assign_error))
        actual_group_name = next((str(item.get("group") or "").strip() for item in assigned_nodes if str(item.get("group") or "").strip()), "")
        group_sync = {"updated": False, "before": "", "after": ""}

        rollback_output = ""
        rollback_code = None
        if should_rollback:
            try:
                rollback_code, rollback_output = _rollback_clash_pool_update(previous_env)
            except Exception as rollback_error:
                rollback_output = f"自动回滚失败: {rollback_error}"
        elif actual_group_name:
            group_sync = _sync_clash_group_name(actual_group_name)

        if code != 0:
            current_env = _read_clash_pool_env()
            runtime_status, runtime_error = _inspect_clash_pool_runtime(current_env)
            message = f"订阅已写入，但更新脚本执行失败 (exit={code})"
            if rollback_code is not None:
                if rollback_code == 0:
                    message += "；已自动回滚到上一条可用订阅"
                else:
                    message += f"；自动回滚失败 (exit={rollback_code})"
            return {
                "status": "error",
                "message": message,
                "output": tail_lines,
                "status_output": status_output,
                "group_candidates": group_candidates,
                "group_error": group_error,
                "assigned_nodes": assigned_nodes,
                "assign_error": assign_error,
                "probe_history": probe_history,
                "rollback_output": rollback_output[-4000:] if rollback_output else "",
                "runtime_status": runtime_status,
                "runtime_error": runtime_error,
                "data": {
                    "sub_url": current_env.get("SUB_URL", ""),
                    "effective_sub_url": effective_sub_url,
                    "auto_fixed": effective_sub_url != sub_url,
                }
            }

        if not assigned_nodes and assign_error:
            current_env = _read_clash_pool_env()
            runtime_status, runtime_error = _inspect_clash_pool_runtime(current_env)
            message = f"订阅更新后未能完成策略组校验：{assign_error}"
            if rollback_code is not None:
                if rollback_code == 0:
                    message += "；已自动回滚到上一条可用订阅"
                else:
                    message += f"；自动回滚失败 (exit={rollback_code})"
            return {
                "status": "error",
                "message": message,
                "output": tail_lines,
                "status_output": status_output,
                "group_candidates": group_candidates,
                "group_error": group_error,
                "assigned_nodes": assigned_nodes,
                "assign_error": assign_error,
                "probe_history": probe_history,
                "rollback_output": rollback_output[-4000:] if rollback_output else "",
                "runtime_status": runtime_status,
                "runtime_error": runtime_error,
                "data": {
                    "sub_url": current_env.get("SUB_URL", ""),
                    "effective_sub_url": effective_sub_url,
                    "auto_fixed": effective_sub_url != sub_url,
                }
            }

        runtime_status, runtime_error = _inspect_clash_pool_runtime(env_map)
        final_message = "✅ Clash 订阅已更新并重载代理池！"
        if effective_sub_url != sub_url:
            final_message += "（已自动修正为可用的 Mihomo 订阅入口）"
        if group_sync.get("updated"):
            final_message += f"（策略组已自动同步为 {group_sync.get('after')}）"
        if assign_error:
            final_message += f"（节点分流未完全成功：{assign_error}）"
        elif assigned_nodes:
            final_message += "（已自动为各实例分配不同节点）"
        return {
            "status": "success",
            "message": final_message,
            "output": tail_lines,
            "status_output": status_output,
            "group_candidates": group_candidates,
            "group_error": group_error,
            "assigned_nodes": assigned_nodes,
            "assign_error": assign_error,
            "probe_history": probe_history,
            "group_sync": group_sync,
            "runtime_status": runtime_status,
            "runtime_error": runtime_error,
            "data": {
                "sub_url": effective_sub_url,
                "effective_sub_url": effective_sub_url,
                "auto_fixed": effective_sub_url != sub_url,
                "count": env_map.get("COUNT", ""),
                "image": env_map.get("IMAGE", ""),
            }
        }
    except subprocess.TimeoutExpired as e:
        partial = ((e.stdout or "") + "\n" + (e.stderr or "")).strip()
        return {"status": "error", "message": "更新脚本执行超时", "output": partial[-4000:]}
    except Exception as e:
        return {"status": "error", "message": f"Clash 订阅更新失败: {e}"}


@router.post("/api/config/add_wildcard_dns")
async def add_wildcard_dns(req: CFSyncExistingReq, token: str = Depends(verify_token)):
    try:
        main_list = [d.strip() for d in req.sub_domains.split(",") if d.strip()]
        if not main_list: return {"status": "error", "message": "❌ 没有找到有效的主域名"}

        proxy_url = getattr(core_engine.cfg, 'DEFAULT_PROXY', None)
        headers = {"X-Auth-Email": req.api_email, "X-Auth-Key": req.api_key, "Content-Type": "application/json"}
        client_kwargs = {"timeout": 30.0}
        if proxy_url: client_kwargs["proxy"] = proxy_url

        semaphore = asyncio.Semaphore(2)

        async def process_single_domain(client, domain):
            async with semaphore:
                try:
                    zone_resp = await client.get(f"https://api.cloudflare.com/client/v4/zones?name={domain}",
                                                 headers=headers)
                    zone_data = zone_resp.json()
                    if not zone_data.get("success") or not zone_data.get("result"): return False
                    zone_id = zone_data["result"][0]["id"]

                    records = [
                        {"type": "MX", "name": "*", "content": "route3.mx.cloudflare.net", "priority": 36, "ttl": 300},
                        {"type": "MX", "name": "*", "content": "route2.mx.cloudflare.net", "priority": 25, "ttl": 300},
                        {"type": "MX", "name": "*", "content": "route1.mx.cloudflare.net", "priority": 51, "ttl": 300},
                        {"type": "TXT", "name": "*", "content": '"v=spf1 include:_spf.mx.cloudflare.net ~all"',
                         "ttl": 300}
                    ]
                    for rec in records:
                        rec_resp = await client.post(
                            f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records", headers=headers,
                            json=rec)
                    return True
                except:
                    return False
                finally:
                    await asyncio.sleep(0.5)

        async with httpx.AsyncClient(**client_kwargs) as client:
            tasks = [process_single_domain(client, dom) for dom in main_list]
            results = await asyncio.gather(*tasks)

        success_count = sum(1 for r in results if r)
        return {"status": "success", "message": f"成功处理 {success_count}/{len(main_list)} 个域名。"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/config/cf_global_status")
def get_cf_global_status(main_domain: str, token: str = Depends(verify_token)):
    try:
        cf_cfg = getattr(core_engine.cfg, '_c', {})
        api_email, api_key = cf_cfg.get("cf_api_email"), cf_cfg.get("cf_api_key")
        if not api_email or not api_key: return {"status": "error", "message": "未配置 CF 账号信息"}

        cf = Cloudflare(api_email=api_email, api_key=api_key)
        domains = [d.strip() for d in main_domain.split(",") if d.strip()]
        results = []

        for dom in domains:
            zones = cf.zones.list(name=dom)
            if not zones.result:
                results.append({"domain": dom, "is_enabled": False, "dns_status": "not_found"})
                continue
            zone_id = zones.result[0].id
            routing_info = cf.email_routing.get(zone_id=zone_id)

            def safe_get(obj, attr, default=None):
                val = getattr(obj, attr, None)
                if val is None and hasattr(obj, 'result'): val = getattr(obj.result, attr, None)
                return val if val is not None else default

            raw_status, raw_synced = safe_get(routing_info, 'status', 'unknown'), safe_get(routing_info, 'synced',
                                                                                           False)
            results.append({"domain": dom, "is_enabled": (raw_status == 'ready' and raw_synced is True),
                            "dns_status": "active" if raw_synced else "pending"})

        return {"status": "success", "data": results}
    except Exception as e:
        return {"status": "error", "message": f"状态同步失败: {str(e)}"}

@router.get("/api/accounts")
async def get_accounts(page: int = Query(1), page_size: int = Query(50), token: str = Depends(verify_token)):
    result = db_manager.get_accounts_page(page, page_size)
    return {"status": "success", "data": result["data"], "total": result["total"], "page": page, "page_size": page_size}


@router.post("/api/accounts/export_selected")
async def export_selected_accounts(req: ExportReq, token: str = Depends(verify_token)):
    if not req.emails: return {"status": "error", "message": "未收到任何要导出的账号"}
    tokens = db_manager.get_tokens_by_emails(req.emails)
    return {"status": "success", "data": tokens} if tokens else {"status": "error", "message": "未能提取到选中账号的有效 Token"}


@router.post("/api/accounts/delete")
async def delete_selected_accounts(req: DeleteReq, token: str = Depends(verify_token)):
    if not req.emails: return {"status": "error", "message": "未收到任何要删除的账号"}
    return {"status": "success", "message": f"成功删除 {len(req.emails)} 个账号"} if db_manager.delete_accounts_by_emails(
        req.emails) else {"status": "error", "message": "删除操作失败"}


@router.post("/api/account/action")
def account_action(data: dict, token: str = Depends(verify_token)):
    try:
        email, action = data.get("email"), data.get("action")
        config = getattr(core_engine.cfg, '_c', {})
        token_data = db_manager.get_token_by_email(email)
        if not token_data: return {"status": "error", "message": f"未找到 {email} 的 Token。"}

        if action == "push":
            if not config.get("cpa_mode", {}).get("enable", False): return {"status": "error",
                                                                            "message": "🚫 推送失败：未开启 CPA 模式！"}
            success, msg = core_engine.upload_to_cpa_integrated(token_data,
                                                                config.get("cpa_mode", {}).get("api_url", ""),
                                                                config.get("cpa_mode", {}).get("api_token", ""))
            return {"status": "success", "message": f"账号 {email} 已成功推送到 CPA！"} if success else {"status": "error",
                                                                                                "message": f"CPA 推送失败: {msg}"}

        elif action == "push_sub2api":
            if not getattr(core_engine.cfg, 'ENABLE_SUB2API_MODE', False): return {"status": "error",
                                                                                   "message": "🚫 推送失败：未开启 Sub2API 模式！"}
            client = Sub2APIClient(api_url=getattr(core_engine.cfg, 'SUB2API_URL', ''),
                                   api_key=getattr(core_engine.cfg, 'SUB2API_KEY', ''))
            success, resp = client.add_account(token_data)
            return {"status": "success", "message": f"账号 {email} 已同步至 Sub2API！"} if success else {"status": "error",
                                                                                                  "message": f"Sub2API 推送失败: {resp}"}
    except Exception as e:
        return {"status": "error", "message": f"后端推送异常: {str(e)}"}


@router.post("/api/accounts/export_sub2api")
async def export_sub2api_accounts(req: ExportReq, token: str = Depends(verify_token)):
    from datetime import datetime, timezone
    try:
        tokens = db_manager.get_tokens_by_emails(req.emails)
        if not tokens: return {"status": "error", "message": "未提取到Token"}

        sub2api_settings = getattr(core_engine.cfg, '_c', {}).get("sub2api_mode", {})
        accounts_list = []
        for td in tokens:
            accounts_list.append({
                "name": str(td.get("email", "unknown"))[:64],
                "platform": "openai", "type": "oauth",
                "credentials": {"refresh_token": td.get("refresh_token", "")},
                "concurrency": int(sub2api_settings.get("account_concurrency", 10)),
                "priority": int(sub2api_settings.get("account_priority", 1)),
                "rate_multiplier": float(sub2api_settings.get("account_rate_multiplier", 1.0)),
                "extra": {"load_factor": int(sub2api_settings.get("account_load_factor", 10))}
            })
        return {"status": "success",
                "data": {"exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "proxies": [],
                         "accounts": accounts_list}}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/cloud/accounts")
def get_cloud_accounts(types: str = "sub2api,cpa", page: int = Query(1), page_size: int = Query(50),
                       token: str = Depends(verify_token)):
    type_list = types.split(",")
    combined_data = []
    try:
        if "sub2api" in type_list and getattr(cfg, 'SUB2API_URL', None) and getattr(cfg, 'SUB2API_KEY', None):
            client = Sub2APIClient(api_url=cfg.SUB2API_URL, api_key=cfg.SUB2API_KEY)
            success, raw_sub2_data = client.get_all_accounts()
            if success:
                for item in raw_sub2_data:
                    raw_time = item.get("updated_at", "-")
                    if raw_time != "-":
                        try:
                            raw_time = raw_time.split(".")[0].replace("T", " ")
                        except:
                            pass
                    extra = item.get("extra", {})
                    combined_data.append({
                        "id": str(item.get("id", "")), "account_type": "sub2api",
                        "credential": item.get("name", "未知账号"),
                        "status": "disabled" if item.get("status") == "inactive" else (
                            "active" if item.get("status") == "active" else "dead"),
                        "last_check": raw_time,
                        "details": {"plan_type": item.get("credentials", {}).get("plan_type", "未知"),
                                    "codex_5h_used_percent": extra.get("codex_5h_used_percent", 0),
                                    "codex_7d_used_percent": extra.get("codex_7d_used_percent", 0)}
                    })

        if "cpa" in type_list and getattr(cfg, 'CPA_API_URL', None) and getattr(cfg, 'CPA_API_TOKEN', None):
            from curl_cffi import requests
            res = requests.get(core_engine._normalize_cpa_auth_files_url(cfg.CPA_API_URL),
                               headers={"Authorization": f"Bearer {cfg.CPA_API_TOKEN}"}, timeout=20,
                               impersonate="chrome110")
            if res.status_code == 200:
                for item in [f for f in res.json().get("files", []) if
                             "codex" in str(f.get("type", "")).lower() or "codex" in str(
                                     f.get("provider", "")).lower()]:
                    combined_data.append({"id": item.get("name", ""), "account_type": "cpa",
                                          "credential": item.get("name", "").replace(".json", ""),
                                          "status": "disabled" if item.get("disabled", False) else "active",
                                          "details": {}, "last_check": "-"})

        return {"status": "success", "data": combined_data[(page - 1) * page_size: page * page_size],
                "total": len(combined_data)}
    except Exception as e:
        return {"status": "error", "message": f"拉取远端数据失败: {str(e)}"}


@router.post("/api/cloud/action")
def process_cloud_action(req: CloudActionReq, token: str = Depends(verify_token)):
    from curl_cffi import requests
    from concurrent.futures import ThreadPoolExecutor

    success_count, fail_count, updated_details_map = 0, 0, {}
    sub2api_client = Sub2APIClient(api_url=cfg.SUB2API_URL, api_key=cfg.SUB2API_KEY) if getattr(cfg, 'SUB2API_URL',
                                                                                                None) and getattr(cfg,
                                                                                                                  'SUB2API_KEY',
                                                                                                                  None) else None

    cpa_files_map = {}
    if any(a.type == "cpa" for a in req.accounts) and req.action == "check" and getattr(cfg, 'CPA_API_URL', None):
        try:
            res = requests.get(core_engine._normalize_cpa_auth_files_url(cfg.CPA_API_URL),
                               headers={"Authorization": f"Bearer {cfg.CPA_API_TOKEN}"}, timeout=15,
                               impersonate="chrome110")
            if res.status_code == 200: cpa_files_map = {f.get("name"): f for f in res.json().get("files", [])}
        except:
            pass

    def _worker(acc: CloudAccountItem):
        is_success, details = False, None
        try:
            if acc.type == "sub2api" and sub2api_client:
                if req.action == "check":
                    result, _ = sub2api_client.test_account(acc.id)
                    is_success = (result == "ok")
                    if not is_success: sub2api_client.set_account_status(acc.id, disabled=True)
                elif req.action in ["enable", "disable"]:
                    is_success = sub2api_client.set_account_status(acc.id, disabled=(req.action == "disable"))
                elif req.action == "delete":
                    is_success, _ = sub2api_client.delete_account(acc.id)

            elif acc.type == "cpa" and getattr(cfg, 'CPA_API_URL', None):
                if req.action == "check":
                    item = cpa_files_map.get(acc.id, {"name": acc.id, "disabled": False})
                    is_success, _ = core_engine.test_cliproxy_auth_file(item, cfg.CPA_API_URL, cfg.CPA_API_TOKEN)
                    if '_raw_usage' in item: details = parse_cpa_usage_to_details(item['_raw_usage'])
                    if not is_success: core_engine.set_cpa_auth_file_status(cfg.CPA_API_URL, cfg.CPA_API_TOKEN, acc.id,
                                                                            disabled=True)
                elif req.action in ["enable", "disable"]:
                    is_success = core_engine.set_cpa_auth_file_status(cfg.CPA_API_URL, cfg.CPA_API_TOKEN, acc.id,
                                                                      disabled=(req.action == "disable"))
                elif req.action == "delete":
                    is_success = requests.delete(core_engine._normalize_cpa_auth_files_url(cfg.CPA_API_URL),
                                                 headers={"Authorization": f"Bearer {cfg.CPA_API_TOKEN}"},
                                                 params={"name": acc.id}, impersonate="chrome110").status_code in (
                                 200, 204)
        except:
            pass
        return (is_success, acc.id, details)

    target_threads = 5
    if any(a.type == "cpa" for a in req.accounts): target_threads = max(target_threads, int(
        getattr(cfg, '_c', {}).get('cpa_mode', {}).get('threads', 10)))
    if any(a.type == "sub2api" for a in req.accounts): target_threads = max(target_threads, int(
        getattr(cfg, '_c', {}).get('sub2api_mode', {}).get('threads', 10)))

    with ThreadPoolExecutor(max_workers=max(1, min(target_threads, 50))) as executor:
        for is_success, acc_id, details in executor.map(_worker, req.accounts):
            if is_success:
                success_count += 1
            else:
                fail_count += 1
            if details: updated_details_map[acc_id] = details

    msg = f"测活完毕 | 存活: {success_count} 个 | 失效并已自动禁用: {fail_count} 个" if req.action == "check" else f"指令已下发 | 成功: {success_count} 个 | 失败: {fail_count} 个"
    return {"status": "success" if fail_count == 0 else "warning", "message": msg,
            "updated_details": updated_details_map}

@router.get('/api/sms/balance')
def api_get_sms_balance(token: str = Depends(verify_token)):
    from utils.integrations.hero_sms import hero_sms_get_balance
    proxy_url = core_engine.cfg.DEFAULT_PROXY
    balance, err = hero_sms_get_balance(proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None)
    return {"status": "success", "balance": f"{balance:.2f}"} if balance >= 0 else {"status": "error", "message": err}


@router.post('/api/sms/prices')
def api_get_sms_prices(req: SMSPriceReq, token: str = Depends(verify_token)):
    from utils.integrations.hero_sms import _hero_sms_prices_by_service
    proxy_url = core_engine.cfg.DEFAULT_PROXY
    rows = _hero_sms_prices_by_service(req.service,
                                       proxies={"http": proxy_url, "https": proxy_url} if proxy_url else None)
    return {"status": "success", "prices": rows} if rows else {"status": "error", "message": "无法获取价格或当前服务无库存"}


@router.post("/api/luckmail/bulk_buy")
def api_luckmail_bulk_buy(req: LuckMailBulkBuyReq, token: str = Depends(verify_token)):
    try:
        from utils.email_providers.luckmail_service import LuckMailService
        lm_service = LuckMailService(api_key=req.config.get("api_key"),
                                     preferred_domain=req.config.get("preferred_domain", ""),
                                     email_type=req.config.get("email_type", "ms_graph"),
                                     variant_mode=req.config.get("variant_mode", ""))
        tag_id = req.config.get("tag_id") or lm_service.get_or_create_tag_id("已使用")
        results = lm_service.bulk_purchase(quantity=req.quantity, auto_tag=req.auto_tag, tag_id=tag_id)
        return {"status": "success", "message": f"成功购买 {len(results)} 个邮箱！", "data": results}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/gmail/auth_url")
async def get_gmail_auth_url(token: str = Depends(verify_token)):
    if not os.path.exists(GMAIL_CLIENT_SECRETS): return {"status": "error",
                                                         "message": f"❌ 未找到凭证文件！请上传至: {GMAIL_CLIENT_SECRETS}"}
    try:
        url, verifier = GmailOAuthHandler.get_authorization_url(GMAIL_CLIENT_SECRETS)
        with open(GMAIL_VERIFIER_PATH, "w") as f:
            f.write(verifier)
        return {"status": "success", "url": url}
    except Exception as e:
        return {"status": "error", "message": f"生成链接失败: {str(e)}"}


@router.post("/api/gmail/exchange_code")
async def exchange_gmail_code(req: GmailExchangeReq, token: str = Depends(verify_token)):
    if not req.code: return {"status": "error", "message": "授权码不能为空"}
    try:
        if not os.path.exists(GMAIL_VERIFIER_PATH): return {"status": "error", "message": "会话已过期，请重新生成链接"}
        with open(GMAIL_VERIFIER_PATH, "r") as f:
            stored_verifier = f.read().strip()
        success, msg = GmailOAuthHandler.save_token_from_code(GMAIL_CLIENT_SECRETS, req.code, GMAIL_TOKEN_PATH,
                                                              code_verifier=stored_verifier,
                                                              proxy=getattr(core_engine.cfg, 'DEFAULT_PROXY', None))
        if success and os.path.exists(GMAIL_VERIFIER_PATH):
            os.remove(GMAIL_VERIFIER_PATH)
            return {"status": "success", "message": "✨ 授权成功！token.json 已保存在 data 目录。"}
        return {"status": "error", "message": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/sub2api/groups")
def get_sub2api_groups(token: str = Depends(verify_token)):
    from curl_cffi import requests as cffi_requests
    sub2api_url = getattr(core_engine.cfg, "SUB2API_URL", "").strip()
    sub2api_key = getattr(core_engine.cfg, "SUB2API_KEY", "").strip()
    proxy_url = getattr(core_engine.cfg, "DEFAULT_PROXY", "").strip()
    if not sub2api_url or not sub2api_key: return {"status": "error",
                                                   "message": "Please save the Sub2API URL and API key first."}
    try:
        request_kwargs = {
            "headers": {"x-api-key": sub2api_key, "Content-Type": "application/json"},
            "timeout": 10,
            "impersonate": "chrome110",
        }
        if proxy_url:
            request_kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
        response = cffi_requests.get(f"{sub2api_url.rstrip('/')}/api/v1/admin/groups/all", **request_kwargs)
        if response.status_code != 200: return {"status": "error",
                                                "message": f"HTTP {response.status_code}: {response.text[:200]}"}
        return {"status": "success", "data": response.json().get("data", [])}
    except Exception as exc:
        return {"status": "error", "message": f"Failed to fetch Sub2API groups: {exc}"}


@router.get("/api/system/check_update")
async def check_update(current_version: str, token: str = Depends(verify_token)):
    release_page_url = f"https://github.com/{GITHUB_UPDATE_REPO}/releases/latest"
    tags_page_url = f"https://github.com/{GITHUB_UPDATE_REPO}/tags"

    def _parse(v):
        return [int(x) for x in re.findall(r'\d+', str(v))]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            common_headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"opaiRe/{current_version or 'unknown'}"
            }

            release_resp = await client.get(
                f"https://api.github.com/repos/{GITHUB_UPDATE_REPO}/releases/latest",
                headers=common_headers,
            )
            if release_resp.status_code == 200:
                release_data = release_resp.json() or {}
                release_version = str(release_data.get("tag_name", "") or "").strip()
                if release_version:
                    has_update = _parse(release_version) > _parse(current_version) if release_version else False
                    assets = release_data.get("assets") or []
                    asset_url = ""
                    if assets and isinstance(assets, list):
                        asset_url = str((assets[0] or {}).get("browser_download_url", "") or "").strip()
                    download_url = asset_url or f"https://github.com/{GITHUB_UPDATE_REPO}/archive/refs/tags/{release_version}.zip"
                    return {
                        "status": "success",
                        "has_update": has_update,
                        "remote_version": release_version,
                        "changelog": str(release_data.get("body", "") or "当前使用 GitHub Release 检查更新。"),
                        "download_url": download_url,
                        "html_url": str(release_data.get("html_url", "") or release_page_url).strip(),
                        "version_page_url": str(release_data.get("html_url", "") or release_page_url).strip(),
                        "source": "release",
                    }

            resp = await client.get(
                f"https://api.github.com/repos/{GITHUB_UPDATE_REPO}/tags?per_page=100",
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"opaiRe/{current_version or 'unknown'}"
                }
            )
            if resp.status_code != 200:
                return {
                    "status": "error",
                    "message": f"无法获取版本数据 (Release HTTP {release_resp.status_code}，Tag HTTP {resp.status_code})",
                    "version_page_url": tags_page_url,
                }
        tags = resp.json() or []

        latest_tag = ""
        latest_item = None
        latest_parsed = []
        for item in tags:
            tag_name = str(item.get("name", "") or "").strip()
            parsed = _parse(tag_name)
            if not parsed:
                continue
            if not latest_parsed or parsed > latest_parsed:
                latest_parsed = parsed
                latest_tag = tag_name
                latest_item = item

        remote_version = latest_tag
        has_update = _parse(remote_version) > _parse(current_version) if remote_version else False
        if not remote_version:
            return {
                "status": "error",
                "message": "未读取到可用版本标签，请先在 GitHub 仓库创建规范的版本 tag。",
                "version_page_url": tags_page_url,
            }

        download_url = f"https://github.com/{GITHUB_UPDATE_REPO}/archive/refs/tags/{remote_version}.zip"
        html_url = f"https://github.com/{GITHUB_UPDATE_REPO}/tree/{remote_version}"
        commit_sha = str(((latest_item or {}).get("commit") or {}).get("sha") or "").strip()
        return {
            "status": "success",
            "has_update": has_update,
            "remote_version": remote_version,
            "changelog": f"当前使用 Git tag 回退检查更新。最新版本标签：{remote_version}{'，提交：' + commit_sha[:7] if commit_sha else ''}",
            "download_url": download_url,
            "html_url": html_url,
            "version_page_url": tags_page_url,
            "source": "tag",
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"检查更新发生未知异常: {str(e)}",
            "version_page_url": tags_page_url,
        }

@router.post("/api/logs/clear")
async def clear_backend_logs(token: str = Depends(verify_token)):
    log_history.clear()
    return {"status": "success"}


@router.get("/api/logs/stream")
async def stream_logs(request: Request, token: str = Query(None)):
    if token not in VALID_TOKENS: raise HTTPException(status_code=401, detail="Unauthorized")

    async def log_generator():
        current_snapshot = list(log_history)
        for old_msg in current_snapshot:
            yield f"data: {old_msg}\n\n"
        last_sent_msg = current_snapshot[-1] if current_snapshot else None
        idle_loops = 0

        try:
            while True:
                if await request.is_disconnected():
                    break
                snap = list(log_history)
                if snap and snap[-1] != last_sent_msg:
                    start_idx = 0
                    for i in range(len(snap) - 1, -1, -1):
                        if snap[i] == last_sent_msg:
                            start_idx = i + 1
                            break
                    for i in range(start_idx, len(snap)):
                        yield f"data: {snap[i]}\n\n"
                    last_sent_msg = snap[-1]
                    idle_loops = 0
                else:
                    idle_loops += 1
                    if idle_loops >= 50:
                        yield ": keepalive\n\n"
                        idle_loops = 0

                await asyncio.sleep(0.3)
        except Exception:
            pass

    return StreamingResponse(log_generator(), media_type="text/event-stream")

@router.post("/api/cluster/control")
async def cluster_control(req: ClusterControlReq, token: str = Depends(verify_token)):
    if req.action not in ["start", "stop", "restart", "export_accounts"]: return {"status": "error",
                                                                                  "message": "不支持的指令"}
    with cluster_lock: NODE_COMMANDS[req.node_name] = req.action
    return {"status": "success", "message": f"指令 [{req.action}] 已排队"}


@router.get("/api/cluster/view")
async def cluster_view(token: str = Depends(verify_token)):
    global CLUSTER_NODES
    now = time.time()
    with cluster_lock:
        CLUSTER_NODES = {k: v for k, v in CLUSTER_NODES.items() if now - v["last_seen"] < 20}
        return {"status": "success", "nodes": CLUSTER_NODES}


@router.post("/api/cluster/report")
async def cluster_report(req: ClusterReportReq):
    cf_dict = getattr(core_engine.cfg, '_c', {})
    if req.secret != str(cf_dict.get("cluster_secret", "change-me-cluster-secret")).strip(): return {"status": "error",
                                                                                      "message": "密钥错误"}

    target_cmd = NODE_COMMANDS.get(req.node_name, "none")
    node_is_running = req.stats.get("is_running", False)

    if target_cmd in ["restart", "export_accounts"]:
        NODE_COMMANDS[req.node_name] = "none"
    elif (target_cmd == "start" and node_is_running) or (target_cmd == "stop" and not node_is_running):
        NODE_COMMANDS[req.node_name] = "none"
        target_cmd = "none"

    with cluster_lock:
        CLUSTER_NODES[req.node_name] = {
            "stats": req.stats, "logs": req.logs, "last_seen": time.time(),
            "join_time": CLUSTER_NODES.get(req.node_name, {}).get("join_time", time.time())
        }
    return {"status": "success", "command": target_cmd}


@router.websocket("/api/cluster/report_ws")
async def ws_cluster_report(websocket: WebSocket, node_name: str, secret: str):
    await websocket.accept()
    if secret != str(getattr(core_engine.cfg, '_c', {}).get("cluster_secret", "change-me-cluster-secret")).strip():
        await websocket.close(code=1008, reason="Secret Mismatch")
        return
    try:
        while True:
            data = await websocket.receive_json()
            target_cmd = NODE_COMMANDS.get(node_name, "none")
            node_is_running = data.get("stats", {}).get("is_running", False)
            if target_cmd in ["restart", "export_accounts"]:
                NODE_COMMANDS[node_name] = "none"
            elif (target_cmd == "start" and node_is_running) or (target_cmd == "stop" and not node_is_running):
                NODE_COMMANDS[node_name] = "none"
                target_cmd = "none"
            with cluster_lock:
                CLUSTER_NODES[node_name] = {
                    "stats": data.get("stats", {}), "logs": data.get("logs", []), "last_seen": time.time(),
                    "join_time": CLUSTER_NODES.get(node_name, {}).get("join_time", time.time())
                }
            await websocket.send_json({"command": target_cmd})
    except Exception:
        pass


@router.websocket("/api/cluster/view_ws")
async def cluster_view_ws(websocket: WebSocket, token: str = Query(None)):
    if token not in VALID_TOKENS:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            global CLUSTER_NODES
            now = time.time()
            with cluster_lock:
                CLUSTER_NODES = {k: v for k, v in CLUSTER_NODES.items() if now - v["last_seen"] < 20}
                await websocket.send_json({"status": "success", "nodes": CLUSTER_NODES})
            await asyncio.sleep(0.5)
    except Exception:
        pass


@router.post("/api/cluster/upload_accounts")
def cluster_upload_accounts(req: ClusterUploadAccountsReq):
    if req.secret != str(getattr(core_engine.cfg, '_c', {}).get("cluster_secret", "change-me-cluster-secret")).strip(): return {
        "status": "error", "message": "密钥错误"}
    success_count = 0
    for acc in req.accounts:
        if acc.get("email") and acc.get("token_data"):
            if db_manager.save_account_to_db(acc.get("email"), acc.get("password"),
                                             acc.get("token_data")): success_count += 1

    msg = f"[{core_engine.ts()}] [系统] 📦 成功从子控 [{req.node_name}] 提取并完美入库 {success_count} 个账号！"
    print(msg)
    try:
        log_history.append(msg)
    except:
        pass
    return {"status": "success", "message": f"成功接收 {success_count} 个账号"}
