import unittest
from unittest.mock import patch

from utils.email_providers import mail_service


class MailServiceCodeWaitTests(unittest.TestCase):
    def test_non_code_pool_mode_keeps_default_attempts(self):
        attempts = mail_service._resolve_code_wait_attempts(4, "generator_email")
        self.assertEqual(4, attempts)

    def test_code_pool_mode_scales_attempts_for_multithread(self):
        with patch.object(mail_service.cfg, "ENABLE_MULTI_THREAD_REG", True), \
                patch.object(mail_service.cfg, "REG_THREADS", 30):
            attempts = mail_service._resolve_code_wait_attempts(4, "openai_cpa")
        self.assertEqual(10, attempts)

    def test_openai_cpa_batch_id_without_assigned_domain_still_falls_back_to_domain_pick(self):
        with patch.object(mail_service.cfg, "EMAIL_API_MODE", "openai_cpa"), \
                patch.object(mail_service.cfg, "MAIL_DOMAINS", "example.com"), \
                patch.object(mail_service.cfg, "ENABLE_SUB_DOMAINS", False), \
                patch.object(mail_service.cfg, "OPENAI_CPA_WEBHOOK_SECRET", "demo-secret"):
            email, token = mail_service.get_email_and_token(
                None,
                assigned_domain=None,
                batch_id=123,
                worker_index=0,
            )

        self.assertTrue(email.endswith("@example.com"))
        self.assertEqual("", token)

    def test_cloudflare_temp_email_falls_back_to_admin_address_lookup(self):
        class FakeResponse:
            def __init__(self, status_code, results):
                self.status_code = status_code
                self.text = "{}"
                self._results = results

            def json(self):
                return {"results": self._results}

        mailbox_response = FakeResponse(200, [])
        admin_response = FakeResponse(200, [{"id": "m1", "subject": "code"}])

        with patch.object(mail_service.cfg, "ADMIN_AUTH", "admin-secret"), \
                patch.object(mail_service, "_ssl_verify", return_value=True), \
                patch.object(mail_service.requests, "get", side_effect=[mailbox_response, admin_response]) as mock_get:
            response, results = mail_service._fetch_cloudflare_temp_email_results(
                "https://worker.example",
                "user@example.com",
                "mailbox-jwt",
                None,
            )

        self.assertIs(response, admin_response)
        self.assertEqual([{"id": "m1", "subject": "code"}], results)
        self.assertEqual(2, mock_get.call_count)


if __name__ == "__main__":
    unittest.main()
