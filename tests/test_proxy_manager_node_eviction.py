import unittest
from unittest.mock import patch

import utils.proxy_manager as pm


class ProxyManagerNodeEvictionTests(unittest.TestCase):
    def test_evict_failed_switch_candidate_blacklists_and_prunes_tested_nodes(self):
        fake_config = {
            "clash_proxy_pool": {
                "blacklist": ["old-node"],
                "tested_nodes": {
                    "节点选择": ["node-a", "node-b"],
                    "其他组": ["node-a", "node-c"],
                },
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=False), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs), \
                patch("utils.proxy_manager.get_current_selected_node", return_value="node-a"):
            ok, msg = pm.evict_failed_switch_candidate("http://127.0.0.1:7890", "node-a")

        self.assertTrue(ok)
        self.assertIn("node-a", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual(["old-node", "node-a"], result["blacklist"])
        self.assertEqual(["node-b"], result["tested_nodes"]["节点选择"])
        self.assertEqual(["node-c"], result["tested_nodes"]["其他组"])


if __name__ == "__main__":
    unittest.main()
