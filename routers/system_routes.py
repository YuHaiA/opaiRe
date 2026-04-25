import os
import time
import secrets
import re
import asyncio
import threading
import sys
import subprocess
import shutil
import zipfile
import httpx
from typing import Optional, Any
from fastapi import APIRouter, Depends, Query, Request, WebSocket, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
import yaml

from global_state import VALID_TOKENS, CLUSTER_NODES, NODE_COMMANDS, cluster_lock, log_history, engine, verify_token, worker_status, append_log
from utils import core_engine, db_manager
from utils.config import reload_all_configs
from utils.integrations.tg_notifier import send_tg_msg_async
import utils.config as cfg

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class DummyArgs:
    def __init__(self, proxy=None, once=False):
        self.proxy = proxy
        self.once = once

class LoginData(BaseModel): password: str
class ClusterUploadAccountsReq(BaseModel): node_name: str; secret: str; accounts: list
class ClusterReportReq(BaseModel): node_name: str; secret: str; stats: dict; logs: list
class ClusterControlReq(BaseModel): node_name: str; action: str
class ProjectUpdateReq(BaseModel): restart_after_update: bool = False
class DownloadUpdatePackageReq(BaseModel): version: str; download_url: str
class MigrateUpdatePackageReq(BaseModel): version: str; cleanup_zip: bool = True; cleanup_other_versions: bool = False

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


def _sanitize_local_microsoft_config(local_ms: Any) -> dict:
    data = dict(local_ms) if isinstance(local_ms, dict) else {}
    data.setdefault("enable_fission", False)
    data.setdefault("pool_fission", False)
    data.setdefault("master_email", "")
    data.setdefault("client_id", "")
    data.setdefault("refresh_token", "")

    mode = str(data.get("suffix_mode", "fixed") or "fixed").strip().lower()
    if mode not in {"fixed", "range", "mystic"}:
        mode = "fixed"

    try:
        min_len = int(data.get("suffix_len_min", 8) or 8)
    except Exception:
        min_len = 8
    try:
        max_len = int(data.get("suffix_len_max", min_len) or min_len)
    except Exception:
        max_len = min_len

    min_len = max(8, min(32, min_len))
    max_len = max(8, min(32, max_len))
    if max_len < min_len:
        max_len = min_len

    data["suffix_mode"] = mode
    data["suffix_len_min"] = min_len
    data["suffix_len_max"] = max_len
    return data


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

    code, _ = _run_git_command(["--version"])
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
    current_password = getattr(core_engine.cfg, "WEB_PASSWORD", "admin")
    if data.password == current_password:
        token = secrets.token_hex(16)
        VALID_TOKENS.add(token)
        return {"status": "success", "token": token}
    return {"status": "error", "message": "密码错误"}


@router.get("/api/status")
async def get_status(token: str = Depends(verify_token)):
    return {"is_running": engine.is_running()}

@router.post("/api/start")
async def start_task(token: str = Depends(verify_token)):
    if engine.is_running(): return {"status": "error", "message": "任务已经在运行中！"}
    try:
        reload_all_configs()
    except Exception as e:
        print(f"[{core_engine.ts()}] [警告] 启动重载提示: {e}")

    default_proxy = getattr(core_engine.cfg, 'DEFAULT_PROXY', None)
    args = DummyArgs(proxy=default_proxy if default_proxy else None)
    core_engine.run_stats.update({"success": 0, "failed": 0, "retries": 0, "pwd_blocked": 0, "phone_verify": 0, "start_time": time.time(),"target": 0})
    if getattr(core_engine.cfg, 'ENABLE_CPA_MODE', False):
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
                                  pwd_blocked=pwd_blocked,phone_verify=phone_blocked,avg_time=avg_time)
    except Exception:
        msg = f"⚠️ TG 模板渲染出错：未知的变量格式。\n请检查配置面板中的模板变量是否正确填写。"

    asyncio.create_task(send_tg_msg_async(msg))
    engine.stop()
    return {"status": "success", "message": "已发送停止指令，正在安全退出..."}


