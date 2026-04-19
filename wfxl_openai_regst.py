import os
import sys
import json
import time
import asyncio
import threading
import signal
import uvicorn
import re
import warnings
import subprocess
import socket
import socks
import atexit
warnings.filterwarnings("ignore", category=RuntimeWarning, module="trio")

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from utils import core_engine, db_manager
from utils.config import reload_all_configs

from global_state import engine, log_history, CLUSTER_RUNTIME_STATUS, cluster_runtime_lock
from routers import api_routes

_shutdown_started = threading.Event()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_LOG_HANDLES = []


class _TeeTextStream:
    def __init__(self, file_handle, mirror=None):
        self._file_handle = file_handle
        self._mirror = mirror
        self.encoding = "utf-8"

    def write(self, data):
        if data is None:
            return 0
        text = str(data)
        self._file_handle.write(text)
        self._file_handle.flush()
        if self._mirror is not None:
            try:
                self._mirror.write(text)
                self._mirror.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        try:
            self._file_handle.flush()
        except Exception:
            pass
        if self._mirror is not None:
            try:
                self._mirror.flush()
            except Exception:
                pass

    def isatty(self):
        return False


def _configure_runtime_log_files():
    out_path = os.path.join(BASE_DIR, "run.out.log")
    err_path = os.path.join(BASE_DIR, "run.err.log")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    out_handle = open(out_path, "a", encoding="utf-8", buffering=1)
    err_handle = open(err_path, "a", encoding="utf-8", buffering=1)
    _LOG_HANDLES.extend([out_handle, err_handle])

    stdout_mirror = sys.stdout if getattr(sys, "stdout", None) not in (None, sys.__stdout__) else sys.__stdout__
    stderr_mirror = sys.stderr if getattr(sys, "stderr", None) not in (None, sys.__stderr__) else sys.__stderr__

    stdout_proxy = _TeeTextStream(out_handle, stdout_mirror)
    stderr_proxy = _TeeTextStream(err_handle, stderr_mirror)
    sys.stdout = stdout_proxy
    sys.stderr = stderr_proxy
    sys.__stdout__ = stdout_proxy
    sys.__stderr__ = stderr_proxy


def _close_runtime_log_files():
    while _LOG_HANDLES:
        handle = _LOG_HANDLES.pop()
        try:
            handle.flush()
            handle.close()
        except Exception:
            pass


def _safe_console_write(message: str):
    stream = getattr(sys, "__stdout__", None) or getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        stream.write(message)
        stream.flush()
    except Exception:
        pass


_configure_runtime_log_files()
atexit.register(_close_runtime_log_files)


def _stop_engine(reason: str):
    print("\n" + "=" * 65, flush=True)
    print(f"[{core_engine.ts()}] [系统] {reason}", flush=True)
    print(f"[{core_engine.ts()}] [系统] 正在停止后台引擎与任务线程...", flush=True)
    try:
        if engine.is_running():
            engine.stop()
    except Exception as exc:
        print(f"[{core_engine.ts()}] [ERROR] 停止引擎时发生异常: {exc}", flush=True)
    print("=" * 65 + "\n", flush=True)


def _force_process_exit(reason: str, wait_seconds: float = 5.0):
    if _shutdown_started.is_set():
        return
    _shutdown_started.set()

    def _worker():
        _stop_engine(reason)
        engine.wait_until_stopped(wait_seconds)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)

    threading.Thread(target=_worker, daemon=True, name="ForcedExitWorker").start()


def _signal_name(sig):
    try:
        return signal.Signals(sig).name
    except Exception:
        return str(sig)


def _set_cluster_runtime_status(**fields):
    with cluster_runtime_lock:
        CLUSTER_RUNTIME_STATUS.update(fields)
        CLUSTER_RUNTIME_STATUS["last_event"] = time.time()


def _drain_runtime_logs_to_history():
    try:
        while not core_engine.log_queue.empty():
            msg = core_engine.log_queue.get_nowait()
            log_history.append(msg)
    except Exception:
        pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    _stop_engine("收到 Web 服务关闭请求，准备退出进程...")

