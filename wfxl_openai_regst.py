import os
import sys
import json
import time
import asyncio
import threading
import atexit
import secrets
import hashlib
import re
import uvicorn
import warnings
import subprocess
import socket
import socks
from typing import Optional
warnings.filterwarnings("ignore", category=RuntimeWarning, module="trio")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from utils import core_engine, db_manager
from utils.config import reload_all_configs
from utils.log_stream_cache import RecentParsedLogCache
from utils.email_providers import mail_service
from utils.memory_predictor import build_memory_report

from global_state import engine, log_history, append_log
from routers import api_routes


def _get_env_int(name: str, default: int) -> int:
    raw_value = str(os.getenv(name, "")).strip()
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def _get_env_bool(name: str, default: bool = False) -> bool:
    raw_value = str(os.getenv(name, "")).strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


def _is_default_cluster_secret(secret: str) -> bool:
    return str(secret or "").strip() in {"", "wenfxl666"}


def _running_under_systemd() -> bool:
    return any(
        os.getenv(name)
        for name in ("INVOCATION_ID", "NOTIFY_SOCKET", "JOURNAL_STREAM", "SYSTEMD_EXEC_PID")
    )


def _calculate_file_sha256(file_path: str) -> str:
    digest = hashlib.sha256()
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if chunk:
                digest.update(chunk)
    return digest.hexdigest()


WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0").strip() or "0.0.0.0"
WEB_PORT = _get_env_int("WEB_PORT", _get_env_int("PORT", 8000))
WEB_PORT_SCAN_LIMIT = max(1, _get_env_int("WEB_PORT_SCAN_LIMIT", 20))
WEB_PORT_STRICT = _get_env_bool("WEB_PORT_STRICT", _running_under_systemd())
WEB_PORT_STRICT_WAIT_SEC = max(0, _get_env_int("WEB_PORT_STRICT_WAIT_SEC", 20))
PID_FILE = os.path.join("data", "web_console.pid")


def _write_pid_file() -> None:
    try:
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w", encoding="utf-8") as handle:
            handle.write(str(os.getpid()))
    except Exception:
        pass


def _remove_pid_file() -> None:
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
    except Exception:
        pass


def _get_listener_pid(host: str, port: int):
    if os.name == "nt":
        try:
            output = subprocess.check_output(
                ["netstat", "-ano", "-p", "tcp"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            target = f":{port}"
            for raw_line in output.splitlines():
                line = raw_line.strip()
                if "LISTENING" not in line or target not in line:
                    continue
                parts = line.split()
                if len(parts) >= 5 and parts[1].endswith(target):
                    try:
                        return int(parts[-1])
                    except ValueError:
                        return -1
        except Exception:
            return -1

    try:
        output = subprocess.check_output(
            ["ss", "-ltnp"],
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        target = f":{port}"
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if "LISTEN" not in line or target not in line:
                continue
            match = re.search(r"pid=(\d+)", line)
            if match:
                return int(match.group(1))
            return -1
    except Exception:
        pass

    tester = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tester.bind((host, port))
        return None
    except OSError:
        pass
    finally:
        try:
            tester.close()
        except Exception:
            pass

    return -1


def _conflict_hosts(host: str) -> list[str]:
    normalized = (host or "").strip() or "0.0.0.0"
    if normalized == "0.0.0.0":
        return ["0.0.0.0", "127.0.0.1"]
    return [normalized]


def _find_conflicting_listener_pid(host: str, port: int) -> Optional[int]:
    checked_pids = set()
    for current_host in _conflict_hosts(host):
        listener_pid = _get_listener_pid(current_host, port)
        if listener_pid is None or listener_pid in checked_pids:
            continue
        checked_pids.add(listener_pid)
        return listener_pid
    return None


def _get_process_command_line(pid_value: int) -> str:
    if pid_value <= 0:
        return ""
    if os.name != "nt":
        try:
            with open(f"/proc/{pid_value}/cmdline", "rb") as handle:
                raw_cmdline = handle.read().replace(b"\x00", b" ").strip()
            if raw_cmdline:
                return raw_cmdline.decode("utf-8", errors="ignore")
        except Exception:
            pass
        try:
            return subprocess.check_output(
                ["ps", "-p", str(pid_value), "-o", "args="],
                text=True,
                encoding="utf-8",
                errors="ignore",
            ).strip()
        except Exception:
            return ""
    try:
        return subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid_value}\").CommandLine",
            ],
            text=True,
            encoding="utf-8",
            errors="ignore",
        ).strip()
    except Exception:
        return ""


