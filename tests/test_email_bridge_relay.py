from fastapi.testclient import TestClient

from routers import email_bridge_routes
from utils.email_bridge import extract_code, parse_webhook_payload


def test_extract_code_openai_style():
    assert extract_code("Your ChatGPT code is 123456") == "123456"
    assert extract_code("enter this code: 654321") == "654321"

def test_extract_code_grok_spacexai():
    raw = """From: SpaceXAI <noreply@x.ai>
Subject: SpaceXAI confirmation code: 881-ELG
To: user@example.com

Thank you for creating a SpaceXAI account.
"""
    assert extract_code(raw) == "881-ELG"


def test_extract_code_ignores_header_digit_junk_when_xai_present():
    raw = """Received: from wfbtsnfp.outbound-mail.sendgrid.net (159.183.98.243)
 by cloudflare-email.net with id 410418
From: SpaceXAI <noreply@x.ai>
Subject: SpaceXAI confirmation code: 1E0-T5K

body
"""
    assert extract_code(raw) == "1E0-T5K"



def test_parse_webhook_payload_flexible():
    address, sender, code, raw = parse_webhook_payload(
        {
            "to": "User@Example.COM",
            "from": "noreply@openai.com",
            "subject": "OpenAI",
            "text": "Your ChatGPT code is 112233",
        }
    )
    assert address == "user@example.com"
    assert code == "112233"
    assert "112233" in raw


def test_parse_official_cpa_worker_payload():
    address, sender, code, raw = parse_webhook_payload(
        {
            "message_id": "<abc@openai.com>",
            "to_addr": "Alias <User@Example.COM>",
            "raw_content": "Subject: Verify\n\nYour ChatGPT code is 445566\n",
        }
    )
    assert address == "user@example.com"
    assert code == "445566"
    assert "445566" in raw


def test_webhook_and_check_and_ws(tmp_path, monkeypatch):
    from utils import email_bridge as eb

    relay = eb.EmailCodeRelay(db_path=tmp_path / "codes.db", ttl_sec=120)
    monkeypatch.setattr(email_bridge_routes, "get_relay", lambda: relay)
    monkeypatch.setattr(email_bridge_routes, "_expected_token", lambda: "secret")

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(email_bridge_routes.router)
    client = TestClient(app)

    headers = {"Authorization": "Bearer secret"}
    with client.websocket_connect("/api/email-bridge/ws/a@b.com", headers=headers) as ws:
        resp = client.post(
            "/api/email-bridge/webhook",
            headers=headers,
            json={"to": "a@b.com", "from": "x", "text": "Your ChatGPT code is 998877"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["stored"] is True
        assert body["delivered"] == 1
        msg = ws.receive_json()
        assert msg["code"] == "998877"

    check = client.get("/api/email-bridge/check/a@b.com", headers=headers)
    assert check.json()["code"] == "998877"


def test_official_webhook_path_and_header(tmp_path, monkeypatch):
    from utils import email_bridge as eb
    from fastapi import FastAPI

    relay = eb.EmailCodeRelay(db_path=tmp_path / "codes2.db", ttl_sec=120)
    monkeypatch.setattr(email_bridge_routes, "get_relay", lambda: relay)
    monkeypatch.setattr(email_bridge_routes, "_expected_token", lambda: "cpa-secret")

    app = FastAPI()
    app.include_router(email_bridge_routes.router)
    client = TestClient(app)

    resp = client.post(
        "/api/webhook/email",
        headers={"X-Webhook-Secret": "cpa-secret"},
        json={
            "message_id": "<m1>",
            "to_addr": "otp@example.com",
            "raw_content": "Your ChatGPT code is 777888",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["stored"] is True
    assert resp.json()["email"] == "otp@example.com"

    check = client.get(
        "/api/email-bridge/check/otp@example.com",
        headers={"Authorization": "Bearer cpa-secret"},
    )
    assert check.json()["code"] == "777888"


def test_normalize_openai_cpa_receive_mode():
    from utils.config import (
        normalize_openai_cpa_receive_mode,
        openai_cpa_local_webhook_enabled,
        openai_cpa_remote_bridge_enabled,
    )

    assert normalize_openai_cpa_receive_mode("remote_bridge") == "remote_bridge"
    assert normalize_openai_cpa_receive_mode("tunnel") == "local_webhook"
    assert normalize_openai_cpa_receive_mode("both") == "dual"
    assert normalize_openai_cpa_receive_mode("", bridge_enabled=True) == "remote_bridge"
    assert normalize_openai_cpa_receive_mode("", bridge_enabled=False) == "local_webhook"
    assert openai_cpa_remote_bridge_enabled("dual") is True
    assert openai_cpa_local_webhook_enabled("dual") is True
    assert openai_cpa_local_webhook_enabled("remote_bridge") is False


def test_local_webhook_injects_code_pool(tmp_path, monkeypatch):
    from utils import email_bridge as eb
    from fastapi import FastAPI
    import utils.email_bridge.client as client

    relay = eb.EmailCodeRelay(db_path=tmp_path / "codes-local.db", ttl_sec=120)
    monkeypatch.setattr(email_bridge_routes, "get_relay", lambda: relay)
    monkeypatch.setattr(email_bridge_routes, "_expected_token", lambda: "local-secret")
    monkeypatch.setattr(email_bridge_routes.cfg, "OPENAI_CPA_LOCAL_WEBHOOK", True, raising=False)
    monkeypatch.setattr(email_bridge_routes.cfg, "OPENAI_CPA_RECEIVE_MODE", "local_webhook", raising=False)

    pool = {}

    def fake_inject(email, code, raw_text=""):
        pool[str(email).lower()] = raw_text or code
        return True

    monkeypatch.setattr(client, "inject_code_pool", fake_inject)

    app = FastAPI()
    app.include_router(email_bridge_routes.router)
    http = TestClient(app)
    resp = http.post(
        "/api/webhook/email",
        headers={"X-Webhook-Secret": "local-secret"},
        json={
            "message_id": "<m-local>",
            "to_addr": "local@example.com",
            "raw_content": "Your ChatGPT code is 135791",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stored"] is True
    assert body["injected"] is True
    assert "135791" in str(pool.get("local@example.com", ""))


def test_remote_bridge_mode_skips_local_inject(tmp_path, monkeypatch):
    from utils import email_bridge as eb
    from fastapi import FastAPI
    import utils.email_bridge.client as client

    relay = eb.EmailCodeRelay(db_path=tmp_path / "codes-remote.db", ttl_sec=120)
    monkeypatch.setattr(email_bridge_routes, "get_relay", lambda: relay)
    monkeypatch.setattr(email_bridge_routes, "_expected_token", lambda: "remote-secret")
    monkeypatch.setattr(email_bridge_routes.cfg, "OPENAI_CPA_LOCAL_WEBHOOK", False, raising=False)
    monkeypatch.setattr(email_bridge_routes.cfg, "OPENAI_CPA_RECEIVE_MODE", "remote_bridge", raising=False)

    called = {"n": 0}

    def fake_inject(*args, **kwargs):
        called["n"] += 1
        return True

    monkeypatch.setattr(client, "inject_code_pool", fake_inject)

    app = FastAPI()
    app.include_router(email_bridge_routes.router)
    http = TestClient(app)
    resp = http.post(
        "/api/webhook/email",
        headers={"X-Webhook-Secret": "remote-secret"},
        json={
            "to_addr": "remote@example.com",
            "raw_content": "Your ChatGPT code is 246810",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["stored"] is True
    assert resp.json().get("injected") is False
    assert called["n"] == 0
