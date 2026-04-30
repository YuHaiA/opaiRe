import unittest
from unittest.mock import patch, mock_open

import yaml

import utils.config as cfg
import utils.proxy_manager as proxy_manager


class _DummySocket:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _DummySession:
    def close(self):
        return None


class ProxyManagerV2rayATests(unittest.TestCase):
    def tearDown(self):
        proxy_manager._reset_v2raya_runtime_state()

    def test_reload_proxy_config_falls_back_to_default_proxy_for_v2raya(self):
        fake_config = {
            "default_proxy": "http://127.0.0.1:20171",
            "clash_proxy_pool": {
                "enable": True,
                "client_type": "v2raya",
                "v2raya_url": "http://127.0.0.1:2017",
                "test_proxy_url": "",
            },
        }
        mocked_open = mock_open(read_data=yaml.safe_dump(fake_config, allow_unicode=True, sort_keys=False))

        with patch("utils.proxy_manager.os.path.exists", return_value=True), patch("builtins.open", mocked_open):
            proxy_manager.reload_proxy_config()

        self.assertEqual("http://127.0.0.1:20171", proxy_manager.LOCAL_PROXY_URL)

    def test_reload_proxy_config_prefers_v2raya_api_url_over_legacy_url(self):
        fake_config = {
            "clash_proxy_pool": {
                "enable": True,
                "client_type": "v2raya",
                "v2raya_api_url": "http://10.0.0.9:2017/api",
                "v2raya_url": "http://127.0.0.1:2017",
            },
        }
        mocked_open = mock_open(read_data=yaml.safe_dump(fake_config, allow_unicode=True, sort_keys=False))

        with patch("utils.proxy_manager.os.path.exists", return_value=True), patch("builtins.open", mocked_open):
            proxy_manager.reload_proxy_config()

        self.assertEqual("http://10.0.0.9:2017", proxy_manager.V2RAYA_PANEL_URL)

    def test_get_local_proxy_diagnostics_reports_reachable_listener(self):
        with patch("utils.proxy_manager.socket.create_connection", return_value=_DummySocket()):
            data = proxy_manager.get_local_proxy_diagnostics("http://127.0.0.1:20171")

        self.assertTrue(data["configured"])
        self.assertTrue(data["reachable"])
        self.assertEqual("127.0.0.1", data["host"])
        self.assertEqual(20171, data["port"])

    def test_get_local_proxy_diagnostics_handles_missing_proxy(self):
        with patch.object(proxy_manager, "LOCAL_PROXY_URL", ""):
            data = proxy_manager.get_local_proxy_diagnostics("")

        self.assertFalse(data["configured"])
        self.assertFalse(data["reachable"])
        self.assertIn("default_proxy", data["error"])

    def test_discover_v2raya_local_proxy_chooses_reachable_listener_candidate(self):
        diagnostics = {
            "http://127.0.0.1:53000": {
                "configured": True,
                "target_proxy": "http://127.0.0.1:53000",
                "display_name": "端口:53000",
                "scheme": "http",
                "host": "127.0.0.1",
                "port": 53000,
                "reachable": True,
                "error": "",
            }
        }
        with patch.object(proxy_manager, "_get_v2raya_runtime_proxy_candidates", return_value=[]), patch.object(
            proxy_manager,
            "_iter_related_listener_candidates",
            return_value=[{"url": "http://127.0.0.1:53000", "source": "listener:clash-core-service.exe"}],
        ), patch.object(
            proxy_manager,
            "get_local_proxy_diagnostics",
            side_effect=lambda url=None: diagnostics.get(url, {"configured": False, "reachable": False, "error": "missing"}),
        ), patch.object(proxy_manager, "_test_proxy_liveness_once", return_value=True):
            result = proxy_manager.discover_v2raya_local_proxy("http://127.0.0.1:20171")

        self.assertEqual("http://127.0.0.1:53000", result["detected_proxy"])
        self.assertEqual("listener:clash-core-service.exe", result["detected_source"])

    def test_align_v2raya_local_proxy_persists_config_when_requested(self):
        fake_discovery = {
            "selected": {"url": "http://127.0.0.1:53000", "source": "listener:test"},
            "detected_proxy": "http://127.0.0.1:53000",
            "detected_source": "listener:test",
            "candidates": [],
            "reachable_candidate_count": 1,
        }
        with patch.object(proxy_manager, "discover_v2raya_local_proxy", return_value=fake_discovery), patch.object(
            proxy_manager, "_set_runtime_default_proxy", return_value="http://127.0.0.1:53000"
        ), patch.object(cfg, "_c", {"default_proxy": "http://127.0.0.1:20171", "clash_proxy_pool": {}}), patch.object(
            cfg, "reload_all_configs"
        ) as mock_reload:
            result = proxy_manager.align_v2raya_local_proxy(persist=True)

        self.assertTrue(result["ok"])
        self.assertTrue(result["persisted"])
        self.assertEqual("http://127.0.0.1:53000", result["applied_proxy"])
        new_config = mock_reload.call_args.kwargs["new_config_dict"]
        self.assertEqual("http://127.0.0.1:53000", new_config["default_proxy"])
        self.assertEqual("http://127.0.0.1:53000", new_config["clash_proxy_pool"]["test_proxy_url"])

    def test_extract_v2raya_nodes_keeps_subscription_context_for_nested_servers(self):
        payload = {
            "code": "SUCCESS",
            "data": {
                "touch": {
                    "subscriptions": [
                        {
                            "id": 1,
                            "_type": "subscription",
                            "host": "demo-subscription",
                            "address": "https://example.com/sub.txt",
                            "servers": [
                                {
                                    "id": 101,
                                    "_type": "subscriptionServer",
                                    "name": "HK-01",
                                    "address": "1.1.1.1:443",
                                    "selected": True,
                                }
                            ],
                        }
                    ]
                }
            },
        }

        raw_nodes = proxy_manager._extract_v2raya_nodes(payload)
        switchable_nodes = [item for item in raw_nodes if item.get("is_switchable")]
        subscriptions = proxy_manager._build_v2raya_subscription_summaries(switchable_nodes, raw_nodes)

        self.assertEqual(2, len(raw_nodes))
        self.assertEqual(1, len(switchable_nodes))
        self.assertEqual("1", switchable_nodes[0]["subscription_id"])
        self.assertEqual("demo-subscription", switchable_nodes[0]["subscription_name"])
        self.assertTrue(switchable_nodes[0]["is_current"])
        self.assertEqual(
            [
                {
                    "id": "1",
                    "host": "demo-subscription",
                    "address": "https://example.com/sub.txt",
                    "node_count": 1,
                    "current_count": 1,
                    "best_latency": None,
                }
            ],
            subscriptions,
        )

    def test_list_v2raya_nodes_keeps_invalid_marks_excluded(self):
        snapshot = {
            "nodes": [
                {"key": "subscriptionServer:1:101", "name": "JP-01"},
                {"key": "subscriptionServer:1:102", "name": "US-02"},
            ]
        }
        proxy_manager.set_v2raya_node_invalid_state(["subscriptionServer:1:101"], invalid=True)

        with patch.object(proxy_manager, "get_v2raya_nodes_snapshot", return_value=snapshot):
            result = proxy_manager._list_v2raya_nodes()

        self.assertEqual(["subscriptionServer:1:102"], [item["key"] for item in result])
        self.assertTrue(proxy_manager.is_v2raya_node_invalid("subscriptionServer:1:101"))

    def test_switch_v2raya_node_safely_rejects_invalid_node(self):
        node = {
            "key": "subscriptionServer:1:101",
            "node_id": "101",
            "node_type": "subscriptionServer",
            "subscription_id": "1",
            "name": "HK-01",
            "is_current": False,
        }
        proxy_manager.set_v2raya_node_invalid_state([node["key"]], invalid=True)

        with patch.object(proxy_manager, "V2RAYA_PANEL_URL", "http://127.0.0.1:2017"), patch.object(
            proxy_manager, "get_v2raya_nodes_snapshot", return_value={"nodes": [node]}
        ), patch.object(proxy_manager, "_preflight_v2raya_node") as mock_preflight:
            result = proxy_manager.switch_v2raya_node_safely(dict(node))

        self.assertFalse(result["ok"])
        self.assertIn("已被标记为失效", result["message"])
        mock_preflight.assert_not_called()

    def test_switch_v2raya_node_safely_marks_node_invalid_when_preflight_fails(self):
        node = {
            "key": "subscriptionServer:1:101",
            "node_id": "101",
            "node_type": "subscriptionServer",
            "subscription_id": "1",
            "name": "HK-01",
            "is_current": False,
        }

        with patch.object(proxy_manager, "V2RAYA_PANEL_URL", "http://127.0.0.1:2017"), patch.object(
            proxy_manager, "get_v2raya_nodes_snapshot", side_effect=[{"nodes": [node]}, {"nodes": [node]}]
        ), patch.object(
            proxy_manager, "_preflight_v2raya_node", return_value=(False, None, "预检失败")
        ), patch.object(proxy_manager, "switch_v2raya_node") as mock_switch:
            result = proxy_manager.switch_v2raya_node_safely(dict(node))

        self.assertFalse(result["ok"])
        self.assertIn("已自动标记为失效", result["message"])
        self.assertTrue(proxy_manager.is_v2raya_node_invalid(node["key"]))
        mock_switch.assert_not_called()

    def test_switch_v2raya_node_safely_rolls_back_when_proxy_chain_does_not_recover(self):
        current_node = {
            "key": "subscriptionServer:1:100",
            "node_id": "100",
            "node_type": "subscriptionServer",
            "subscription_id": "1",
            "name": "US-OLD",
            "is_current": True,
        }
        target_node = {
            "key": "subscriptionServer:1:101",
            "node_id": "101",
            "node_type": "subscriptionServer",
            "subscription_id": "1",
            "name": "HK-NEW",
            "is_current": False,
        }

        with patch.object(proxy_manager, "V2RAYA_PANEL_URL", "http://127.0.0.1:2017"), patch.object(
            proxy_manager, "get_v2raya_nodes_snapshot", side_effect=[{"nodes": [current_node, target_node]}, {"nodes": [current_node, target_node]}]
        ), patch.object(
            proxy_manager, "_preflight_v2raya_node", return_value=(True, 88.0, "")
        ), patch.object(
            proxy_manager, "switch_v2raya_node", return_value=True
        ), patch.object(
            proxy_manager, "test_proxy_liveness", return_value=False
        ), patch.object(
            proxy_manager, "_recover_v2raya_node", return_value=(True, current_node)
        ), patch.object(
            proxy_manager, "_log_v2raya_proxy_unavailable"
        ), patch("utils.proxy_manager.time.sleep", return_value=None):
            result = proxy_manager.switch_v2raya_node_safely(dict(target_node), proxy_url="http://127.0.0.1:20171")

        self.assertFalse(result["ok"])
        self.assertTrue(proxy_manager.is_v2raya_node_invalid(target_node["key"]))
        self.assertIn("并回滚到", result["message"])


if __name__ == "__main__":
    unittest.main()
