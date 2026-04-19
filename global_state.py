import threading
from collections import deque
from fastapi import Header, HTTPException
from utils import core_engine

VALID_TOKENS = set()
CLUSTER_NODES = {}
NODE_COMMANDS = {}
CLUSTER_NODE_BLOCKLIST = set()
cluster_lock = threading.Lock()
cluster_runtime_lock = threading.Lock()
CLUSTER_RUNTIME_STATUS = {
    "enabled": True,
    "connected": False,
    "transport": "idle",
    "master_url": "",
    "node_name": "",
    "last_error": "",
    "last_event": 0.0,
    "last_report_at": 0.0,
    "last_command": "none",
}
log_history = deque(maxlen=500)
worker_status: dict = {}
engine = core_engine.RegEngine()

async def verify_token(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效凭证")
    token = authorization.split(" ")[1]
    if token not in VALID_TOKENS:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    return token
