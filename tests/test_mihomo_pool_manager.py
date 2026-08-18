from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


MANAGER_DIR = Path(__file__).resolve().parents[1] / "deploy" / "sub2-mihomo"
sys.path.insert(0, str(MANAGER_DIR))
SPEC = importlib.util.spec_from_file_location("sub2_mihomo_manager", MANAGER_DIR / "manager.py")
assert SPEC is not None and SPEC.loader is not None
manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(manager)


def _proxies(count: int) -> list[dict[str, object]]:
    return [
        {"id": index, "name": f"mihomo-egress-{index:02d}", "port": 7900 + index}
        for index in range(1, count + 1)
    ]


def _accounts(group_id: int, count: int, start_id: int) -> list[dict[str, object]]:
    return [
        {
            "id": start_id + offset,
            "group_ids": [group_id],
            "proxy_id": None,
            "last_used_at": "",
        }
        for offset in range(count)
    ]


def test_allocate_accounts_spreads_each_group_across_all_egresses() -> None:
    proxies = _proxies(10)
    candidates = _accounts(5, 30, 100) + _accounts(6, 30, 200)

    slots, selected = manager._allocate_accounts_to_egresses(candidates, proxies, 2)

    assert len(selected) == 20
    for bound in slots.values():
        assert len(bound) == 2
        assert {manager._account_group_ids(account) for account in bound} == {(5,), (6,)}


def test_allocate_accounts_prefers_existing_binding_when_distribution_is_equal() -> None:
    proxies = _proxies(2)
    candidates = _accounts(5, 2, 100) + _accounts(6, 2, 200)
    candidates[0]["proxy_id"] = 2
    candidates[2]["proxy_id"] = 1

    slots, selected = manager._allocate_accounts_to_egresses(candidates, proxies, 2)

    assert selected[100] == 2
    assert selected[200] == 1
    assert all(len(bound) == 2 for bound in slots.values())


def test_failed_egress_can_reuse_cooled_but_unoccupied_candidate() -> None:
    selected_nodes: list[str] = []
    state = {
        "node_last_used_at": {"cooled-node": manager.utc_now()},
        "ip_last_used_at": {"203.0.113.10": manager.utc_now()},
    }

    with (
        patch.object(manager, "select_proxy", side_effect=lambda node, _group: selected_nodes.append(node)),
        patch.object(manager, "probe_egress_ip", return_value="203.0.113.10"),
        patch.object(manager, "probe_grok_egress", return_value=401),
    ):
        node, exit_ip, _ = manager._select_unique_egress_candidate(
            index=3,
            current="broken-node",
            current_ip="198.51.100.10",
            healthy_names=["cooled-node"],
            state=state,
            reserved_nodes=set(),
            reserved_ips=set(),
            start=0,
            cooldown_minutes=60,
            allow_recent_fallback=True,
        )

    assert node == "cooled-node"
    assert exit_ip == "203.0.113.10"
    assert selected_nodes == ["cooled-node"]
