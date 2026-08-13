import unittest
from contextlib import ExitStack
from unittest.mock import patch

from utils import config as cfg
from utils.email_providers import mail_service


class MailDomainBatchFallbackTests(unittest.TestCase):
    def _config(self, runtime_control: bool):
        stack = ExitStack()
        stack.enter_context(patch.object(cfg, "EMAIL_API_MODE", "openai_cpa"))
        stack.enter_context(patch.object(cfg, "MAIL_DOMAINS", "first.example,second.example"))
        stack.enter_context(patch.object(cfg, "DISABLED_MAIL_DOMAINS", []))
        stack.enter_context(patch.object(cfg, "ENABLE_SUB_DOMAINS", False))
        stack.enter_context(patch.object(cfg, "ENABLE_MAIL_DOMAIN_RUNTIME_CONTROL", runtime_control))
        stack.enter_context(patch.object(cfg, "OPENAI_CPA_WEBHOOK_SECRET", "configured"))
        stack.enter_context(patch.object(cfg, "OPENAI_CPA_BRIDGE_ENABLED", False))
        stack.enter_context(patch.object(cfg, "OPENAI_CPA_LOCAL_WEBHOOK", False))
        stack.enter_context(patch.object(mail_service, "_get_ai_data_package", return_value=("worker", False)))
        stack.enter_context(patch.object(mail_service, "pick_available_main_domain", return_value="first.example"))
        return stack

    def test_batch_worker_falls_back_to_domain_pool_when_runtime_control_is_disabled(self):
        with self._config(runtime_control=False):
            email, token = mail_service.get_email_and_token(
                None,
                assigned_domain=None,
                batch_id=123,
                worker_index=0,
            )

        self.assertEqual("worker@first.example", email)
        self.assertEqual("", token)

    def test_batch_worker_does_not_bypass_failed_preallocation_when_runtime_control_is_enabled(self):
        with self._config(runtime_control=True):
            email, token = mail_service.get_email_and_token(
                None,
                assigned_domain=None,
                batch_id=123,
                worker_index=0,
            )

        self.assertIsNone(email)
        self.assertIsNone(token)


if __name__ == "__main__":
    unittest.main()
