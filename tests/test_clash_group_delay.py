# -*- coding: utf-8 -*-
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_group_delay_preferred_over_node_404(monkeypatch):
    cm = importlib.import_module("utils.integrations.clash_manager")
    monkeypatch.setattr(
        cm,
        "_fetch_controller_proxies",
        lambda target="all": {
            "PROXY": {"type": "Selector", "all": ["leaf-a", "AUTO", "DIRECT"], "now": "leaf-a"},
            "AUTO": {"type": "URLTest", "all": ["leaf-a"]},
            "DIRECT": {"type": "Direct"},
        },
    )
    monkeypatch.setattr(cm, "_get_controller_endpoint", lambda target="all": ("http://127.0.0.1:19098", "secret"))
    monkeypatch.setattr(cm, "_read_runtime_config", lambda: {"clash_proxy_pool": {}})
    monkeypatch.setattr(cm, "_enrich_nodes_with_providers", lambda *a, **k: ["leaf-a", "leaf-b"])
    monkeypatch.setattr(cm, "_persist_tested_nodes", lambda *a, **k: None)
    monkeypatch.setattr(
        cm,
        "_fetch_group_delay_map",
        lambda *a, **k: {"leaf-a": 120, "leaf-b": 200, "AUTO": 150, "DIRECT": 10},
    )
    ok, res = cm.test_group_latency("PROXY")
    assert ok is True
    assert res["method"] == "group_delay"
    assert "leaf-a" in res["healthy_nodes"]
    assert "leaf-b" in res["healthy_nodes"]
    assert "DIRECT" not in res["healthy_nodes"]
    assert "AUTO" not in res["healthy_nodes"]


if __name__ == "__main__":
    class MP:
        def __init__(self):
            self._s = []
        def setattr(self, obj, name, value):
            if isinstance(obj, str):
                obj = importlib.import_module(obj)
            old = getattr(obj, name)
            self._s.append((obj, name, old))
            setattr(obj, name, value)
        def undo(self):
            for o, n, v in reversed(self._s):
                setattr(o, n, v)

    mp = MP()
    try:
        test_group_delay_preferred_over_node_404(mp)
        print("PASS")
    finally:
        mp.undo()
