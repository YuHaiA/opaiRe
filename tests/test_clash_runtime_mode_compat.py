# -*- coding: utf-8 -*-
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_detect_runtime_mode_respects_windows_single_core(monkeypatch, tmp_path):
    cm = importlib.import_module("utils.integrations.clash_manager")

    monkeypatch.setattr(cm, "_configured_runtime_mode", lambda: "windows_single_core")
    assert cm._detect_runtime_mode(client=object()) == "windows_single_core"
    assert cm._detect_runtime_mode(client=None) == "windows_single_core"


def test_detect_runtime_mode_keeps_server_modes(monkeypatch):
    cm = importlib.import_module("utils.integrations.clash_manager")

    monkeypatch.setattr(cm, "_configured_runtime_mode", lambda: "linux_single_core")
    assert cm._detect_runtime_mode(client=None) == "linux_single_core"

    monkeypatch.setattr(cm, "_configured_runtime_mode", lambda: "docker_pool")
    assert cm._detect_runtime_mode(client=object()) == "docker_pool"


def test_detect_runtime_mode_local_gui_explicit(monkeypatch):
    cm = importlib.import_module("utils.integrations.clash_manager")
    monkeypatch.setattr(cm, "_configured_runtime_mode", lambda: "local_gui")
    assert cm._detect_runtime_mode(client=None) == "local_gui"


def test_detect_native_linux_core_outside_path(monkeypatch, tmp_path):
    cm = importlib.import_module("utils.integrations.clash_manager")
    core = tmp_path / "mihomo"
    core.write_bytes(b"core")
    core.chmod(0o755)

    monkeypatch.setattr(cm.os, "name", "posix")
    monkeypatch.setenv("MIHOMO_BIN", str(core))

    assert cm._linux_mihomo_core_available() is True


def test_control_runtime_does_not_touch_external_windows_core(monkeypatch):
    cm = importlib.import_module("utils.integrations.clash_manager")
    monkeypatch.setattr(cm, "_detect_runtime_mode", lambda client: "windows_single_core")
    called = {"stop": 0, "start": 0}
    monkeypatch.setattr(cm, "_stop_single_core", lambda: called.__setitem__("stop", called["stop"] + 1))
    monkeypatch.setattr(cm, "_start_single_core", lambda: (True, "started"))

    ok, msg = cm.control_runtime("stop")
    assert ok is False
    assert "共享代理" in msg or "外部" in msg
    assert called["stop"] == 0
    assert called["start"] == 0


def test_patch_and_update_windows_mode_does_not_apply_controller(monkeypatch, tmp_path):
    cm = importlib.import_module("utils.integrations.clash_manager")
    monkeypatch.setattr(cm, "_detect_runtime_mode", lambda client: "windows_single_core")
    monkeypatch.setattr(cm, "get_client", lambda: None)
    monkeypatch.setattr(cm, "_normalize_single_subscription_url", lambda url, resolved_url="": "https://example.com/sub")
    monkeypatch.setattr(cm, "_persist_sub_url", lambda url, subscription_id="": None)
    monkeypatch.setattr(cm, "_build_requests_proxies", lambda: None)
    monkeypatch.setattr(cm, "MANUAL_SUBSCRIPTION_PATH", str(tmp_path / "sub.txt"))
    monkeypatch.setattr(cm, "MANUAL_CONFIG_PATH", str(tmp_path / "manual.yaml"))
    monkeypatch.setattr(cm, "BASE_PATH", str(tmp_path))

    monkeypatch.setattr(
        cm,
        "fetch_subscription_text",
        lambda *a, **k: SimpleNamespace(
            ok=True,
            text="proxies: []\nproxy-groups: []\n",
            message="",
        ),
    )
    applied = {"n": 0}
    monkeypatch.setattr(cm, "_apply_config_to_controller", lambda *a, **k: applied.__setitem__("n", applied["n"] + 1) or (True, "ok"))
    monkeypatch.setattr(cm, "_write_single_core_config", lambda raw: applied.__setitem__("n", applied["n"] + 10) or raw)
    monkeypatch.setattr(cm, "_start_single_core", lambda: applied.__setitem__("n", applied["n"] + 100) or (True, "start"))

    ok, msg = cm.patch_and_update("https://example.com/sub", "all")
    assert ok is True
    assert applied["n"] == 0
    assert "共享" in msg or "外部" in msg
