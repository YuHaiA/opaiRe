# -*- coding: utf-8 -*-
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from typing import Any, Callable, Dict, List, Optional


_lock = threading.RLock()
_job_q: Optional["queue.Queue[Optional[_PoolJob]]"] = None
_workers: List[threading.Thread] = []
_worker_count = 0
_headless = True
_started = False
_shutting_down = False
_DEFAULT_RECYCLE_JOBS = 8
_DEFAULT_MAX_WORKERS = 2
_DEFAULT_IDLE_TIMEOUT = 60.0


class _PoolJob:
    __slots__ = ("fn", "kwargs", "future")

    def __init__(self, fn: Callable[..., Any], kwargs: Dict[str, Any], future: Future):
        self.fn = fn
        self.kwargs = kwargs
        self.future = future


def _desired_size() -> int:
    try:
        from utils import config as cfg

        multi = bool(getattr(cfg, "ENABLE_MULTI_THREAD_REG", False))
        threads = int(getattr(cfg, "REG_THREADS", 1) or 1)
        wanted = max(1, threads) if multi else 1
        max_workers = int(getattr(cfg, "GROK_BROWSER_MAX_WORKERS", _DEFAULT_MAX_WORKERS) or 0)
        return min(wanted, max_workers) if max_workers > 0 else wanted
    except Exception:
        return 1


def _recycle_jobs() -> int:
    """Return the number of completed jobs before recycling a browser.

    A zero value disables periodic recycling; task shutdown still closes the
    pool. Keeping this behind config lets low-memory hosts choose a smaller
    lifetime without changing the worker protocol.
    """
    try:
        from utils import config as cfg

        value = int(getattr(cfg, "GROK_BROWSER_RECYCLE_JOBS", _DEFAULT_RECYCLE_JOBS) or 0)
    except Exception:
        value = _DEFAULT_RECYCLE_JOBS
    return max(0, value)


def _idle_timeout() -> float:
    try:
        from utils import config as cfg

        value = float(getattr(cfg, "GROK_BROWSER_IDLE_TIMEOUT", _DEFAULT_IDLE_TIMEOUT) or 0)
    except Exception:
        value = _DEFAULT_IDLE_TIMEOUT
    return max(0.0, value)


def _launch_browser(headless: bool):
    from camoufox.sync_api import Camoufox

    # 代理放在 Context 上，浏览器进程本身长期复用
    cm = Camoufox(headless=bool(headless))
    browser = cm.__enter__()
    return cm, browser


def _close_browser(cm, browser) -> None:
    try:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    finally:
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass


def _browser_alive(browser) -> bool:
    if browser is None:
        return False
    try:
        return bool(browser.is_connected())
    except Exception:
        return False


def _worker_loop(worker_id: int, headless: bool) -> None:
    global _shutting_down
    cm = None
    browser = None
    jobs_since_launch = 0
    last_job_finished_at = 0.0
    try:
        while True:
            with _lock:
                if _shutting_down and (_job_q is None or _job_q.empty()):
                    break
            try:
                job = _job_q.get(timeout=0.4) if _job_q is not None else None
            except queue.Empty:
                idle_timeout = _idle_timeout()
                if (
                    browser is not None
                    and idle_timeout > 0
                    and last_job_finished_at > 0
                    and time.monotonic() - last_job_finished_at >= idle_timeout
                ):
                    _close_browser(cm, browser)
                    cm, browser = None, None
                    jobs_since_launch = 0
                continue
            if job is None:
                # 毒丸：退出
                try:
                    if _job_q is not None:
                        _job_q.task_done()
                except Exception:
                    pass
                break

            if not _browser_alive(browser):
                _close_browser(cm, browser)
                cm, browser = None, None
                jobs_since_launch = 0
                try:
                    cm, browser = _launch_browser(headless)
                except Exception as exc:
                    try:
                        job.future.set_exception(exc)
                    except Exception:
                        pass
                    try:
                        if _job_q is not None:
                            _job_q.task_done()
                    except Exception:
                        pass
                    continue

            try:
                result = job.fn(browser, **job.kwargs)
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:
                # 浏览器可能已坏，下次任务重建
                try:
                    if not _browser_alive(browser):
                        _close_browser(cm, browser)
                        cm, browser = None, None
                        jobs_since_launch = 0
                except Exception:
                    cm, browser = None, None
                    jobs_since_launch = 0
                if not job.future.done():
                    try:
                        job.future.set_exception(exc)
                    except Exception:
                        pass
            finally:
                jobs_since_launch += 1
                last_job_finished_at = time.monotonic()
                try:
                    if _job_q is not None:
                        _job_q.task_done()
                except Exception:
                    pass

            recycle_after = _recycle_jobs()
            if browser is not None and recycle_after > 0 and jobs_since_launch >= recycle_after:
                _close_browser(cm, browser)
                cm, browser = None, None
                jobs_since_launch = 0
    finally:
        _close_browser(cm, browser)


