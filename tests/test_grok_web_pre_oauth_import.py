import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# register imports browser modules that are unavailable in the minimal test image.
_ce = types.ModuleType("utils.core_engine")
_ce.grok2api_admin_login = lambda: (True, "admin-token", "ok")
_ce._grok2api_import_web_sso = lambda sso, token: (True, "web result")
_ce._grok2api_import_expires_at = lambda d: ""
_ce._grok2api_import_payload = lambda d: {}
_ce.cfg = None
_ce.ts = lambda: ""
_hero = types.ModuleType("utils.integrations.hero_sms")
_hero._try_verify_phone_via_hero_sms = lambda *a, **k: (False, "")
_hero.get_phone_for_signup = lambda *a, **k: (False, "")
_hero.wait_code_for_signup = lambda *a, **k: (False, "")
_hero.report_signup_result = lambda *a, **k: None
_core = types.ModuleType("utils.auth_core")
_core.generate_payload = lambda *a, **k: {}

_IMPORT_STUBS = {
    "camoufox": types.SimpleNamespace(Camoufox=object),
    "utils.integrations.hero_sms": _hero,
    "utils.auth_core": _core,
}
_previous_modules = {name: sys.modules.get(name) for name in _IMPORT_STUBS}
try:
    sys.modules.update(_IMPORT_STUBS)
    from utils.grok_auth import register
finally:
    for name, previous in _previous_modules.items():
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


class _OAuth:
    token = {"access_token": "build-access", "refresh_token": "build-refresh"}
    userinfo = {"email": "test@example.com"}


def _install_core_engine_stub(monkeypatch):
    import utils

    monkeypatch.setitem(sys.modules, "utils.core_engine", _ce)
    monkeypatch.setattr(utils, "core_engine", _ce, raising=False)


def _run(monkeypatch, events, *, enabled=True, web_ok=True, status_ok=True):
    _install_core_engine_stub(monkeypatch)
    monkeypatch.setattr(register.cfg, "GROK2API_IMPORT_SSO_AS_GROK_WEB", enabled, raising=False)
    monkeypatch.setattr(register.cfg, "GROK2API_SSO_ONLY_MODE", False, raising=False)
    monkeypatch.setattr(register, "ensure_camoufox", lambda force=False: (True, ""))
    monkeypatch.setattr(register, "get_email_and_token", lambda *a, **k: ("test@example.com", "mail-token"))
    monkeypatch.setattr(register, "set_last_email", lambda email: None)
    monkeypatch.setattr(register, "signup_with_camoufox", lambda *a, **k: {
        "ok": True,
        "sso": "sso-secret",
        "cookies": {"sso": "sso-secret"},
    })
    monkeypatch.setattr(register, "inspect_sso_account_state", lambda *a, **k: (
        {"found": True, "bot_flag_source": 0, "denied": False, "risk": 0.1}
        if status_ok else
        {"found": False, "error": "TLS connect error"}
    ))

    def complete(*args, **kwargs):
        events.append("build_oauth")
        return _OAuth()

    monkeypatch.setattr(register, "complete_build_oauth", complete)
    monkeypatch.setattr(register, "build_cliproxyapi_auth_record", lambda *a, **k: {"email": "test@example.com"})

    monkeypatch.setattr(_ce, "grok2api_admin_login", lambda: (True, "admin-token", "ok"))

    def import_web(sso, token):
        events.append("grok_web")
        assert sso == "sso-secret"
        assert token == "admin-token"
        return web_ok, "web result"

    monkeypatch.setattr(_ce, "_grok2api_import_web_sso", import_web)
    ctx = {}
    result = register.run(run_ctx=ctx)
    return result, ctx


def test_enabled_imports_grok_web_before_build_oauth(monkeypatch):
    events = []
    result, ctx = _run(monkeypatch, events, enabled=True, web_ok=True)
    assert result[0]
    assert events == ["grok_web", "build_oauth"]
    assert ctx["grok_web_import_ok"] is True


def test_grok_web_failure_does_not_block_build_oauth(monkeypatch):
    events = []
    result, ctx = _run(monkeypatch, events, enabled=True, web_ok=False)
    assert result[0]
    assert events == ["grok_web", "build_oauth"]
    assert ctx["grok_web_import_ok"] is False


def test_disabled_skips_grok_web_and_keeps_build_oauth(monkeypatch):
    events = []
    result, ctx = _run(monkeypatch, events, enabled=False)
    assert result[0]
    assert events == ["build_oauth"]
    assert "grok_web_import_ok" not in ctx