app = FastAPI(title="Wenfxl Codex Manager", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="static"), name="static")

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
    last_role = None
    last_ws_error = None
    ws_retry_after = 0.0

    def _internal_start():
        try:
            reload_all_configs()
        except Exception:
            pass
        args = DummyArgs(proxy=getattr(core_engine.cfg, 'DEFAULT_PROXY', None))
        core_engine.run_stats.update({"success": 0, "failed": 0, "retries": 0, "pwd_blocked": 0, "phone_verify": 0, "start_time": time.time(), "ext_is_running": False})
        if getattr(core_engine.cfg, 'ENABLE_CPA_MODE', False):
            engine.start_cpa(args)
        elif getattr(core_engine.cfg, 'ENABLE_SUB2API_MODE', False):
            engine.start_sub2api(args)
        else:
            engine.start_normal(args)

    async def _ws_loop():
        nonlocal last_role, last_ws_error, ws_retry_after

        try:
            import websockets
        except ImportError:
            print(f"[{core_engine.ts()}] [系统] ❌ 缺少 WebSocket 库！请在终端执行: pip install websockets")
            return

        def _build_cluster_payload():
            _drain_runtime_logs_to_history()
            s = core_engine.run_stats
            is_running = engine.is_running()
            total = s["success"] + s["failed"]
            if is_running:
                elapsed = round(time.time() - s["start_time"], 1) if s.get("start_time", 0) > 0 else 0
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
                "mode": "CPA仓管" if getattr(core_engine.cfg, 'ENABLE_CPA_MODE', False) else ("Sub2Api" if getattr(core_engine.cfg, 'ENABLE_SUB2API_MODE', False) else "常规量产"),
            }

            parsed_logs = []
            for raw in list(log_history)[-50:]:
                m = re.match(r"^\[(.*?)\]\s*\[(.*?)\]\s+(.*)$", raw.strip())
                if m:
                    parsed_logs.append({
                        "parsed": True,
                        "time": m.group(1),
                        "level": m.group(2).upper(),
                        "text": m.group(3),
                        "raw": raw,
                    })
                else:
                    parsed_logs.append({"parsed": False, "raw": raw})
            return {"stats": stats_payload, "logs": parsed_logs}

        def _handle_cluster_command(cmd, master_url, node_name, secret, is_running):
            _set_cluster_runtime_status(last_command=cmd or "none")
            if cmd == "restart":
                print(f"[{core_engine.ts()}] [集群] 🔄 收到总控重启指令，正在重启...")

                def _do_restart():
                    time.sleep(1)
                    sys.stdout.flush()
                    subprocess.Popen([sys.executable] + sys.argv)
                    os._exit(0)

                threading.Thread(target=_do_restart, daemon=True).start()
            elif cmd == "start" and not is_running:
                threading.Thread(target=_internal_start, daemon=True).start()
            elif cmd == "stop" and is_running:
                engine.stop()
            elif cmd == "disconnect":
                _set_cluster_runtime_status(connected=False, transport="disabled", last_error="主控主动断开当前子控")
            elif cmd == "export_accounts":
                print(f"[{core_engine.ts()}] [系统] 收到总控提取指令，准备发货！")

                def _upload_task():
                    try:
                        import urllib.request

                        local_accounts = db_manager.get_all_accounts_with_token(10000)
                        if not local_accounts:
                            print(f"[{core_engine.ts()}] [系统] ⚠️ 本地库存为空，无账号可提取。")
                            return
                        req_data = {"node_name": node_name, "secret": secret, "accounts": local_accounts}
                        req_body = json.dumps(req_data).encode('utf-8')
                        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                        upload_req = urllib.request.Request(
                            f"{master_url.rstrip('/')}/api/cluster/upload_accounts",
                            data=req_body,
                            headers={'Content-Type': 'application/json'},
                        )
                        with opener.open(upload_req, timeout=15) as _:
                            print(f"[{core_engine.ts()}] [系统] 📤 已成功将 {len(local_accounts)} 个账号打包发往总控！")
                    except Exception as e:
                        print(f"[{core_engine.ts()}] [ERROR] ❌ 账号上传总控失败: {e}")

                threading.Thread(target=_upload_task, daemon=True).start()

        async def _post_cluster_report_http(master_url, node_name, secret, payload):
            import urllib.request

            req_body = json.dumps({
                "node_name": node_name,
                "secret": secret,
                "stats": payload.get("stats", {}),
                "logs": payload.get("logs", []),
            }).encode("utf-8")

            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            req = urllib.request.Request(
                f"{master_url.rstrip('/')}/api/cluster/report",
                data=req_body,
                headers={"Content-Type": "application/json"},
            )

            def _send_once():
                with opener.open(req, timeout=8) as resp:
                    return json.loads(resp.read().decode("utf-8") or "{}")

            return await asyncio.to_thread(_send_once)

        while True:
            _drain_runtime_logs_to_history()

            master_url = str(getattr(core_engine.cfg, 'CLUSTER_MASTER_URL', '') or '').strip().rstrip('/')
            node_name = str(getattr(core_engine.cfg, 'CLUSTER_NODE_NAME', '') or '').strip() or "未命名节点"
            secret = str(getattr(core_engine.cfg, 'CLUSTER_SECRET', 'change-me-cluster-secret') or '').strip()
            cluster_enabled = bool(getattr(core_engine.cfg, 'CLUSTER_ENABLED', True))
            prefer_ws = bool(getattr(core_engine.cfg, 'CLUSTER_PREFER_WS', True))

            _set_cluster_runtime_status(enabled=cluster_enabled, master_url=master_url, node_name=node_name)

            if not cluster_enabled:
                if last_role != "disabled":
                    print(f"[{core_engine.ts()}] [集群] 子控上报已手动断开，主任务继续独立运行。")
                    last_role = "disabled"
                _set_cluster_runtime_status(connected=False, transport="disabled", last_error="已手动断开")
                await asyncio.sleep(2.0)
                continue

            if not master_url:
                if last_role != "master":
                    print(f"[{core_engine.ts()}] [集群] 主控模式激活。")
                    last_role = "master"
                _set_cluster_runtime_status(connected=False, transport="idle", last_error="当前未配置主控地址")
                await asyncio.sleep(1.5)
                continue

            if not master_url.startswith("http://") and not master_url.startswith("https://"):
                _set_cluster_runtime_status(connected=False, transport="idle", last_error="主控地址格式无效，仅支持 http/https")
                await asyncio.sleep(3)
                continue

            payload = _build_cluster_payload()
            use_ws_now = prefer_ws and master_url.startswith("http") and time.time() >= ws_retry_after

            if use_ws_now:
                import urllib.parse

                ws_url = master_url.replace("http://", "ws://").replace("https://", "wss://")
                ws_endpoint = f"{ws_url.rstrip('/')}/api/cluster/report_ws?node_name={urllib.parse.quote(node_name)}&secret={urllib.parse.quote(secret)}"

                try:
                    async with websockets.connect(
                        ws_endpoint,
                        ping_interval=20,
                        ping_timeout=20,
                        close_timeout=5,
                        open_timeout=8,
                        max_size=2_000_000,
                    ) as ws:
                        if last_role != "node":
                            print(f"[{core_engine.ts()}] [集群] 🚀 已通过 WebSocket 建立超高速光纤连接: {master_url}")
                            last_role = "node"
                        last_ws_error = None
                        _set_cluster_runtime_status(connected=True, transport="wss", last_error="")

                        while True:
                            current_enabled = bool(getattr(core_engine.cfg, 'CLUSTER_ENABLED', True))
                            current_master = str(getattr(core_engine.cfg, 'CLUSTER_MASTER_URL', '') or '').strip().rstrip('/')
                            if (not current_enabled) or current_master != master_url:
                                await ws.close()
                                break

                            payload = _build_cluster_payload()
                            is_running = bool(payload.get("stats", {}).get("is_running", False))
                            await ws.send(json.dumps(payload))

                            resp_str = await asyncio.wait_for(ws.recv(), timeout=25)
                            cmd = json.loads(resp_str).get("command", "none")
                            _set_cluster_runtime_status(connected=True, transport="wss", last_report_at=time.time(), last_error="")
                            _handle_cluster_command(cmd, master_url, node_name, secret, is_running)
                            await asyncio.sleep(1.5)
                except Exception as e:
                    err_text = str(e)
                    if err_text != last_ws_error:
                        print(f"[{core_engine.ts()}] [集群] ⚠️ WebSocket 上报链路异常，已自动降级到 HTTP 心跳: {err_text}")
                        last_ws_error = err_text
                    ws_retry_after = time.time() + 60
                    _set_cluster_runtime_status(connected=False, transport="http-fallback", last_error=err_text)

            try:
                response = await _post_cluster_report_http(master_url, node_name, secret, payload)
                is_running = bool(payload.get("stats", {}).get("is_running", False))
                cmd = str((response or {}).get("command", "none") or "none")
                _set_cluster_runtime_status(connected=True, transport="http", last_report_at=time.time(), last_error="")
                _handle_cluster_command(cmd, master_url, node_name, secret, is_running)
            except Exception as e:
                err_text = str(e)
                _set_cluster_runtime_status(connected=False, transport="http", last_error=err_text)
                if err_text != last_ws_error:
                    print(f"[{core_engine.ts()}] [集群] ⚠️ 集群上报失败，但不会影响主任务运行: {err_text}")
                    last_ws_error = err_text

            await asyncio.sleep(3)

    asyncio.run(_ws_loop())

