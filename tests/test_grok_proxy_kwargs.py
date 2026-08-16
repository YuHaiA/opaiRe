import unittest

from utils.grok_auth.sso_to_auth_json import _proxy_kwargs


class GrokProxyKwargsTests(unittest.TestCase):
    def test_keeps_basic_auth_when_bracketing_ipv6(self):
        result = _proxy_kwargs("http://user:p%40ss@[2001:db8::1]:8080")
        self.assertEqual(
            {
                "proxies": {
                    "http": "http://user:p%40ss@[2001:db8::1]:8080",
                    "https": "http://user:p%40ss@[2001:db8::1]:8080",
                }
            },
            result,
        )

    def test_keeps_basic_auth_for_ipv4(self):
        result = _proxy_kwargs("http://user:pass@127.0.0.1:8080")
        self.assertEqual(
            {
                "proxies": {
                    "http": "http://user:pass@127.0.0.1:8080",
                    "https": "http://user:pass@127.0.0.1:8080",
                }
            },
            result,
        )


if __name__ == "__main__":
    unittest.main()
