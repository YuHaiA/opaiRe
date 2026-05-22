import unittest
from unittest.mock import patch

from utils.integrations import clash_manager


class ClashManagerRuntimeConfigTests(unittest.TestCase):
    def test_read_runtime_config_prefers_live_cfg_snapshot(self):
        live_config = {
            "clash_proxy_pool": {
                "sub_url": "https://example.com/live.yaml",
                "sub_urls": [{"id": "1", "name": "live", "url": "https://example.com/live.yaml"}],
            }
        }
        with patch.object(clash_manager.cfg, "_c", live_config, create=True):
            data = clash_manager._read_runtime_config()

        self.assertEqual("https://example.com/live.yaml", data["clash_proxy_pool"]["sub_url"])
        self.assertIsNot(data, live_config)


if __name__ == "__main__":
    unittest.main()