def _wait_for_port_release(host: str, port: int, timeout_sec: int) -> Optional[int]:
    if timeout_sec <= 0:
        return _find_conflicting_listener_pid(host, port)

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        listener_pid = _find_conflicting_listener_pid(host, port)
        if listener_pid is None:
            return None
        time.sleep(0.5)
    return _find_conflicting_listener_pid(host, port)


def _is_same_console_instance(cmdline: str) -> bool:
    if not cmdline or "wfxl_openai_regst.py" not in cmdline:
        return False
    normalized = cmdline.replace("\\", "/").lower()
    current_script = os.path.abspath(__file__).replace("\\", "/").lower()
    return current_script in normalized


def _ensure_web_port_available(host: str, port: int) -> bool:
    listener_pid = _get_listener_pid(host, port)
    if listener_pid is None:
        return True

    cmdline = _get_process_command_line(listener_pid)
    if _is_same_console_instance(cmdline):
        print(f"[{core_engine.ts()}] [系统] Web 控制台已经在运行中，无需重复启动。")
        print(f"[{core_engine.ts()}] [系统] 现有实例 PID: {listener_pid}")
        sys.__stdout__.write(f"[{core_engine.ts()}] [系统] 控制台地址：http://127.0.0.1:{port} \n")
        sys.__stdout__.flush()
        return False

    print(f"[{core_engine.ts()}] [ERROR] 端口 {port} 已被其他进程占用，无法启动控制台。")
    if listener_pid > 0:
        print(f"[{core_engine.ts()}] [ERROR] 占用 PID: {listener_pid}")
    if cmdline:
        print(f"[{core_engine.ts()}] [ERROR] 占用进程命令行: {cmdline}")
    return False


def _find_existing_console_port(host: str, start_port: int, max_ports: int = WEB_PORT_SCAN_LIMIT) -> Optional[int]:
    for current_port in range(start_port, start_port + max_ports):
        checked_pids = set()
        for current_host in _conflict_hosts(host):
            listener_pid = _get_listener_pid(current_host, current_port)
            if listener_pid is None or listener_pid <= 0 or listener_pid in checked_pids:
                continue
            checked_pids.add(listener_pid)
            cmdline = _get_process_command_line(listener_pid)
            if _is_same_console_instance(cmdline):
                return current_port
    return None


def _find_first_available_port(host: str, start_port: int, max_ports: int = WEB_PORT_SCAN_LIMIT) -> Optional[int]:
    for current_port in range(start_port, start_port + max_ports):
        if all(_get_listener_pid(current_host, current_port) is None for current_host in _conflict_hosts(host)):
            return current_port
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    print("\n" + "="*65, flush=True)
    print("🛑 接收到系统终止信号，正在强制结束引擎...", flush=True)
    try:
        if engine.is_running():
            engine.stop()
    except Exception: pass
    print("💥 已强制斩断所有底层连接，进程秒退！", flush=True)
    print("="*65 + "\n", flush=True)
    os._exit(0)

app = FastAPI(title="Wenfxl Codex Manager", lifespan=lifespan)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 拼接出 static 文件夹的绝对路径
STATIC_DIR = os.path.join(BASE_DIR, "static")

# 使用绝对路径挂载
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db_manager.init_db()

app.include_router(api_routes.router)

class DummyArgs:
    def __init__(self, proxy=None, once=False):
        self.proxy = proxy
        self.once = once

