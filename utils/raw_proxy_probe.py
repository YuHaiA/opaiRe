import concurrent.futures
import re
import socket
import time
import urllib.parse
from collections import Counter
from typing import Any, Iterable

from curl_cffi import requests

from utils.config import normalize_raw_proxy_entry


RAW_PROXY_TEST_URL = "https://cloudflare.com/cdn-cgi/trace"
DEFAULT_SAMPLE_SIZE = 20
MAX_SAMPLE_SIZE = 50
DEFAULT_TIMEOUT_SEC = 8.0
MAX_TIMEOUT_SEC = 15.0
DEFAULT_CONCURRENCY = 8
MAX_CONCURRENCY = 10


def _iter_proxy_lines(entries: Any) -> Iterable[str]:
    if isinstance(entries, str):
        yield from entries.splitlines()
        return
    if isinstance(entries, (list, tuple)):
        for entry in entries:
            yield str(entry or "")


def normalize_probe_entries(entries: Any) -> tuple[list[dict], int]:
    normalized: list[dict] = []
    seen: set[str] = set()
    invalid_count = 0

    for line_number, raw_entry in enumerate(_iter_proxy_lines(entries), start=1):
        text = str(raw_entry or "").strip()
        if not text or text.startswith("#"):
            continue
        try:
            proxy = normalize_raw_proxy_entry(text)
        except (TypeError, ValueError):
            proxy = ""
        if not proxy:
            invalid_count += 1
            continue
        if proxy in seen:
            continue
        seen.add(proxy)
        normalized.append({"source_index": line_number, "proxy": proxy})

    return normalized, invalid_count


def select_evenly_spaced(entries: list[dict], sample_size: int) -> list[dict]:
    if not entries:
        return []
    size = max(1, min(MAX_SAMPLE_SIZE, int(sample_size or DEFAULT_SAMPLE_SIZE)))
    if len(entries) <= size:
        return list(entries)
    if size == 1:
        return [entries[0]]

    last_index = len(entries) - 1
    indices = [round(last_index * position / (size - 1)) for position in range(size)]
    return [entries[index] for index in dict.fromkeys(indices)]


def proxy_display_name(proxy: str) -> str:
    parsed = urllib.parse.urlparse(proxy)
    scheme = (parsed.scheme or "proxy").lower()
    host = parsed.hostname or "invalid-host"
    try:
        port = parsed.port or (1080 if scheme.startswith("socks5") else 8080)
    except ValueError:
        port = 0
    auth_marker = "***@" if parsed.username is not None else ""
    return f"{scheme}://{auth_marker}{host}:{port}"


def _safe_failure(code: str, message: str, *, source_index: int, proxy: str, elapsed_ms: int) -> dict:
    return {
        "source_index": source_index,
        "proxy": proxy_display_name(proxy),
        "ok": False,
        "code": code,
        "message": message,
        "http_status": None,
        "country": "",
        "latency_ms": elapsed_ms,
    }


def _classify_proxy_exception(exc: Exception) -> tuple[str, str]:
    detail = str(exc or "").lower()
    if "407" in detail or "proxy authentication required" in detail:
        return "auth_failed", "代理认证失败，请检查账号密码"
    if "curl: (28)" in detail or "timed out" in detail or "timeout" in detail:
        return "proxy_timeout", "代理请求超时"
    if "curl: (5)" in detail or "could not resolve proxy" in detail:
        return "dns_error", "无法解析代理地址"
    if "curl: (7)" in detail or "connection refused" in detail or "failed to connect" in detail:
        return "connect_failed", "代理端口拒绝或无法建立连接"
    if "curl: (60)" in detail or "certificate" in detail or "ssl" in detail:
        return "tls_error", "代理链路 TLS 校验失败"
    return "proxy_error", "代理请求失败"


