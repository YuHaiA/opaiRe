import urllib.parse
import random
import time
import requests as std_requests
import copy
from datetime import datetime
import yaml
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils.clash_group_utils import resolve_group_name

CLASH_API_URL = ""
LOCAL_PROXY_URL = ""
ENABLE_NODE_SWITCH = False
POOL_MODE = False
FASTEST_MODE = False
PROXY_GROUP_NAME = "节点选择"
CLASH_SECRET = ""
NODE_BLACKLIST = []
EVICTED_NODES = []
TESTED_NODES_MAP = {}
PREFERRED_NODES_MAP = {}
PREFERRED_ONLY_MODE = False
_IS_IN_DOCKER = os.path.exists('/.dockerenv')
_global_switch_lock = threading.Lock()
_last_switch_time = 0
_CURRENT_NODE_BY_PROXY = {}
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(CURRENT_DIR)
DEFAULT_NODE_BLACKLIST = ["港", "HK", "台", "TW", "中国", "CN"]
MIN_CLASH_CANDIDATES_BEFORE_EVICT = 3

def format_docker_url(url: str) -> str:
    """智能检测：如果在 Docker 中运行，自动把 127.0.0.1 转为宿主机魔法地址"""
    if not url or not isinstance(url, str):
        return url
    if _IS_IN_DOCKER:
        if "127.0.0.1" in url:
            return url.replace("127.0.0.1", "host.docker.internal")
        if "localhost" in url:
            return url.replace("localhost", "host.docker.internal")
    return url

def reload_proxy_config():
    global CLASH_API_URL, LOCAL_PROXY_URL, ENABLE_NODE_SWITCH, POOL_MODE, \
           FASTEST_MODE, PROXY_GROUP_NAME, CLASH_SECRET, NODE_BLACKLIST, EVICTED_NODES, TESTED_NODES_MAP, \
           PREFERRED_NODES_MAP, PREFERRED_ONLY_MODE
    config_dir = os.path.join(BASE_DIR, "data")
    config_path = os.path.join(config_dir, "config.yaml")
    if not os.path.exists(config_path):
        print(f"[{ts()}] [WARNING] 配置文件 {config_path} 不存在，使用默认代理设置。")
        conf_data = {}
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            conf_data = yaml.safe_load(f) or {}

    clash_conf = conf_data.get("clash_proxy_pool", {})
    ENABLE_NODE_SWITCH = clash_conf.get("enable", False)
    POOL_MODE = clash_conf.get("pool_mode", False)
    FASTEST_MODE = clash_conf.get("fastest_mode", False)
    CLASH_API_URL = format_docker_url(clash_conf.get("api_url", "http://127.0.0.1:9090"))
    LOCAL_PROXY_URL = format_docker_url(clash_conf.get("test_proxy_url", "http://127.0.0.1:7890"))
    
    PROXY_GROUP_NAME = clash_conf.get("group_name", "节点选择")
    CLASH_SECRET = clash_conf.get("secret", "")
    raw_blacklist = clash_conf.get("blacklist", DEFAULT_NODE_BLACKLIST)
    NODE_BLACKLIST = raw_blacklist if isinstance(raw_blacklist, list) else list(DEFAULT_NODE_BLACKLIST)
    raw_evicted_nodes = clash_conf.get("evicted_nodes", [])
    EVICTED_NODES = raw_evicted_nodes if isinstance(raw_evicted_nodes, list) else []
    TESTED_NODES_MAP = clash_conf.get("tested_nodes", {}) if isinstance(clash_conf.get("tested_nodes", {}), dict) else {}
    PREFERRED_NODES_MAP = clash_conf.get("preferred_nodes", {}) if isinstance(clash_conf.get("preferred_nodes", {}), dict) else {}
    PREFERRED_ONLY_MODE = bool(clash_conf.get("preferred_only_mode", False))
   
    print(f"[{ts()}] [系统] 代理管理模块配置已同步更新。")

def ts() -> str:
    """获取当前时间戳字符串，用于日志"""
    return datetime.now().strftime("%H:%M:%S")

