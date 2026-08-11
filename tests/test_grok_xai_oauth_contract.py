import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from utils import core_engine
from utils.grok_auth import browser_signup, sso_to_auth_json, xai_oauth


class _DeviceCodeResponse:
    status_code = 200
    text = '{"device_code":"device-1","user_code":"CODE-1"}'

    def json(self):
        return {"device_code": "device-1", "user_code": "CODE-1"}


class _CaptureSession:
    def __init__(self):
        self.data = None
        self.headers = None
        self.url = None

    def post(self, url, *, data, **_kwargs):
        self.url = url
        self.data = dict(data)
        self.headers = dict(_kwargs.get("headers") or {})
        return _DeviceCodeResponse()


class _SignupPage:
    def __init__(self, url=browser_signup.SIGNUP_URL):
        self.url = url
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        self.url = url

    def wait_for_load_state(self, *_args, **_kwargs):
        return None

    def wait_for_selector(self, *_args, **_kwargs):
        return object()

    def title(self):
        return "Grok"

    def locator(self, _selector):
        return self

    def inner_text(self, **_kwargs):
        return "Ask anything"


class _Cookie:
    def __init__(self, name, value, domain="accounts.x.ai"):
        self.name = name
        self.value = value
        self.domain = domain


class _CookieSession:
    def __init__(self, cookies):
        self.cookies = type("Cookies", (), {"jar": cookies})()


