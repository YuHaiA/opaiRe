import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "sub2-mihomo"


def load_converter():
    sys.path.insert(0, str(DEPLOY))
    spec = importlib.util.spec_from_file_location("sub2_mihomo_v2ray_convert", DEPLOY / "v2ray_convert.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Sub2MihomoHttpNodesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.converter = load_converter()

    def test_http_uri_with_credentials_is_converted_without_leaking_secret(self):
        proxy = self.converter.parse_http_proxy(
            "http://alice:p%40ss@example.com:8080#Tokyo HTTP"
        )

        self.assertEqual(
            proxy,
            {
                "name": "Tokyo HTTP",
                "type": "http",
                "server": "example.com",
                "port": 8080,
                "username": "alice",
                "password": "p@ss",
            },
        )
        self.assertNotIn("p@ss", proxy["name"])

    def test_https_uri_sets_tls(self):
        proxy = self.converter.parse_http_proxy("https://proxy.example:8443")
        self.assertEqual(proxy["type"], "http")
        self.assertEqual(proxy["port"], 8443)
        self.assertTrue(proxy["tls"])

    def test_subscription_url_is_not_treated_as_http_proxy(self):
        url = "https://example.com:443/subscription.yaml"
        self.assertFalse(self.converter.looks_like_http_proxy_uri(url))
        self.assertTrue(self.converter.looks_like_single_url(url))

    def test_http_proxy_lines_are_detected(self):
        parsed = self.converter.detect_and_parse_subscription(
            "http://one:secret@one.example:8080#one\n"
            "https://two.example:8443#two\n"
        )

        self.assertEqual(parsed["kind"], "http_proxy_links")
        self.assertEqual(parsed["count"], 2)
        self.assertEqual([item["name"] for item in parsed["proxies"]], ["one", "two"])
        self.assertNotIn("secret", parsed["sample"])

    def test_clash_http_nodes_and_http_uri_can_be_mixed(self):
        parsed = self.converter.detect_and_parse_subscription(
            "proxies:\n"
            "  - name: clash-http\n"
            "    type: http\n"
            "    server: clash.example\n"
            "    port: 3128\n"
            "http://mixed.example:8080#manual\n"
        )

        self.assertEqual(parsed["kind"], "mixed")
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(
            {item["name"] for item in parsed["proxies"]},
            {"clash-http", "manual"},
        )

    def test_mixed_http_and_v2ray_links_are_supported(self):
        parsed = self.converter.detect_and_parse_subscription(
            "http://manual.example:8080#manual\n"
            "vless://00000000-0000-4000-8000-000000000000@example.com:443?security=tls&type=tcp#vless\n"
        )

        self.assertEqual(parsed["kind"], "mixed")
        self.assertEqual(parsed["count"], 2)
        self.assertEqual(
            {item["type"] for item in parsed["proxies"]},
            {"http", "vless"},
        )


if __name__ == "__main__":
    unittest.main()