def clean_for_log(text: str) -> str:
    """用于日志输出：过滤掉字符串中的国旗、飞机、火箭等 Emoji 符号"""
    emoji_pattern = re.compile(
        r'[\U0001F1E6-\U0001F1FF]'
        r'|[\U0001F300-\U0001F6FF]'
        r'|[\U0001F900-\U0001F9FF]'
        r'|[\U00002600-\U000027BF]'
        r'|[\uFE0F]'
    )
    return emoji_pattern.sub('', text).strip()

def get_display_name(proxy_url: str) -> str:
    """统一日志脱敏：将 URL 转换为 [X号机] 或隐藏域名"""
    if not proxy_url:
        return "全局单机"
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        if parsed.port and 41000 < parsed.port <= 41050:
            return f"{parsed.port - 41000}号机"
        return f"端口:{parsed.port}"
    except:
        return "未知通道"

def get_api_url_for_proxy(proxy_url: str) -> str:
    """根据开关决定是独立容器 API，还是使用固定 API"""
    if not POOL_MODE or not proxy_url:
        return CLASH_API_URL
    try:
        parsed = urllib.parse.urlparse(proxy_url)
        port = parsed.port
        if port and 41000 < port <= 41050:
            api_port = port + 1000
            return format_docker_url(f"http://{parsed.hostname}:{api_port}")
    except Exception:
        pass
    return CLASH_API_URL


def _proxy_key(proxy_url=None) -> str:
    normalized = format_docker_url(proxy_url) if proxy_url else ""
    return normalized or "__shared__"


def _remember_current_node(proxy_url, node_name: str) -> None:
    if not node_name:
        return
    _CURRENT_NODE_BY_PROXY[_proxy_key(proxy_url)] = str(node_name).strip()


def _load_runtime_config_for_write() -> dict:
    try:
        from utils import config as runtime_cfg
        runtime_config = getattr(runtime_cfg, "_c", None)
        if isinstance(runtime_config, dict) and runtime_config:
            return copy.deepcopy(runtime_config)
    except Exception:
        pass
    config_path = os.path.join(BASE_DIR, "data", "config.yaml")
    if not os.path.exists(config_path):
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except Exception:
        return {}


def get_current_selected_node(proxy_url=None) -> str:
    cached = str(_CURRENT_NODE_BY_PROXY.get(_proxy_key(proxy_url), "") or "").strip()
    if cached:
        return cached

    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code != 200:
            return ""
        proxies_data = resp.json().get("proxies", {})
        actual_group_name = resolve_group_name(proxies_data, PROXY_GROUP_NAME)
        if not actual_group_name:
            return ""
        selected = str(proxies_data.get(actual_group_name, {}).get("now", "") or "").strip()
        if selected:
            _remember_current_node(proxy_url, selected)
        return selected
    except Exception:
        return ""


def get_failure_bucket_id(proxy_url=None) -> str:
    normalized_proxy = format_docker_url(proxy_url) if proxy_url else ""
    try:
        from utils import config as runtime_cfg
        if runtime_cfg.is_raw_proxy_pool_enabled() and normalized_proxy:
            return f"raw::{normalized_proxy}"
    except Exception:
        pass

    current_node = get_current_selected_node(proxy_url)
    if current_node:
        return f"clash::{current_node}"
    if normalized_proxy:
        return f"proxy::{normalized_proxy}"
    return "shared::default"


def _is_skip_evict_guard_message(message: str) -> bool:
    return str(message or "").startswith("SKIP_EVICT_GUARD:")


def _format_skip_evict_guard_message(message: str) -> str:
    raw = str(message or "")
    if _is_skip_evict_guard_message(raw):
        return raw.split(":", 1)[1].strip()
    return raw


def _lookup_group_nodes(node_map: dict, actual_group_name: str, configured_group_name: str) -> list[str]:
    if not isinstance(node_map, dict):
        return []
    preferred = node_map.get(actual_group_name)
    if isinstance(preferred, list):
        return [str(node).strip() for node in preferred if str(node).strip()]
    fallback = node_map.get(configured_group_name)
    if isinstance(fallback, list):
        return [str(node).strip() for node in fallback if str(node).strip()]
    return []


