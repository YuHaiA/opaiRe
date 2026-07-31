from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Tuple


GROK_CLI_BASE_URL = "https://cli-chat-proxy.grok.com/v1"
GROK_CLI_HEADERS = {
    "X-XAI-Token-Auth": "xai-grok-cli",
    "x-grok-client-version": "0.2.93",
    "x-grok-client-identifier": "grok-shell",
}


def detect_account_provider(token_data: Dict[str, Any]) -> str:
    """识别本地凭证属于 OpenAI、Grok，或不适合导出到两个中转。"""
    if not isinstance(token_data, dict):
        return "unknown"

    markers = [
        str(token_data.get(key) or "").strip().lower()
        for key in ("type", "provider", "platform", "status")
    ]
    if any("grok" in value or "xai" in value for value in markers):
        return "grok"

    base_url = str(token_data.get("base_url") or "").strip().lower()
    if "grok.com" in base_url or "x.ai" in base_url:
        return "grok"

    if any("image2api" in value or "仅注册成功" in value for value in markers):
        return "unknown"

    if (
        token_data.get("agent_identity")
        or token_data.get("codex_agent")
        or token_data.get("codex_data")
        or str(token_data.get("auth_mode") or "").strip().lower() == "agent_identity"
    ):
        return "openai"

    if any("codex" in value or "openai" in value for value in markers):
        return "openai"

    if any(
        token_data.get(key)
        for key in (
            "access_token",
            "refresh_token",
            "id_token",
            "account_id",
            "chatgpt_account_id",
            "workspace_id",
        )
    ):
        return "openai"

    return "unknown"


def build_cpa_export_record(token_data: Dict[str, Any]) -> Dict[str, Any]:
    """生成可直接作为 CLIProxyAPI auth-file 使用的单账号 JSON。"""
    provider = detect_account_provider(token_data)
    if provider == "unknown":
        raise ValueError("账号缺少可导出的 OpenAI/Grok 凭证")

    record = deepcopy(token_data)
    if provider == "grok":
        record["type"] = "xai"
        record["provider"] = "grok"
        record["base_url"] = str(record.get("base_url") or GROK_CLI_BASE_URL).strip()
        headers = dict(GROK_CLI_HEADERS)
        raw_headers = record.get("headers")
        if isinstance(raw_headers, dict):
            headers.update({str(key): str(value) for key, value in raw_headers.items() if value is not None})
        record["headers"] = headers
    else:
        # CLIProxyAPI 以 codex 作为 OpenAI OAuth auth-file 的类型标识。
        if not (
            record.get("agent_identity")
            or record.get("codex_agent")
            or record.get("codex_data")
            or str(record.get("auth_mode") or "").strip().lower() == "agent_identity"
        ):
            record["type"] = "codex"
        record["provider"] = "openai"

    return record


def build_cpa_export_records(
    token_items: Iterable[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    records: List[Dict[str, Any]] = []
    skipped: List[str] = []
    for token_data in token_items:
        try:
            records.append(build_cpa_export_record(token_data))
        except ValueError:
            skipped.append(str((token_data or {}).get("email") or "unknown"))
    return records, skipped
