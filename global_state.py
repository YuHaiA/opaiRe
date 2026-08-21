import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import deque
from fastapi import Header, HTTPException
from utils import core_engine
import utils.config as cfg

VALID_TOKENS = set()
AUTH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
_AUTH_TOKEN_VERSION = "v1"
_AUTH_TOKEN_CONTEXT = b"opaire-web-session-v1\0"
_AUTH_SECRET_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", ".auth_token_secret")
_auth_secret_cache = None
_auth_secret_lock = threading.Lock()
CLUSTER_NODES = {}
NODE_COMMANDS = {}
cluster_lock = threading.Lock()
log_history = deque(maxlen=cfg.MAX_LOG_LINES)
worker_status: dict = {}
engine = core_engine.RegEngine()


def append_log(msg: str):
    log_history.append(msg)


def _auth_secret_bytes() -> bytes:
    global _auth_secret_cache
    if _auth_secret_cache is not None:
        return _auth_secret_cache
    with _auth_secret_lock:
        if _auth_secret_cache is not None:
            return _auth_secret_cache
        try:
            with open(_AUTH_SECRET_PATH, "rb") as secret_file:
                secret = secret_file.read().strip()
        except FileNotFoundError:
            secret = b""
        if len(secret) < 32:
            os.makedirs(os.path.dirname(_AUTH_SECRET_PATH), exist_ok=True)
            secret = secrets.token_hex(32).encode("ascii")
            try:
                fd = os.open(_AUTH_SECRET_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as secret_file:
                    secret_file.write(secret)
            except FileExistsError:
                with open(_AUTH_SECRET_PATH, "rb") as secret_file:
                    secret = secret_file.read().strip()
        _auth_secret_cache = secret
        return secret


def _auth_signing_key() -> bytes:
    password = str(getattr(cfg, "WEB_PASSWORD", "admin") or "admin")
    return hmac.new(
        _auth_secret_bytes(), _AUTH_TOKEN_CONTEXT + password.encode("utf-8"), hashlib.sha256
    ).digest()


def create_auth_token() -> str:
    issued_at = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    payload = f"{_AUTH_TOKEN_VERSION}.{issued_at}.{nonce}"
    signature = hmac.new(_auth_signing_key(), payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def is_valid_auth_token(token: str) -> bool:
    token = str(token or "").strip()
    if not token:
        return False
    # Keep compatibility with in-memory tokens used by extensions and older tests.
    if token in VALID_TOKENS:
        return True

    try:
        version, issued_at_raw, nonce, supplied_signature = token.split(".", 3)
        if version != _AUTH_TOKEN_VERSION or not nonce:
            return False
        issued_at = int(issued_at_raw)
    except (TypeError, ValueError):
        return False

    now = int(time.time())
    if issued_at > now + 300 or now - issued_at > AUTH_TOKEN_TTL_SECONDS:
        return False

    payload = f"{version}.{issued_at_raw}.{nonce}"
    expected_signature = hmac.new(
        _auth_signing_key(), payload.encode("ascii"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(supplied_signature, expected_signature)


async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效凭证")
    token = authorization.split(" ", 1)[1].strip()
    if not is_valid_auth_token(token):
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return token
