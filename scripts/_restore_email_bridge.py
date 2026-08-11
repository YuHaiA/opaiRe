from pathlib import Path

# 1) api_routes
api = Path(r"C:\Users\yu\Desktop\opaiRe\routers\api_routes.py")
api.write_text(
'''from fastapi import APIRouter
from . import system_routes
from . import account_routes
from . import service_routes
from . import sms_routes
from . import email_bridge_routes
from utils.auth_core import router as email_router
from utils.auth_core import code_pool, cache_lock, generate_payload

router = APIRouter()

router.include_router(system_routes.router)
router.include_router(account_routes.router)
router.include_router(service_routes.router)
router.include_router(sms_routes.router)
router.include_router(email_bridge_routes.router)
router.include_router(email_router)
''',
    encoding="utf-8",
)
print("api_routes restored")

# 2) config.py
cfg_path = Path(r"C:\Users\yu\Desktop\opaiRe\utils\config.py")
text = cfg_path.read_text(encoding="utf-8")

helpers = '''
OPENAI_CPA_RECEIVE_MODES = ("remote_bridge", "local_webhook", "dual")


def normalize_openai_cpa_receive_mode(value, bridge_enabled=None) -> str:
    """Normalize OpenAI-CPA code receive path.

    remote_bridge: CF Worker -> public server bridge -> local WS/HTTP pull
    local_webhook: CF Worker -> local /api/webhook/email (CF Tunnel or public panel)
    dual: both paths active

    Missing receive_mode falls back to legacy bridge_enabled.
    """
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "remote": "remote_bridge",
        "remote_bridge": "remote_bridge",
        "bridge": "remote_bridge",
        "server": "remote_bridge",
        "server_bridge": "remote_bridge",
        "local": "local_webhook",
        "local_webhook": "local_webhook",
        "webhook": "local_webhook",
        "tunnel": "local_webhook",
        "cf_tunnel": "local_webhook",
        "direct": "local_webhook",
        "dual": "dual",
        "both": "dual",
        "all": "dual",
    }
    if raw in aliases:
        return aliases[raw]
    if bridge_enabled is None:
        return "local_webhook"
    return "remote_bridge" if bool(bridge_enabled) else "local_webhook"


def openai_cpa_remote_bridge_enabled(receive_mode: str) -> bool:
    return str(receive_mode or "").strip().lower() in {"remote_bridge", "dual"}


def openai_cpa_local_webhook_enabled(receive_mode: str) -> bool:
    return str(receive_mode or "").strip().lower() in {"local_webhook", "dual"}

'''

if "def normalize_openai_cpa_receive_mode" not in text:
    # insert after format_docker_url function block - find first major constant after format_docker_url
    anchor = "def format_docker_url(url: str) -> str:"
    idx = text.find(anchor)
    if idx < 0:
        raise SystemExit("format_docker_url missing")
    # end of function: next double newline after return/body - find "\n\n" after function, then next def or CONST
    # simpler: insert before first ALLCAPS config that currently follows helpers in file
    # Look for "CURRENT_DIR" or early constants - actually insert right before OPENAI-related later.
    # Best: after format_docker_url complete. Read a bit.
    end = text.find("\n\n", idx)
    # find the closing of format_docker_url by searching return and following blank
    # Use: insert just before "OPENAI_CPA_WEBHOOK_SECRET = \"\"" globals? Helpers should be top-level early.
    # Insert after format_docker_url function - locate "return url\n" within it
    chunk = text[idx: idx + 800]
    rel = chunk.find("\n\n")
    # find last line of function - usually return url
    marker = "    return url\n"
    # There may be multiple return url - use first after format_docker_url
    ridx = text.find(marker, idx)
    if ridx < 0:
        raise SystemExit("return url missing")
    insert_at = ridx + len(marker)
    text = text[:insert_at] + "\n" + helpers + text[insert_at:]
    print("helpers inserted")
else:
    print("helpers already present")

