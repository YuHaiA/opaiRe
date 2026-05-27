import unittest
from unittest.mock import patch

import utils.integrations.clash_manager as clash_manager


class ClashManagerEvictedNodesClearTests(unittest.TestCase):
    def test_clear_evicted_nodes_clears_runtime_pool(self):
        fake_config = {
            "clash_proxy_pool": {
                "evicted_nodes": ["node-a", "node-b"],
                "tested_nodes": {"节点选择": ["node-c"]},
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = clash_manager.clear_evicted_nodes()

        self.assertTrue(ok)
        self.assertIn("已清空拉黑节点池", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual([], result["evicted_nodes"])
        self.assertEqual({"节点选择": ["node-c"]}, result["tested_nodes"])

    def test_get_pool_status_exposes_evicted_nodes_in_local_gui_mode(self):
        fake_config = {
            "default_proxy": "http://127.0.0.1:7897",
            "clash_proxy_pool": {
                "api_url": "http://127.0.0.1:9097",
                "evicted_nodes": ["node-a", "node-b"],
            }
        }

        with patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config), \
                patch("utils.integrations.clash_manager.get_client", return_value=None), \
                patch("utils.integrations.clash_manager._probe_local_ports", return_value=True), \
                patch("utils.integrations.clash_manager._collect_groups_from_config", return_value=[]), \
                patch("utils.integrations.clash_manager.get_subscription_state", return_value={"items": []}):
            status = clash_manager.get_pool_status()

        self.assertEqual("local_gui", status["mode"])
        self.assertEqual(["node-a", "node-b"], status["evicted_nodes"])


if __name__ == "__main__":
    unittest.main()
