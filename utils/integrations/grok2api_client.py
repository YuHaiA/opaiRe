"""Grok2API 管理端 API 客户端。"""

import json
import time
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from curl_cffi import CurlMime, requests

from utils import config as cfg


def _is_xai_like_token(token_or_item: Any) -> bool:
    """识别 Grok/xAI 账号。"""
    if not isinstance(token_or_item, dict):
        return False
    for key in ("type", "provider", "platform", "status"):
        value = str(token_or_item.get(key) or "").lower()
        if "xai" in value or "grok" in value:
            return True
    credentials = token_or_item.get("credentials")
    if isinstance(credentials, dict):
        for key in ("type", "provider", "platform"):
            value = str(credentials.get(key) or "").lower()
            if "xai" in value or "grok" in value:
                return True
    return False


def _grok2api_import_expires_at(token_data: dict) -> str:
    if token_data.get("refresh_token"):
        return datetime.fromtimestamp(int(time.time()) - 60, timezone.utc).isoformat().replace("+00:00", "Z")

    exp = token_data.get("expires_at")
    expires_str = ""
    if exp is not None:
        try:
            if isinstance(exp, (int, float)):
                expires_str = datetime.fromtimestamp(int(exp), timezone.utc).isoformat().replace("+00:00", "Z")
            elif str(exp).isdigit():
                expires_str = datetime.fromtimestamp(int(str(exp)), timezone.utc).isoformat().replace("+00:00", "Z")
            else:
                expires_str = str(exp)
        except Exception:
            expires_str = str(exp) if exp else ""
    return expires_str

def _grok2api_import_payload(token_data: dict) -> dict:
    expires_str = _grok2api_import_expires_at(token_data)
    return {
        "provider": "grok_build",
        "name": token_data.get("email", "Grok Build account"),
        "client_id": token_data.get("client_id", ""),
        "access_token": token_data.get("access_token", ""),
        "refresh_token": token_data.get("refresh_token", ""),
        "id_token": token_data.get("id_token", ""),
        "token_type": token_data.get("token_type", "Bearer"),
        "email": token_data.get("email", ""),
        "user_id": token_data.get("user_id") or token_data.get("principal_id", ""),
        "team_id": token_data.get("team_id", ""),
        "expires_at": expires_str,
    }

def import_web_sso(sso: str, token_value: str) -> Tuple[bool, str]:
    sso = str(sso or "").strip()
    if not sso:
        return False, "缺少 sso"
    grok_url = (getattr(cfg, "GROK2API_URL", "") or "http://host.docker.internal:8000").rstrip("/")
    mime = CurlMime()
    mime.addpart(
        name="files",
        data=(sso + "\n").encode("utf-8"),
        filename="grok-web-sso-token.txt",
        content_type="text/plain",
    )
    try:
        resp = requests.post(
            f"{grok_url}/api/admin/v1/accounts/web/import",
            multipart=mime,
            headers={"Authorization": f"Bearer {token_value}"},
            timeout=180,
            impersonate="chrome",
        )
        if resp.status_code in (200, 201):
            return True, "Grok Web SSO 导入成功"
        return False, f"Grok Web SSO 导入失败 HTTP {resp.status_code}"
    except Exception as exc:
        return False, f"Grok Web SSO 导入异常: {exc}"

def import_to_grok2api(token_data: dict) -> Tuple[bool, str]:
    grok_url = (getattr(cfg, "GROK2API_URL", "") or "http://host.docker.internal:8000").rstrip("/")
    grok_pass = getattr(cfg, "GROK2API_ADMIN_PASSWORD", "") or ""
    if not grok_pass:
        return False, "Grok2API admin_password 未配置"
    if not _is_xai_like_token(token_data) and str(getattr(cfg, "REG_PROVIDER", "openai")).lower() != "grok":
        return False, "非 Grok/xAI 账号"
    if not (token_data.get("access_token") or token_data.get("refresh_token")):
        return False, "缺少 access_token/refresh_token"
    try:
        login_resp = requests.post(
            f"{grok_url}/api/admin/v1/auth/login",
            json={"username": "admin", "password": grok_pass},
            timeout=20,
            impersonate="chrome",
        )
        if login_resp.status_code != 200:
            return False, f"Grok2API 登录失败 HTTP {login_resp.status_code}"
        grok_token = login_resp.json().get("data", {}).get("tokens", {}).get("accessToken", "")
        if not grok_token:
            return False, "Grok2API 登录未返回 accessToken"

        payload = _grok2api_import_payload(token_data)
        file_content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        mime = CurlMime()
        mime.addpart(name="file", data=file_content, filename="auth.json", content_type="application/json")
        import_resp = requests.post(
            f"{grok_url}/api/admin/v1/accounts/import",
            multipart=mime,
            headers={"Authorization": f"Bearer {grok_token}"},
            timeout=180,
            impersonate="chrome",
        )
        if import_resp.status_code in (200, 201):
            return True, "导入成功"
        return False, f"导入失败 HTTP {import_resp.status_code}"
    except Exception as e:
        return False, str(e)