def ensure_browser_pool(*, headless: bool = True, size: Optional[int] = None) -> int:
    """按当前多线程配置启动/扩容浏览器池，返回实际 worker 数。"""
    global _job_q, _workers, _worker_count, _headless, _started, _shutting_down

    want = max(1, int(size if size is not None else _desired_size()))
    with _lock:
        if _shutting_down:
            # 停止后允许再次启动
            _shutting_down = False
            _started = False
            _workers = []
            _worker_count = 0
            _job_q = None

        if not _started or _job_q is None:
            _job_q = queue.Queue()
            _headless = bool(headless)
            _workers = []
            _worker_count = 0
            _started = True

        # 只扩容不缩容（缩容在 shutdown）
        while _worker_count < want:
            wid = _worker_count + 1
            t = threading.Thread(
                target=_worker_loop,
                args=(wid, _headless),
                name=f"grok-browser-pool-{wid}",
                daemon=True,
            )
            t.start()
            _workers.append(t)
            _worker_count += 1

        return _worker_count


def run_with_browser(
    fn: Callable[..., Any],
    *,
    headless: bool = True,
    timeout: Optional[float] = None,
    **kwargs: Any,
) -> Any:
    """
    在池内某个 worker 线程执行 fn(browser, **kwargs)。
    Playwright 同步 API 非线程安全：browser 只在所属 worker 线程使用。
    """
    if not callable(fn):
        raise TypeError("fn must be callable")

    ensure_browser_pool(headless=headless)
    fut: Future = Future()
    job = _PoolJob(fn=fn, kwargs=dict(kwargs), future=fut)

    with _lock:
        if _job_q is None or _shutting_down:
            raise RuntimeError("browser pool is not available")
        _job_q.put(job)

    wait_s = None if timeout is None else max(30.0, float(timeout))
    try:
        return fut.result(timeout=wait_s)
    except Exception:
        # 超时/取消时 future 可能仍被 worker 写回，忽略即可
        raise


def shutdown_browser_pool(timeout: float = 8.0) -> None:
    """停止所有浏览器 worker 并关闭进程。"""
    global _job_q, _workers, _worker_count, _started, _shutting_down

    with _lock:
        if not _started and not _workers:
            return
        _shutting_down = True
        q = _job_q
        workers = list(_workers)
        n = len(workers)

    if q is not None:
        for _ in range(n):
            try:
                q.put(None)
            except Exception:
                pass

    deadline = time.time() + max(1.0, float(timeout or 8.0))
    for t in workers:
        remain = deadline - time.time()
        if remain <= 0:
            break
        try:
            t.join(timeout=remain)
        except Exception:
            pass

    with _lock:
        _workers = []
        _worker_count = 0
        _job_q = None
        _started = False
        _shutting_down = False


def browser_pool_status() -> Dict[str, Any]:
    with _lock:
        return {
            "started": _started,
            "workers": _worker_count,
            "headless": _headless,
            "desired": _desired_size(),
            "queue": (0 if _job_q is None else _job_q.qsize()),
        }
