import sys
import types
import unittest
from unittest.mock import MagicMock, patch


def _stub_global_state():
    module = types.SimpleNamespace()
    module.VALID_TOKENS = set()

    async def verify_token(authorization: str = None):
        return "test-token"

    module.verify_token = verify_token
    module.log_history = []
    module.engine = types.SimpleNamespace(is_running=lambda: False, stop=lambda: None)
    module.append_log = lambda msg: None
    return module


core_engine_stub = types.SimpleNamespace(
    _normalize_cpa_auth_files_url=lambda url: url,
    _shared_global_switch_force_requested=lambda previous_batch_force_switch: bool(previous_batch_force_switch),
)
auth_core_stub = types.SimpleNamespace(
    email_jwt="",
    generate_payload=lambda *args, **kwargs: None,
    init_auth=lambda *args, **kwargs: (None, None),
    image2api_data=None,
    sys_node_allocate=lambda *args, **kwargs: (False, "", "", ""),
    sys_node_release=lambda *args, **kwargs: None,
    code_pool={},
)
sub2api_client_stub = types.SimpleNamespace(
    Sub2APIClient=object,
    build_sub2api_export_bundle=lambda *args, **kwargs: {},
    get_sub2api_push_settings=lambda: {},
)
image2api_client_stub = types.SimpleNamespace(Image2APIClient=object)

for module_name, stub in {
    "global_state": _stub_global_state(),
    "utils.core_engine": core_engine_stub,
    "utils.auth_core": auth_core_stub,
    "utils.integrations.sub2api_client": sub2api_client_stub,
    "utils.integrations.image2api_client": image2api_client_stub,
}.items():
    sys.modules.setdefault(module_name, stub)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.account_routes as account_routes
from global_state import VALID_TOKENS


class CloudAccountsRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(account_routes.router)
        self.client = TestClient(self.app)
        self.token = "test-token"
        VALID_TOKENS.add(self.token)

    def tearDown(self):
        VALID_TOKENS.discard(self.token)

    def test_default_cloud_accounts_does_not_fetch_sub2api_usage(self):
        sub_client = MagicMock()
        sub_client.get_all_accounts.return_value = (
            True,
            [
                {
                    "id": "acc-1",
                    "name": "demo@example.com",
                    "status": "active",
                    "updated_at": "2026-05-27T00:00:00.000Z",
                    "credentials": {"plan_type": "free"},
                    "extra": {"codex_5h_used_percent": 12, "codex_7d_used_percent": 3},
                }
            ],
        )

        with patch.object(account_routes, "Sub2APIClient", return_value=sub_client), \
                patch.object(account_routes.cfg, "SUB2API_URL", "https://sub2api.example"), \
                patch.object(account_routes.cfg, "SUB2API_KEY", "demo-key"):
            response = self.client.get(
                "/api/cloud/accounts?types=sub2api",
                headers={"Authorization": f"Bearer {self.token}"},
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("success", body["status"])
        self.assertEqual(1, body["total"])
        self.assertEqual(1, len(body["data"]))
        sub_client.get_account_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
