import importlib.util
import sys
from pathlib import Path
import tempfile
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
        self.assertEqual(settings["max_accounts_per_egress"], 20)
        self.assertEqual(settings["node_test_minutes"], 5)
        self.assertTrue(settings["egress_auto_rotate_enabled"])

    def test_cached_healthy_nodes_exclude_failed_and_unknown(self):
        manager = load_manager()
        manager.load_delay_cache = lambda: {
            "tested_at": "2026-08-14T00:00:00+00:00",
            "rows": {
                "alive": {"ok": True, "delay": 88},
                "failed": {"ok": False, "delay": 0},
            },
        }

        self.assertEqual(
            manager.cached_healthy_node_names(["unknown", "failed", "alive"]),
            ["alive"],
        )

    def test_rotate_egresses_uses_only_cached_healthy_nodes(self):
        manager = load_manager()
        healthy = [f"healthy-{index}" for index in range(12)]
        selected = []
        saved = {}
        manager.controller_online = lambda: True
        manager.provider_node_names = lambda: ["failed", *healthy]
        manager.node_test_due = lambda settings=None: False
        manager.load_delay_cache = lambda: {
            "tested_at": "2026-08-14T00:00:00+00:00",
            "rows": {
                "failed": {"ok": False, "delay": 0},
                **{name: {"ok": True, "delay": 100} for name in healthy},
            },
        }
        manager.load_egress_state = lambda: {"cursor": 0, "assignments": {}}
        manager.save_egress_state = lambda state: saved.update(state)
        manager.select_proxy = lambda name, group: selected.append((group, name))

        result = manager.rotate_egresses()

        self.assertEqual(result["count"], 10)
        self.assertEqual(result["healthy_nodes"], 12)
        self.assertEqual(len(selected), 10)
        self.assertNotIn("failed", [name for _, name in selected])
        self.assertEqual(len(set(name for _, name in selected)), 10)
        self.assertEqual(len(saved["assignments"]), 10)

    def test_rotate_one_egress_uses_unoccupied_healthy_node(self):
        manager = load_manager()
        healthy = [f"healthy-{index}" for index in range(12)]
        assignments = {
            manager.egress_group_name(index): healthy[index - 1]
            for index in range(1, 11)
        }
        selected = []
        saved = {}
        manager.controller_online = lambda: True
        manager.provider_node_names = lambda: list(healthy)
        manager.node_test_due = lambda settings=None: False
        manager.load_delay_cache = lambda: {
            "tested_at": "2026-08-14T00:00:00+00:00",
            "rows": {name: {"ok": True, "delay": 100} for name in healthy},
        }
        manager.load_egress_state = lambda: {"cursor": 0, "assignments": dict(assignments)}
        manager.current_egress_assignments = lambda state=None: dict(assignments)
        manager.select_proxy = lambda name, group: selected.append((group, name))
        manager.save_egress_state = lambda state: saved.update(state)
        manager.load_settings = lambda: manager.normalized_settings()

        result = manager.rotate_egress(3)

        self.assertEqual(result["index"], 3)
        self.assertEqual(result["previous"], "healthy-2")
        self.assertEqual(result["node"], "healthy-10")
        self.assertEqual(selected, [(manager.egress_group_name(3), "healthy-10")])
        self.assertEqual(len(set(saved["assignments"].values())), 10)

    def test_repair_egresses_only_switches_failed_assignments(self):
        manager = load_manager()
        healthy = [f"healthy-{index}" for index in range(12)]
        live = {
            manager.egress_group_name(index): healthy[index - 1]
            for index in range(1, 11)
        }
        live[manager.egress_group_name(6)] = "failed"
        selected = []
        saved = {}
        manager.load_egress_state = lambda: {"cursor": 0, "assignments": dict(live)}
        manager.controller_request = lambda path, timeout=10: {
            "proxies": {group: {"now": node} for group, node in live.items()}
        }
        manager.select_proxy = lambda name, group: selected.append((group, name))
        manager.save_egress_state = lambda state: saved.update(state)

        result = manager.repair_unhealthy_egresses(healthy)

        self.assertEqual(result["switched"], 1)
        self.assertEqual(selected[0][0], manager.egress_group_name(6))
        self.assertEqual(len(set(saved["assignments"].values())), 10)

    def test_node_test_requires_grok_and_openai_targets(self):
        manager = load_manager()
        responses = iter(
            [
                {"both": 120, "grok-only": 100},
                {"both": 180, "grok-only": 0},
            ]
        )
        manager.controller_online = lambda: True
        manager.provider_node_names = lambda: ["both", "grok-only"]
        manager.controller_request = lambda *args, **kwargs: next(responses)

        with tempfile.TemporaryDirectory() as temp_dir:
            manager.DELAYS_FILE = Path(temp_dir) / "delays.json"
            result = manager.test_nodes(repair=False)
            cache = manager.load_delay_cache()

        self.assertEqual(result["alive"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(cache["rows"]["both"], {"ok": True, "delay": 180})
        self.assertEqual(cache["rows"]["grok-only"], {"ok": False, "delay": 0})

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
        self.assertTrue(public["egress_auto_rotate_enabled"])
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