def test_status_probe_failure_discards_before_build_oauth(monkeypatch):
    events = []
    result, ctx = _run(monkeypatch, events, status_ok=False)
    assert result == (None, None)
    assert events == []
    assert ctx["discarded"] is True
    assert ctx["discard_reason"] == "status_check_failed"


def _run_sso_only(monkeypatch, events, *, enabled=True, web_ok=True):
    _install_core_engine_stub(monkeypatch)
    monkeypatch.setattr(register.cfg, "GROK2API_IMPORT_SSO_AS_GROK_WEB", enabled, raising=False)
    monkeypatch.setattr(register, "ensure_camoufox", lambda force=False: (True, ""))
    monkeypatch.setattr(register, "get_email_and_token", lambda *a, **k: ("test@example.com", "mail-token"))
    monkeypatch.setattr(register, "set_last_email", lambda email: None)
    monkeypatch.setattr(register, "signup_with_camoufox", lambda *a, **k: {
        "ok": True,
        "sso": "sso-secret",
        "cookies": {"sso": "sso-secret"},
    })
    monkeypatch.setattr(register, "inspect_sso_account_state", lambda *a, **k: {
        "found": True,
        "bot_flag_source": 0,
        "denied": False,
        "risk": 0.0,
        "error": "",
    })

    def complete(*args, **kwargs):
        events.append("build_oauth")
        return _OAuth()

    monkeypatch.setattr(register, "complete_build_oauth", complete)

    monkeypatch.setattr(_ce, "grok2api_admin_login", lambda: (True, "admin-token", "ok"))

    def import_web(sso, token):
        events.append("grok_web")
        assert sso == "sso-secret"
        assert token == "admin-token"
        return web_ok, "web result"

    monkeypatch.setattr(_ce, "_grok2api_import_web_sso", import_web)
    ctx = {}
    result = register.run(run_ctx=ctx, sso_only=True)
    return result, ctx


def test_sso_only_skips_build_oauth_and_imports_grok_web(monkeypatch):
    events = []
    result, ctx = _run_sso_only(monkeypatch, events, enabled=True, web_ok=True)
    token_json_str, password = result
    assert token_json_str is not None
    assert password
    assert events == ["grok_web"]
    import json
    record = json.loads(token_json_str)
    assert record["email"] == "test@example.com"
    assert record["sso"] == "sso-secret"
    assert record["password"] == password
    assert record["status"] == "grok_sso"
    assert record["provider"] == "grok"


def test_sso_only_with_grok_web_failure(monkeypatch):
    events = []
    result, ctx = _run_sso_only(monkeypatch, events, enabled=True, web_ok=False)
    token_json_str, password = result
    assert token_json_str is not None
    assert events == ["grok_web"]
    assert ctx["grok_web_import_ok"] is False


def test_sso_only_disabled_grok_web_import(monkeypatch):
    events = []
    result, ctx = _run_sso_only(monkeypatch, events, enabled=False)
    token_json_str, password = result
    assert token_json_str is not None
    assert events == []
    assert "grok_web_import_ok" not in ctx


def test_sso_only_runs_status_check(monkeypatch):
    events = []
    _install_core_engine_stub(monkeypatch)
    monkeypatch.setattr(register.cfg, "GROK2API_IMPORT_SSO_AS_GROK_WEB", True, raising=False)
    monkeypatch.setattr(register, "ensure_camoufox", lambda force=False: (True, ""))
    monkeypatch.setattr(register, "get_email_and_token", lambda *a, **k: ("test@example.com", "mail-token"))
    monkeypatch.setattr(register, "set_last_email", lambda email: None)
    monkeypatch.setattr(register, "signup_with_camoufox", lambda *a, **k: {
        "ok": True,
        "sso": "sso-secret",
        "cookies": {"sso": "sso-secret"},
    })

    risk_checked = []
    def fake_inspect(cookies, proxy=""):
        risk_checked.append(True)
        return {"found": True, "bot_flag_source": 0, "denied": False, "risk": 0.0, "error": ""}
    monkeypatch.setattr(register, "inspect_sso_account_state", fake_inspect)
    monkeypatch.setattr(register.cfg, "DISCARD_ON_DOWNGRADE", True, raising=False)

    def import_web(sso, token):
        events.append("grok_web")
        return True, "web result"
    monkeypatch.setattr(_ce, "_grok2api_import_web_sso", import_web)

    ctx = {}
    result = register.run(run_ctx=ctx, sso_only=True)
    token_json_str, password = result
    assert token_json_str is not None
    assert risk_checked == [True]
    assert events == ["grok_web"]