class GrokXaiOAuthContractTests(unittest.TestCase):
    def test_signup_url_matches_current_grok_return_contract(self):
        self.assertIn("redirect=grok-com", browser_signup.SIGNUP_URL)
        self.assertIn("return_to=%2F", browser_signup.SIGNUP_URL)

    def test_grok_registration_switches_shared_batch_but_keeps_worker_sticky(self):
        with patch.object(core_engine.cfg, "REG_PROVIDER", "grok", create=True), \
                patch.object(core_engine.cfg, "_clash_enable", True, create=True), \
                patch.object(core_engine.cfg, "_clash_pool_mode", False, create=True), \
                patch.object(core_engine.cfg, "is_raw_proxy_pool_enabled", return_value=False):
            self.assertTrue(core_engine._should_switch_shared_batch())
            self.assertFalse(core_engine._should_switch_before_registration(False))
            self.assertEqual(4, core_engine._registration_batch_size(4))
        with patch.object(core_engine.cfg, "REG_PROVIDER", "openai", create=True):
            self.assertTrue(core_engine._should_switch_before_registration(False))
            self.assertEqual(4, core_engine._registration_batch_size(4))
        self.assertFalse(core_engine._should_switch_before_registration(True))

    def test_grok_shared_mode_switches_once_for_concurrent_batch(self):
        args = SimpleNamespace(proxy="http://127.0.0.1:7890", once=True)
        stop_event = Mock()
        stop_event.is_set.return_value = False
        stop_event.wait.return_value = False

        with patch.object(core_engine.cfg, "REG_PROVIDER", "grok", create=True), \
                patch.object(core_engine.cfg, "_clash_enable", True, create=True), \
                patch.object(core_engine.cfg, "_clash_pool_mode", False, create=True), \
                patch.object(core_engine.cfg, "POOL_EXHAUSTED", False, create=True), \
                patch.object(core_engine.cfg, "ENABLE_MULTI_THREAD_REG", True, create=True), \
                patch.object(core_engine.cfg, "REG_THREADS", 3, create=True), \
                patch.object(core_engine.cfg, "NORMAL_TARGET_COUNT", 0, create=True), \
                patch.object(core_engine.cfg, "NORMAL_SLEEP_MIN", 1, create=True), \
                patch.object(core_engine.cfg, "NORMAL_SLEEP_MAX", 1, create=True), \
                patch.object(core_engine.cfg, "EMAIL_API_MODE", "", create=True), \
                patch.object(core_engine.cfg, "is_raw_proxy_pool_enabled", return_value=False), \
                patch.object(core_engine, "smart_switch_node", return_value=True) as switch_node, \
                patch.object(core_engine, "run_and_refresh", return_value="success") as run_registration, \
                patch("builtins.print"):
            core_engine.normal_main_loop(args, stop_event)

        switch_node.assert_called_once_with(args.proxy)
        self.assertEqual(3, run_registration.call_count)
        for call in run_registration.call_args_list:
            self.assertEqual(args.proxy, call.args[0])
            self.assertIs(args, call.args[1])
            self.assertFalse(call.args[2])
            self.assertTrue(call.kwargs["skip_switch"])

    def test_default_scope_matches_current_official_cli_contract(self):
        self.assertEqual(
            "openid profile email offline_access grok-cli:access api:access "
            "conversations:read conversations:write workspaces:read workspaces:write",
            sso_to_auth_json.OIDC_SCOPES,
        )

    def test_device_code_request_uses_configured_scope(self):
        session = _CaptureSession()

        with patch.object(sso_to_auth_json, "_wait_device_flow_slot"):
            result = sso_to_auth_json.request_device_code(session=session, proxy_kw={})

        self.assertEqual("device-1", result["device_code"])
        self.assertEqual(sso_to_auth_json.OIDC_SCOPES, session.data["scope"])
        self.assertEqual("grok-build", session.data["referrer"])
        self.assertEqual("0.2.111", session.headers["x-grok-client-version"])
        self.assertEqual("headless", session.headers["x-grok-client-surface"])
        self.assertEqual("*/*", session.headers["Accept"])
        self.assertEqual("gzip, br, deflate", session.headers["Accept-Encoding"])
        self.assertEqual(sso_to_auth_json.GROK_TOKEN_UA, session.headers["User-Agent"])
        self.assertNotIn("referrer", session.headers)
        self.assertEqual(
            "0.2.111",
            xai_oauth.CLIPROXYAPI_GROK_HEADERS["x-grok-client-version"],
        )

    def test_token_poll_uses_same_official_cli_headers(self):
        session = _CaptureSession()

        with patch.object(sso_to_auth_json.time, "sleep") as sleep:
            result = sso_to_auth_json.poll_token(
                "device-1",
                interval=5,
                session=session,
                proxy_kw={},
                timeout=10,
                immediate=False,
            )

        self.assertEqual("device-1", result["device_code"])
        sleep.assert_called_once_with(1.5)
        self.assertTrue(session.url.endswith("/oauth2/token"))
        self.assertEqual("headless", session.headers["x-grok-client-surface"])
        self.assertEqual(sso_to_auth_json.GROK_TOKEN_UA, session.headers["User-Agent"])

    def test_refreshed_sso_cookie_ignores_original_and_prefers_rotated_rw(self):
        session = _CookieSession([
            _Cookie("sso", "original", ".x.ai"),
            _Cookie("sso", "rotated-read", "accounts.x.ai"),
            _Cookie("sso-rw", "rotated-write", "accounts.x.ai"),
        ])

        refreshed = sso_to_auth_json._refreshed_sso_cookie(session, "original")

        self.assertEqual("rotated-write", refreshed)

    def test_refreshed_sso_cookie_returns_empty_when_server_did_not_rotate(self):
        session = _CookieSession([
            _Cookie("sso", "original", ".x.ai"),
            _Cookie("sso-rw", "original", "accounts.x.ai"),
        ])

        refreshed = sso_to_auth_json._refreshed_sso_cookie(session, "original")

        self.assertEqual("", refreshed)

    def test_approval_prefers_official_overlay_and_preserves_form_principal(self):
        overlay = {
            "user_code": "CODE-1",
            "action": "allow",
            "principal_type": "User",
            "principal_id": "principal-from-form",
            "referrer": "grok-build",
            "plan": "generic",
        }

        variants = sso_to_auth_json._device_approval_form_variants("CODE-1", "", overlay)

        self.assertEqual("overlay", variants[0][0])
        self.assertEqual("principal-from-form", variants[0][1]["principal_id"])
        self.assertEqual("referrer", variants[1][0])
        self.assertNotIn("principal_id", variants[1][1])

    def test_post_signup_settle_rejects_session_still_on_signup_page(self):
        page = _SignupPage()

        with patch.object(browser_signup.time, "sleep"):
            settled = browser_signup._settle_post_signup_page(page, rounds=1)

        self.assertFalse(settled)
        self.assertEqual([], page.goto_calls)

    def test_post_signup_settle_waits_even_after_natural_grok_redirect(self):
        page = _SignupPage(url=browser_signup.POST_SIGNUP_URL)

        with patch.object(browser_signup.time, "sleep") as sleep:
            settled = browser_signup._settle_post_signup_page(page, rounds=1)

        self.assertTrue(settled)
        self.assertEqual([], page.goto_calls)
        sleep.assert_called_once_with(12.0)


if __name__ == "__main__":
    unittest.main()
