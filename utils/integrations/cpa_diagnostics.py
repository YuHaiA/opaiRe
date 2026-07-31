"""CLIProxyAPI 上游测活结果的安全分类与展示辅助函数。

CPA 的 management ``api-call`` 会把真正的上游响应包在 ``status_code`` /
``body`` 中。仅看外层 HTTP 200 会把 Grok 的 402/403 误判成凭证死亡，进而
触发不必要的禁用或复活流程。本模块只提取状态和短错误摘要，不返回令牌、
Cookie 或完整响应体。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


FAILURE_CLASSES = {
    "credential",  # 401、明确的 token 失效
    "quota",  # 402、spending-limit/额度耗尽
    "access_denied",  # 403；可能是风控、地区或账号权限
    "transient",  # 408/409/429/5xx 等暂时性上游错误
    "transport",  # CPA/代理链路超时或连接失败
    "upstream",  # 其他可见的上游错误
}

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(x-api-key\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(access[_-]?token\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(refresh[_-]?token\s*[:=]\s*)[^\s,;]+"),
)


def coerce_status(value: Any) -> int:
    try:
        status = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return status if 100 <= status <= 599 else 0


def decode_json_like(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                return json.loads(text)
            except (TypeError, ValueError):
                return value
    return value


def extract_upstream_status(payload: Any, fallback: Any = 0) -> int:
    """从 CPA envelope 或嵌套 body 提取真实上游 HTTP 状态。"""
    data = decode_json_like(payload)
    if isinstance(data, dict):
        for key in ("status_code", "statusCode", "http_status", "httpStatus", "status"):
            status = coerce_status(data.get(key))
            if status:
                return status
        for key in ("body", "response", "data", "result", "content"):
            status = extract_upstream_status(data.get(key), 0)
            if status:
                return status
    return coerce_status(fallback)


def _walk_error_values(value: Any, depth: int = 0):
    if depth > 4:
        return
    value = decode_json_like(value)
    if isinstance(value, dict):
        for key in ("type", "code", "name", "message", "detail", "error", "status_message"):
            if key in value:
                item = value.get(key)
                if isinstance(item, (str, int, float)):
                    yield str(item)
                elif isinstance(item, (dict, list)):
                    yield from _walk_error_values(item, depth + 1)
        for key in ("body", "response", "data", "result", "content", "text"):
            if key in value:
                yield from _walk_error_values(value.get(key), depth + 1)
    elif isinstance(value, list):
        for item in value[:8]:
            yield from _walk_error_values(item, depth + 1)
    elif isinstance(value, str):
        yield value


def extract_error_summary(payload: Any, *, max_length: int = 240) -> str:
    """返回脱敏、短小的上游错误摘要。"""
    values: list[str] = []
    seen: set[str] = set()
    for raw in _walk_error_values(payload):
        text = " ".join(str(raw).split()).strip()
        if not text:
            continue
        for pattern in _SENSITIVE_PATTERNS:
            text = pattern.sub(r"\1<redacted>", text)
        if text.lower() not in seen:
            seen.add(text.lower())
            values.append(text)
        if len("; ".join(values)) >= max_length:
            break
    summary = "; ".join(values)
    return summary[:max_length].rstrip() if summary else ""


def classify_failure(status_code: Any, payload: Any = None, exception: Any = None) -> Optional[str]:
    """按可恢复性分类，不把 403/网络问题当作永久凭证失效。"""
    status = coerce_status(status_code)
    detail = extract_error_summary(payload).lower()
    if exception is not None or status == 0:
        return "transport"
    if status < 400:
        return None
    if status == 401 or any(
        marker in detail
        for marker in (
            "invalid token",
            "invalid credential",
            "invalid_api_key",
            "unauthorized",
            "token expired",
            "authentication required",
        )
    ):
        return "credential"
    if status == 402 or any(
        marker in detail
        for marker in (
            "spending-limit",
            "spending limit",
            "insufficient_quota",
            "insufficient quota",
            "quota exceeded",
            "quota_exceeded",
            "limit reached",
        )
    ):
        return "quota"
    if status == 403:
        return "access_denied"
    if status in (408, 409, 425, 429) or status >= 500:
        return "transient"
    return "upstream"


def format_failure(status_code: Any, payload: Any = None, failure_class: Optional[str] = None) -> str:
    status = coerce_status(status_code)
    category = failure_class or classify_failure(status, payload)
    labels = {
        "credential": "凭证失效",
        "quota": "上游额度/消费限额",
        "access_denied": "上游拒绝（可能是风控、地区或权限）",
        "transient": "上游暂时性错误",
        "transport": "CPA/代理链路异常",
        "upstream": "上游错误",
    }
    prefix = labels.get(category or "upstream", "上游错误")
    suffix = f" HTTP {status}" if status else ""
    detail = extract_error_summary(payload)
    return f"{prefix}{suffix}" + (f"：{detail}" if detail else "")


def should_preserve_enabled_state(failure_class: Optional[str]) -> bool:
    """403、网络、暂时性和未知上游错误都保留远端启用状态。"""
    return failure_class in {"access_denied", "transient", "transport", "upstream"}
