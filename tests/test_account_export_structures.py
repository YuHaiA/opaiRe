import asyncio
import unittest
from unittest.mock import MagicMock, patch

import routers.account_routes as account_routes
from utils.integrations.account_export import (
    GROK_CLI_BASE_URL,
    build_cpa_export_record,
    build_cpa_export_records,
)
from utils.integrations.sub2api_client import Sub2APIClient, build_sub2api_export_bundle


SETTINGS = {
    "concurrency": 6,
    "load_factor": 8,
    "priority": 2,
    "rate_multiplier": 1.25,
    "group_ids": [3],
    "enable_ws": True,
}


class AccountExportStructureTests(unittest.TestCase):
    def test_cpa_export_uses_provider_specific_auth_file_markers(self):
        openai = {
            "email": "openai@example.com",
            "type": "oauth",
            "access_token": "openai-access",
            "refresh_token": "openai-refresh",
        }
        grok = {
            "email": "grok@example.com",
            "status": "grok_oauth",
            "access_token": "grok-access",
            "refresh_token": "grok-refresh",
        }

        openai_record = build_cpa_export_record(openai)
        grok_record = build_cpa_export_record(grok)

        self.assertEqual("codex", openai_record["type"])
        self.assertEqual("openai", openai_record["provider"])
        self.assertEqual("xai", grok_record["type"])
        self.assertEqual("grok", grok_record["provider"])
        self.assertEqual(GROK_CLI_BASE_URL, grok_record["base_url"])
        self.assertEqual("xai-grok-cli", grok_record["headers"]["X-XAI-Token-Auth"])
        self.assertEqual("oauth", openai["type"])
        self.assertNotIn("provider", grok)

    def test_cpa_export_skips_non_relay_accounts(self):
        records, skipped = build_cpa_export_records(
            [
                {"email": "half@example.com", "status": "仅注册成功"},
                {"email": "image@example.com", "status": "image2api", "access_token": "image-token"},
            ]
        )

        self.assertEqual([], records)
        self.assertEqual(["half@example.com", "image@example.com"], skipped)

    def test_sub2api_export_bundle_uses_openai_and_grok_models(self):
        bundle = build_sub2api_export_bundle(
            [
                {
                    "email": "openai@example.com",
                    "type": "codex",
                    "access_token": "openai-access",
                    "refresh_token": "openai-refresh",
                    "account_id": "chatgpt-account",
                    "workspace_id": "workspace",
                },
                {
                    "email": "grok@example.com",
                    "provider": "grok",
                    "access_token": "grok-access",
                    "refresh_token": "grok-refresh",
                    "id_token": "grok-id",
                    "expires_at": 1_700_000_000,
                },
            ],
            SETTINGS,
        )

        self.assertEqual("sub2api-data", bundle["type"])
        self.assertEqual(1, bundle["version"])
        self.assertEqual([], bundle["proxies"])

        openai_account, grok_account = bundle["accounts"]
        self.assertEqual("openai", openai_account["platform"])
        self.assertEqual("oauth", openai_account["type"])
        self.assertEqual("chatgpt-account", openai_account["credentials"]["chatgpt_account_id"])
        self.assertTrue(openai_account["extra"]["openai_oauth_responses_websockets_v2_enabled"])

        self.assertEqual("grok", grok_account["platform"])
        self.assertEqual("oauth", grok_account["type"])
        self.assertEqual("grok-access", grok_account["credentials"]["access_token"])
        self.assertEqual("grok-refresh", grok_account["credentials"]["refresh_token"])
        self.assertEqual("2023-11-14T22:13:20Z", grok_account["credentials"]["expires_at"])
        self.assertEqual(GROK_CLI_BASE_URL, grok_account["credentials"]["base_url"])
        self.assertEqual("xai-grok-cli", grok_account["credentials"]["headers"]["X-XAI-Token-Auth"])
        self.assertNotIn("chatgpt_account_id", grok_account["credentials"])
        self.assertNotIn("openai_oauth_responses_websockets_v2_enabled", grok_account["extra"])

    def test_sub2api_grok_export_rejects_sso_only_record(self):
        with self.assertRaisesRegex(ValueError, "缺少 OAuth 凭证"):
            build_sub2api_export_bundle(
                [{"email": "grok@example.com", "provider": "grok", "sso": "sso-value"}],
                SETTINGS,
            )

    def test_existing_export_routes_return_dedicated_structures(self):
        grok = {
            "email": "grok@example.com",
            "provider": "grok",
            "access_token": "grok-access",
            "refresh_token": "grok-refresh",
        }
        request = account_routes.ExportReq(emails=["grok@example.com"])

        with patch.object(account_routes.db_manager, "get_tokens_by_emails", return_value=[grok]):
            cpa_response = asyncio.run(account_routes.export_selected_accounts(request, token="test"))

        with patch.object(account_routes.db_manager, "get_tokens_by_emails", return_value=[grok]), \
                patch.object(account_routes, "get_sub2api_push_settings", return_value=SETTINGS), \
                patch("utils.integrations.sub2api_client.cfg.get_next_sub2api_proxy_url", return_value=""):
            sub2_response = asyncio.run(account_routes.export_sub2api_accounts(request, token="test"))

        self.assertEqual("xai", cpa_response["data"][0]["type"])
        self.assertEqual("grok", cpa_response["data"][0]["provider"])
        self.assertEqual("sub2api-data", sub2_response["data"]["type"])
        self.assertEqual("grok", sub2_response["data"]["accounts"][0]["platform"])

    def test_grok_push_falls_back_to_generic_sub2api_data_import_on_404(self):
        client = Sub2APIClient.__new__(Sub2APIClient)
        client._get_push_settings = MagicMock(return_value=SETTINGS)
        client._import_grok_sso = MagicMock(return_value=(False, "Grok 推送失败 | HTTP 404 | 404 page not found"))
        client._import_account = MagicMock(return_value=(True, "Sub2API account import succeeded"))
        client._force_bind_groups = MagicMock()

        with patch("utils.integrations.sub2api_client.cfg.get_next_sub2api_proxy_url", return_value=""):
            ok, message = client.add_account(
                {
                    "email": "grok@example.com",
                    "provider": "grok",
                    "access_token": "grok-access",
                    "refresh_token": "grok-refresh",
                }
            )

        self.assertTrue(ok)
        self.assertIn("OAuth 数据导入成功", message)
        client._import_account.assert_called_once()
        client._import_grok_sso.assert_not_called()

    def test_sso_only_grok_record_still_uses_special_push_when_provider_is_grok(self):
        client = Sub2APIClient.__new__(Sub2APIClient)
        client._get_push_settings = MagicMock(return_value=SETTINGS)
        client._import_grok_sso = MagicMock(return_value=(True, "special route ok"))
        client._import_account = MagicMock()
        client._force_bind_groups = MagicMock()

        with patch("utils.integrations.sub2api_client.cfg.get_next_sub2api_proxy_url", return_value=""), \
                patch("utils.integrations.sub2api_client.cfg.REG_PROVIDER", "grok"):
            ok, message = client.add_account(
                {"email": "grok@example.com", "sso": "sso-value"}
            )

        self.assertTrue(ok)
        self.assertEqual("special route ok", message)
        client._import_grok_sso.assert_called_once()
        client._import_account.assert_not_called()


if __name__ == "__main__":
    unittest.main()