# globals
old_g = '''OPENAI_CPA_WEBHOOK_SECRET = ""
USE_ORIGINAL_PASSWORD_FLOW: bool = False
'''
new_g = '''OPENAI_CPA_WEBHOOK_SECRET = ""
OPENAI_CPA_RECEIVE_MODE: str = "local_webhook"
OPENAI_CPA_BRIDGE_ENABLED: bool = False
OPENAI_CPA_LOCAL_WEBHOOK: bool = True
OPENAI_CPA_BRIDGE_BASE_URL: str = ""
OPENAI_CPA_BRIDGE_TOKEN: str = ""
USE_ORIGINAL_PASSWORD_FLOW: bool = False
'''
if "OPENAI_CPA_BRIDGE_ENABLED" not in text:
    if old_g not in text:
        raise SystemExit("globals anchor missing")
    text = text.replace(old_g, new_g, 1)
    print("globals inserted")
else:
    print("globals already present")

# reload globals
old_rg = '''    global OPENAI_CPA_WEBHOOK_SECRET, USE_ORIGINAL_PASSWORD_FLOW
    global TEAM_MODE_ENABLE, TEAM_MODE_OVERSPEED
'''
new_rg = '''    global OPENAI_CPA_WEBHOOK_SECRET, USE_ORIGINAL_PASSWORD_FLOW
    global OPENAI_CPA_RECEIVE_MODE, OPENAI_CPA_LOCAL_WEBHOOK
    global OPENAI_CPA_BRIDGE_ENABLED, OPENAI_CPA_BRIDGE_BASE_URL, OPENAI_CPA_BRIDGE_TOKEN
    global TEAM_MODE_ENABLE, TEAM_MODE_OVERSPEED
'''
if "global OPENAI_CPA_RECEIVE_MODE" not in text:
    if old_rg not in text:
        raise SystemExit("reload global anchor missing")
    text = text.replace(old_rg, new_rg, 1)
    print("reload globals inserted")
else:
    print("reload globals already present")

# load block
old_load = '''    _ocpa = _c.get("openai_cpa", {})
    OPENAI_CPA_WEBHOOK_SECRET = str(_ocpa.get("webhook_secret", "")).strip()
    USE_ORIGINAL_PASSWORD_FLOW = bool(_ocpa.get("use_original_password_flow", False))

    DEFAULT_PROXY = format_docker_url(_c.get("default_proxy", ""))
'''
new_load = '''    _ocpa = _c.get("openai_cpa", {}) if isinstance(_c.get("openai_cpa", {}), dict) else {}
    OPENAI_CPA_WEBHOOK_SECRET = str(_ocpa.get("webhook_secret", "")).strip()
    USE_ORIGINAL_PASSWORD_FLOW = bool(_ocpa.get("use_original_password_flow", False))
    _legacy_bridge_enabled = safe_bool(_ocpa.get("bridge_enabled", False), default=False)
    OPENAI_CPA_RECEIVE_MODE = normalize_openai_cpa_receive_mode(
        _ocpa.get("receive_mode"),
        bridge_enabled=_legacy_bridge_enabled,
    )
    OPENAI_CPA_BRIDGE_ENABLED = openai_cpa_remote_bridge_enabled(OPENAI_CPA_RECEIVE_MODE)
    OPENAI_CPA_LOCAL_WEBHOOK = openai_cpa_local_webhook_enabled(OPENAI_CPA_RECEIVE_MODE)
    OPENAI_CPA_BRIDGE_BASE_URL = format_docker_url(str(_ocpa.get("bridge_base_url", "") or "").strip()).rstrip("/")
    OPENAI_CPA_BRIDGE_TOKEN = str(_ocpa.get("bridge_token", "") or "").strip() or OPENAI_CPA_WEBHOOK_SECRET
    # Keep yaml-facing keys aligned so UI/save round-trips stay consistent.
    _ocpa["receive_mode"] = OPENAI_CPA_RECEIVE_MODE
    _ocpa["bridge_enabled"] = OPENAI_CPA_BRIDGE_ENABLED
    _c["openai_cpa"] = _ocpa

    DEFAULT_PROXY = format_docker_url(_c.get("default_proxy", ""))
'''
if "OPENAI_CPA_BRIDGE_BASE_URL = format_docker_url" not in text:
    if old_load not in text:
        raise SystemExit("load anchor missing")
    text = text.replace(old_load, new_load, 1)
    print("load block inserted")
else:
    print("load block already present")

cfg_path.write_text(text, encoding="utf-8")
compile(text, str(cfg_path), "exec")
print("config.py ok")
