import threading
import os
import math
import ctypes
from collections import deque
from fastapi import Header, HTTPException
from utils import core_engine
import utils.config as cfg

VALID_TOKENS = set()
CLUSTER_NODES = {}
NODE_COMMANDS = {}
CLUSTER_NODE_BLOCKLIST = set()
CLUSTER_RUNTIME_STATUS = {}
cluster_lock = threading.Lock()
cluster_runtime_lock = threading.Lock()
log_history = deque(maxlen=cfg.MAX_LOG_LINES)
_log_lock = threading.Lock()
_log_append_counter = 0
worker_status: dict = {}
engine = core_engine.RegEngine()


def _get_process_rss_bytes() -> int:
    try:
        if os.name == "nt":
            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", ctypes.c_ulong),
                    ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            proc = ctypes.windll.kernel32.GetCurrentProcess()
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                proc,
                ctypes.byref(counters),
                counters.cb,
            )
            if ok:
                return int(counters.WorkingSetSize)
            return 0
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        return int(parts[1]) * 1024
    except Exception:
        return 0
    return 0


def _ensure_log_history_capacity_locked() -> None:
    global log_history
    target_maxlen = max(50, int(getattr(cfg, "MAX_LOG_LINES", 500) or 500))
    if log_history.maxlen == target_maxlen:
        return
    log_history = deque(list(log_history)[-target_maxlen:], maxlen=target_maxlen)


def _trim_log_history_if_needed_locked() -> None:
    rss_bytes = _get_process_rss_bytes()
    trim_mb = int(getattr(cfg, "LOG_MEMORY_TRIM_MB", 700) or 0)
    if trim_mb <= 0 or rss_bytes <= trim_mb * 1024 * 1024:
        return

    current_len = len(log_history)
    if current_len <= 50:
        return

    trim_ratio = float(getattr(cfg, "LOG_MEMORY_TRIM_RATIO", 0.7) or 0.7)
    trim_count = min(current_len - 50, max(1, math.ceil(current_len * trim_ratio)))
    kept = list(log_history)[trim_count:]
    log_history.clear()
    log_history.extend(kept)
    rss_mb = round(rss_bytes / 1024 / 1024, 1)
    log_history.append(
        f"[{core_engine.ts()}] [系统] 日志缓存触发内存保护：RSS={rss_mb}MB，已清理最老 {trim_count} 条日志，仅保留最近 {len(log_history)} 条。"
    )


def append_log(msg: str):
    global _log_append_counter
    with _log_lock:
        _ensure_log_history_capacity_locked()
        log_history.append(msg)
        _log_append_counter += 1
        every = max(1, int(getattr(cfg, "LOG_MEMORY_CHECK_EVERY", 25) or 25))
        if _log_append_counter % every == 0:
            _trim_log_history_if_needed_locked()


async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效凭证")
    token = authorization.split(" ")[1]
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return token
