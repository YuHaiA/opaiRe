"""Local client: pull codes from remote email bridge into auth_core.code_pool."""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional, Set
from urllib.parse import quote

from utils import config as cfg

_client_lock = threading.Lock()
_watched: Set[str] = set()
_threads: Dict[str, threading.Thread] = {}
_sockets: Dict[str, Any] = {}
_deadlines: Dict[str, float] = {}
_code_events: Dict[str, threading.Event] = {}
_code_arrival_ts: Dict[str, float] = {}
_stop = threading.Event()
_DEFAULT_LISTENER_TTL_SEC = 300.0
# Cloudflare / 公网反代上 websockets 默认 20s ping 很容易 1011 keepalive timeout，
# 并在后台线程打出吓人的 traceback；收码以 HTTP 轮询为主、WS 只做加速。
_WS_RECV_TIMEOUT_SEC = 15.0
_HTTP_POLL_IDLE_SEC = 1.2
_WS_RETRY_SLEEP_SEC = 1.0


def _log(msg: str) -> None:
    try:
        print(f"[{cfg.ts()}] {msg}")
    except Exception:
        print(msg)


def _bridge_enabled() -> bool:
    return bool(getattr(cfg, "OPENAI_CPA_BRIDGE_ENABLED", False))


def _local_webhook_enabled() -> bool:
    return bool(getattr(cfg, "OPENAI_CPA_LOCAL_WEBHOOK", False))


def _listener_enabled() -> bool:
    """Remote bridge pull and/or local WS push against this process."""
    return _bridge_enabled() or _local_webhook_enabled()


def _bridge_base() -> str:
    return str(getattr(cfg, "OPENAI_CPA_BRIDGE_BASE_URL", "") or "").strip().rstrip("/")


def _local_base() -> str:
    """Loopback base for same-process WS/HTTP (local_webhook mode)."""
    host = str(getattr(cfg, "WEB_LISTEN_HOST", "") or "127.0.0.1").strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    port = (
        getattr(cfg, "WEB_LISTEN_PORT", None)
        or getattr(cfg, "WEB_PORT", None)
        or os_getenv_port()
    )
    try:
        port = int(port or 8000)
    except (TypeError, ValueError):
        port = 8000
    return f"http://{host}:{port}"


def os_getenv_port() -> int:
    import os
    for key in ("WEB_PORT", "PORT"):
        raw = str(os.getenv(key, "") or "").strip()
        if raw.isdigit():
            return int(raw)
    return 8000


def _bridge_token() -> str:
    token = str(getattr(cfg, "OPENAI_CPA_BRIDGE_TOKEN", "") or "").strip()
    if token:
        return token
    return str(getattr(cfg, "OPENAI_CPA_WEBHOOK_SECRET", "") or "").strip()


def _auth_headers() -> Dict[str, str]:
    token = _bridge_token()
    return {"Authorization": f"Bearer {token}"} if token else {}


