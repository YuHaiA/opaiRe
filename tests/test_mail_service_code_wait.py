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
        self.assertEqual(15, attempts)

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


if __name__ == "__main__":
    unittest.main()
