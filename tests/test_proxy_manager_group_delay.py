import unittest
from unittest.mock import patch

from utils import proxy_manager


class _Response:
    status_code = 200
    text = ""

    def json(self):
        return {"node-a": 120, "node-b": 240, "DIRECT": 1}


class ProxyManagerGroupDelayTests(unittest.TestCase):
    def test_group_delay_endpoint_is_used(self):
        with patch.object(proxy_manager.std_requests, "get", return_value=_Response()) as mock_get:
            delays = proxy_manager._fetch_group_delay_map(
                "http://127.0.0.1:19098",
                {"Authorization": "Bearer secret"},
                "PROXY",
                timeout_ms=3000,
            )

        self.assertEqual({"node-a": 120, "node-b": 240, "DIRECT": 1}, delays)
        requested_url = mock_get.call_args.args[0]
        self.assertEqual("http://127.0.0.1:19098/group/PROXY/delay", requested_url)
        self.assertNotIn("/proxies/", requested_url)


if __name__ == "__main__":
    unittest.main()
