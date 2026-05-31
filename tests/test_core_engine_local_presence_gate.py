import sys
import types
import unittest
from types import SimpleNamespace
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


from utils import core_engine


class CoreEngineLocalPresenceGateTests(unittest.TestCase):
    def test_cpa_dead_remote_without_local_account_is_skipped(self):
        item = {"name": "orphan@example.com.json", "disabled": False}
        args = SimpleNamespace(proxy=None)

        with patch.object(core_engine, "test_cliproxy_auth_file", return_value=(False, "HTTP 401")), \
                patch.object(core_engine.db_manager, "check_account_exists", return_value=False), \
                patch.object(core_engine.db_manager, "mark_account_revive_failed") as mark_failed, \
                patch.object(core_engine, "_handle_dead_account") as handle_dead, \
                patch.object(core_engine, "refresh_oauth_token") as refresh_token:
            result = core_engine.process_account_worker(1, 1, item, args)

        self.assertFalse(result)
        mark_failed.assert_not_called()
        handle_dead.assert_not_called()
        refresh_token.assert_not_called()

    def test_sub2api_dead_remote_without_local_account_is_skipped(self):
        item = {
            "name": "orphan-sub2api-name",
            "id": "acc-1",
            "platform": "openai",
            "credentials": {"plan_type": "free", "refresh_token": "rt"},
        }
        client = SimpleNamespace(test_account=lambda account_id: ("dead", "HTTP 401"))
        args = SimpleNamespace(proxy=None)

        with patch.object(core_engine.db_manager, "check_account_exists_by_truncated_name", return_value=False), \
                patch.object(core_engine.db_manager, "mark_account_revive_failed_by_truncated_name") as mark_failed, \
                patch.object(core_engine, "_handle_sub2api_dead_account") as handle_dead, \
                patch.object(core_engine, "refresh_oauth_token") as refresh_token:
            result = core_engine.process_sub2api_worker(1, 1, item, client, args)

        self.assertFalse(result)
        mark_failed.assert_not_called()
        handle_dead.assert_not_called()
        refresh_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
