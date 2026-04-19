import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from utils import config as cfg

from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)


class Sub2APIClient:
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
        }
        self.request_kwargs = {
            "timeout": 15,
            "impersonate": "chrome110",
        }
        self._recent_error_log_at: Dict[str, float] = {}
        proxy_url = str(getattr(cfg, "DEFAULT_PROXY", "") or "").strip()
        self.use_proxy = bool(getattr(cfg, "SUB2API_USE_PROXY", False))
        if self.use_proxy and proxy_url:
            self.request_kwargs["proxies"] = {
                "http": proxy_url,
                "https": proxy_url,
            }

    def _log_request_issue(self, key: str, level: str, message: str, *args: Any) -> None:
        now = time.time()
        last = self._recent_error_log_at.get(key, 0.0)
        if now - last < 30:
            return
        self._recent_error_log_at[key] = now
        getattr(logger, level, logger.warning)(message, *args)

    @staticmethod
    def _as_int(value: Any, default: int, minimum: int) -> int:
        try:
            return max(minimum, int(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_timeout_like_error(error: Any) -> bool:
        text = str(error or "").lower()
        return any(
            token in text
            for token in (
                "timeout",
                "timed out",
                "connection timed out",
                "recv failure",
                "connection reset",
                "proxyconnect tcp",
            )
        )

    def _get_account_page_size(self) -> int:
        raw = getattr(cfg, "SUB2API_ACCOUNT_PAGE_SIZE", 20)
        return self._as_int(raw, 20, 1)

    def _get_account_fetch_timeout(self) -> int:
        raw = getattr(cfg, "SUB2API_ACCOUNT_FETCH_TIMEOUT", 45)
        return self._as_int(raw, 45, 5)

    def _build_request_kwargs(self, timeout: Optional[int] = None) -> Dict[str, Any]:
        kwargs = self.request_kwargs.copy()
        kwargs["timeout"] = self._as_int(
            timeout if timeout is not None else self._get_account_fetch_timeout(),
            self._get_account_fetch_timeout(),
            5,
        )
        return kwargs

    def _handle_response(
        self,
        response: cffi_requests.Response,
        success_codes: Tuple[int, ...] = (200, 201, 204),
    ) -> Tuple[bool, Any]:
        if response.status_code in success_codes:
            try:
                return True, response.json() if response.text else {}
            except ValueError:
                return True, response.text

        error_msg = f"HTTP {response.status_code}"
        try:
            detail = response.json()
            if isinstance(detail, dict):
                error_msg = detail.get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg} - {response.text[:200]}"

        return False, error_msg

    def _get_push_settings(self) -> Dict[str, Any]:
        try:
            import utils.config as cfg
        except ImportError:
            cfg = None

        def as_int(value: Any, default: int, minimum: int) -> int:
            try:
                return max(minimum, int(value))
            except (TypeError, ValueError):
                return default
        def as_float(value: Any, default: float, minimum: float) -> float:
            try:
                return max(minimum, float(value))
            except (TypeError, ValueError):
                return default

        raw_group_ids = getattr(cfg, "SUB2API_ACCOUNT_GROUP_IDS", []) if cfg else []
        if isinstance(raw_group_ids, list):
            group_ids = [int(item) for item in raw_group_ids if str(item).strip().isdigit()]
        else:
            group_ids = [int(item.strip()) for item in str(raw_group_ids or "").split(",") if
                         item.strip().isdigit()]

        return {
            "concurrency": as_int(getattr(cfg, "SUB2API_ACCOUNT_CONCURRENCY", 10) if cfg else 10, 10, 1),
            "load_factor": as_int(getattr(cfg, "SUB2API_ACCOUNT_LOAD_FACTOR", 10) if cfg else 10, 10, 1),
            "priority": as_int(getattr(cfg, "SUB2API_ACCOUNT_PRIORITY", 1) if cfg else 1, 1, 1),
            "rate_multiplier": as_float(getattr(cfg, "SUB2API_ACCOUNT_RATE_MULTIPLIER", 1.0) if cfg else 1.0, 1.0,
                                        0.0),
            "group_ids": group_ids,
            "enable_ws": bool(getattr(cfg, "SUB2API_ENABLE_WS_MODE", True) if cfg else True),
        }

    def _build_account_extra(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        extra = {"load_factor": settings["load_factor"]}
        if settings["enable_ws"]:
            extra["openai_oauth_responses_websockets_v2_enabled"] = True
            extra["openai_oauth_responses_websockets_v2_mode"] = "passthrough"
        return extra

    def _refresh_created_account(self, account_id: str) -> None:
        if not account_id:
            return

        refresh_urls = [
            f"{self.api_url}/api/v1/admin/accounts/{account_id}/refresh",
            f"{self.api_url}/api/v1/admin/openai/accounts/{account_id}/refresh",
        ]

        for refresh_url in refresh_urls:
            try:
                response = cffi_requests.post(
                    refresh_url,
                    json={},
                    headers=self.headers,
                    timeout=30,
                    impersonate="chrome110",
                    proxies=None,
                )
                if response.status_code in (200, 201, 204):
                    logger.info("Sub2API account refresh succeeded (ID: %s)", account_id)
                    return
            except Exception as exc:
                logger.warning("Sub2API account refresh failed via %s: %s", refresh_url, exc)

        logger.warning("Sub2API account refresh did not succeed for %s", account_id)

    def _import_account(self, token_data: Dict[str, Any], settings: Dict[str, Any]) -> Tuple[bool, str]:
        url = f"{self.api_url}/api/v1/admin/accounts/data"
        exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        extra = self._build_account_extra(settings)

        account_item = {
            "name": token_data.get("email", "unknown"),
            "platform": "openai",
            "type": "oauth",
            "credentials": {
                "access_token": token_data.get("access_token", ""),
                "chatgpt_account_id": token_data.get("account_id", ""),
                "client_id": token_data.get("client_id", ""),
                "expires_at": int(time.time() + 864000),
                "expires_in": 863999,
                "model_mapping": {
                    "gpt-4o": "gpt-4o",
                    "gpt-4": "gpt-4",
                    "gpt-3.5-turbo": "gpt-3.5-turbo",
                },
                "organization_id": token_data.get("workspace_id", ""),
                "refresh_token": token_data.get("refresh_token", ""),
            },
            "extra": extra,
            "concurrency": settings["concurrency"],
            "priority": settings["priority"],
            "rate_multiplier": settings["rate_multiplier"],
            "auto_pause_on_expired": True,
        }
        if settings["group_ids"]:
            account_item["group_ids"] = settings["group_ids"]

        payload = {
            "data": {
                "type": "sub2api-data",
                "version": 1,
                "exported_at": exported_at,
                "proxies": [],
                "accounts": [account_item],
            },
            "skip_default_group_bind": not bool(settings["group_ids"]),
        }

        try:
            headers = self.headers.copy()
            headers["Idempotency-Key"] = f"import-{int(time.time())}"
            response = cffi_requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
                impersonate="chrome110",
                proxies=None,
            )
            ok, result = self._handle_response(response, success_codes=(200, 201))
            if ok:
                return True, "Sub2API account import succeeded"
            return False, str(result)
        except Exception as exc:
            return False, f"Network request failed: {exc}"

    def get_accounts(
        self,
        page: int = 1,
        page_size: Optional[int] = None,
        timeout: Optional[int] = None,
    ) -> Tuple[bool, Any]:
        url = f"{self.api_url}/api/v1/admin/accounts"
        resolved_page_size = self._as_int(
            page_size if page_size is not None else self._get_account_page_size(),
            self._get_account_page_size(),
            1,
        )
        params = {
            "page": page,
            "page_size": resolved_page_size,
        }
        try:
            response = cffi_requests.get(
                url,
                headers=self.headers,
                params=params,
                **self._build_request_kwargs(timeout),
            )
            return self._handle_response(response)
        except cffi_requests.exceptions.Timeout as exc:
            self._log_request_issue("get_accounts_timeout", "warning", "Get Sub2API accounts timed out: %s", exc)
            return False, f"timeout: {exc}"
        except cffi_requests.exceptions.ConnectionError as exc:
            self._log_request_issue("get_accounts_connection", "warning", "Get Sub2API accounts connection failed: %s", exc)
            return False, f"connection error: {exc}"
        except Exception as exc:
            self._log_request_issue("get_accounts_failed", "error", "Get Sub2API accounts failed: %s", exc)
            return False, str(exc)

    def get_all_accounts(self, page_size: Optional[int] = None) -> Tuple[bool, Any]:
        all_items: List[dict] = []
        page = 1
        resolved_page_size = self._as_int(
            page_size if page_size is not None else self._get_account_page_size(),
            self._get_account_page_size(),
            1,
        )
        resolved_timeout = self._get_account_fetch_timeout()
        fallback_page_sizes = [
            size for size in (resolved_page_size, 20, 10, 5)
            if size <= resolved_page_size and size >= 1
        ]
        fallback_page_sizes = list(dict.fromkeys(fallback_page_sizes))

        while True:
            ok, data = self.get_accounts(
                page=page,
                page_size=resolved_page_size,
                timeout=resolved_timeout,
            )
            if not ok and page == 1 and self._is_timeout_like_error(data):
                for fallback_size in fallback_page_sizes[1:]:
                    fallback_timeout = min(90, max(resolved_timeout + 15, 30))
                    logger.warning(
                        "Sub2API accounts page 1 timed out with page_size=%s timeout=%ss; retrying with page_size=%s timeout=%ss",
                        resolved_page_size,
                        resolved_timeout,
                        fallback_size,
                        fallback_timeout,
                    )
                    ok, data = self.get_accounts(
                        page=1,
                        page_size=fallback_size,
                        timeout=fallback_timeout,
                    )
                    if ok:
                        resolved_page_size = fallback_size
                        resolved_timeout = fallback_timeout
                        break
            if not ok:
                if page == 1:
                    return False, data
                logger.warning(
                    "Sub2API pagination failed on page %s; continue with %s fetched accounts",
                    page,
                    len(all_items),
                )
                break

            inner = data.get("data", {}) if isinstance(data, dict) else {}
            items = inner.get("items", [])
            if not items:
                break

            all_items.extend(items)

            total = inner.get("total", 0)
            if total and len(all_items) >= total:
                break
            if not total and len(items) < resolved_page_size:
                break

            page += 1

        logger.info("Fetched %s Sub2API accounts across paginated results", len(all_items))
        return True, all_items

    def probe_connectivity(self, timeout: Optional[int] = None, page_size: int = 1) -> Dict[str, Any]:
        started_at = time.perf_counter()
        resolved_timeout = self._as_int(
            timeout if timeout is not None else min(self._get_account_fetch_timeout(), 20),
            min(self._get_account_fetch_timeout(), 20),
            5,
        )
        ok, data = self.get_accounts(page=1, page_size=page_size, timeout=resolved_timeout)
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)

        result: Dict[str, Any] = {
            "ok": ok,
            "elapsed_ms": elapsed_ms,
            "page_size": page_size,
            "timeout": resolved_timeout,
            "use_proxy": self.use_proxy,
        }

        if ok:
            inner = data.get("data", {}) if isinstance(data, dict) else {}
            items = inner.get("items", []) if isinstance(inner, dict) else []
            result["count"] = len(items) if isinstance(items, list) else 0
            result["total"] = inner.get("total") if isinstance(inner, dict) else None
            result["message"] = "Sub2API 管理接口探测成功"
        else:
            result["message"] = str(data)

        return result

    def add_account(self, token_data: Dict[str, Any]) -> Tuple[bool, str]:
        settings = self._get_push_settings()
        refresh_token = token_data.get("refresh_token", "")

        if not refresh_token:
            return self._import_account(token_data, settings)

        url = f"{self.api_url}/api/v1/admin/accounts"
        payload = {
            "name": token_data.get("email", "unknown")[:64],
            "platform": "openai",
            "type": "oauth",
            "credentials": {"refresh_token": refresh_token},
            "concurrency": settings["concurrency"],
            "priority": settings["priority"],
            "rate_multiplier": settings["rate_multiplier"],
            "extra": self._build_account_extra(settings),
        }
        if settings["group_ids"]:
            payload["group_ids"] = settings["group_ids"]

        try:
            response = cffi_requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=30,
                impersonate="chrome110",
                proxies=None,
            )
            ok, result = self._handle_response(response, success_codes=(200, 201))
            if not ok:
                logger.warning("Sub2API direct create failed, falling back to import endpoint: %s", result)
                return self._import_account(token_data, settings)

            account_id = result.get("data", {}).get("id") if isinstance(result, dict) else None
            if account_id:
                self._refresh_created_account(str(account_id))
            return True, "Sub2API account created successfully"
        except Exception as exc:
            logger.warning("Sub2API direct create raised an exception, falling back to import: %s", exc)
            return self._import_account(token_data, settings)

    def update_account(self, account_id: str, update_data: Dict[str, Any]) -> Tuple[bool, Any]:
        url = f"{self.api_url}/api/v1/admin/accounts/{account_id}"
        try:
            response = cffi_requests.put(url, json=update_data, headers=self.headers, **self.request_kwargs)
            return self._handle_response(response)
        except Exception as exc:
            logger.error("Update Sub2API account %s failed: %s", account_id, exc)
            return False, str(exc)

    def set_account_status(self, account_id: str, disabled: bool) -> bool:
        url = f"{self.api_url}/api/v1/admin/accounts/{account_id}"

        status_val = "inactive" if disabled else "active"
        payload = {"status": status_val}

        try:
            response = cffi_requests.patch(url, json=payload, headers=self.headers, **self.request_kwargs)
            if response.status_code in (200, 201, 204):
                return True

            response = cffi_requests.put(url, json=payload, headers=self.headers, **self.request_kwargs)
            return response.status_code in (200, 201, 204)
        except Exception as exc:
            logger.error("Set Sub2API account %s status failed: %s", account_id, exc)
            return False

    def delete_account(self, account_id: str) -> Tuple[bool, Any]:
        url = f"{self.api_url}/api/v1/admin/accounts/{account_id}"
        try:
            response = cffi_requests.delete(url, headers=self.headers, **self.request_kwargs)
            return self._handle_response(response, success_codes=(200, 204))
        except Exception as exc:
            logger.error(f"删除账号 {account_id} 失败: {exc}")
            return False, str(exc)

    def refresh_account(self, account_id: str) -> Tuple[bool, Any]:
        url = f"{self.api_url}/api/v1/admin/accounts/{account_id}/refresh"
        try:
            response = cffi_requests.post(url, headers=self.headers, json={}, **self.request_kwargs)
            return self._handle_response(response)
        except Exception as exc:

            logger.error(f"刷新账号 {account_id} 失败: {exc}")
            return False, str(exc)

    def test_account(self, account_id: int) -> Tuple[str, str]:
        url = f"{self.api_url}/api/v1/admin/accounts/{account_id}/test"
        try:
            response = cffi_requests.post(
                url,
                headers=self.headers,
                json={"model_id": cfg.SUB2API_TEST_MODEL},
                timeout=60,
                impersonate="chrome110",
            )
            if response.status_code != 200:
                logger.warning("Sub2API test_account %s returned HTTP %s; keep current state", account_id, response.status_code)
                return "ok", f"HTTP {response.status_code}, skipped"

            for line in response.text.splitlines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue

                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue

                try:
                    event = json.loads(raw)
                except Exception:
                    continue

                event_type = event.get("type", "")
                if event_type == "test_complete":
                    if event.get("success"):
                        return "ok", "test completed"
                    err = str(event.get("error") or event.get("text") or "")
                    return _classify_sse_error(err)

                if event_type == "error":
                    err = str(event.get("error") or event.get("text") or "")
                    return _classify_sse_error(err)

            logger.warning("Sub2API test_account %s did not emit a terminal SSE event; keep current state", account_id)
            return "ok", "no terminal SSE event, skipped"
        except cffi_requests.exceptions.Timeout as exc:
            logger.warning("Sub2API test_account %s timed out: %s", account_id, exc)
            return "retry_proxy", f"timeout: {str(exc)[:120]}"
        except cffi_requests.exceptions.ConnectionError as exc:
            logger.warning("Sub2API test_account %s connection failed: %s", account_id, exc)
            return "retry_proxy", f"connection error: {str(exc)[:120]}"
        except Exception as exc:
            logger.warning("Sub2API test_account %s failed: %s", account_id, exc)
            msg = str(exc)[:120]
            if any(token in msg.lower() for token in ["timeout", "timed out", "connection", "reset", "unreachable", "proxy"]):
                return "retry_proxy", f"network error: {msg}"
            return "ok", f"test error, skipped: {msg}"

    def test_connection(self) -> Tuple[bool, str]:
        url = f"{self.api_url}/api/v1/admin/accounts/data"
        try:
            kwargs = self.request_kwargs.copy()
            kwargs["timeout"] = 10
            response = cffi_requests.get(url, headers=self.headers, **kwargs)

            if response.status_code in (200, 201, 204, 405):
                return True, "Sub2API connection test succeeded. The API key is valid."
            if response.status_code == 401:
                return False, "Connected, but the API key is invalid (401 Unauthorized)."
            if response.status_code == 403:
                return False, "Connected, but the API key does not have enough permission (403 Forbidden)."
            return False, f"Unexpected server status code: {response.status_code}"
        except cffi_requests.exceptions.ConnectionError as exc:
            return False, f"Could not connect to the Sub2API server: {exc}"
        except cffi_requests.exceptions.Timeout:
            return False, "连接超时，请检查网络配置或服务器状态"
        except Exception as exc:
            return False, f"连接测试失败: {str(exc)}"

def _classify_sse_error(err_text: str) -> Tuple[str, str]:
    text = err_text.lower()
    if any(keyword in text for keyword in ("429", "rate_limit", "rate limit", "too many request")):
        return "quota", f"quota limited: {err_text[:120]}"
    if err_text.strip():
        return "dead", f"test failed: {err_text[:120]}"
    return "ok", "empty SSE error, skipped"
