import os
import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from curl_cffi import requests
from utils import config as cfg
from utils import task_log_guard
from . import auth_fingerprint


def _ssl_verify() -> bool:
    flag = os.getenv("OPENAI_SSL_VERIFY", "1").strip().lower()
    return flag not in {"0", "false", "no", "off"}


def _skip_net_check() -> bool:
    flag = os.getenv("SKIP_NET_CHECK", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _to_int(v: Any) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _post_form(
        url: str,
        data: Dict[str, str],
        proxies: Any = None,
        timeout: int = 30,
        retries: int = 3,
) -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        task_log_guard.raise_if_current_batch_aborted()
        try:
            resp = requests.post(
                url, data=data, headers=headers,
                proxies=proxies, verify=_ssl_verify(),
                timeout=timeout, impersonate=auth_fingerprint.token_impersonate(),
            )
            if resp.status_code != 200:
                raise RuntimeError(
                    f"token exchange failed: {resp.status_code}: {resp.text}"
                )
            return resp.json()
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                print(f"\n[{cfg.ts()}] [WARNING] 换取 Token 时遇到网络异常: {exc}。"
                      f"准备第 {attempt + 1}/{retries} 次重试...")
                task_log_guard.sleep_with_batch_abort(2 * (attempt + 1))
    raise RuntimeError(
        f"token exchange failed after {retries} retries: {last_error}"
    ) from last_error


def _post_with_retry(
        session: requests.Session,
        url: str,
        *,
        headers: Dict[str, Any],
        data: Any = None,
        json_body: Any = None,
        proxies: Any = None,
        timeout: int = 30,
        retries: int = 2,
        allow_redirects: bool = True,
) -> Any:
    last_error: Optional[Exception] = None
    for attempt in range(retries + 1):
        if getattr(cfg, 'GLOBAL_STOP', False): raise RuntimeError("系统已停止，强制中断网络请求")
        task_log_guard.raise_if_current_batch_aborted()
        try:
            if json_body is not None:
                return session.post(
                    url, headers=headers, json=json_body,
                    proxies=proxies, verify=_ssl_verify(),
                    timeout=timeout, allow_redirects=allow_redirects,
                )
            return session.post(
                url, headers=headers, data=data,
                proxies=proxies, verify=_ssl_verify(),
                timeout=timeout, allow_redirects=allow_redirects,
            )
        except Exception as e:
            last_error = e
            if attempt >= retries:
                break
            task_log_guard.sleep_with_batch_abort(2 * (attempt + 1))
    if last_error:
        raise last_error
    raise RuntimeError("Request failed without exception")


def _oai_headers(did: str, extra: dict = None, is_navigate: bool = False) -> dict:
    return auth_fingerprint.oai_headers(did, extra=extra, is_navigate=is_navigate)


def _follow_redirect_chain_local(
        session: requests.Session,
        start_url: str,
        proxies: Any = None,
        max_redirects: int = 12,
) -> Tuple[Any, str]:
    current_url = start_url
    response = None
    for _ in range(max_redirects):
        task_log_guard.raise_if_current_batch_aborted()
        try:
            response = session.get(
                current_url,
                allow_redirects=False,
                proxies=proxies,
                verify=_ssl_verify(),
                timeout=15,
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                return response, current_url
            loc = response.headers.get("Location", "")
            if not loc:
                return response, current_url
            current_url = urllib.parse.urljoin(current_url, loc)
            if "code=" in current_url and "state=" in current_url:
                return None, current_url
        except Exception:
            return None, current_url
    return response, current_url
