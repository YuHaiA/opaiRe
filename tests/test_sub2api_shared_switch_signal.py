import sys
import types
import unittest

_stubs = {
    "yaml": types.SimpleNamespace(
        safe_load=lambda *a, **kw: {},
        safe_dump=lambda *a, **kw: "",
    ),
    "curl_cffi": types.SimpleNamespace(
        requests=types.SimpleNamespace(),
        CurlMime=object,
    ),
    "utils.email_providers.mail_service": types.SimpleNamespace(
        mask_email=lambda value: value,
    ),
    "utils.auth_pipeline.register": types.SimpleNamespace(
        run=lambda *args, **kwargs: None,
    ),
    "utils.auth_pipeline.oauth": types.SimpleNamespace(
        refresh_oauth_token=lambda *args, **kwargs: (False, {}),
    ),
    "utils.proxy_manager": types.SimpleNamespace(
        smart_switch_node=lambda *args, **kwargs: True,
        reload_proxy_config=lambda *args, **kwargs: None,
        get_failure_bucket_id=lambda *args, **kwargs: "bucket",
        evict_current_proxy_or_node=lambda *args, **kwargs: (True, "ok"),
    ),
    "utils.integrations.sub2api_client": types.SimpleNamespace(
        Sub2APIClient=object,
    ),
    "utils.integrations.tg_notifier": types.SimpleNamespace(
        send_tg_msg_sync=lambda *args, **kwargs: None,
    ),
    "utils.email_providers.postman_center": types.SimpleNamespace(
        global_postman_fleet=types.SimpleNamespace(clear_fleet=lambda: None),
    ),
}
for mod_name, stub in _stubs.items():
    if mod_name not in sys.modules:
        sys.modules[mod_name] = stub

from utils.core_engine import _consume_sub2api_shared_switch_signal


class Sub2ApiSharedSwitchSignalTests(unittest.TestCase):
    def test_shared_global_mode_turns_switch_into_next_batch_refresh(self):
        refresh_requested, keep_force_switch = _consume_sub2api_shared_switch_signal(True, True)
        self.assertTrue(refresh_requested)
        self.assertFalse(keep_force_switch)

    def test_non_shared_mode_preserves_force_switch(self):
        refresh_requested, keep_force_switch = _consume_sub2api_shared_switch_signal(False, True)
        self.assertFalse(refresh_requested)
        self.assertTrue(keep_force_switch)

    def test_no_signal_keeps_both_flags_false(self):
        refresh_requested, keep_force_switch = _consume_sub2api_shared_switch_signal(True, False)
        self.assertFalse(refresh_requested)
        self.assertFalse(keep_force_switch)


if __name__ == "__main__":
    unittest.main()