@router.get("/api/stats")
async def get_stats(token: str = Depends(verify_token)):
    stats = core_engine.run_stats
    is_running = engine.is_running()
    current_reg_mode = getattr(core_engine.cfg, 'REG_MODE', 'protocol')

    if current_reg_mode == 'extension':
        is_running = stats.get("ext_is_running", False)
    else:
        is_running = engine.is_running()

    if is_running or (current_reg_mode == 'extension' and stats["start_time"] > 0):
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
                print(f"[{core_engine.ts()}] [系统] 项目更新完成，准备自动重启...")
                try:
                    sys.stdout.flush()
                    sys.stderr.flush()
                    subprocess.Popen([sys.executable] + sys.argv)
                    os._exit(0)
                except Exception as restart_error:
                    print(f"[{core_engine.ts()}] [系统] 更新后重启失败: {restart_error}")
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
    config_data = getattr(core_engine.cfg, '_c', {}).copy()

    if isinstance(config_data.get("sub2api_mode"), dict):
        config_data["sub2api_mode"].pop("min_remaining_weekly_percent", None)
    config_data["web_password"] = getattr(core_engine.cfg, "WEB_PASSWORD", config_data.get("web_password", "admin"))
    config_data["local_microsoft"] = _sanitize_local_microsoft_config(config_data.get("local_microsoft"))
    return config_data


@router.post("/api/config")
async def save_config(new_config: dict, token: str = Depends(verify_token)):
    try:
        if isinstance(new_config.get("sub2api_mode"), dict):
            new_config["sub2api_mode"].pop("min_remaining_weekly_percent", None)
        new_config["local_microsoft"] = _sanitize_local_microsoft_config(new_config.get("local_microsoft"))
        reload_all_configs(new_config_dict=new_config)

        return {"status": "success", "message": "✅ 配置已成功保存并同步至云端！"}
    except Exception as e:
        return {"status": "error", "message": f"❌ 保存失败: {str(e)}"}