threading.Thread(target=_worker_push_thread, daemon=True).start()


class ManagedUvicornServer(uvicorn.Server):
    def handle_exit(self, sig: int, frame) -> None:
        _force_process_exit(f"收到 {_signal_name(sig)}，准备安全退出...", wait_seconds=5.0)
        super().handle_exit(sig, frame)

if __name__ == "__main__":
    try: reload_all_configs()
    except: pass
    print("=" * 65)
    print(f"[{core_engine.ts()}] [系统] OpenAI 全链路自动化生产与多维资源中转调度平台")
    print(f"[{core_engine.ts()}] [系统] Author: (wenfxl)轩灵")
    print(f"[{core_engine.ts()}] [系统] 如果遇到问题请更换域名解决，目前eu.cc，xyz，cn，edu.cc等常见域名均不可用，请更换为冷门域名")
    print("-" * 65)
    print(f"[{core_engine.ts()}] [系统] Web 控制台已准备就绪，等待下发指令...")
    _safe_console_write(f"[{core_engine.ts()}] [系统] 控制台地址：http://127.0.0.1:8000 \n")
    _safe_console_write(f"[{core_engine.ts()}] [系统] 控制台初始密码：admin \n")
    _safe_console_write(f"[{core_engine.ts()}] [系统] 结束请猛猛重复按CTRL+C \n")
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning", access_log=False, timeout_graceful_shutdown=1)
    ManagedUvicornServer(config).run()
