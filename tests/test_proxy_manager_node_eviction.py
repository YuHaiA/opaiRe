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
