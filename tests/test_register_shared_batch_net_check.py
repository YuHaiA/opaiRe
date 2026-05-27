import asyncio
import sys
import types
import unittest
from concurrent.futures import CancelledError as FuturesCancelledError, Future
from types import SimpleNamespace
from unittest.mock import patch


class _DummySession:
    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None
        self.get_called = False
        self.cookies = _DummyCookies()

    def get(self, *args, **kwargs):
        self.get_called = True
        raise AssertionError("shared batch mode should skip proxy net check")

    def close(self):
        return None


class _DummyCookies(dict):
    def clear(self):
        super().clear()

    def get(self, key, default=None):
        return super().get(key, default)


class _DummyResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = ""

    def json(self):
        return self._payload


_auth_core_stub = types.SimpleNamespace(
    generate_payload=lambda *args, **kwargs: None,
    init_auth=lambda *args, **kwargs: (None, None),
    image2api_data=None,
    sys_node_allocate=lambda *args, **kwargs: (False, "", "", ""),
    sys_node_release=lambda *args, **kwargs: None,
    code_pool={},
)

if "utils.auth_core" not in sys.modules:
    sys.modules["utils.auth_core"] = _auth_core_stub

from utils.auth_pipeline import register as register_module
from utils import core_engine


class RegisterSharedBatchNetCheckTests(unittest.TestCase):
    def test_shared_batch_flag_skips_duplicate_proxy_net_check(self):
        dummy_session = _DummySession()

        with patch.object(register_module.requests, "Session", return_value=dummy_session), \
                patch.object(register_module, "_skip_net_check", return_value=False), \
                patch.object(register_module, "get_email_and_token", return_value=(None, None)):
            result = register_module.run(
                "http://127.0.0.1:7890",
                run_ctx={"skip_proxy_net_check": True},
            )

        self.assertEqual((None, None), result)
        self.assertFalse(dummy_session.get_called)

    def test_shared_switch_force_only_enabled_after_fault_batch(self):
        self.assertFalse(core_engine._shared_global_switch_force_requested(False))
        self.assertTrue(core_engine._shared_global_switch_force_requested(True))

    def test_shared_batch_start_delay_only_applies_to_later_workers(self):
        self.assertEqual(0.0, register_module._get_shared_batch_start_delay({}, 3))
        self.assertEqual(0.0, register_module._get_shared_batch_start_delay({"skip_proxy_net_check": True}, 0))
        with patch.object(register_module.cfg, "EMAIL_API_MODE", "openai_cpa"):
            self.assertGreater(
                register_module._get_shared_batch_start_delay({"skip_proxy_net_check": True}, 5),
                0.1,
            )

    def test_passwordless_send_delay_only_applies_to_openai_cpa_shared_batch(self):
        with patch.object(register_module.cfg, "EMAIL_API_MODE", "openai_cpa"):
            self.assertGreater(
                register_module._get_passwordless_send_delay({"skip_proxy_net_check": True}, 6),
                0.1,
            )
        with patch.object(register_module.cfg, "EMAIL_API_MODE", "generator_email"):
            self.assertEqual(
                0.0,
                register_module._get_passwordless_send_delay({"skip_proxy_net_check": True}, 6),
            )

    def test_passwordless_takeover_success_does_not_trigger_extra_resend_and_continues_flow(self):
        post_calls = []

        def fake_post(*args, **kwargs):
            url = args[1] if len(args) > 1 else ""
            post_calls.append(url)
            if url.endswith("/authorize/continue"):
                return _DummyResponse(200, {"continue_url": "https://auth.openai.com/email-verification"})
            if url.endswith("/passwordless/send-otp"):
                return _DummyResponse(200, {})
            if url.endswith("/email-otp/validate"):
                return _DummyResponse(200, {"continue_url": "https://auth.openai.com/sign-in-with-chatgpt/codex/consent"})
            raise AssertionError(f"unexpected post url: {url}")

        with patch.object(register_module.requests, "Session", side_effect=lambda *args, **kwargs: _DummySession()), \
                patch.object(register_module, "_skip_net_check", return_value=True), \
                patch.object(register_module, "get_email_and_token", return_value=("takeover@example.com", "jwt-token")), \
                patch.object(register_module, "init_auth", return_value=("did-1", "ua-1")), \
                patch.object(register_module, "generate_payload", return_value="sentinel-token"), \
                patch.object(register_module, "_oai_headers", return_value={}), \
                patch.object(register_module, "_post_with_retry", side_effect=fake_post), \
                patch.object(register_module, "get_oai_code", return_value="123456") as mock_get_code, \
                patch.object(register_module, "generate_oauth_url", return_value=SimpleNamespace(state="state-1", code_verifier="verifier-1")), \
                patch.object(register_module, "_follow_redirect_chain_local", return_value=(None, "https://callback.local/?code=abc&state=state-1")), \
                patch.object(register_module, "submit_callback_url", return_value='{"email":"takeover@example.com"}'), \
                patch.object(register_module, "image2api_data", return_value=""), \
                patch.object(register_module.task_log_guard, "sleep_with_batch_abort", return_value=None):
            result = register_module.run("http://127.0.0.1:7890")

        self.assertEqual(('{"email":"takeover@example.com"}', "Takeover_NoPassword"), result)
        self.assertEqual(1, mock_get_code.call_count)
        self.assertNotIn("https://auth.openai.com/api/accounts/email-otp/resend", post_calls)

    def test_async_batch_collection_ignores_expected_cancelled_futures(self):
        async def runner():
            task_log_guard = __import__("utils.task_log_guard", fromlist=["task_log_guard"])
            task_log_guard.abort_batch("batch-a")
            future = asyncio.get_running_loop().create_future()
            future.cancel()
            result = await core_engine._collect_async_batch_results([future], batch_id="batch-a")
            self.assertEqual((0, True, 0), result)
            task_log_guard.clear_batch("batch-a")

        asyncio.run(runner())

    def test_sync_batch_collection_ignores_expected_cancelled_futures(self):
        task_log_guard = __import__("utils.task_log_guard", fromlist=["task_log_guard"])
        task_log_guard.abort_batch("batch-a")
        future = Future()
        future.set_exception(FuturesCancelledError())
        result = core_engine._collect_sync_batch_results([future], batch_id="batch-a")
        self.assertEqual((0, True, 0), result)
        task_log_guard.clear_batch("batch-a")


if __name__ == "__main__":
    unittest.main()
