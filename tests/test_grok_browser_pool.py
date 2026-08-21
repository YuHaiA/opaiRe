import queue
import threading
import time
import unittest
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import patch

from utils.grok_auth import browser_pool


class _FakeBrowser:
    def is_connected(self):
        return True


class GrokBrowserPoolTests(unittest.TestCase):
    def test_desired_size_respects_browser_worker_cap(self):
        with patch("utils.config.ENABLE_MULTI_THREAD_REG", True), \
                patch("utils.config.REG_THREADS", 8), \
                patch("utils.config.GROK_BROWSER_MAX_WORKERS", 2, create=True):
            self.assertEqual(browser_pool._desired_size(), 2)

    def test_zero_browser_worker_cap_keeps_thread_count(self):
        with patch("utils.config.ENABLE_MULTI_THREAD_REG", True), \
                patch("utils.config.REG_THREADS", 4), \
                patch("utils.config.GROK_BROWSER_MAX_WORKERS", 0, create=True):
            self.assertEqual(browser_pool._desired_size(), 4)

    def test_worker_recycles_browser_after_configured_job_count(self):
        work_queue = queue.Queue()
        close_calls = []
        launched = []
        original = {
            "job_q": browser_pool._job_q,
            "workers": browser_pool._workers,
            "worker_count": browser_pool._worker_count,
            "started": browser_pool._started,
            "shutting_down": browser_pool._shutting_down,
        }

        def launch(_headless):
            browser = _FakeBrowser()
            launched.append(browser)
            return SimpleNamespace(), browser

        def close(cm, browser):
            if browser is not None:
                close_calls.append(browser)

        try:
            browser_pool._job_q = work_queue
            browser_pool._workers = []
            browser_pool._worker_count = 1
            browser_pool._started = True
            browser_pool._shutting_down = False

            with patch.object(browser_pool, "_launch_browser", side_effect=launch), \
                    patch.object(browser_pool, "_close_browser", side_effect=close), \
                    patch("utils.config.GROK_BROWSER_RECYCLE_JOBS", 1, create=True):
                worker = threading.Thread(target=browser_pool._worker_loop, args=(1, True))
                worker.start()

                futures = [Future(), Future()]
                for future in futures:
                    work_queue.put(browser_pool._PoolJob(lambda _browser: "ok", {}, future))
                for future in futures:
                    self.assertEqual(future.result(timeout=2), "ok")

                deadline = time.time() + 2
                while len(close_calls) < 1 and time.time() < deadline:
                    time.sleep(0.01)
                self.assertGreaterEqual(len(close_calls), 1)
                self.assertGreaterEqual(len(launched), 2)

                browser_pool._shutting_down = True
                work_queue.put(None)
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertGreaterEqual(len(close_calls), 2)
        finally:
            browser_pool._job_q = original["job_q"]
            browser_pool._workers = original["workers"]
            browser_pool._worker_count = original["worker_count"]
            browser_pool._started = original["started"]
            browser_pool._shutting_down = original["shutting_down"]

    def test_worker_closes_browser_after_idle_timeout(self):
        work_queue = queue.Queue()
        closed = threading.Event()
        original = {
            "job_q": browser_pool._job_q,
            "workers": browser_pool._workers,
            "worker_count": browser_pool._worker_count,
            "started": browser_pool._started,
            "shutting_down": browser_pool._shutting_down,
        }

        try:
            browser_pool._job_q = work_queue
            browser_pool._workers = []
            browser_pool._worker_count = 1
            browser_pool._started = True
            browser_pool._shutting_down = False

            with patch.object(
                browser_pool,
                "_launch_browser",
                return_value=(SimpleNamespace(), _FakeBrowser()),
            ), patch.object(
                browser_pool,
                "_close_browser",
                side_effect=lambda _cm, browser: closed.set() if browser is not None else None,
            ), patch(
                "utils.config.GROK_BROWSER_IDLE_TIMEOUT", 0.05, create=True
            ), patch(
                "utils.config.GROK_BROWSER_RECYCLE_JOBS", 0, create=True
            ):
                worker = threading.Thread(target=browser_pool._worker_loop, args=(1, True))
                worker.start()
                future = Future()
                work_queue.put(browser_pool._PoolJob(lambda _browser: "ok", {}, future))
                self.assertEqual(future.result(timeout=2), "ok")
                self.assertTrue(closed.wait(timeout=2))

                browser_pool._shutting_down = True
                work_queue.put(None)
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
        finally:
            browser_pool._job_q = original["job_q"]
            browser_pool._workers = original["workers"]
            browser_pool._worker_count = original["worker_count"]
            browser_pool._started = original["started"]
            browser_pool._shutting_down = original["shutting_down"]


if __name__ == "__main__":
    unittest.main()
