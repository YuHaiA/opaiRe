import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import routers.account_routes as account_routes
from utils import core_engine
from utils.integrations.cpa_diagnostics import classify_failure, should_preserve_enabled_state


class _Response:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Mime:
    last_part = None

    def addpart(self, **kwargs):
        type(self).last_part = kwargs


class CPAXAIDiagnosticsTests(unittest.TestCase):
    def test_failure_classification_separates_quota_access_and_transport(self):
        self.assertEqual("quota", classify_failure(402, {"error": {"message": "spending-limit"}}))
        self.assertEqual("access_denied", classify_failure(403, {"error": {"message": "Access denied"}}))
        self.assertEqual("credential", classify_failure(401, {"error": {"message": "unauthorized"}}))
        self.assertEqual("transport", classify_failure(0, exception=TimeoutError()))
        self.assertTrue(should_preserve_enabled_state("access_denied"))
        self.assertTrue(should_preserve_enabled_state("transport"))
        self.assertFalse(should_preserve_enabled_state("credential"))

    def test_cpa_api_call_records_real_xai_403_without_calling_it_credential_failure(self):
        payload = {
            "status_code": 403,
            "body": json.dumps({"error": {"message": "Access denied"}}),
        }
        item = {"type": "xai", "provider": "grok", "auth_index": "xai-test"}

        with patch.object(core_engine.requests, "post", return_value=_Response(200, payload)):
            ok, message = core_engine.test_cliproxy_auth_file(item, "http://cpa.local", "key")

        self.assertFalse(ok)
        self.assertEqual(403, item["_cpa_status_code"])
        self.assertEqual("access_denied", item["_cpa_failure_class"])
        self.assertIn("上游拒绝", message)
        self.assertNotIn("凭证失效", message)

    def test_xai_403_worker_preserves_local_and_remote_enabled_state(self):
        item = {
            "name": "grok@example.com.json",
            "type": "xai",
            "provider": "grok",
            "disabled": False,
            "_cpa_status_code": 403,
            "_cpa_failure_class": "access_denied",
        }
        args = SimpleNamespace(check_stop=lambda: False)

        with patch.object(core_engine, "test_cliproxy_auth_file", return_value=(False, "上游拒绝 HTTP 403")), \
                patch.object(core_engine.db_manager, "check_account_exists", return_value=True), \
                patch.object(core_engine.db_manager, "update_account_status") as update_local, \
                patch.object(core_engine, "set_cpa_auth_file_status") as update_remote:
            ok = core_engine.process_account_worker(1, 1, item, args)

        self.assertFalse(ok)
        update_local.assert_not_called()
        update_remote.assert_not_called()

    def test_upload_always_uses_dedicated_grok_cpa_structure(self):
        token_data = {
            "email": "grok@example.com",
            "status": "grok_oauth",
            "access_token": "access",
            "refresh_token": "refresh",
        }

        with patch.object(core_engine, "CurlMime", _Mime), \
                patch.object(core_engine.requests, "post", return_value=_Response(200, {"ok": True})):
            ok, message = core_engine.upload_to_cpa_integrated(token_data, "http://cpa.local", "key")

        self.assertTrue(ok, message)
        uploaded = json.loads(_Mime.last_part["data"].decode("utf-8"))
        self.assertEqual("xai", uploaded["type"])
        self.assertEqual("grok", uploaded["provider"])
        self.assertEqual("xai-grok-cli", uploaded["headers"]["X-XAI-Token-Auth"])
        self.assertNotIn("provider", token_data)

    def test_cloud_manual_check_does_not_disable_xai_403(self):
        item = {
            "name": "grok.json",
            "auth_index": "xai-test",
            "type": "xai",
            "provider": "grok",
            "disabled": False,
        }

        def fake_check(target, *_args):
            target["_cpa_status_code"] = 403
            target["_cpa_failure_class"] = "access_denied"
            return False, "上游拒绝 HTTP 403"

        request = account_routes.CloudActionReq(
            accounts=[account_routes.CloudAccountItem(id="grok.json", type="cpa")],
            action="check",
        )
        listing = _Response(200, {"files": [item]})

        with patch.object(account_routes.cfg, "CPA_API_URL", "http://cpa.local"), \
                patch.object(account_routes.cfg, "CPA_API_TOKEN", "key"), \
                patch("curl_cffi.requests.get", return_value=listing), \
                patch.object(core_engine, "test_cliproxy_auth_file", side_effect=fake_check), \
                patch.object(core_engine, "set_cpa_auth_file_status") as set_status:
            response = account_routes.process_cloud_action(request, token="test")

        self.assertEqual("warning", response["status"])
        self.assertIn("保留启用: 1", response["message"])
        self.assertTrue(response["updated_details"]["grok.json"]["preserved_enabled"])
        set_status.assert_not_called()


if __name__ == "__main__":
    unittest.main()
