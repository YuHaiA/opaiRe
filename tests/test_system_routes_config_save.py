import unittest

from utils.config_save_guard import merge_runtime_owned_clash_state


class SystemRoutesConfigSaveTests(unittest.TestCase):
    def test_merge_runtime_owned_clash_state_preserves_runtime_keys(self):
        current_config = {
            "default_proxy": "http://127.0.0.1:7897",
            "clash_proxy_pool": {
                "sub_url": "https://current.example/sub.yaml",
                "sub_urls": [{"id": "a1", "url": "https://current.example/sub.yaml"}],
                "selected_subscription_id": "a1",
                "tested_nodes": {"节点选择": ["node-a", "node-b"]},
                "preferred_nodes": {"节点选择": ["node-b"]},
                "preferred_only_mode": True,
                "evicted_nodes": ["bad-node"],
                "blacklist": ["港", "HK"],
            },
        }
        incoming_config = {
            "default_proxy": "http://127.0.0.1:7899",
            "clash_proxy_pool": {
                "api_url": "http://127.0.0.1:9097",
                "sub_url": "https://stale.example/sub.yaml",
                "sub_urls": [{"id": "stale", "url": "https://stale.example/sub.yaml"}],
                "selected_subscription_id": "stale",
                "tested_nodes": {"节点选择": ["stale-node"]},
                "preferred_nodes": {"节点选择": ["stale-node"]},
                "preferred_only_mode": False,
                "evicted_nodes": [],
                "blacklist": ["自动"],
            },
        }

        merged = merge_runtime_owned_clash_state(current_config, incoming_config)
        clash_conf = merged["clash_proxy_pool"]

        self.assertEqual("http://127.0.0.1:7899", merged["default_proxy"])
        self.assertEqual("http://127.0.0.1:9097", clash_conf["api_url"])
        self.assertEqual(["自动"], clash_conf["blacklist"])
        self.assertEqual("https://current.example/sub.yaml", clash_conf["sub_url"])
        self.assertEqual([{"id": "a1", "url": "https://current.example/sub.yaml"}], clash_conf["sub_urls"])
        self.assertEqual("a1", clash_conf["selected_subscription_id"])
        self.assertEqual({"节点选择": ["node-a", "node-b"]}, clash_conf["tested_nodes"])
        self.assertEqual({"节点选择": ["node-b"]}, clash_conf["preferred_nodes"])
        self.assertTrue(clash_conf["preferred_only_mode"])
        self.assertEqual(["bad-node"], clash_conf["evicted_nodes"])


if __name__ == "__main__":
    unittest.main()
