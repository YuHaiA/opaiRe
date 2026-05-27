import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.account_routes as account_routes


async def _fake_verify_token(authorization: str = None):
    return "test-token"


class CloudAccountsRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(account_routes.router)
        self.app.dependency_overrides[account_routes.verify_token] = _fake_verify_token
        self.client = TestClient(self.app)

    def tearDown(self):
        self.app.dependency_overrides.clear()

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
                headers={"Authorization": "Bearer test-token"},
            )

        self.assertEqual(200, response.status_code)
        body = response.json()
        self.assertEqual("success", body["status"])
        self.assertEqual(1, body["total"])
        self.assertEqual(1, len(body["data"]))
        sub_client.get_account_usage.assert_not_called()


if __name__ == "__main__":
    unittest.main()
