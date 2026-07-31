"""FastAPI routes for CPA email relay (server side).

Official CF Worker path:
  POST /api/webhook/email
  Header: X-Webhook-Secret
  Body: {message_id, to_addr, raw_content}

opaiRe client paths (local pull):
  GET  /api/email-bridge/health
  POST /api/email-bridge/webhook
  GET  /api/email-bridge/check/{address}
  WS   /api/email-bridge/ws/{address}
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import unquote

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, WebSocketDisconnect

from utils import config as cfg
from utils.email_bridge import get_relay, parse_webhook_payload, token_matches

router = APIRouter(tags=["email-bridge"])


def _expected_token() -> str:
    # Prefer dedicated bridge token, fallback to openai_cpa webhook secret.
    token = str(getattr(cfg, "OPENAI_CPA_BRIDGE_TOKEN", "") or "").strip()
    if token:
        return token
    return str(getattr(cfg, "OPENAI_CPA_WEBHOOK_SECRET", "") or "").strip()


def _require_token(*candidates: Optional[str]) -> None:
    expected = _expected_token()
    for item in candidates:
        if token_matches(item, expected):
            return
    raise HTTPException(status_code=401, detail="unauthorized")


async def _handle_webhook(
    request: Request,
    authorization: Optional[str] = None,
    x_webhook_token: Optional[str] = None,
    x_email_webhook_secret: Optional[str] = None,
    x_webhook_secret: Optional[str] = None,
):
    # Official Worker uses X-Webhook-Secret; keep Bearer / x-webhook-token for local tools.
    _require_token(authorization, x_webhook_token, x_email_webhook_secret, x_webhook_secret)
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="invalid payload")

    address, sender, code, raw_text = parse_webhook_payload(data)
    if not address or not code:
        return {"ok": True, "stored": False, "reason": "missing address or code"}

    relay = get_relay()
    delivered = await relay.publish(address, code, sender=sender, raw_text=raw_text)
    injected = False
    # local_webhook / dual: CF Worker (or Tunnel) hits this process directly.
    if bool(getattr(cfg, "OPENAI_CPA_LOCAL_WEBHOOK", False)):
        try:
            from utils.email_bridge.client import inject_code_pool

            injected = bool(inject_code_pool(address, code, raw_text or code))
        except Exception:
            injected = False
    return {
        "ok": True,
        "stored": True,
        "email": address,
        "delivered": delivered,
        "injected": injected,
        "receive_mode": str(getattr(cfg, "OPENAI_CPA_RECEIVE_MODE", "") or ""),
    }


@router.get("/api/email-bridge/health")
async def email_bridge_health():
    relay = get_relay()
    return {
        "status": "ok",
        "listeners": sum(len(v) for v in relay.listeners.values()),
        "receive_mode": str(getattr(cfg, "OPENAI_CPA_RECEIVE_MODE", "") or ""),
        "bridge_enabled": bool(getattr(cfg, "OPENAI_CPA_BRIDGE_ENABLED", False)),
        "local_webhook": bool(getattr(cfg, "OPENAI_CPA_LOCAL_WEBHOOK", False)),
    }


@router.post("/api/email-bridge/webhook")
async def email_bridge_webhook(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_webhook_token: Optional[str] = Header(default=None),
    x_email_webhook_secret: Optional[str] = Header(default=None),
    x_webhook_secret: Optional[str] = Header(default=None),
):
    return await _handle_webhook(
        request,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_email_webhook_secret=x_email_webhook_secret,
        x_webhook_secret=x_webhook_secret,
    )


@router.post("/api/webhook/email")
async def openai_cpa_email_webhook(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_webhook_token: Optional[str] = Header(default=None),
    x_email_webhook_secret: Optional[str] = Header(default=None),
    x_webhook_secret: Optional[str] = Header(default=None),
):
    """Official openai-cpa-email Worker endpoint (auto path append target)."""
    return await _handle_webhook(
        request,
        authorization=authorization,
        x_webhook_token=x_webhook_token,
        x_email_webhook_secret=x_email_webhook_secret,
        x_webhook_secret=x_webhook_secret,
    )


@router.get("/api/email-bridge/check/{address:path}")
async def email_bridge_check(
    address: str,
    authorization: Optional[str] = Header(default=None),
    x_webhook_token: Optional[str] = Header(default=None),
    x_webhook_secret: Optional[str] = Header(default=None),
):
    _require_token(authorization, x_webhook_token, x_webhook_secret)
    row = await get_relay().latest(unquote(address))
    if not row:
        return {"code": None}
    return {"code": row[0], "from": row[1], "raw_text": row[2]}


@router.websocket("/api/email-bridge/ws/{address:path}")
async def email_bridge_ws(websocket: WebSocket, address: str):
    auth = (
        websocket.headers.get("authorization")
        or websocket.headers.get("x-webhook-secret")
        or websocket.query_params.get("token")
    )
    try:
        _require_token(auth)
    except HTTPException:
        await websocket.close(code=4401)
        return

    address = unquote(address).lower().strip()
    if not address:
        await websocket.close(code=4400)
        return

    await websocket.accept()
    relay = get_relay()
    relay.listeners[address].add(websocket)
    try:
        row = await relay.latest(address)
        if row:
            await websocket.send_json(
                {"code": row[0], "from": row[1], "email": address, "raw_text": row[2]}
            )
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        relay.listeners[address].discard(websocket)
        if not relay.listeners.get(address):
            relay.listeners.pop(address, None)