def probe_raw_proxy(
    entry: dict,
    *,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    test_url: str = RAW_PROXY_TEST_URL,
) -> dict:
    source_index = int(entry.get("source_index") or 0)
    proxy = str(entry.get("proxy") or "")
    parsed = urllib.parse.urlparse(proxy)
    host = parsed.hostname
    try:
        port = parsed.port or (1080 if (parsed.scheme or "").startswith("socks5") else 8080)
    except ValueError:
        port = 0
    timeout_value = max(3.0, min(MAX_TIMEOUT_SEC, float(timeout_sec or DEFAULT_TIMEOUT_SEC)))
    started_at = time.perf_counter()

    if not host or not port:
        return _safe_failure(
            "invalid_proxy",
            "代理地址无效",
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=0,
        )

    try:
        with socket.create_connection((host, port), timeout=min(5.0, timeout_value)):
            pass
    except (TimeoutError, socket.timeout):
        return _safe_failure(
            "tcp_timeout",
            "代理端口连接超时，优先检查 IP 白名单或本机网络",
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
    except ConnectionRefusedError:
        return _safe_failure(
            "tcp_refused",
            "代理端口拒绝连接",
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
    except socket.gaierror:
        return _safe_failure(
            "dns_error",
            "无法解析代理地址",
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )
    except OSError:
        return _safe_failure(
            "tcp_error",
            "无法连接代理端口",
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )

    try:
        response = requests.get(
            test_url,
            proxies={"http": proxy, "https": proxy},
            timeout=timeout_value,
            verify=True,
            impersonate="chrome",
        )
    except Exception as exc:
        code, message = _classify_proxy_exception(exc)
        return _safe_failure(
            code,
            message,
            source_index=source_index,
            proxy=proxy,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000),
        )

    elapsed_ms = round((time.perf_counter() - started_at) * 1000)
    status_code = int(getattr(response, "status_code", 0) or 0)
    response_text = str(getattr(response, "text", "") or "")
    loc_match = re.search(r"^loc=([^\r\n]+)$", response_text, re.MULTILINE)
    country = (loc_match.group(1).strip().upper() if loc_match else "")

    if status_code == 407:
        return {
            **_safe_failure(
                "auth_failed",
                "代理认证失败，请检查账号密码",
                source_index=source_index,
                proxy=proxy,
                elapsed_ms=elapsed_ms,
            ),
            "http_status": status_code,
        }
    if status_code < 200 or status_code >= 300:
        return {
            **_safe_failure(
                "http_error",
                f"代理返回 HTTP {status_code or '未知'}",
                source_index=source_index,
                proxy=proxy,
                elapsed_ms=elapsed_ms,
            ),
            "http_status": status_code or None,
            "country": country,
        }
    if country in {"CN", "HK"}:
        return {
            **_safe_failure(
                "blocked_region",
                f"出口地区 {country} 不适合 OpenAI",
                source_index=source_index,
                proxy=proxy,
                elapsed_ms=elapsed_ms,
            ),
            "http_status": status_code,
            "country": country,
        }

    return {
        "source_index": source_index,
        "proxy": proxy_display_name(proxy),
        "ok": True,
        "code": "ok",
        "message": "代理可用",
        "http_status": status_code,
        "country": country,
        "latency_ms": elapsed_ms,
    }


def _build_recommendation(sampled_count: int, ok_count: int, status_counts: Counter) -> str:
    if sampled_count <= 0:
        return "没有可测试的有效代理"
    if ok_count == sampled_count:
        return "抽测代理全部可用"
    if ok_count > 0:
        return f"抽测可用 {ok_count}/{sampled_count}，建议只保留测活成功的代理"
    if status_counts.get("tcp_timeout", 0) == sampled_count:
        return "全部代理端口连接超时，请检查代理商 IP 白名单、本机网络或端口限制"
    if status_counts.get("auth_failed", 0) == sampled_count:
        return "代理端口可达，但账号密码认证全部失败"
    if status_counts.get("blocked_region", 0) == sampled_count:
        return "代理可连接，但出口地区均不适合 OpenAI"
    return "抽测代理均不可用，请按失败原因检查供应商配置"


def probe_raw_proxy_pool(
    entries: Any,
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    concurrency: int = DEFAULT_CONCURRENCY,
) -> dict:
    input_lines = list(_iter_proxy_lines(entries))
    normalized, invalid_count = normalize_probe_entries(input_lines)
    selected = select_evenly_spaced(normalized, sample_size)
    timeout_value = max(3.0, min(MAX_TIMEOUT_SEC, float(timeout_sec or DEFAULT_TIMEOUT_SEC)))
    worker_count = max(1, min(MAX_CONCURRENCY, int(concurrency or DEFAULT_CONCURRENCY), len(selected) or 1))

    results: list[dict] = []
    if selected:
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(probe_raw_proxy, entry, timeout_sec=timeout_value): entry
                for entry in selected
            }
            for future in concurrent.futures.as_completed(futures):
                entry = futures[future]
                try:
                    results.append(future.result())
                except Exception:
                    results.append(
                        _safe_failure(
                            "probe_error",
                            "代理测活发生内部异常",
                            source_index=int(entry.get("source_index") or 0),
                            proxy=str(entry.get("proxy") or ""),
                            elapsed_ms=0,
                        )
                    )
        results.sort(key=lambda item: int(item.get("source_index") or 0))

    status_counts = Counter(str(item.get("code") or "unknown") for item in results)
    country_counts = Counter(
        str(item.get("country") or "").upper()
        for item in results
        if str(item.get("country") or "").strip()
    )
    ok_count = sum(1 for item in results if item.get("ok"))
    sampled_count = len(results)

    return {
        "total_input": len(input_lines),
        "valid_count": len(normalized),
        "invalid_count": invalid_count,
        "sampled_count": sampled_count,
        "ok_count": ok_count,
        "failed_count": sampled_count - ok_count,
        "status_counts": dict(status_counts),
        "country_counts": dict(country_counts),
        "recommendation": _build_recommendation(sampled_count, ok_count, status_counts),
        "results": results,
    }