def _resolve_group_candidate_nodes(proxies_data: dict, group_name: str, current_node: str = "", clash_conf: dict | None = None):
    actual_group_name = resolve_group_name(proxies_data, group_name)
    if not actual_group_name:
        return "", [], {"preferred_only_mode": False, "preferred_nodes": [], "tested_nodes": [], "valid_nodes": []}

    source_conf = clash_conf if isinstance(clash_conf, dict) else {}
    evicted_nodes = source_conf.get("evicted_nodes", EVICTED_NODES)
    if not isinstance(evicted_nodes, list):
        evicted_nodes = EVICTED_NODES
    tested_map = source_conf.get("tested_nodes", TESTED_NODES_MAP)
    if not isinstance(tested_map, dict):
        tested_map = TESTED_NODES_MAP
    preferred_map = source_conf.get("preferred_nodes", PREFERRED_NODES_MAP)
    if not isinstance(preferred_map, dict):
        preferred_map = PREFERRED_NODES_MAP
    preferred_only_mode = bool(source_conf.get("preferred_only_mode", PREFERRED_ONLY_MODE))

    runtime_group = proxies_data.get(actual_group_name, {})
    all_nodes = runtime_group.get("all", []) if isinstance(runtime_group, dict) else []
    valid_nodes = [
        node for node in all_nodes
        if node != current_node
        and node not in evicted_nodes
        and not any(kw.upper() in str(node).upper() for kw in NODE_BLACKLIST)
    ]
    preferred_nodes = [
        node for node in _lookup_group_nodes(preferred_map, actual_group_name, group_name)
        if node in valid_nodes
    ]
    tested_nodes = [
        node for node in _lookup_group_nodes(tested_map, actual_group_name, group_name)
        if node in valid_nodes
    ]

    if preferred_only_mode:
        candidates = preferred_nodes
    elif tested_nodes:
        candidates = tested_nodes
    else:
        candidates = valid_nodes
    return actual_group_name, candidates, {
        "preferred_only_mode": preferred_only_mode,
        "preferred_nodes": preferred_nodes,
        "tested_nodes": tested_nodes,
        "valid_nodes": valid_nodes,
    }


def _resolve_effective_candidate_count(proxy_url, clash_conf: dict, current_node: str) -> int | None:
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}

    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code == 200:
            proxies_data = resp.json().get("proxies", {})
            _, candidate_nodes, _ = _resolve_group_candidate_nodes(
                proxies_data,
                PROXY_GROUP_NAME,
                current_node=current_node,
                clash_conf=clash_conf,
            )
            return len(candidate_nodes)
    except Exception:
        pass

    preferred_only_mode = bool(clash_conf.get("preferred_only_mode", PREFERRED_ONLY_MODE))
    fallback_map = clash_conf.get("preferred_nodes", PREFERRED_NODES_MAP) if preferred_only_mode else clash_conf.get("tested_nodes", TESTED_NODES_MAP)
    if not isinstance(fallback_map, dict):
        fallback_map = PREFERRED_NODES_MAP if preferred_only_mode else TESTED_NODES_MAP
    fallback_candidates = fallback_map.get(PROXY_GROUP_NAME, [])
    if isinstance(fallback_candidates, list) and fallback_candidates:
        filtered = [node for node in fallback_candidates if node != current_node]
        return len(filtered)
    return None


def _is_preferred_clash_node(clash_conf: dict, current_node: str) -> bool:
    preferred_map = clash_conf.get("preferred_nodes", PREFERRED_NODES_MAP)
    if not isinstance(preferred_map, dict):
        return False
    for nodes in preferred_map.values():
        if isinstance(nodes, list) and current_node in nodes:
            return True
    return False