def set_local_listen_endpoint(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Called by web launcher so local WS knows the real bound port."""
    try:
        port_i = int(port)
    except (TypeError, ValueError):
        port_i = 8000
    host_s = str(host or "127.0.0.1").strip() or "127.0.0.1"
    if host_s in {"0.0.0.0", "::", "[::]"}:
        host_s = "127.0.0.1"
    try:
        cfg.WEB_LISTEN_HOST = host_s
        cfg.WEB_LISTEN_PORT = port_i
    except Exception:
        pass


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _remaining_watch_time(email: str) -> float:
    if _stop.is_set():
        return 0.0
    now = time.monotonic()
    with _client_lock:
        if email not in _watched:
            return 0.0
        deadline = _deadlines.get(email)
        if deadline is None:
            deadline = now + _DEFAULT_LISTENER_TTL_SEC
            _deadlines[email] = deadline
        remaining = deadline - now
        if remaining <= 0:
            _watched.discard(email)
            _deadlines.pop(email, None)
            return 0.0
        return remaining


def _remember_socket(email: str, socket: Any) -> bool:
    with _client_lock:
        if email not in _watched or _stop.is_set():
            return False
        _sockets[email] = socket
        return True


def _forget_socket(email: str, socket: Any) -> None:
    with _client_lock:
        if _sockets.get(email) is socket:
            _sockets.pop(email, None)


def _mask_email(email: str) -> str:
    raw = str(email or "").strip()
    if "@" not in raw:
        return raw[:3] + "***" if raw else ""
    name, domain = raw.split("@", 1)
    return f"{name[:2]}***@{domain[:3]}***"


def arm_code_wait(email: str) -> threading.Event:
    """Register an event so local webhook can wake the waiter immediately."""
    email = _normalize_email(email)
    ev = threading.Event()
    if not email:
        return ev
    with _client_lock:
        old = _code_events.get(email)
        _code_events[email] = ev
    if old is not None and old.is_set():
        ev.set()
    return ev


def clear_code_wait(email: str, event: Optional[threading.Event] = None) -> None:
    email = _normalize_email(email)
    if not email:
        return
    with _client_lock:
        cur = _code_events.get(email)
        if event is None or cur is event:
            _code_events.pop(email, None)


def wait_code_signal(email: str, event: Optional[threading.Event], timeout_sec: float) -> bool:
    if event is None:
        time.sleep(max(0.0, float(timeout_sec or 0.0)))
        return False
    return bool(event.wait(timeout=max(0.0, float(timeout_sec or 0.0))))


def get_code_arrival_age(email: str) -> Optional[float]:
    email = _normalize_email(email)
    with _client_lock:
        ts = _code_arrival_ts.get(email)
    if not ts:
        return None
    return max(0.0, time.time() - ts)


def mark_code_arrived(email: str) -> None:
    email = _normalize_email(email)
    if not email:
        return
    now = time.time()
    with _client_lock:
        _code_arrival_ts[email] = now
        ev = _code_events.get(email)
    if ev is not None:
        ev.set()


def inject_code_pool(email: str, code: str, raw_text: str = "") -> bool:
    """Inject into auth_core.code_pool and wake waiters."""
    email = _normalize_email(email)
    code = str(code or "").strip()
    if not email or not code:
        return False
    try:
        from utils.auth_core import code_pool

        # First line = parsed code for fast consume; keep raw for debug/re-extract.
        payload = code if not raw_text else f"{code}\n{raw_text}"
        code_pool[email] = payload
        mark_code_arrived(email)
        return True
    except Exception as exc:
        _log(f"[EMAIL-BRIDGE] 注入 code_pool 失败: {exc}")
        return False


def _bases_for_listen() -> list[tuple[str, str]]:
    """Return (mode_label, base_url) candidates in priority order."""
    items: list[tuple[str, str]] = []
    if _bridge_enabled():
        remote = _bridge_base()
        if remote:
            items.append(("remote", remote))
    if _local_webhook_enabled():
        items.append(("local", _local_base()))
    seen = set()
    out: list[tuple[str, str]] = []
    for label, base in items:
        key = base.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((label, base.rstrip("/")))
    return out


def _ws_urls_for_base(base: str, email: str) -> list[str]:
    if not base:
        return []
    path = f"/api/email-bridge/ws/{quote(email, safe='@')}"
    # 只使用与 base 协议匹配的单一 URL，避免 wss 成功后又无意义地试 ws。
    if base.startswith("https://"):
        return ["wss://" + base[len("https://") :] + path]
    if base.startswith("http://"):
        return ["ws://" + base[len("http://") :] + path]
    if base.startswith("wss://") or base.startswith("ws://"):
        return [base.rstrip("/") + path]
    return [f"wss://{base}{path}"]


def _ws_urls(email: str) -> list[str]:
    urls: list[str] = []
    for _label, base in _bases_for_listen():
        urls.extend(_ws_urls_for_base(base, email))
    seen = set()
    out = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _http_check(email: str) -> Optional[Dict[str, Any]]:
    token = _bridge_token()
    if not token:
        return None
    headers = _auth_headers()
    for _label, base in _bases_for_listen():
        url = f"{base}/api/email-bridge/check/{quote(email, safe='@')}"
        # 1) httpx, ignore env proxy (Mihomo/系统代理常把长连接搞挂)
        try:
            import httpx

            resp = httpx.get(url, headers=headers, timeout=5.0, trust_env=False)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, dict) and data.get("code"):
                    return data
                continue
        except Exception:
            pass
        # 2) stdlib fallback
        try:
            import urllib.request

            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:  # nosec - controlled URL
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict) and data.get("code"):
                return data
        except Exception:
            continue
    return None


def pull_latest_code(email: str) -> Optional[Dict[str, Any]]:
    """Public helper for registration threads: HTTP pull from bridge bases."""
    email = _normalize_email(email)
    if not email:
        return None
    return _http_check(email)


def _try_inject_from_http(email: str) -> bool:
    data = _http_check(email)
    if not data or not data.get("code"):
        return False
    code = str(data.get("code") or "").strip()
    if not code:
        return False
    raw_text = str(data.get("raw_text") or code)
    if inject_code_pool(email, code, raw_text):
        return True
    return False


def _close_socket_quiet(socket: Any) -> None:
    if socket is None:
        return
    try:
        socket.close()
    except Exception:
        pass


def _watch_loop(email: str) -> None:
    email = _normalize_email(email)
    modes = ",".join(label for label, _ in _bases_for_listen()) or "none"
    _log(f"[EMAIL-BRIDGE] 开始监听验证码({modes}): {_mask_email(email)}")
    fail_streak = 0

    while _remaining_watch_time(email) > 0:
        if not _listener_enabled() or not _bridge_token():
            time.sleep(min(2.0, max(0.1, _remaining_watch_time(email))))
            continue

        # HTTP 优先：不依赖 WS keepalive，公网/CF 下更稳，也避免拖慢注册收码。
        try:
            if _try_inject_from_http(email):
                _log(f"[EMAIL-BRIDGE] HTTP 收码成功并自动断开: {_mask_email(email)}")
                stop_listen(email)
                break
        except Exception:
            pass

        uris = _ws_urls(email)
        if not uris:
            remaining = _remaining_watch_time(email)
            if remaining > 0:
                time.sleep(min(_HTTP_POLL_IDLE_SEC, remaining))
            continue

        connected = False
        for uri in uris:
            if _remaining_watch_time(email) <= 0:
                break
            socket = None
            try:
                from websockets.sync.client import connect

                # proxy=None: 不要走系统/环境代理
                # ping_interval=None: 关闭库内置 keepalive，消除 1011 ping timeout traceback
                with connect(
                    uri,
                    additional_headers=_auth_headers(),
                    open_timeout=8,
                    close_timeout=2,
                    proxy=None,
                    ping_interval=None,
                    ping_timeout=None,
                ) as socket:
                    if not _remember_socket(email, socket):
                        break
                    connected = True
                    fail_streak = 0
                    _log(f"[EMAIL-BRIDGE] WS 已连接: {uri}")
                    try:
                        while _remaining_watch_time(email) > 0:
                            try:
                                raw = socket.recv(
                                    timeout=min(
                                        _WS_RECV_TIMEOUT_SEC,
                                        max(0.2, _remaining_watch_time(email)),
                                    )
                                )
                            except TimeoutError:
                                # 空闲不 ping；改 HTTP 补捞
                                if _try_inject_from_http(email):
                                    _log(
                                        f"[EMAIL-BRIDGE] WS空闲HTTP补捞成功并自动断开: {_mask_email(email)}"
                                    )
                                    stop_listen(email)
                                    return
                                continue
                            except Exception:
                                break

                            try:
                                payload = json.loads(raw) if isinstance(raw, str) else raw
                            except Exception:
                                continue
                            code = str((payload or {}).get("code") or "").strip()
                            if not code:
                                continue
                            raw_text = str((payload or {}).get("raw_text") or code)
                            if inject_code_pool(email, code, raw_text):
                                _log(f"[EMAIL-BRIDGE] WS 收码成功并自动断开: {_mask_email(email)}")
                                stop_listen(email)
                                return
                    finally:
                        _forget_socket(email, socket)
                        _close_socket_quiet(socket)
                break
            except Exception as exc:
                connected = False
                fail_streak += 1
                # 压缩噪音：ConnectionClosed / keepalive 类只简写
                msg = str(exc or "") or type(exc).__name__
                if "keepalive" in msg.lower() or "1011" in msg or "ConnectionClosed" in type(exc).__name__:
                    _log(f"[EMAIL-BRIDGE] WS 断开，改HTTP轮询({uri.split('://',1)[-1][:48]})")
                else:
                    _log(f"[EMAIL-BRIDGE] WS 连接失败({uri}): {type(exc).__name__}: {msg[:160]}")
                continue

        remaining = _remaining_watch_time(email)
        if remaining <= 0:
            break
        if connected:
            time.sleep(min(0.3, remaining))
        else:
            backoff = min(3.0, _WS_RETRY_SLEEP_SEC * max(1, fail_streak))
            time.sleep(min(backoff, remaining))

    _log(f"[EMAIL-BRIDGE] 停止监听并断开: {_mask_email(email)}")
    with _client_lock:
        if _threads.get(email) is threading.current_thread():
            _threads.pop(email, None)
        _sockets.pop(email, None)
        if email not in _watched:
            _deadlines.pop(email, None)


def ensure_listen(email: str, ttl_sec: float = _DEFAULT_LISTENER_TTL_SEC) -> None:
    """Start per-mailbox listener (HTTP poll + best-effort WS).

    Auto-stops when:
      - a code is received (stop_listen inside watch loop)
      - ttl deadline hits
      - caller invokes stop_listen/stop_all
    """
    if not _listener_enabled() or _stop.is_set():
        return
    if not _bridge_token():
        return
    email = _normalize_email(email)
    if not email or "@" not in email:
        return
    try:
        ttl = max(5.0, float(ttl_sec or _DEFAULT_LISTENER_TTL_SEC))
    except (TypeError, ValueError):
        ttl = _DEFAULT_LISTENER_TTL_SEC
    deadline = time.monotonic() + ttl
    with _client_lock:
        _watched.add(email)
        _deadlines[email] = max(deadline, _deadlines.get(email, 0.0))
        thr = _threads.get(email)
        if thr and thr.is_alive():
            return
        t = threading.Thread(
            target=_watch_loop,
            args=(email,),
            daemon=True,
            name=f"email-bridge-{email}",
        )
        _threads[email] = t
        t.start()


def stop_listen(email: str) -> bool:
    """Stop one mailbox listener and close its active websocket immediately."""
    email = _normalize_email(email)
    if not email:
        return False
    with _client_lock:
        was_active = email in _watched or email in _threads or email in _sockets
        _watched.discard(email)
        _deadlines.pop(email, None)
        socket = _sockets.pop(email, None)
        thr = _threads.pop(email, None)
    _close_socket_quiet(socket)
    if was_active:
        _log(f"[EMAIL-BRIDGE] 已自动断开监听: {_mask_email(email)}")
    return was_active


def stop_all() -> None:
    _stop.set()
    with _client_lock:
        _watched.clear()
        _deadlines.clear()
        sockets = list(_sockets.values())
        _sockets.clear()
    for socket in sockets:
        _close_socket_quiet(socket)


def wait_code_from_bridge(email: str, timeout_sec: int = 90) -> str:
    """Blocking helper: listen + poll until code appears or timeout."""
    email = _normalize_email(email)
    if not email:
        return ""
    timeout = max(5, int(timeout_sec or 90))
    ensure_listen(email, ttl_sec=timeout + 15)
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = _http_check(email)
            if data and data.get("code"):
                code = str(data["code"])
                inject_code_pool(email, code, str(data.get("raw_text") or code))
                return code
            try:
                from utils.auth_core import code_pool
                from utils.email_providers.mail_service import _extract_otp_code, _clean_html_to_text

                raw = code_pool.get(email, "")
                code = _extract_otp_code(_clean_html_to_text(raw)) if raw else ""
                if code:
                    return code
            except Exception:
                pass
            time.sleep(1)
        return ""
    finally:
        stop_listen(email)
