import sys
import types
import unittest
import asyncio
from unittest.mock import patch


if "yaml" not in sys.modules:
    sys.modules["yaml"] = types.SimpleNamespace(
        safe_load=lambda *a, **kw: {},
        safe_dump=lambda *a, **kw: "",
        dump=lambda *a, **kw: "",
    )

if "curl_cffi" not in sys.modules:
    sys.modules["curl_cffi"] = types.SimpleNamespace(
        requests=types.SimpleNamespace(Session=object),
        CurlMime=object,
    )

if "utils.auth_pipeline.register" not in sys.modules:
    sys.modules["utils.auth_pipeline.register"] = types.SimpleNamespace(
        run=lambda *args, **kwargs: None,
    )

if "utils.email_providers.mail_service" not in sys.modules:
    sys.modules["utils.email_providers.mail_service"] = types.SimpleNamespace(
        mask_email=lambda value: value,
        get_last_email=lambda: "",
        get_oai_code=lambda *args, **kwargs: "",
    )

if "utils.auth_pipeline.oauth" not in sys.modules:
    sys.modules["utils.auth_pipeline.oauth"] = types.SimpleNamespace(
        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
    )

if "utils.integrations.sub2api_client" not in sys.modules:
    sys.modules["utils.integrations.sub2api_client"] = types.SimpleNamespace(
        Sub2APIClient=object,
    )

if "utils.integrations.tg_notifier" not in sys.modules:
    sys.modules["utils.integrations.tg_notifier"] = types.SimpleNamespace(
        send_tg_msg_sync=lambda *args, **kwargs: None,
    )

if "utils.email_providers.postman_center" not in sys.modules:
    sys.modules["utils.email_providers.postman_center"] = types.SimpleNamespace(
        global_postman_fleet=types.SimpleNamespace(clear_fleet=lambda: None),
    )


from utils import core_engine, task_log_guard


class CoreEngineAbortCleanupTests(unittest.TestCase):
    def tearDown(self):
        task_log_guard.end_task()
        task_log_guard.reset_bucket("bucket-a")
        task_log_guard.clear_batch("batch-a")

    def test_execute_registration_run_cleanup_does_not_reenter_aborted_batch(self):
        abort_error = task_log_guard.TaskAbortError(
            bucket_id="bucket-a",
            count=5,
            kind="curl_timeout",
            message="timeout",
            label="bucket-a",
            batch_id="batch-a",
        )

        def fake_run(*args, **kwargs):
            raise abort_error

        def fake_evict(*args, **kwargs):
            task_log_guard.raise_if_current_batch_aborted()
            return True, "removed"

        with patch.object(core_engine, "run", side_effect=fake_run), \
                patch.object(core_engine, "get_failure_bucket_id", return_value="bucket-a"), \
                patch.object(core_engine, "evict_current_proxy_or_node", side_effect=fake_evict), \
                patch.object(core_engine, "format_docker_url", side_effect=lambda value: value), \
                patch.object(core_engine.task_log_guard, "bind_task_batch", wraps=task_log_guard.bind_task_batch), \
                patch.object(core_engine.task_log_guard, "start_task", wraps=task_log_guard.start_task), \
                patch.object(core_engine.task_log_guard, "end_task", wraps=task_log_guard.end_task):
            result, status = core_engine._execute_registration_run(
                "http://127.0.0.1:7890",
                args=object(),
                batch_id="batch-a",
            )

        self.assertIsNone(result)
        self.assertEqual("switch_node", status)

    def test_empty_batch_wait_uses_configured_fast_timeout(self):
        async def run_check():
            event = asyncio.Event()
            with patch.object(core_engine.cfg, "REG_EMPTY_BATCH_WAIT_SECONDS", 0.01):
                start = asyncio.get_running_loop().time()
                await core_engine._wait_after_empty_shared_batch(event, 0, 0, False, "test")
                return asyncio.get_running_loop().time() - start

        elapsed = asyncio.run(run_check())
        self.assertLess(elapsed, 0.2)


if __name__ == "__main__":
    unittest.main()
