import unittest
from unittest.mock import patch

import utils.proxy_manager as proxy_manager


class ProxyManagerV2rayNTests(unittest.TestCase):
    def test_switch_v2rayn_profile_marks_failed_node_invalid(self):
        profile = {"index_id": "abc", "remarks": "node-a", "address": "1.1.1.1", "port": 443, "subid": ""}

        with patch.object(proxy_manager, "V2RAYN_BASE_DIR", "C:\\v2rayn"), patch.object(
            proxy_manager, "_get_v2rayn_profile_by_id", return_value=profile
        ), patch.object(proxy_manager, "_activate_v2rayn_profile", return_value=(False, None, None)), patch.object(
            proxy_manager, "_mark_v2rayn_profile_valid"
        ) as mock_mark_valid, patch.object(proxy_manager, "_mark_v2rayn_profile_invalid") as mock_mark_invalid:
            result = proxy_manager.switch_v2rayn_profile("abc", proxy_url="http://127.0.0.1:7890")

        self.assertFalse(result["ok"])
        mock_mark_valid.assert_called_once_with("abc")
        mock_mark_invalid.assert_called_once_with("abc")
        self.assertIn("已自动标记为失效", result["message"])

    def test_switch_v2rayn_profile_returns_success_payload(self):
        profile = {"index_id": "xyz", "remarks": "node-b", "address": "2.2.2.2", "port": 443, "subid": ""}

        with patch.object(proxy_manager, "V2RAYN_BASE_DIR", "C:\\v2rayn"), patch.object(
            proxy_manager, "_get_v2rayn_profile_by_id", return_value=profile
        ), patch.object(proxy_manager, "_activate_v2rayn_profile", return_value=(True, "US", 321.0)), patch.object(
            proxy_manager, "_mark_v2rayn_profile_valid"
        ) as mock_mark_valid, patch.object(proxy_manager, "_mark_v2rayn_profile_invalid") as mock_mark_invalid:
            result = proxy_manager.switch_v2rayn_profile("xyz")

        self.assertTrue(result["ok"])
        mock_mark_valid.assert_called_once_with("xyz")
        mock_mark_invalid.assert_not_called()
        self.assertEqual(profile, result["profile"])
        self.assertIn("node-b", result["message"])
        self.assertIn("321.0ms / US", result["message"])


if __name__ == "__main__":
    unittest.main()