def _worker_push_thread():
    asyncio_ref = asyncio
    json_ref = json
    time_ref = time
    subprocess_ref = subprocess
    os_ref = os
    sys_ref = sys
    secrets_ref = secrets
    core = core_engine
    engine_ref = engine
    mail_service_ref = mail_service
    append_log_ref = append_log
    log_history_ref = log_history
    db_manager_ref = db_manager
    build_memory_report_ref = build_memory_report
    base_dir = BASE_DIR
    calculate_file_sha256 = _calculate_file_sha256
    is_default_cluster_secret = _is_default_cluster_secret
    last_role = None
    log_cache = RecentParsedLogCache(limit=50)
    push_interval = 1.0

    def _internal_start():
        try:
            reload_all_configs()
        except Exception:
            pass
        args = DummyArgs(proxy=getattr(core.cfg, "DEFAULT_PROXY", None))
        core.run_stats.update(
            {
                "success": 0,
                "failed": 0,
                "retries": 0,
                "pwd_blocked": 0,
                "phone_verify": 0,
                "start_time": time_ref.time(),
            }
        )
        mail_service_ref.start_mail_domain_runtime_tracking()
        if getattr(core.cfg, "ENABLE_CPA_MODE", False):
            engine_ref.start_cpa(args)
        elif getattr(core.cfg, "ENABLE_SUB2API_MODE", False):
            engine_ref.start_sub2api(args)
        else:
            engine_ref.start_normal(args)

    async def _ws_loop():
        nonlocal last_role
        try:
            import websockets
        except ImportError:
            print(f"[{core.ts()}] [系统] ❌ 缺少 WebSocket 库！请在终端执行: pip install websockets")
            return

        while True:
            try:
                while not core.log_queue.empty():
                    append_log_ref(core.log_queue.get_nowait())
            except Exception:
                pass

            cf_dict = getattr(core.cfg, "_c", {})
            master_url = str(cf_dict.get("cluster_master_url", "")).strip()
            node_name = str(cf_dict.get("cluster_node_name", "")).strip() or "未命名节点"
            secret = str(cf_dict.get("cluster_secret", "wenfxl666")).strip()

            if not master_url:
                if last_role != "master":
                    print(f"[{core.ts()}] [集群] 主控模式激活。")
                    last_role = "master"
                await asyncio_ref.sleep(0.5)
                continue

            if getattr(core.cfg, "CLUSTER_SYNC_REQUIRE_CUSTOM_SECRET", True) and is_default_cluster_secret(secret):
                if last_role != "secret_invalid":
                    print(f"[{core.ts()}] [集群] ❌ 当前 cluster_secret 仍为默认值，请先修改集群秘钥后再连接主控。")
                    last_role = "secret_invalid"
                await asyncio_ref.sleep(3)
                continue

            if master_url.startswith("http"):
                import urllib.parse

                ws_url = master_url.replace("http://", "ws://").replace("https://", "wss://")
                ws_endpoint = (
                    f"{ws_url.rstrip('/')}/api/cluster/report_ws?"
                    f"node_name={urllib.parse.quote(node_name)}&secret={urllib.parse.quote(secret)}"
                )

                try:
                    async with websockets.connect(ws_endpoint, ping_interval=None) as ws:
                        if last_role != "node":
                            print(f"[{core.ts()}] [集群] 🚀 已通过 WebSocket 建立超高速光纤连接: {master_url}")
                            last_role = "node"

                        while True:
                            try:
                                while not core.log_queue.empty():
                                    append_log_ref(core.log_queue.get_nowait())
                            except Exception:
                                pass

                            s = core.run_stats
                            is_running = engine_ref.is_running()
                            total = s["success"] + s["failed"]
                            if is_running:
                                elapsed = round(time_ref.time() - s["start_time"], 1) if s.get("start_time", 0) > 0 else 0
                                s["_frozen_elapsed"] = elapsed
                            else:
                                elapsed = s.get("_frozen_elapsed", 0)

                            stats_payload = {
                                "success": s["success"],
                                "failed": s["failed"],
                                "retries": s["retries"],
                                "pwd_blocked": s.get("pwd_blocked", 0),
                                "phone_verify": s.get("phone_verify", 0),
                                "total": total,
                                "target": s["target"] if s["target"] > 0 else "∞",
                                "success_rate": f"{round(s['success'] / total * 100, 2) if total > 0 else 0}%",
                                "elapsed": f"{elapsed}s",
                                "avg_time": f"{round(elapsed / s['success'], 1) if s['success'] > 0 else 0}s",
                                "progress_pct": f"{min(100, round(s['success'] / s['target'] * 100, 1)) if s['target'] > 0 else 0}%",
                                "is_running": is_running,
                                "mode": "CPA仓管"
                                if getattr(core.cfg, "ENABLE_CPA_MODE", False)
                                else ("Sub2Api" if getattr(core.cfg, "ENABLE_SUB2API_MODE", False) else "常规量产"),
                            }
                            try:
                                memory_report = build_memory_report_ref(getattr(core.cfg, "_c", {}))
                                stats_payload["memory"] = {
                                    "rss_mb": memory_report.get("actual", {}).get("rss_mb"),
                                    "predicted_mid_mb": memory_report.get("prediction", {}).get("predicted_mb", {}).get("mid"),
                                    "predicted_high_mb": memory_report.get("prediction", {}).get("predicted_mb", {}).get("high"),
                                    "safety_level": memory_report.get("safety", {}).get("level"),
                                    "safety_label": memory_report.get("safety", {}).get("label"),
                                }
                            except Exception:
                                pass

                            _, parsed_logs, changed = log_cache.refresh(log_history_ref)
                            if changed or is_running:
                                await ws.send(json_ref.dumps({"stats": stats_payload, "logs": parsed_logs}))
                            else:
                                await ws.send(json_ref.dumps({"stats": stats_payload}))

                            resp_str = await ws.recv()
                            cmd = json_ref.loads(resp_str).get("command", "none")

                            if cmd == "restart":
                                print(f"[{core.ts()}] [集群] 🔄 收到总控重启指令，正在重启...")

                                def _do_restart():
                                    time_ref.sleep(1)
                                    sys_ref.stdout.flush()
                                    subprocess_ref.Popen([sys_ref.executable] + sys_ref.argv)
                                    os_ref._exit(0)

                                threading.Thread(target=_do_restart, daemon=True).start()
                            elif cmd == "start" and not is_running:
                                threading.Thread(target=_internal_start, daemon=True).start()
                            elif cmd == "stop" and is_running:
                                engine_ref.stop()
                                mail_service_ref.stop_mail_domain_runtime_tracking()
                            elif cmd == "export_accounts":
                                print(f"[{core.ts()}] [系统] 收到总控提取指令，准备发货！")

                                def _upload_task():
                                    file_path = ""
                                    try:
                                        import urllib.request
                                        import urllib.parse

                                        shared_dir = str(
                                            getattr(core.cfg, "CLUSTER_SYNC_SHARED_DIR", "data/cluster_sync")
                                            or "data/cluster_sync"
                                        ).strip()
                                        shared_root = shared_dir if os_ref.path.isabs(shared_dir) else os_ref.path.join(base_dir, shared_dir)
                                        node_dir = os_ref.path.join(shared_root, node_name)
                                        os_ref.makedirs(node_dir, exist_ok=True)
                                        secret_value = str(secret or "").strip()
                                        if getattr(core.cfg, "CLUSTER_SYNC_REQUIRE_CUSTOM_SECRET", True) and is_default_cluster_secret(secret_value):
                                            raise RuntimeError("请先配置自定义 cluster_secret 后再发起同步")
                                        local_accounts = db_manager_ref.get_all_accounts_with_token(0, 0)
                                        if not local_accounts:
                                            print(f"[{core.ts()}] [系统] ⚠️ 本地库存为空，无账号可提取。")
                                            return
                                        max_records = max(1, int(getattr(core.cfg, "CLUSTER_SYNC_MAX_RECORDS", 100000) or 100000))
                                        if len(local_accounts) > max_records:
                                            raise RuntimeError(f"同步记录数量超限，当前 {len(local_accounts)}，上限 {max_records}")
                                        task_id = f"{node_name}-{int(time_ref.time())}-{secrets_ref.token_hex(4)}"
                                        print(f"[{core.ts()}] [系统] 📦 准备直传数据，共 {len(local_accounts)} 个账号...")
                                        req_data = {
                                            "node_name": node_name,
                                            "secret": secret_value,
                                            "task_id": task_id,
                                            "total_count": len(local_accounts),
                                            "accounts_data": local_accounts,
                                        }
                                        req_body = json_ref.dumps(req_data, ensure_ascii=False).encode("utf-8")
                                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                                        upload_timeout = getattr(core.cfg, "CLUSTER_UPLOAD_TIMEOUT_SEC", 30)
                                        upload_req = urllib.request.Request(
                                            f"{master_url.rstrip('/')}/api/cluster/sync_tasks",
                                            data=req_body,
                                            headers={"Content-Type": "application/json"},
                                        )
                                        with opener.open(upload_req, timeout=upload_timeout) as resp:
                                            resp_body = resp.read().decode("utf-8", errors="replace").strip()
                                        try:
                                            resp_json = json_ref.loads(resp_body) if resp_body else {}
                                        except Exception:
                                            raise RuntimeError(f"主控返回了非 JSON 响应: {resp_body[:200]}")
                                        if resp_json.get("status") != "success":
                                            raise RuntimeError(resp_json.get("message") or "主控未确认同步任务")
                                        print(f"[{core.ts()}] [系统] 📤 同步任务 {task_id} 已提交主控，等待异步导入。")
                                    except Exception as e:
                                        print(f"[{core.ts()}] [ERROR] ❌ 账号同步任务提交失败: {e}")
                                threading.Thread(target=_upload_task, daemon=True).start()

                            await asyncio_ref.sleep(push_interval if is_running else 3.0)
                except Exception:
                    pass
            await asyncio_ref.sleep(3)

    asyncio_ref.run(_ws_loop())

