import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.modules.setdefault("camoufox", types.SimpleNamespace(Camoufox=object))

from utils.grok_auth import register


class GrokStatusDiscardTests(unittest.TestCase):
    def test_status_probe_failure_does_not_continue_to_oauth(self):
        context = {}
        oauth = Mock()

        with patch.object(register, "ensure_camoufox", return_value=(True, "")), \
                patch.object(register, "get_email_and_token", return_value=("test@example.com", "mail-token")), \
                patch.object(register, "set_last_email"), \
                patch.object(register, "signup_with_camoufox", return_value={
                    "ok": True,
                    "sso": "sso-secret",
                    "cookies": {"sso": "sso-secret"},
                }), \
                patch.object(register, "inspect_sso_account_state", return_value={
                    "found": False,
                    "error": "TLS connect error",
                }), \
                patch.object(register, "complete_build_oauth", oauth):
            result = register.run(run_ctx=context)

        self.assertEqual((None, None), result)
        self.assertTrue(context["discarded"])
        self.assertEqual("status_check_failed", context["discard_reason"])
        oauth.assert_not_called()


if __name__ == "__main__":
    unittest.main()
