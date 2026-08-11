import unittest
from unittest.mock import patch

from utils.integrations.subscription_fetcher import fetch_subscription_text


class _FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class SubscriptionFetcherTests(unittest.TestCase):
    def test_fetch_subscription_falls_back_from_proxy_403_to_direct_200(self):
        def fake_get(url, **kwargs):
            if kwargs.get("proxies"):
                return _FakeResponse(403, "forbidden")
            return _FakeResponse(200, "mixed-port: 7890")

        with patch("utils.integrations.subscription_fetcher.cffi_requests.get", side_effect=fake_get):
            result = fetch_subscription_text(
                "https://example.com/sub.yaml",
                proxies={"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            )

        self.assertTrue(result.ok)
        self.assertEqual(200, result.status_code)
        self.assertIn("mixed-port", result.text)

    def test_fetch_subscription_returns_clear_403_message_after_all_attempts_fail(self):
        with patch(
            "utils.integrations.subscription_fetcher.cffi_requests.get",
            return_value=_FakeResponse(403, "forbidden"),
        ):
            result = fetch_subscription_text("https://example.com/sub.yaml", proxies=None)

        self.assertFalse(result.ok)
        self.assertEqual(403, result.status_code)
        self.assertIn("HTTP 403", result.message)


if __name__ == "__main__":
    unittest.main()
