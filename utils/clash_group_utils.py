import re
from typing import Optional

_GROUP_TYPES_SWITCHABLE = {"selector"}
_PREFERRED_SWITCH_GROUPS = (
    "PROXY",
    "Proxy",
    "proxy",
    "节点选择",
    "手动选择",
    "选择节点",
)


def strip_group_decorations(text: str) -> str:
    raw = str(text or "").strip().lower()
    raw = re.sub(r'[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\ufe0f]', '', raw)
    raw = re.sub(r'[\s\-_]+', '', raw)
    return raw


def resolve_group_name(proxy_map: dict, desired_group_name: str) -> Optional[str]:
    desired = strip_group_decorations(desired_group_name)
    for key, value in (proxy_map or {}).items():
        if isinstance(value, dict) and "all" in value and key == desired_group_name:
            return key
    fuzzy = []
    for key, value in (proxy_map or {}).items():
        if not (isinstance(value, dict) and 'all' in value):
            continue
        current = strip_group_decorations(key)
        if desired and (desired in current or current in desired):
            fuzzy.append(key)
    for key in fuzzy:
        if is_switchable_group(proxy_map, key):
            return key
    return fuzzy[0] if fuzzy else None


def group_type_name(proxy_map: dict, group_name: str) -> str:
    meta = (proxy_map or {}).get(group_name) if group_name else None
    return str(meta.get("type") or "").strip() if isinstance(meta, dict) else ""


def is_switchable_group(proxy_map: dict, group_name: str) -> bool:
    return group_type_name(proxy_map, group_name).lower() in _GROUP_TYPES_SWITCHABLE


def resolve_switchable_group_name(proxy_map: dict, desired_group_name: str) -> Optional[str]:
    primary = resolve_group_name(proxy_map, desired_group_name)
    if primary and is_switchable_group(proxy_map, primary):
        return primary
    for candidate in _PREFERRED_SWITCH_GROUPS:
        resolved = resolve_group_name(proxy_map, candidate)
        if resolved and is_switchable_group(proxy_map, resolved):
            return resolved
    selectors = [
        (len(value.get("all") or []), key)
        for key, value in (proxy_map or {}).items()
        if isinstance(value, dict) and "all" in value and is_switchable_group(proxy_map, key)
    ]
    return max(selectors)[1] if selectors else None


def merge_proxy_provider_metadata(proxy_map: dict, provider_payload: dict) -> dict:
    merged = dict(proxy_map or {})
    providers = provider_payload.get("providers", {}) if isinstance(provider_payload, dict) else {}
    if not isinstance(providers, dict):
        return merged
    for provider in providers.values():
        provider_proxies = provider.get("proxies", []) if isinstance(provider, dict) else []
        for proxy in provider_proxies if isinstance(provider_proxies, list) else []:
            if not isinstance(proxy, dict):
                continue
            name = str(proxy.get("name") or "").strip()
            if name and name not in merged:
                merged[name] = proxy
    return merged
