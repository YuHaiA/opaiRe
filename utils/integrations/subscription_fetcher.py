import urllib.parse
from dataclasses import dataclass
from typing import Optional

from curl_cffi import requests as cffi_requests


_BROWSER_PROFILES = (
    ("chrome136", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"),
    ("chrome133a", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"),
    ("edge101", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/101.0.4951.67 Safari/537.36 Edg/101.0.1210.47"),
    ("safari184", "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15"),
)


@dataclass
class SubscriptionFetchResult:
    ok: bool
    text: str = ""
    status_code: int = 0
    message: str = ""


def _build_headers(url: str, user_agent: str) -> dict:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/x-yaml,text/yaml,text/plain,application/octet-stream,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }
    if origin:
        headers["Referer"] = origin + "/"
        headers["Origin"] = origin
    return headers


def _iter_attempts(proxies: Optional[dict]) -> list[tuple[str, dict]]:
    attempts = []
    proxy_variants = [("proxy", proxies)] if proxies else []
    proxy_variants.append(("direct", None))
    for route_name, route_proxies in proxy_variants:
        for impersonate, user_agent in _BROWSER_PROFILES:
            request_kwargs = {
                "headers": _build_headers("", user_agent),
                "timeout": 30,
                "allow_redirects": True,
            }
            if impersonate:
                request_kwargs["impersonate"] = impersonate
            if route_proxies:
                request_kwargs["proxies"] = route_proxies
            attempts.append((f"{route_name}:{impersonate}", request_kwargs))
    return attempts


def _build_failure_message(status_code: int) -> str:
    if status_code == 403:
        return "订阅拉取失败：HTTP 403，目标站点拒绝了当前服务器指纹或出口请求。"
    if status_code == 429:
        return "订阅拉取失败：HTTP 429，目标站点触发了频率限制。"
    return f"订阅拉取失败：HTTP {status_code}，目标站点拒绝了服务器请求。"


def fetch_subscription_text(url: str, proxies: Optional[dict] = None) -> SubscriptionFetchResult:
    normalized_url = str(url or "").strip()
    best_status = 0
    last_error = ""

    for attempt_name, request_kwargs in _iter_attempts(proxies):
        request_kwargs["headers"] = _build_headers(normalized_url, request_kwargs["headers"]["User-Agent"])
        try:
            response = cffi_requests.get(normalized_url, **request_kwargs)
        except Exception as exc:
            last_error = f"{attempt_name}: {exc}"
            continue

        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code < 400:
            return SubscriptionFetchResult(ok=True, text=str(response.text or ""), status_code=status_code)
        if best_status == 0 or status_code < best_status:
            best_status = status_code
        last_error = _build_failure_message(status_code)

    if best_status:
        return SubscriptionFetchResult(ok=False, status_code=best_status, message=_build_failure_message(best_status))
    return SubscriptionFetchResult(ok=False, message=f"订阅拉取失败：{last_error or '未拿到有效响应'}")
