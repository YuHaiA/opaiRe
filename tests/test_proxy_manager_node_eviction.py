import unittest
from unittest.mock import patch

import utils.proxy_manager as pm


class ProxyManagerNodeEvictionTests(unittest.TestCase):
    def test_resolve_group_candidate_nodes_uses_preferred_pool_when_mode_enabled(self):
        proxies_data = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-c"],
                }
            }
        }
        clash_conf = {
            "tested_nodes": {"节点选择": ["node-a", "node-b", "node-c"]},
            "preferred_nodes": {"节点选择": ["node-b"]},
            "preferred_only_mode": True,
            "evicted_nodes": [],
        }

        actual_group, candidates, meta = pm._resolve_group_candidate_nodes(proxies_data["proxies"], "节点选择", clash_conf=clash_conf)

        self.assertEqual("节点选择", actual_group)
        self.assertEqual(["node-b"], candidates)
        self.assertTrue(meta["preferred_only_mode"])
        self.assertEqual(["node-b"], meta["preferred_nodes"])

    def test_evict_failed_switch_candidate_prunes_tested_nodes_without_polluting_keyword_blacklist(self):
        fake_config = {
            "clash_proxy_pool": {
                "blacklist": ["港", "HK"],
                "evicted_nodes": ["old-node"],
                "tested_nodes": {
                    "节点选择": ["node-a", "node-b", "node-d", "node-e", "node-f", "node-g", "node-h"],
                    "其他组": ["node-a", "node-c"],
                },
            }
        }
        saved_config = {}

        fake_proxies = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-d", "node-e", "node-f", "node-g", "node-h"],
                }
            }
        }

        class _FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return fake_proxies

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=False), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs), \
                patch("utils.proxy_manager.get_current_selected_node", return_value="node-a"), \
                patch("utils.proxy_manager.std_requests.get", return_value=_FakeResponse()):
            ok, msg = pm.evict_failed_switch_candidate("http://127.0.0.1:7890", "node-a")

        self.assertTrue(ok)
        self.assertIn("node-a", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual(["港", "HK"], result["blacklist"])
        self.assertEqual(["old-node", "node-a"], result["evicted_nodes"])
        self.assertEqual(["node-b", "node-d", "node-e", "node-f", "node-g", "node-h"], result["tested_nodes"]["节点选择"])
        self.assertEqual(["node-c"], result["tested_nodes"]["其他组"])

    def test_evict_failed_switch_candidate_skips_blacklist_when_effective_pool_is_too_small(self):
        fake_config = {
            "clash_proxy_pool": {
                "blacklist": ["港", "HK"],
                "evicted_nodes": ["old-node"],
                "tested_nodes": {
                    "节点选择": ["node-a", "node-b", "node-c", "node-d", "node-e", "node-f"],
                },
            }
        }
        saved_config = {}
        fake_proxies = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-c", "node-d", "node-e", "node-f"],
                }
            }
        }

        class _FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return fake_proxies

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=False), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs), \
                patch("utils.proxy_manager.get_current_selected_node", return_value="node-a"), \
                patch("utils.proxy_manager.std_requests.get", return_value=_FakeResponse()):
            ok, msg = pm.evict_failed_switch_candidate("http://127.0.0.1:7890", "node-a")

        self.assertFalse(ok)
        self.assertIn("触发保底保护", msg)
        self.assertEqual({}, saved_config)

    def test_mark_current_clash_node_preferred_updates_preferred_and_healthy_pools(self):
        fake_config = {
            "clash_proxy_pool": {
                "preferred_nodes": {"节点选择": ["node-a"]},
                "tested_nodes": {"节点选择": ["node-a"]},
            }
        }
        saved_config = {}
        fake_proxies = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-c"],
                }
            }
        }

        class _FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return fake_proxies

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.proxy_manager.get_current_selected_node", return_value="node-b"), \
                patch("utils.proxy_manager.std_requests.get", return_value=_FakeResponse()), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = pm.mark_current_clash_node_preferred("http://127.0.0.1:7890")

        self.assertTrue(ok)
        self.assertIn("标记为标优", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual(["node-a", "node-b"], result["preferred_nodes"]["节点选择"])
        self.assertEqual(["node-a", "node-b"], result["tested_nodes"]["节点选择"])

    def test_force_switch_bypasses_shared_cooldown(self):
        previous_last_switch = pm._last_switch_time
        previous_enable = pm.ENABLE_NODE_SWITCH
        previous_pool_mode = pm.POOL_MODE
        try:
            pm._last_switch_time = 100
            pm.ENABLE_NODE_SWITCH = True
            pm.POOL_MODE = False
            with patch("utils.proxy_manager.time.time", return_value=105), \
                    patch("utils.proxy_manager._do_smart_switch", return_value=True) as mock_switch:
                ok = pm.smart_switch_node("http://127.0.0.1:7890", force=True)
            self.assertTrue(ok)
            mock_switch.assert_called_once_with("http://127.0.0.1:7890")
            self.assertEqual(105, pm._last_switch_time)
        finally:
            pm._last_switch_time = previous_last_switch
            pm.ENABLE_NODE_SWITCH = previous_enable
            pm.POOL_MODE = previous_pool_mode

    def test_non_forced_switch_respects_shared_cooldown(self):
        previous_last_switch = pm._last_switch_time
        previous_enable = pm.ENABLE_NODE_SWITCH
        previous_pool_mode = pm.POOL_MODE
        try:
            pm._last_switch_time = 100
            pm.ENABLE_NODE_SWITCH = True
            pm.POOL_MODE = False
            with patch("utils.proxy_manager.time.time", return_value=105), \
                    patch("utils.proxy_manager._do_smart_switch", return_value=True) as mock_switch:
                ok = pm.smart_switch_node("http://127.0.0.1:7890")
            self.assertTrue(ok)
            mock_switch.assert_not_called()
            self.assertEqual(100, pm._last_switch_time)
        finally:
            pm._last_switch_time = previous_last_switch
            pm.ENABLE_NODE_SWITCH = previous_enable
            pm.POOL_MODE = previous_pool_mode


if __name__ == "__main__":
    unittest.main()
