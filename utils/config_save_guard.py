from copy import deepcopy


CLASH_RUNTIME_PRESERVED_KEYS = (
    "sub_url",
    "sub_urls",
    "selected_subscription_id",
    "tested_nodes",
    "evicted_nodes",
)


def merge_runtime_owned_clash_state(current_config: dict, incoming_config: dict) -> dict:
    merged_config = deepcopy(incoming_config if isinstance(incoming_config, dict) else {})
    current_clash = current_config.get("clash_proxy_pool", {}) if isinstance(current_config.get("clash_proxy_pool"), dict) else {}
    incoming_clash = merged_config.get("clash_proxy_pool", {}) if isinstance(merged_config.get("clash_proxy_pool"), dict) else {}

    if not current_clash and not incoming_clash:
        return merged_config

    merged_clash = deepcopy(incoming_clash)
    for key in CLASH_RUNTIME_PRESERVED_KEYS:
        if key in current_clash:
            merged_clash[key] = deepcopy(current_clash.get(key))
    merged_config["clash_proxy_pool"] = merged_clash
    return merged_config