threading.Thread(target=_worker_push_thread, daemon=True).start()

if __name__ == "__main__":
    try: reload_all_configs()
    except: pass
    atexit.register(_remove_pid_file)
    existing_port = _find_existing_console_port(WEB_HOST, WEB_PORT)
    if WEB_PORT_STRICT:
        selected_port = WEB_PORT
        conflict_pid = _find_conflicting_listener_pid(WEB_HOST, selected_port)
        if conflict_pid is not None:
            cmdline = _get_process_command_line(conflict_pid)
            if _is_same_console_instance(cmdline):
                print(f"[{core_engine.ts()}] [系统] 固定端口 {selected_port} 仍被上一個控制台進程占用，等待釋放中...")
                conflict_pid = _wait_for_port_release(WEB_HOST, selected_port, WEB_PORT_STRICT_WAIT_SEC)
                cmdline = _get_process_command_line(conflict_pid) if conflict_pid is not None else ""
            if conflict_pid is None:
                print(f"[{core_engine.ts()}] [系统] 固定端口 {selected_port} 已釋放，繼續啟動。")
            else:
                print(f"[{core_engine.ts()}] [ERROR] 固定端口模式已启用，但端口 {selected_port} 已被占用，拒绝自动顺延。")
                if conflict_pid > 0:
                    print(f"[{core_engine.ts()}] [ERROR] 占用 PID: {conflict_pid}")
                if cmdline:
                    print(f"[{core_engine.ts()}] [ERROR] 占用进程命令行: {cmdline}")
                raise SystemExit(1)
    else:
        selected_port = _find_first_available_port(WEB_HOST, WEB_PORT)
        if selected_port is None:
            print(f"[{core_engine.ts()}] [ERROR] 在 {WEB_PORT}-{WEB_PORT + WEB_PORT_SCAN_LIMIT - 1} 端口区间内未找到可用端口。")
            raise SystemExit(1)

    print("=" * 65)
    print(f"[{core_engine.ts()}] [系统] OpenAI 全链路自动化生产与多维资源中转调度平台")
    print(f"[{core_engine.ts()}] [系统] Author: (wenfxl)轩灵")
    print(f"[{core_engine.ts()}] [系统] 如果遇到问题请更换域名解决，目前eu.cc，xyz，cn，edu.cc，fun，icu，top，bbroot.com，dpdns.org，qzz.io，info等常见域名均不可用，请更换为冷门域名")
    print(f"[{core_engine.ts()}] [系统] 根据官网披露消息：add-phone主要面向美国、荷兰、法国、西班牙、英国、波兰、德国、日本、印度、巴基斯坦、阿尔及利亚、乌兹别克斯坦和乌克兰的新用户推出。暂无其他地区的计划。")
    print(f"[{core_engine.ts()}] [系统] 根据官网披露消息：创建账号时验证手机号一个号码只能验证一个账号，创建API 密钥时也就是我们所说的拿凭证出现手机验证一个手机号可以验证3个账号。")
    print(f"[{core_engine.ts()}] [系统] 根据官网披露消息：在某些国家，您可以使用 WhatsApp 完成手机验证，而无需通过短信：阿拉伯联合酋长国、埃及、印度尼西亚、以色列、印度、马来西亚、尼日利亚、巴基斯坦、沙特阿拉伯、土耳其、乌克兰、越南，目前WhatsApp需要大家测试后在说。")
    print("-" * 65)
    print(f"[{core_engine.ts()}] [系统] Web 控制台已准备就绪，等待下发指令...")
    if existing_port is not None and not WEB_PORT_STRICT:
        print(f"[{core_engine.ts()}] [系统] 检测到已有控制台实例正在端口 {existing_port} 运行，本次将自动寻找新的可用端口继续启动。")
    if WEB_PORT_STRICT:
        print(f"[{core_engine.ts()}] [系统] 已启用固定端口模式，控制台将锁定运行在端口 {selected_port}。")
    elif selected_port != WEB_PORT:
        print(f"[{core_engine.ts()}] [系统] 默认端口 {WEB_PORT} 已被占用，已自动切换到端口 {selected_port}。")
    _write_pid_file()
    sys.__stdout__.write(f"[{core_engine.ts()}] [系统] 控制台地址：http://127.0.0.1:{selected_port} \n")
    sys.__stdout__.write(f"[{core_engine.ts()}] [系统] 控制台初始密码：admin \n")
    sys.__stdout__.write(f"[{core_engine.ts()}] [系统] 结束请猛猛重复按CTRL+C \n")
    sys.__stdout__.flush()
    uvicorn.run(app, host=WEB_HOST, port=selected_port, log_level="warning", access_log=False, timeout_graceful_shutdown=1)
