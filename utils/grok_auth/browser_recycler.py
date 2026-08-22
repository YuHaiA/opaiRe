# -*- coding: utf-8 -*-
from __future__ import annotations

import threading
import time
from typing import Any, Dict

_lock = threading.RLock()
_started_at = time.monotonic()
_task_count = 0
_recycle_pending = False
_recycling = False


def _settings() -> tuple[bool, int, float]:
    from utils import config as cfg

    enabled = bool(getattr(cfg, "GROK_BROWSER_RECYCLE_ENABLED", True))
    try:
        task_limit = max(0, int(getattr(cfg, "GROK_BROWSER_RECYCLE_TASK_LIMIT", 50) or 0))
    except (TypeError, ValueError):
        task_limit = 50
    try:
        minutes_limit = max(0.0, float(getattr(cfg, "GROK_BROWSER_RECYCLE_MINUTES_LIMIT", 120) or 0))
    except (TypeError, ValueError):
        minutes_limit = 120.0
    return enabled, task_limit, minutes_limit


def _threshold_reached(now: float) -> bool:
    enabled, task_limit, minutes_limit = _settings()
    if not enabled:
        return False
    task_due = task_limit > 0 and _task_count >= task_limit
    time_due = minutes_limit > 0 and now - _started_at >= minutes_limit * 60.0
    return task_due or time_due


def mark_task_finished() -> None:
    global _task_count, _recycle_pending

    with _lock:
        _task_count += 1
        if _threshold_reached(time.monotonic()):
            _recycle_pending = True


def recycle_before_next_task(*, headless: bool = True) -> bool:
    global _started_at, _task_count, _recycle_pending, _recycling

    with _lock:
        if _recycling:
            return False
        if not (_recycle_pending or _threshold_reached(time.monotonic())):
            return False
        _recycling = True

    try:
        from utils import config as cfg
        from .browser_pool import ensure_browser_pool, shutdown_browser_pool

        print(f"[{cfg.ts()}] [Grok] 达到生命周期阈值，将在本任务前重建...", flush=True)
        shutdown_browser_pool(timeout=15.0)
        ensure_browser_pool(headless=bool(headless))
        return True
    finally:
        with _lock:
            _started_at = time.monotonic()
            _task_count = 0
            _recycle_pending = False
            _recycling = False


def reset_browser_recycle_state() -> None:
    global _started_at, _task_count, _recycle_pending, _recycling

    with _lock:
        _started_at = time.monotonic()
        _task_count = 0
        _recycle_pending = False
        _recycling = False


def browser_recycle_status() -> Dict[str, Any]:
    with _lock:
        enabled, task_limit, minutes_limit = _settings()
        return {
            "enabled": enabled,
            "task_count": _task_count,
            "task_limit": task_limit,
            "minutes_limit": minutes_limit,
            "age_seconds": max(0.0, time.monotonic() - _started_at),
            "pending": _recycle_pending,
            "recycling": _recycling,
        }