def _probe_clash_group_nodes(proxy_url, group_name: str) -> tuple[list[str], str]:
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
    if resp.status_code != 200:
        return [], f"无法连接 Clash API: HTTP {resp.status_code}"
    proxies_data = resp.json().get("proxies", {})
    actual_group = resolve_group_name(proxies_data, group_name)
    runtime_group = proxies_data.get(actual_group) if actual_group else None
    if not isinstance(runtime_group, dict):
        return [], f"未找到策略组 [{clean_for_log(group_name)}]"
    nodes = runtime_group.get("all")
    if not isinstance(nodes, list) or not nodes:
        return [], f"策略组 [{clean_for_log(actual_group or group_name)}] 没有可测节点"
    delay_url = "https://www.gstatic.com/generate_204"

    def probe(node_name: str):
        encoded = urllib.parse.quote(node_name, safe="")
        try:
            result = std_requests.get(
                f"{current_api_url}/proxies/{encoded}/delay",
                headers=headers,
                params={"timeout": 5000, "url": delay_url},
                timeout=8,
            )
            if result.status_code != 200:
                return node_name, None
            delay = (result.json() or {}).get("delay")
            if isinstance(delay, (int, float)) and delay > 0:
                return node_name, int(delay)
        except Exception:
            pass
        return node_name, None

    results = []
    worker_count = max(1, min(20, len(nodes)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(probe, node) for node in nodes]
        for future in as_completed(futures):
            node_name, delay = future.result()
            if delay is not None:
                results.append((node_name, delay))
    healthy_nodes = [node for node, _ in sorted(results, key=lambda item: item[1])]
    return healthy_nodes, actual_group or group_name


def _rebuild_clash_node_pools_after_floor(proxy_url, config_data: dict, clash_conf: dict) -> tuple[dict, str]:
    group_name = PROXY_GROUP_NAME
    healthy_nodes, resolved_group = _probe_clash_group_nodes(proxy_url, group_name)
    clash_conf["evicted_nodes"] = []
    clash_conf["preferred_nodes"] = {}
    clash_conf["tested_nodes"] = {str(resolved_group or group_name): healthy_nodes}
    config_data["clash_proxy_pool"] = clash_conf
    return config_data, (
        f"触发底线重建：已清空拉黑/标优/有效节点池，"
        f"策略组 [{clean_for_log(resolved_group or group_name)}] 重新测活通过 {len(healthy_nodes)} 个节点"
    )


def mark_current_clash_node_preferred(proxy_url=None) -> tuple[bool, str]:
    config_data = _load_runtime_config_for_write()
    current_node = get_current_selected_node(proxy_url)
    if not current_node:
        return False, f"{get_display_name(proxy_url)} 当前未解析到可标优节点"

    clash_conf = config_data.get("clash_proxy_pool", {})
    if not isinstance(clash_conf, dict):
        clash_conf = {}

    group_name = PROXY_GROUP_NAME
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code == 200:
            proxies_data = resp.json().get("proxies", {})
            resolved_group = resolve_group_name(proxies_data, PROXY_GROUP_NAME)
            if resolved_group:
                group_name = resolved_group
    except Exception:
        pass

    preferred_map = clash_conf.get("preferred_nodes", {})
    if not isinstance(preferred_map, dict):
        preferred_map = {}
    preferred_nodes = preferred_map.get(group_name, [])
    if not isinstance(preferred_nodes, list):
        preferred_nodes = []
    if current_node in preferred_nodes:
        return True, f"Clash 节点 [{clean_for_log(current_node)}] 已在标优池中"
    preferred_nodes.append(current_node)
    preferred_map[group_name] = preferred_nodes
    clash_conf["preferred_nodes"] = preferred_map

    tested_map = clash_conf.get("tested_nodes", {})
    if not isinstance(tested_map, dict):
        tested_map = {}
    tested_nodes = tested_map.get(group_name, [])
    if not isinstance(tested_nodes, list):
        tested_nodes = []
    if current_node not in tested_nodes:
        tested_nodes.append(current_node)
    tested_map[group_name] = tested_nodes
    clash_conf["tested_nodes"] = tested_map

    config_data["clash_proxy_pool"] = clash_conf
    try:
        from utils import config as runtime_cfg
        runtime_cfg.reload_all_configs(new_config_dict=config_data)
    except Exception as exc:
        return False, f"保存标优节点失败: {exc}"
    return True, f"已将 Clash 节点标记为标优 [{clean_for_log(current_node)}]"


def evict_current_proxy_or_node(proxy_url=None):
    config_data = _load_runtime_config_for_write()
    try:
        from utils import config as runtime_cfg
    except Exception as exc:
        return False, f"加载运行配置失败: {exc}"

    normalized_proxy = format_docker_url(proxy_url) if proxy_url else ""

    if runtime_cfg.is_raw_proxy_pool_enabled():
        raw_conf = config_data.get("raw_proxy_pool", {})
        entries = raw_conf.get("proxy_list", []) if isinstance(raw_conf, dict) else []
        target = runtime_cfg.normalize_raw_proxy_entry(normalized_proxy)
        kept_entries = [
            entry for entry in entries
            if runtime_cfg.normalize_raw_proxy_entry(entry) != target
        ]
        if len(kept_entries) == len(entries):
            return False, f"原始代理池里未找到目标代理: {get_display_name(normalized_proxy)}"
        raw_conf["proxy_list"] = kept_entries
        config_data["raw_proxy_pool"] = raw_conf
        runtime_cfg.reload_all_configs(new_config_dict=config_data)
        if not kept_entries:
            runtime_cfg.POOL_EXHAUSTED = True
        return True, f"已从原始代理池移除 {get_display_name(normalized_proxy)}"

    current_node = get_current_selected_node(proxy_url)
    if not current_node:
        return False, f"{get_display_name(proxy_url)} 当前未解析到可拉黑节点"

    clash_conf = config_data.get("clash_proxy_pool", {})
    if not isinstance(clash_conf, dict):
        clash_conf = {}

    remaining_candidates = _resolve_effective_candidate_count(proxy_url, clash_conf, current_node)
    should_rebuild_after_evict = (
        remaining_candidates is not None
        and remaining_candidates <= MIN_CLASH_CANDIDATES_BEFORE_EVICT
    )

    evicted_nodes = clash_conf.get("evicted_nodes", [])
    if not isinstance(evicted_nodes, list):
        evicted_nodes = []
    if current_node not in evicted_nodes:
        evicted_nodes.append(current_node)
    clash_conf["evicted_nodes"] = evicted_nodes

    tested_map = clash_conf.get("tested_nodes", {})
    if isinstance(tested_map, dict):
        for group_name, nodes in list(tested_map.items()):
            if isinstance(nodes, list):
                tested_map[group_name] = [node for node in nodes if node != current_node]
        clash_conf["tested_nodes"] = tested_map

    preferred_map = clash_conf.get("preferred_nodes", {})
    if isinstance(preferred_map, dict):
        for group_name, nodes in list(preferred_map.items()):
            if isinstance(nodes, list):
                preferred_map[group_name] = [node for node in nodes if node != current_node]
        clash_conf["preferred_nodes"] = preferred_map

    config_data["clash_proxy_pool"] = clash_conf
    rebuild_msg = ""
    if should_rebuild_after_evict:
        try:
            config_data, rebuild_msg = _rebuild_clash_node_pools_after_floor(proxy_url, config_data, clash_conf)
        except Exception as exc:
            rebuild_msg = f"触发底线重建但重新测活失败: {exc}"
    runtime_cfg.reload_all_configs(new_config_dict=config_data)
    msg = f"已从活节点池移除并拉黑 Clash 节点 [{clean_for_log(current_node)}]"
    if rebuild_msg:
        msg = f"{msg}；{rebuild_msg}"
    return True, msg


def evict_failed_switch_candidate(proxy_url=None, candidate_name: str = "") -> tuple[bool, str]:
    candidate_name = str(candidate_name or "").strip()
    if candidate_name:
        _remember_current_node(proxy_url, candidate_name)
    return evict_current_proxy_or_node(proxy_url)

def test_proxy_liveness(proxy_url=None):
    """测试当前代理是否可用 (脱敏)"""
    raw_url = proxy_url if proxy_url else LOCAL_PROXY_URL
    target_proxy = format_docker_url(raw_url)
    proxies = {"http": target_proxy, "https": target_proxy}
    display_name = get_display_name(proxy_url if proxy_url else LOCAL_PROXY_URL)
    
    try:
        res = std_requests.get("https://cloudflare.com/cdn-cgi/trace", proxies=proxies, timeout=5)
        if res.status_code == 200:
            loc = "UNKNOWN"
            for line in res.text.split('\n'):
                if line.startswith("loc="):
                    loc = line.split("=")[1].strip()

            blocked_regions = ["CN", "HK"]
            if loc in blocked_regions:
                print(f"[{ts()}] [代理测活] {display_name} 地区受限 ({loc})，弃用！")
                return False
                
            print(f"[{ts()}] [代理测活] {display_name} 成功！地区 ({loc})，延迟: {res.elapsed.total_seconds():.2f}s")
            return True
        return False
    except Exception:
        print(f"[{ts()}] [代理测活] {display_name} 链路中断或超时。")
        return False


def smart_switch_node(proxy_url=None, force=False):
    global _last_switch_time
    if not ENABLE_NODE_SWITCH:
        return True

    # 如果是独立代理池模式，互相不影响，不需要锁
    if POOL_MODE and proxy_url:
        return _do_smart_switch(proxy_url)

    with _global_switch_lock:
        if not force and time.time() - _last_switch_time < 10:
            print(f"[{ts()}] [代理池] 其他线程刚完成切换，跳过本次请求...")
            return True

        success = _do_smart_switch(proxy_url)
        if success:
            _last_switch_time = time.time()
        return success

def _do_smart_switch(proxy_url=None):
    """智能切换节点并测活的核心逻辑 (脱敏)"""
    if not ENABLE_NODE_SWITCH:
        return True
        
    current_api_url = get_api_url_for_proxy(proxy_url)
    headers = {"Authorization": f"Bearer {CLASH_SECRET}"} if CLASH_SECRET else {}
    
    display_name = get_display_name(proxy_url)

    api_display = get_display_name(current_api_url).replace("号机", "号API")
    
    try:
        resp = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
        if resp.status_code != 200:
            print(f"[{ts()}] [ERROR] 无法连接 Clash API ({api_display})，请检查容器状态。")
            return False
            
        proxies_data = resp.json().get('proxies', {})

        actual_group_name = resolve_group_name(proxies_data, PROXY_GROUP_NAME)

        if not actual_group_name:
            available_groups = [
                key for key, value in proxies_data.items()
                if isinstance(value, dict) and 'all' in value
            ]
            print(
                f"[{ts()}] [ERROR] {display_name} 找不到策略组关键词 '{PROXY_GROUP_NAME}'。"
                f" 当前可用策略组: {', '.join(clean_for_log(g) for g in available_groups[:8])}"
            )
            return False
            
        safe_group_name = urllib.parse.quote(actual_group_name)
        _, valid_nodes, pool_meta = _resolve_group_candidate_nodes(proxies_data, actual_group_name)
        if pool_meta["preferred_only_mode"]:
            if valid_nodes:
                print(f"[{ts()}] [代理池] {display_name} 已锁定到标优节点池，共 {len(valid_nodes)} 个。")
            else:
                print(f"[{ts()}] [ERROR] {display_name} 当前已开启仅用标优节点，但策略组暂无标优节点。")
                return False
        elif pool_meta["tested_nodes"]:
            print(f"[{ts()}] [代理池] {display_name} 已锁定到测速通过节点池，共 {len(valid_nodes)} 个。")

        if not valid_nodes:
            print(f"[{ts()}] [ERROR] {display_name} 过滤后无可用节点，请检查黑名单。")
            return False

        nodes_with_delay = []
        try:
            for node_name in valid_nodes:
                history = proxies_data.get(node_name, {}).get("history", [])
                if not history:
                    continue
                delay = history[-1].get("delay", 0)
                if isinstance(delay, (int, float)) and delay > 0:
                    nodes_with_delay.append((node_name, float(delay)))
        except Exception:
            nodes_with_delay = []

        if FASTEST_MODE:
            print(f"\n[{ts()}] [代理池] {display_name} 开启优选模式，并发测速 {len(valid_nodes)} 个节点...")
            
            session = std_requests.Session()
            
            def trigger_delay(n):
                enc_n = urllib.parse.quote(n, safe="")
                try:
                    session.get(
                        f"{current_api_url}/proxies/{enc_n}/delay?timeout=2000&url=http://www.gstatic.com/generate_204", 
                        headers=headers, timeout=2.5
                    )
                except:
                    pass

            thread_count = min(10, len(valid_nodes))
            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                executor.map(trigger_delay, valid_nodes)
                
            session.close()
                
            time.sleep(1.5)
            
            try:
                resp2 = std_requests.get(f"{current_api_url}/proxies", headers=headers, timeout=5)
                if resp2.status_code == 200:
                    p_data = resp2.json().get('proxies', {})
                    best_node = None
                    min_delay = float('inf')
                    
                    for n in valid_nodes:
                        history = p_data.get(n, {}).get("history", [])
                        if history:
                            delay = history[-1].get("delay", 0)
                            if 0 < delay < min_delay:
                                min_delay = delay
                                best_node = n
                    
                    if best_node:
                        print(f"[{ts()}] [代理池] {display_name} 测速完成，最快节点: [{clean_for_log(best_node)}] ({min_delay}ms)")
                        switch_resp = std_requests.put(
                            f"{current_api_url}/proxies/{safe_group_name}", 
                            headers=headers, json={"name": best_node}, timeout=5
                        )
                        if switch_resp.status_code == 204:
                            time.sleep(1)
                            if test_proxy_liveness(proxy_url):
                                _remember_current_node(proxy_url, best_node)
                                return True
                            removed, remove_msg = evict_failed_switch_candidate(proxy_url, best_node)
                            if removed:
                                print(f"[{ts()}] [代理池] {display_name} 测活失败，已剔除节点: {remove_msg}")
                            elif _is_skip_evict_guard_message(remove_msg):
                                print(
                                    f"[{ts()}] [代理池] {display_name} 测活失败，但已触发保底保护: "
                                    f"{_format_skip_evict_guard_message(remove_msg)}"
                                )
                            else:
                                print(f"[{ts()}] [代理池] {display_name} 测活失败，剔除节点失败: {remove_msg}")
                            valid_nodes = [n for n in valid_nodes if n != best_node]
                            nodes_with_delay = [item for item in nodes_with_delay if item[0] != best_node]
                            print(f"[{ts()}] [代理池] {display_name} 最快节点测活失败，回退到随机抽卡模式...")
                    else:
                        print(f"[{ts()}] [代理池] {display_name} 所有节点均超时，回退到随机抽卡模式...")
            except Exception as e:
                print(f"[{ts()}] [代理池] {display_name} 优选模式异常: {e}，回退到随机抽卡模式...")

        random_candidates = [name for name, _ in sorted(nodes_with_delay, key=lambda item: item[1])]
        if not random_candidates:
            random_candidates = list(valid_nodes)
            print(f"[{ts()}] [代理池] {display_name} 未发现带有效延迟记录的节点，回退为全量候选抽卡。")

        max_retries = 10
        for i in range(1, max_retries + 1):
            selected_node = random.choice(random_candidates)
            
            print(f"\n[{ts()}] [代理池] {display_name} 尝试切换节点: [{clean_for_log(selected_node)}] ({i}/{max_retries})")
            
            switch_resp = std_requests.put(
                f"{current_api_url}/proxies/{safe_group_name}", 
                headers=headers, json={"name": selected_node}, timeout=5
            )
            
            if switch_resp.status_code == 204:
                time.sleep(1.5)
                if test_proxy_liveness(proxy_url):
                    _remember_current_node(proxy_url, selected_node)
                    return True
                removed, remove_msg = evict_failed_switch_candidate(proxy_url, selected_node)
                if removed:
                    print(f"[{ts()}] [代理池] {display_name} 测活失败，已剔除节点: {remove_msg}")
                elif _is_skip_evict_guard_message(remove_msg):
                    print(
                        f"[{ts()}] [代理池] {display_name} 测活失败，但已触发保底保护: "
                        f"{_format_skip_evict_guard_message(remove_msg)}"
                    )
                else:
                    print(f"[{ts()}] [代理池] {display_name} 测活失败，剔除节点失败: {remove_msg}")
                random_candidates = [name for name in random_candidates if name != selected_node]
                print(f"[{ts()}] [代理池] {display_name} 测活失败，重新抽卡...")
            else:
                print(f"[{ts()}] [代理池] {display_name} 指令下发失败 (HTTP {switch_resp.status_code})。")
                
        print(f"\n[{ts()}] [代理池] {display_name} 连续 10 次抽卡均不可用！")
        return False
        
    except Exception as e:
        print(f"[{ts()}] [ERROR] {display_name} 切换节点异常: {e}")
        return False

reload_proxy_config()
