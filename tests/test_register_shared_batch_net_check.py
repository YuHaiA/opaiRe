import sys
import types
import unittest
from unittest.mock import patch


class _DummySession:
    def __init__(self, *args, **kwargs):
        self.headers = {}
        self.timeout = None
        self.get_called = False

    def get(self, *args, **kwargs):
        self.get_called = True
        raise AssertionError("shared batch mode should skip proxy net check")

    def close(self):
        return None


_auth_core_stub = types.SimpleNamespace(
    generate_payload=lambda *args, **kwargs: None,
    init_auth=lambda *args, **kwargs: (None, None),
    image2api_data=None,
    sys_node_allocate=lambda *args, **kwargs: (False, "", "", ""),
    sys_node_release=lambda *args, **kwargs: None,
    code_pool={},
)

if "utils.auth_core" not in sys.modules:
    sys.modules["utils.auth_core"] = _auth_core_stub

from utils.auth_pipeline import register as register_module


class RegisterSharedBatchNetCheckTests(unittest.TestCase):
    def test_shared_batch_flag_skips_duplicate_proxy_net_check(self):
        dummy_session = _DummySession()

        with patch.object(register_module.requests, "Session", return_value=dummy_session), \
                patch.object(register_module, "_skip_net_check", return_value=False), \
                patch.object(register_module, "get_email_and_token", return_value=(None, None)):
            result = register_module.run(
                "http://127.0.0.1:7890",
                run_ctx={"skip_proxy_net_check": True},
            )

        self.assertEqual((None, None), result)
        self.assertFalse(dummy_session.get_called)


if __name__ == "__main__":
    unittest.main()
