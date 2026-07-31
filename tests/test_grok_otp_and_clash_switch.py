import unittest
from unittest.mock import patch

from utils.clash_group_utils import (
    resolve_group_name,
    resolve_switchable_group_name,
    is_switchable_group,
)
from utils.grok_auth.otp import extract_xai_code
from utils.email_bridge.client import inject_code_pool
from utils.email_providers import mail_service


class OtpExtractTests(unittest.TestCase):
    def test_prefers_subject_dash_code_over_domain_label(self):
        raw = (
            "Received: by cloudflare for <user@uomzx73k.nffd2w.kdns.fr>\r\n"
            "To: user@uomzx73k.nffd2w.kdns.fr\r\n"
            "From: SpaceXAI <noreply@x.ai>\r\n"
            "Subject: SpaceXAI confirmation code: 7HM-6DX\r\n\r\n"
            "<html>Your code is 7HM-6DX</html>"
        )
        self.assertEqual("7HM-6DX", extract_xai_code(raw))

    def test_does_not_return_domain_fragment_as_code(self):
        raw = "To: abc@uomzx73k.nffd2w.kdns.fr\r\nFrom: noreply@x.ai\r\n\r\nhello"
        self.assertIsNone(extract_xai_code(raw))


class ClashSwitchableGroupTests(unittest.TestCase):
    def test_loadbalance_falls_back_to_proxy_selector(self):
        proxy_map = {
            "AUTO-BALANCE": {"type": "LoadBalance", "all": ["n1", "n2"], "now": None},
            "PROXY": {"type": "Selector", "all": ["n1", "n2", "AUTO-URLTEST"], "now": "n1"},
            "AUTO-URLTEST": {"type": "URLTest", "all": ["n1", "n2"], "now": "n1"},
            "n1": {"type": "Vless"},
            "n2": {"type": "Vless"},
        }
        self.assertEqual("AUTO-BALANCE", resolve_group_name(proxy_map, "AUTO-BALANCE"))
        self.assertFalse(is_switchable_group(proxy_map, "AUTO-BALANCE"))
        self.assertEqual("PROXY", resolve_switchable_group_name(proxy_map, "AUTO-BALANCE"))


class CodePoolInjectTests(unittest.TestCase):
    def test_consume_uses_injected_code_not_domain_in_raw(self):
        email = "user@uomzx73k.nffd2w.kdns.fr"
        raw = (
            f"To: {email}\r\nSubject: SpaceXAI confirmation code: 7HM-6DX\r\n\r\n"
            "body nffd2w should not win"
        )
        with patch("utils.auth_core.code_pool", {}) as pool:
            self.assertTrue(inject_code_pool(email, "7HM-6DX", raw))
            with patch.object(mail_service, "_is_grok_registration_mode", return_value=True):
                code = mail_service._consume_code_pool_code(email, allow_relay_fallback=False)
            self.assertEqual("7HM-6DX", code)
            self.assertNotIn(email, pool)


if __name__ == "__main__":
    unittest.main()