@router.get("/api/system/check_update")
async def check_update(current_version: str, token: str = Depends(verify_token)):
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get("https://api.github.com/repos/wenfxl/openai-cpa/releases/latest",
                                    headers={"Accept": "application/vnd.github.v3+json"})
            if resp.status_code != 200: return {"status": "error",
                                                "message": f"无法获取更新数据 (GitHub API 返回 HTTP {resp.status_code})"}
        data = resp.json()
        remote_version = data.get("tag_name", "")

        def _parse(v):
            return [int(x) for x in re.findall(r'\d+', str(v))]

        has_update = _parse(remote_version) > _parse(current_version) if remote_version else False
        assets = data.get("assets")
        download_url = assets[0].get("browser_download_url", "") if assets else data.get("zipball_url", "")
        return {"status": "success", "has_update": has_update, "remote_version": remote_version,
                "changelog": data.get("body", "无更新日志"), "download_url": download_url,
                "html_url": data.get("html_url", "")}
    except Exception as e:
        return {"status": "error", "message": f"检查更新发生未知异常: {str(e)}"}

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
    if req.secret != str(cf_dict.get("cluster_secret", "wenfxl666")).strip(): return {"status": "error",
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
    if secret != str(getattr(core_engine.cfg, '_c', {}).get("cluster_secret", "wenfxl666")).strip():
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
                nodes_snapshot = CLUSTER_NODES.copy()
            await websocket.send_json({"status": "success", "nodes": nodes_snapshot})

            await asyncio.sleep(0.5)
    except Exception:
        pass

@router.post("/api/cluster/upload_accounts")
def cluster_upload_accounts(req: ClusterUploadAccountsReq):
    if req.secret != str(getattr(core_engine.cfg, '_c', {}).get("cluster_secret", "wenfxl666")).strip(): return {
        "status": "error", "message": "密钥错误"}
    success_count = 0
    for acc in req.accounts:
        if acc.get("email") and acc.get("token_data"):
            if db_manager.save_account_to_db(acc.get("email"), acc.get("password"),
                                             acc.get("token_data")): success_count += 1

    msg = f"[{core_engine.ts()}] [系统] 📦 成功从子控 [{req.node_name}] 提取并完美入库 {success_count} 个账号！"
    print(msg)
    try:
        append_log(msg)
    except:
        pass
    return {"status": "success", "message": f"成功接收 {success_count} 个账号"}

#模式二注册
@router.get("/api/ext/generate_task")
def ext_generate_task(token: str = Depends(verify_token)):
    from utils.email_providers.mail_service import mask_email, get_email_and_token, clear_sticky_domain
    from utils.auth_pipeline.user_utils import generate_random_user_info, _generate_password
    from utils.auth_pipeline.oauth import generate_oauth_url

    import utils.config as cfg
    import time
    print(f"[{cfg.ts()}] [INFO] 正在进行插件古法注册模式，请稍后...")
    try:
        cfg.GLOBAL_STOP = False
        clear_sticky_domain()

        email = None
        email_jwt = None
        for attempt in range(3):
            print(f"[{cfg.ts()}] [INFO] 正在进行邮箱创建...")
            email, email_jwt = get_email_and_token(proxies=None)
            if email:
                break
            time.sleep(1.5)

        if not email:
            return {"status": "error", "message": "邮箱获取超时或暂无库存，请稍候"}

        user_info = generate_random_user_info()
        password = _generate_password()

        oauth_reg = generate_oauth_url()

        print(f"[{cfg.ts()}] [INFO] （{mask_email(email)}）下发任务数据 (昵称: {user_info['name']}) (密码: {password}) (生日: {user_info['birthdate']})...")

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
    from utils import core_engine
    from utils.auth_pipeline.register import submit_callback_url

    if req.status == "success":
        token_json = req.token_data
        if not token_json and req.callback_url:
            try:
                token_json = submit_callback_url(
                    callback_url=req.callback_url,
                    expected_state=req.expected_state,
                    code_verifier=req.code_verifier
                )
            except Exception as e:
                print(f"换取 Token 失败: {e}")
                return {"status": "error", "message": "Token 换取失败"}
        db_manager.save_account_to_db(req.email, req.password, token_json)
        core_engine.run_stats['success'] = core_engine.run_stats.get('success', 0) + 1

        return {"status": "success", "message": "战利品已入库"}
    else:
        core_engine.run_stats['failed'] = core_engine.run_stats.get('failed', 0) + 1
        is_dead_account = False
        if req.error_type == 'phone_verify':
            core_engine.run_stats['phone_verify'] = core_engine.run_stats.get('phone_verify', 0) + 1
            is_dead_account = True
        elif req.error_type == 'pwd_blocked':
            core_engine.run_stats['pwd_blocked'] = core_engine.run_stats.get('pwd_blocked', 0) + 1
        if is_dead_account and getattr(cfg, "EMAIL_API_MODE", "") == "local_microsoft" and req.email:
            db_manager.update_local_mailbox_status(req.email, 3)
            print(f"[{cfg.ts()}] [WARNING] 插件上报邮箱不可用，已将邮箱标记为死号: {req.email}")
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
    return {
        "status": "success",
        "online": is_online,
        "last_seen": last_seen
    }

@router.post("/api/ext/reset_stats")
def ext_reset_stats(token: str = Depends(verify_token)):
    from utils import core_engine
    import time
    core_engine.run_stats.update({
        "success": 0, "failed": 0, "retries": 0,
        "pwd_blocked": 0, "phone_verify": 0,
        "start_time": time.time(),
        "target": getattr(core_engine.cfg, 'NORMAL_TARGET_COUNT', 0),
        "ext_is_running": True
    })
    return {"status": "success"}

@router.post("/api/ext/stop")
def ext_stop(token: str = Depends(verify_token)):
    from utils import core_engine
    core_engine.run_stats["ext_is_running"] = False
    return {"status": "success"}
