import socket
import unittest
from unittest.mock import patch

from utils.raw_proxy_probe import (
    normalize_probe_entries,
    probe_raw_proxy,
    probe_raw_proxy_pool,
    proxy_display_name,
    select_evenly_spaced,
)


class _SocketContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class RawProxyProbeTests(unittest.TestCase):
    def test_normalize_entries_and_display_never_return_credentials(self):
        entries, invalid_count = normalize_probe_entries([
            "http://user:secret@1.2.3.4:8080",
            "bad-entry",
            "http://1.2.3.4:not-a-port",
            "http://user:secret@1.2.3.4:8080",
        ])

        self.assertEqual(1, len(entries))
        self.assertEqual(2, invalid_count)
        display = proxy_display_name(entries[0]["proxy"])
        self.assertEqual("http://***@1.2.3.4:8080", display)
        self.assertNotIn("user", display)
        self.assertNotIn("secret", display)

    def test_even_sample_includes_first_and_last_entries(self):
        entries = [{"source_index": i + 1, "proxy": f"http://127.0.0.{i + 1}:8080"} for i in range(100)]
        selected = select_evenly_spaced(entries, 5)

        self.assertEqual(5, len(selected))
        self.assertEqual(1, selected[0]["source_index"])
        self.assertEqual(100, selected[-1]["source_index"])

    @patch("utils.raw_proxy_probe.socket.create_connection", side_effect=socket.timeout())
    def test_tcp_timeout_is_classified_without_http_request(self, _mock_connect):
        with patch("utils.raw_proxy_probe.requests.get") as mock_get:
            result = probe_raw_proxy(
                {"source_index": 3, "proxy": "http://user:secret@1.2.3.4:8080"},
                timeout_sec=3,
            )

        self.assertFalse(result["ok"])
        self.assertEqual("tcp_timeout", result["code"])
        self.assertEqual("http://***@1.2.3.4:8080", result["proxy"])
        mock_get.assert_not_called()

    @patch("utils.raw_proxy_probe.socket.create_connection", return_value=_SocketContext())
    @patch("utils.raw_proxy_probe.requests.get", return_value=_Response(407, ""))
    def test_auth_failure_is_classified(self, _mock_get, _mock_connect):
        result = probe_raw_proxy(
            {"source_index": 1, "proxy": "http://user:secret@1.2.3.4:8080"},
            timeout_sec=3,
        )

        self.assertFalse(result["ok"])
        self.assertEqual("auth_failed", result["code"])
        self.assertEqual(407, result["http_status"])

    @patch("utils.raw_proxy_probe.socket.create_connection", return_value=_SocketContext())
    @patch(
        "utils.raw_proxy_probe.requests.get",
        return_value=_Response(200, "fl=1\nloc=US\nwarp=off\n"),
    )
    def test_success_returns_country_and_no_credentials(self, _mock_get, _mock_connect):
        result = probe_raw_proxy(
            {"source_index": 2, "proxy": "http://user:secret@1.2.3.4:8080"},
            timeout_sec=3,
        )

        self.assertTrue(result["ok"])
        self.assertEqual("ok", result["code"])
        self.assertEqual("US", result["country"])
        self.assertNotIn("secret", str(result))

    @patch("utils.raw_proxy_probe.probe_raw_proxy")
    def test_pool_summary_recommends_checking_whitelist_for_all_tcp_timeouts(self, mock_probe):
        mock_probe.side_effect = lambda entry, **kwargs: {
            "source_index": entry["source_index"],
            "proxy": proxy_display_name(entry["proxy"]),
            "ok": False,
            "code": "tcp_timeout",
            "message": "timeout",
            "http_status": None,
            "country": "",
            "latency_ms": 3000,
        }
        result = probe_raw_proxy_pool(
            [
                "http://user:secret@1.2.3.4:8080",
                "http://user:secret@1.2.3.5:8080",
            ],
            sample_size=20,
        )

        self.assertEqual(2, result["sampled_count"])
        self.assertEqual(0, result["ok_count"])
        self.assertEqual(2, result["status_counts"]["tcp_timeout"])
        self.assertIn("IP 白名单", result["recommendation"])


if __name__ == "__main__":
    unittest.main()
