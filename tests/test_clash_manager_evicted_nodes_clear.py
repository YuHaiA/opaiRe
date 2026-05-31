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
                "preferred_nodes": {"节点选择": ["node-c"]},
                "preferred_only_mode": True,
            }
        }

        with patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config), \
                patch("utils.integrations.clash_manager.get_client", return_value=None), \
                patch("utils.integrations.clash_manager._probe_local_ports", return_value=True), \
                patch("utils.integrations.clash_manager._collect_groups_from_config", return_value=[{"name": "节点选择", "nodes": ["node-a", "node-c"], "count": 2, "type": "Selector"}]), \
                patch("utils.integrations.clash_manager.get_subscription_state", return_value={"items": []}):
            status = clash_manager.get_pool_status()

        self.assertEqual("local_gui", status["mode"])
        self.assertEqual(["node-a", "node-b"], status["evicted_nodes"])
        self.assertTrue(status["preferred_only_mode"])
        self.assertEqual(["node-c"], status["groups"][0]["preferred_nodes"])

    def test_set_preferred_only_mode_persists_runtime_flag(self):
        fake_config = {"clash_proxy_pool": {"preferred_only_mode": False}}
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = clash_manager.set_preferred_only_mode(True)

        self.assertTrue(ok)
        self.assertIn("仅用标优节点模式", msg)
        self.assertTrue(saved_config["value"]["clash_proxy_pool"]["preferred_only_mode"])

    def test_clear_preferred_nodes_clears_only_target_group_pool(self):
        fake_config = {
            "clash_proxy_pool": {
                "evicted_nodes": ["node-a"],
                "tested_nodes": {"节点选择": ["node-b"]},
                "preferred_nodes": {
                    "🚀 节点选择": ["node-c"],
                    "🇺🇸 节点-选择": ["node-e"],
                    "备用策略": ["node-d"],
                },
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs), \
                patch("utils.proxy_manager.PREFERRED_NODES_MAP", {
                    "🚀 节点选择": ["node-c"],
                    "🇺🇸 节点-选择": ["node-e"],
                    "备用策略": ["node-d"],
                }):
            ok, msg = clash_manager.clear_preferred_nodes("节点选择")
            from utils import proxy_manager
            runtime_preferred = dict(proxy_manager.PREFERRED_NODES_MAP)

        self.assertTrue(ok)
        self.assertIn("已清空策略组 [节点选择] 的标优节点池", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual({"备用策略": ["node-d"]}, result["preferred_nodes"])
        self.assertEqual(["node-a"], result["evicted_nodes"])
        self.assertEqual({"节点选择": ["node-b"]}, result["tested_nodes"])
        self.assertEqual({"备用策略": ["node-d"]}, runtime_preferred)

    def test_switch_proxy_group_rejects_non_preferred_node_when_preferred_only_enabled(self):
        fake_config = {
            "clash_proxy_pool": {
                "preferred_only_mode": True,
                "preferred_nodes": {"节点选择": ["node-a"]},
            }
        }

        with patch("utils.integrations.clash_manager._get_controller_endpoint", return_value=("http://127.0.0.1:9090", "")), \
                patch("utils.integrations.clash_manager._resolve_runtime_group_name", return_value="节点选择"), \
                patch("utils.integrations.clash_manager._read_runtime_config", return_value=fake_config):
            ok, msg = clash_manager.switch_proxy_group("节点选择", "node-b")

        self.assertFalse(ok)
        self.assertIn("不在标优池内", msg)


if __name__ == "__main__":
    unittest.main()