def grok2api_admin_login() -> Tuple[bool, str, str]:
    """登录 Grok2API 管理端，供独立仓管巡检/补货使用。"""
    grok_url = (getattr(cfg, "GROK2API_URL", "") or "").rstrip("/")
    grok_pass = getattr(cfg, "GROK2API_ADMIN_PASSWORD", "") or ""
    if not grok_url:
        return False, "", "Grok2API api_url 未配置"
    if not grok_pass:
        return False, "", "Grok2API admin_password 未配置"
    try:
        resp = requests.post(
            f"{grok_url}/api/admin/v1/auth/login",
            json={"username": "admin", "password": grok_pass},
            timeout=30,
            impersonate="chrome",
        )
        if resp.status_code != 200:
            return False, "", f"Grok2API 登录失败 HTTP {resp.status_code}"
        token_value = resp.json().get("data", {}).get("tokens", {}).get("accessToken", "")
        if not token_value:
            return False, "", "Grok2API 登录未返回 accessToken"
        return True, token_value, "OK"
    except Exception as exc:
        return False, "", f"Grok2API 登录异常: {exc}"

def grok2api_admin_request(method: str, path: str, token_value: str, **kwargs):
    grok_url = (getattr(cfg, "GROK2API_URL", "") or "").rstrip("/")
    headers = kwargs.pop("headers", {}) or {}
    headers["Authorization"] = f"Bearer {token_value}"
    return requests.request(
        method,
        f"{grok_url}/api/admin/v1{path}",
        headers=headers,
        timeout=kwargs.pop("timeout", 60),
        impersonate="chrome",
        **kwargs,
    )

def grok2api_list_accounts(token_value: str, provider: str = None, page_size: int = 500) -> Tuple[bool, list, str]:
    items = []
    page = 1
    total = None
    try:
        while True:
            params = {"page": page, "pageSize": page_size}
            if provider:
                params["provider"] = provider
            resp = grok2api_admin_request("GET", "/accounts", token_value, params=params, timeout=30)
            if resp.status_code != 200:
                return False, items, f"Grok2API 账号列表 HTTP {resp.status_code}"
            data = resp.json().get("data", {})
            batch = data.get("items", []) or []
            items.extend(batch)
            total = data.get("total", total)
            if not batch or len(items) >= int(total or 0) or len(batch) < page_size:
                break
            page += 1
            if page > 50:
                break
        return True, items, "OK"
    except Exception as exc:
        return False, items, f"Grok2API 拉取账号异常: {exc}"

def _grok2api_provider(item: dict) -> str:
    return str((item or {}).get("provider") or "").strip().lower()

def _grok2api_account_label(item: dict) -> str:
    return str((item or {}).get("email") or (item or {}).get("name") or (item or {}).get("id") or "unknown")

def _grok2api_quota_remaining_percent(item: dict) -> Optional[float]:
    quota = (item or {}).get("quota") or {}
    if not isinstance(quota, dict):
        return None
    usage = quota.get("usagePercent")
    if isinstance(usage, (int, float)):
        return max(0.0, min(100.0, 100.0 - float(usage)))
    remaining = quota.get("remaining")
    limit = quota.get("limit")
    try:
        if remaining is not None and limit:
            return max(0.0, min(100.0, float(remaining) * 100.0 / float(limit)))
    except Exception:
        return None
    return None

def _grok2api_quota_exhausted(item: dict) -> bool:
    quota = (item or {}).get("quota") or {}
    if isinstance(quota, dict):
        status = str(quota.get("status") or "").lower()
        if status in {"exhausted", "limit_reached", "limited", "disabled"}:
            return True
        remaining = quota.get("remaining")
        try:
            if remaining is not None and float(remaining) <= 0:
                return True
        except Exception:
            pass
    pct = _grok2api_quota_remaining_percent(item)
    threshold = int(getattr(cfg, "GROK2API_MIN_REMAINING_WEEKLY_PERCENT", 0) or 0)
    return threshold > 0 and pct is not None and pct < threshold

def _set_grok2api_account_enabled(token_value: str, account_id: str, enabled: bool) -> Tuple[bool, str]:
    try:
        resp = grok2api_admin_request(
            "PATCH", f"/accounts/{account_id}", token_value,
            json={"enabled": enabled}, timeout=30,
        )
        return resp.status_code == 200, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)

def _delete_grok2api_account(token_value: str, item: dict) -> Tuple[bool, str]:
    account_id = str((item or {}).get("id") or "")
    if not account_id:
        return False, "缺少账号 ID"
    provider = _grok2api_provider(item)
    body = {"provider": provider} if provider else {}
    try:
        resp = grok2api_admin_request("DELETE", f"/accounts/{account_id}", token_value, json=body, timeout=40)
        return resp.status_code in (200, 204), f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)
