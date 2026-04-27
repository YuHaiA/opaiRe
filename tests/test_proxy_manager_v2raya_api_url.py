import importlib
import sys
import types
import unittest
from unittest.mock import mock_open, patch


_yaml_module = types.SimpleNamespace(safe_load=lambda *args, **kwargs: {})
_requests_module = types.SimpleNamespace(
    Session=object,
    get=None,
    put=None,
    post=None,
    exceptions=types.SimpleNamespace(ConnectionError=Exception, Timeout=TimeoutError),
)


class ProxyManagerV2RayAApiUrlTests(unittest.TestCase):
    module_name = "utils.proxy_manager"

    def setUp(self):
        self.original_modules = {}
        for module_name in ["yaml", "requests", self.module_name]:
            if module_name in sys.modules:
                self.original_modules[module_name] = sys.modules[module_name]
            sys.modules.pop(module_name, None)

        sys.modules["yaml"] = _yaml_module
        sys.modules["requests"] = _requests_module
        self.proxy_manager = importlib.import_module(self.module_name)

    def tearDown(self):
        for module_name in ["yaml", "requests", self.module_name]:
            sys.modules.pop(module_name, None)
        sys.modules.update(self.original_modules)

    def test_reload_proxy_config_prefers_v2raya_api_url_over_legacy_url(self):
        config = {
            "clash_proxy_pool": {
                "enable": True,
                "client_type": "v2raya",
                "v2raya_runtime_mode": "server",
                "v2raya_url": "https://panel.example.com/v2raya",
                "v2raya_api_url": "http://127.0.0.1:2017/api",
            }
        }

        with patch.object(self.proxy_manager.os.path, "exists", return_value=True), patch(
            "builtins.open", mock_open(read_data="ignored")
        ), patch.object(self.proxy_manager.yaml, "safe_load", return_value=config):
            self.proxy_manager.reload_proxy_config()

        self.assertEqual("http://127.0.0.1:2017", self.proxy_manager.V2RAYA_PANEL_URL)

    def test_reload_proxy_config_prefers_local_api_url_in_local_mode(self):
        config = {
            "clash_proxy_pool": {
                "enable": True,
                "client_type": "v2raya",
                "v2raya_runtime_mode": "local",
                "v2raya_url": "https://panel.example.com/v2raya",
                "v2raya_api_url": "http://10.0.0.9:2017",
                "v2raya_local_api_url": "http://127.0.0.1:2017/api",
            }
        }

        with patch.object(self.proxy_manager.os.path, "exists", return_value=True), patch(
            "builtins.open", mock_open(read_data="ignored")
        ), patch.object(self.proxy_manager.yaml, "safe_load", return_value=config):
            self.proxy_manager.reload_proxy_config()

        self.assertEqual("local", self.proxy_manager.V2RAYA_RUNTIME_MODE)
        self.assertEqual("http://127.0.0.1:2017", self.proxy_manager.V2RAYA_PANEL_URL)


if __name__ == "__main__":
    unittest.main()
