import importlib.util
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "sub2-mihomo"


def load_manager():
    sys.path.insert(0, str(DEPLOY))
    spec = importlib.util.spec_from_file_location("sub2_mihomo_manager", DEPLOY / "manager.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class Sub2MihomoManagerTest(unittest.TestCase):
    def test_fixed_egress_config_is_exactly_ten(self):
        manager = load_manager()
        manager.controller_secret = lambda: "test-secret"
        settings = manager.normalized_settings({"egress_count": 99, "max_accounts_per_egress": 99})
        document = manager.config_document(settings)

        listeners = document["listeners"]
        self.assertEqual(len(listeners), 10)
        self.assertEqual([item["port"] for item in listeners], list(range(7901, 7911)))
        self.assertEqual(
            [item["proxy"] for item in listeners],
            [f"EGRESS-{index:02d}" for index in range(1, 11)],
        )
        self.assertEqual(settings["egress_count"], 10)
        self.assertEqual(settings["max_accounts_per_egress"], 2)

    def test_public_settings_do_not_expose_database_configuration(self):
        manager = load_manager()
        public = manager.public_settings(
            manager.normalized_settings(
                {
                    "sub2api_deploy_dir": "/secret/path",
                    "sub2api_postgres_container": "secret-container",
                }
            )
        )

        self.assertEqual(public["egress_count"], 10)
        self.assertEqual(public["max_accounts_per_egress"], 2)
        self.assertNotIn("sub2api_deploy_dir", public)
        self.assertNotIn("sub2api_postgres_container", public)

    def test_account_health_rejects_active_cooldown(self):
        manager = load_manager()
        self.assertTrue(manager._account_healthy({"status": "active", "temp_unschedulable_until": None}))
        self.assertFalse(
            manager._account_healthy(
                {"status": "active", "temp_unschedulable_until": "2999-01-01T00:00:00+00:00"}
            )
        )
        self.assertFalse(manager._account_healthy({"status": "error", "temp_unschedulable_until": None}))


if __name__ == "__main__":
    unittest.main()
