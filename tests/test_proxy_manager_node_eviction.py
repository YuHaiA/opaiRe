import unittest
from unittest.mock import patch

import utils.proxy_manager as pm


class ProxyManagerNodeEvictionTests(unittest.TestCase):
    def setUp(self):
        with pm._raw_proxy_evict_lock:
            pm._raw_proxy_evict_history.clear()

    def tearDown(self):
        with pm._raw_proxy_evict_lock:
            pm._raw_proxy_evict_history.clear()

    def test_raw_proxy_eviction_removes_only_failed_entry_and_reloads(self):
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "proxy_list": [
                    "http://user:pass@127.0.0.1:3129",
                    "http://user:pass@127.0.0.2:3129",
                ],
                "success_proxy_list": [
                    "http://user:pass@127.0.0.1:3129",
                ],
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.1:3129")

        self.assertTrue(ok)
        self.assertIn("原始代理池", msg)
        self.assertEqual(
            ["http://user:pass@127.0.0.2:3129"],
            saved_config["value"]["raw_proxy_pool"]["proxy_list"],
        )
        self.assertEqual(
            [],
            saved_config["value"]["raw_proxy_pool"]["success_proxy_list"],
        )

    def test_raw_proxy_eviction_rate_guard_pauses_persistent_delete(self):
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "auto_evict_max_per_window": 1,
                "auto_evict_window_seconds": 60,
                "proxy_list": [
                    "http://user:pass@127.0.0.1:3129",
                    "http://user:pass@127.0.0.2:3129",
                    "http://user:pass@127.0.0.3:3129",
                ],
            }
        }

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs") as mock_reload:
            first_ok, _ = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.1:3129")
            second_ok, second_msg = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.2:3129")

        self.assertTrue(first_ok)
        self.assertFalse(second_ok)
        self.assertTrue(pm._is_skip_evict_guard_message(second_msg))
        self.assertIn("自动切换下一条", second_msg)
        self.assertEqual(1, mock_reload.call_count)
        self.assertIn(
            "http://user:pass@127.0.0.2:3129",
            fake_config["raw_proxy_pool"]["proxy_list"],
        )

    def test_success_pool_eviction_removes_failed_entry_from_both_lists(self):
        target = "http://user:pass@127.0.0.1:3129"
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "success_pool_enabled": True,
                "proxy_list": [
                    target,
                    "http://user:pass@127.0.0.2:3129",
                    "http://user:pass@127.0.0.3:3129",
                ],
                "success_proxy_list": [
                    target,
                    "http://user:pass@127.0.0.2:3129",
                ],
            }
        }
        saved_config = {}

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs):
            ok, msg = pm.evict_current_proxy_or_node(target)

        self.assertTrue(ok)
        self.assertIn("成功代理池", msg)
        raw_conf = saved_config["value"]["raw_proxy_pool"]
        self.assertNotIn(target, raw_conf["proxy_list"])
        self.assertNotIn(target, raw_conf["success_proxy_list"])

    def test_success_pool_minimum_guard_counts_active_success_entries(self):
        target = "http://user:pass@127.0.0.1:3129"
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "success_pool_enabled": True,
                "auto_evict_min_remaining": 1,
                "proxy_list": [
                    target,
                    "http://user:pass@127.0.0.2:3129",
                    "http://user:pass@127.0.0.3:3129",
                ],
                "success_proxy_list": [target],
            }
        }

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs") as mock_reload:
            ok, msg = pm.evict_current_proxy_or_node(target)

        self.assertFalse(ok)
        self.assertTrue(pm._is_skip_evict_guard_message(msg))
        self.assertIn("成功代理池至少保留 1 条", msg)
        mock_reload.assert_not_called()

    def test_raw_proxy_eviction_guard_keeps_minimum_candidate(self):
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "auto_evict_min_remaining": 1,
                "proxy_list": ["http://user:pass@127.0.0.1:3129"],
            }
        }

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs") as mock_reload:
            ok, msg = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.1:3129")

        self.assertFalse(ok)
        self.assertTrue(pm._is_skip_evict_guard_message(msg))
        mock_reload.assert_not_called()

    def test_raw_proxy_eviction_rate_guard_expires_after_window(self):
        fake_config = {
            "raw_proxy_pool": {
                "enable": True,
                "auto_evict_max_per_window": 1,
                "auto_evict_window_seconds": 60,
                "proxy_list": [
                    "http://user:pass@127.0.0.1:3129",
                    "http://user:pass@127.0.0.2:3129",
                    "http://user:pass@127.0.0.3:3129",
                ],
            }
        }

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=True), \
                patch("utils.config.reload_all_configs") as mock_reload, \
                patch.object(pm.time, "monotonic", side_effect=[100.0, 161.0]):
            first_ok, _ = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.1:3129")
            second_ok, _ = pm.evict_current_proxy_or_node("http://user:pass@127.0.0.2:3129")

        self.assertTrue(first_ok)
        self.assertTrue(second_ok)
        self.assertEqual(2, mock_reload.call_count)

    def test_resolve_group_candidate_nodes_uses_preferred_pool_when_mode_enabled(self):
        proxies_data = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-c", "DIRECT", "自动选择"],
                },
                "node-a": {"type": "vless"},
                "node-b": {"type": "vless"},
                "node-c": {"type": "vless"},
                "DIRECT": {"type": "Direct"},
                "自动选择": {"type": "URLTest"},
            }
        }
        clash_conf = {
            "tested_nodes": {"节点选择": ["node-a", "node-b", "node-c", "DIRECT", "自动选择"]},
            "preferred_nodes": {"节点选择": ["node-b", "DIRECT", "自动选择"]},
            "preferred_only_mode": True,
            "evicted_nodes": [],
        }

        actual_group, candidates, meta = pm._resolve_group_candidate_nodes(proxies_data["proxies"], "节点选择", clash_conf=clash_conf)

        self.assertEqual("节点选择", actual_group)
        self.assertEqual(["node-b"], candidates)
        self.assertTrue(meta["preferred_only_mode"])
        self.assertEqual(["node-b"], meta["preferred_nodes"])

    def test_resolve_group_candidate_nodes_accepts_unexpanded_provider_nodes(self):
        proxies_data = {
            "PROXY": {"all": ["provider-node", "AUTO-URLTEST", "DIRECT"]},
            "AUTO-URLTEST": {"type": "URLTest", "all": ["provider-node"]},
            "DIRECT": {"type": "Direct"},
        }

        actual_group, candidates, _ = pm._resolve_group_candidate_nodes(proxies_data, "PROXY")

        self.assertEqual("PROXY", actual_group)
        self.assertEqual(["provider-node"], candidates)

    def test_evict_failed_switch_candidate_prunes_tested_nodes_without_polluting_keyword_blacklist(self):
        fake_config = {
            "clash_proxy_pool": {
                "blacklist": ["港", "HK"],
                "evicted_nodes": ["old-node"],
                "tested_nodes": {
                    "节点选择": ["node-a", "node-b", "node-d", "node-e", "node-f", "node-g", "node-h"],
                    "其他组": ["node-a", "node-c"],
                },
                "preferred_nodes": {
                    "节点选择": ["node-a", "node-b", "node-d", "node-e", "node-f", "node-g", "node-h"],
                    "其他组": ["node-a", "node-c"],
                },
                "preferred_only_mode": True,
            }
        }
        saved_config = {}

        fake_proxies = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-d", "node-e", "node-f", "node-g", "node-h"],
                },
                "node-a": {"type": "vless"},
                "node-b": {"type": "vless"},
                "node-d": {"type": "vless"},
                "node-e": {"type": "vless"},
                "node-f": {"type": "vless"},
                "node-g": {"type": "vless"},
                "node-h": {"type": "vless"},
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
                patch.object(pm, "PROXY_GROUP_NAME", "节点选择"), \
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
        self.assertEqual(["node-b", "node-d", "node-e", "node-f", "node-g", "node-h"], result["preferred_nodes"]["节点选择"])
        self.assertEqual(["node-c"], result["preferred_nodes"]["其他组"])
        self.assertTrue(result["preferred_only_mode"])

    def test_evict_failed_switch_candidate_rebuilds_pools_when_effective_pool_hits_floor(self):
        fake_config = {
            "clash_proxy_pool": {
                "blacklist": ["港", "HK"],
                "evicted_nodes": ["old-node"],
                "tested_nodes": {
                    "节点选择": ["node-a", "node-b", "node-c", "node-d"],
                },
                "preferred_nodes": {"节点选择": ["node-a", "node-b"]},
            }
        }
        saved_config = {}
        fake_group_proxies = {
            "proxies": {
                "节点选择": {
                    "all": ["node-a", "node-b", "node-c", "node-d"],
                },
                "node-a": {"type": "vless"},
                "node-b": {"type": "vless"},
                "node-c": {"type": "vless"},
                "node-d": {"type": "vless"},
            }
        }

        class _FakeGroupResponse:
            status_code = 200

            @staticmethod
            def json():
                return fake_group_proxies

        class _FakeDelayResponse:
            status_code = 200

            def __init__(self, delay):
                self.delay = delay

            def json(self):
                return {"delay": self.delay}

        def fake_get(url, *args, **kwargs):
            if url.endswith("/proxies"):
                return _FakeGroupResponse()
            if "/delay" in url:
                if "node-b" in url or "node-d" in url:
                    return _FakeDelayResponse(88 if "node-b" in url else 120)
                return _FakeDelayResponse(0)
            raise AssertionError(url)

        def fake_reload_all_configs(new_config_dict=None):
            saved_config["value"] = new_config_dict

        with patch("utils.proxy_manager._load_runtime_config_for_write", return_value=fake_config), \
                patch("utils.config.is_raw_proxy_pool_enabled", return_value=False), \
                patch("utils.config.reload_all_configs", side_effect=fake_reload_all_configs), \
                patch.object(pm, "PROXY_GROUP_NAME", "节点选择"), \
                patch("utils.proxy_manager.get_current_selected_node", return_value="node-a"), \
                patch("utils.proxy_manager.std_requests.get", side_effect=fake_get):
            ok, msg = pm.evict_failed_switch_candidate("http://127.0.0.1:7890", "node-a")

        self.assertTrue(ok)
        self.assertIn("触发底线重建", msg)
        result = saved_config["value"]["clash_proxy_pool"]
        self.assertEqual([], result["evicted_nodes"])
        self.assertEqual({}, result["preferred_nodes"])
        self.assertEqual({"节点选择": ["node-b", "node-d"]}, result["tested_nodes"])

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
                },
                "node-a": {"type": "vless"},
                "node-b": {"type": "vless"},
                "node-c": {"type": "vless"},
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
                patch.object(pm, "PROXY_GROUP_NAME", "节点选择"), \
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
