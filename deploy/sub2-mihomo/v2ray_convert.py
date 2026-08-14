# -*- coding: utf-8 -*-
"""Convert share links, HTTP proxies, and subscriptions into Clash Meta proxies."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import yaml


class V2RayConvertError(ValueError):
    """Raised when subscription/share content cannot be converted."""


_SHARE_SCHEMES = (
    "vmess://",
    "vless://",
    "trojan://",
    "ss://",
    "ssr://",
    "hysteria2://",
    "hy2://",
    "hysteria://",
    "tuic://",
    "wireguard://",
)


def _pad_b64(raw: str) -> str:
    s = (raw or "").strip().replace("-", "+").replace("_", "/")
    s = re.sub(r"\s+", "", s)
    missing = (-len(s)) % 4
    if missing:
        s += "=" * missing
    return s


def b64decode_text(raw: str) -> str:
    data = base64.b64decode(_pad_b64(raw), validate=False)
    for enc in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def b64decode_bytes(raw: str) -> bytes:
    return base64.b64decode(_pad_b64(raw), validate=False)


def sanitize_proxy_name(name: str, *, fallback: str = "node") -> str:
    text = str(name or "").strip() or fallback
    # mihomo / UI: avoid separators that break group selection labels
    for ch in (":", "|", "\n", "\r", "\t"):
        text = text.replace(ch, "-")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:80] or fallback


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in {"1", "true", "yes", "on", "tls", "reality"}


def _query_first(qs: dict[str, list[str]], *keys: str, default: str = "") -> str:
    for key in keys:
        vals = qs.get(key) or qs.get(key.lower()) or qs.get(key.upper())
        if vals:
            return unquote(str(vals[0] or "")).strip()
    return default


def _network_opts(network: str, qs: dict[str, list[str]], *, host_header: str = "") -> dict[str, Any]:
    net = (network or "tcp").lower()
    if net == "websocket":
        net = "ws"
    path = _query_first(qs, "path", "spx") or "/"
    host = host_header or _query_first(qs, "host", "authority")
    opts: dict[str, Any] = {}
    if net == "ws":
        ws: dict[str, Any] = {"path": path or "/"}
        if host:
            ws["headers"] = {"Host": host}
        opts["ws-opts"] = ws
    elif net == "h2":
        h2: dict[str, Any] = {"path": path or "/"}
        if host:
            h2["host"] = [host]
        opts["h2-opts"] = h2
    elif net in {"http", "httpupgrade"}:
        net = "http"
        http_opts: dict[str, Any] = {"path": [path or "/"]}
        if host:
            http_opts["headers"] = {"Host": [host]}
        opts["http-opts"] = http_opts
    elif net == "grpc":
        service = _query_first(qs, "serviceName", "service_name", "path") or "GunService"
        opts["grpc-opts"] = {"grpc-service-name": service}
    return {"network": net, **opts}


def parse_vmess(uri: str) -> dict[str, Any] | None:
    raw = uri.strip()
    if not raw.lower().startswith("vmess://"):
        return None
    payload = raw[8:]
    try:
        obj = json.loads(b64decode_text(payload))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    server = str(obj.get("add") or obj.get("host") or "").strip()
    port = int(obj.get("port") or 0)
    uuid = str(obj.get("id") or "").strip()
    if not server or port <= 0 or not uuid:
        return None
    name = sanitize_proxy_name(obj.get("ps") or obj.get("remark") or f"vmess-{server}-{port}")
    network = str(obj.get("net") or "tcp").lower()
    if network == "websocket":
        network = "ws"
    tls_raw = str(obj.get("tls") or "").lower()
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": uuid,
        "alterId": int(obj.get("aid") or obj.get("alterId") or 0),
        "cipher": str(obj.get("scy") or obj.get("security") or "auto") or "auto",
        "udp": True,
    }
    if tls_raw in {"tls", "true", "1"}:
        proxy["tls"] = True
        sni = str(obj.get("sni") or obj.get("peer") or obj.get("host") or "").strip()
        if sni:
            proxy["servername"] = sni
    alpn = str(obj.get("alpn") or "").strip()
    if alpn:
        proxy["alpn"] = [x.strip() for x in alpn.split(",") if x.strip()]
    fp = str(obj.get("fp") or "").strip()
    if fp:
        proxy["client-fingerprint"] = fp
    path = str(obj.get("path") or "/").strip() or "/"
    host = str(obj.get("host") or "").strip()
    if network == "ws":
        proxy["network"] = "ws"
        ws: dict[str, Any] = {"path": path}
        if host:
            ws["headers"] = {"Host": host}
        proxy["ws-opts"] = ws
    elif network == "grpc":
        proxy["network"] = "grpc"
        proxy["grpc-opts"] = {"grpc-service-name": path if path != "/" else "GunService"}
    elif network in {"h2", "http"}:
        proxy["network"] = network
        if network == "h2":
            h2: dict[str, Any] = {"path": path}
            if host:
                h2["host"] = [host]
            proxy["h2-opts"] = h2
        else:
            http_opts: dict[str, Any] = {"path": [path]}
            if host:
                http_opts["headers"] = {"Host": [host]}
            proxy["http-opts"] = http_opts
    else:
        proxy["network"] = network or "tcp"
    return proxy


def parse_vless(uri: str) -> dict[str, Any] | None:
    raw = uri.strip()
    if not raw.lower().startswith("vless://"):
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    uuid = unquote(parsed.username or "").strip()
    server = (parsed.hostname or "").strip()
    port = int(parsed.port or 0)
    if not uuid or not server or port <= 0:
        return None
    qs = parse_qs(parsed.query, keep_blank_values=True)
    name = sanitize_proxy_name(unquote(parsed.fragment) or f"vless-{server}-{port}")
    security = _query_first(qs, "security", "sec").lower()
    network = _query_first(qs, "type", "net") or "tcp"
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vless",
        "server": server,
        "port": port,
        "uuid": uuid,
        "udp": True,
    }
    encryption = _query_first(qs, "encryption") or "none"
    if encryption:
        proxy["packet-encoding"] = _query_first(qs, "packetEncoding", "packet-encoding") or None
        if proxy["packet-encoding"] is None:
            proxy.pop("packet-encoding", None)
    flow = _query_first(qs, "flow")
    if flow:
        proxy["flow"] = flow
    net_info = _network_opts(network, qs, host_header=_query_first(qs, "host", "authority"))
    proxy.update(net_info)
    if security in {"tls", "reality"}:
        proxy["tls"] = True
        sni = _query_first(qs, "sni", "peer", "servername")
        if sni:
            proxy["servername"] = sni
        fp = _query_first(qs, "fp", "fingerprint")
        if fp:
            proxy["client-fingerprint"] = fp
        alpn = _query_first(qs, "alpn")
        if alpn:
            proxy["alpn"] = [x.strip() for x in alpn.split(",") if x.strip()]
        if security == "reality":
            pbk = _query_first(qs, "pbk", "publicKey", "public-key")
            sid = _query_first(qs, "sid", "shortId", "short-id")
            reality: dict[str, Any] = {}
            if pbk:
                reality["public-key"] = pbk
            if sid:
                reality["short-id"] = sid
            if reality:
                proxy["reality-opts"] = reality
    return proxy


def parse_trojan(uri: str) -> dict[str, Any] | None:
    raw = uri.strip()
    if not raw.lower().startswith("trojan://"):
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    password = unquote(parsed.username or "").strip()
    server = (parsed.hostname or "").strip()
    port = int(parsed.port or 0)
    if not password or not server or port <= 0:
        return None
    qs = parse_qs(parsed.query, keep_blank_values=True)
    name = sanitize_proxy_name(unquote(parsed.fragment) or f"trojan-{server}-{port}")
    network = _query_first(qs, "type", "net") or "tcp"
    proxy: dict[str, Any] = {
        "name": name,
        "type": "trojan",
        "server": server,
        "port": port,
        "password": password,
        "udp": True,
    }
    sni = _query_first(qs, "sni", "peer", "servername")
    if sni:
        proxy["sni"] = sni
    fp = _query_first(qs, "fp", "fingerprint")
    if fp:
        proxy["client-fingerprint"] = fp
    alpn = _query_first(qs, "alpn")
    if alpn:
        proxy["alpn"] = [x.strip() for x in alpn.split(",") if x.strip()]
    allow_insecure = _query_first(qs, "allowInsecure", "allow_insecure", "insecure")
    if _truthy(allow_insecure):
        proxy["skip-cert-verify"] = True
    net_info = _network_opts(network, qs, host_header=_query_first(qs, "host", "authority"))
    # trojan default is tcp without network field unless ws/grpc
    if net_info.get("network") and net_info.get("network") != "tcp":
        proxy.update(net_info)
    return proxy


def parse_ss(uri: str) -> dict[str, Any] | None:
    raw = uri.strip()
    if not raw.lower().startswith("ss://"):
        return None
    body = raw[5:]
    name = "ss-node"
    if "#" in body:
        body, frag = body.split("#", 1)
        name = sanitize_proxy_name(unquote(frag) or name)
    method = password = server = ""
    port = 0
    plugin = ""
    plugin_opts = ""
    try:
        if "@" in body:
            userinfo, hostinfo = body.rsplit("@", 1)
            # userinfo may be plain method:pass or base64
            if ":" in userinfo and not re.fullmatch(r"[A-Za-z0-9+/=_-]+", userinfo):
                method, password = userinfo.split(":", 1)
                method = unquote(method)
                password = unquote(password)
            else:
                decoded = b64decode_text(userinfo)
                if ":" not in decoded:
                    return None
                method, password = decoded.split(":", 1)
            # hostinfo may include ?plugin=
            host_part = hostinfo
            if "?" in host_part:
                host_part, query = host_part.split("?", 1)
                qs = parse_qs(query, keep_blank_values=True)
                plugin = _query_first(qs, "plugin")
            if ":" not in host_part:
                return None
            host, port_s = host_part.rsplit(":", 1)
            server = unquote(host.strip("[]"))
            port = int(port_s)
        else:
            # ss://base64(method:pass@host:port)
            decoded = b64decode_text(body)
            if "@" not in decoded or ":" not in decoded:
                return None
            userinfo, hostinfo = decoded.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
            host, port_s = hostinfo.rsplit(":", 1)
            server = host.strip("[]")
            port = int(port_s)
    except Exception:
        return None
    if not method or not password or not server or port <= 0:
        return None
    proxy: dict[str, Any] = {
        "name": sanitize_proxy_name(name or f"ss-{server}-{port}"),
        "type": "ss",
        "server": server,
        "port": port,
        "cipher": method,
        "password": password,
        "udp": True,
    }
    if plugin:
        # simple plugin pass-through for common v2rayN exports
        proxy["plugin"] = plugin.split(";")[0]
        # remaining plugin options as plugin-opts string map is complex; keep raw if present
        if ";" in plugin:
            opts = {}
            for part in plugin.split(";")[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    opts[k] = v
            if opts:
                proxy["plugin-opts"] = opts
    return proxy


def parse_hysteria2(uri: str) -> dict[str, Any] | None:
    raw = uri.strip()
    low = raw.lower()
    if not (low.startswith("hysteria2://") or low.startswith("hy2://")):
        return None
    try:
        parsed = urlparse(raw)
    except Exception:
        return None
    password = unquote(parsed.username or "").strip()
    server = (parsed.hostname or "").strip()
    port = int(parsed.port or 0)
    if not server or port <= 0:
        return None
    qs = parse_qs(parsed.query, keep_blank_values=True)
    name = sanitize_proxy_name(unquote(parsed.fragment) or f"hy2-{server}-{port}")
    proxy: dict[str, Any] = {
        "name": name,
        "type": "hysteria2",
        "server": server,
        "port": port,
        "password": password or _query_first(qs, "auth", "password"),
        "udp": True,
    }
    sni = _query_first(qs, "sni", "peer")
    if sni:
        proxy["sni"] = sni
    if _truthy(_query_first(qs, "insecure", "allowInsecure")):
        proxy["skip-cert-verify"] = True
    obfs = _query_first(qs, "obfs")
    if obfs:
        proxy["obfs"] = obfs
        obfs_pass = _query_first(qs, "obfs-password", "obfsPassword")
        if obfs_pass:
            proxy["obfs-password"] = obfs_pass
    return proxy


def parse_share_link(line: str) -> dict[str, Any] | None:
    text = (line or "").strip()
    if not text:
        return None
    low = text.lower()
    if low.startswith("vmess://"):
        return parse_vmess(text)
    if low.startswith("vless://"):
        return parse_vless(text)
    if low.startswith("trojan://"):
        return parse_trojan(text)
    if low.startswith("ss://"):
        return parse_ss(text)
    if low.startswith("hysteria2://") or low.startswith("hy2://"):
        return parse_hysteria2(text)
    return None


def parse_http_proxy(uri: str) -> dict[str, Any] | None:
    """Convert an HTTP/HTTPS proxy URI to a Mihomo HTTP proxy mapping."""
    text = (uri or "").strip()
    try:
        parsed = urlparse(text)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if not port or port <= 0 or port > 65535:
        return None

    server = parsed.hostname
    name = sanitize_proxy_name(
        unquote(parsed.fragment) or f"http-{server}-{port}",
        fallback=f"http-{server}-{port}",
    )
    proxy: dict[str, Any] = {
        "name": name,
        "type": "http",
        "server": server,
        "port": port,
    }
    if parsed.username is not None:
        proxy["username"] = unquote(parsed.username)
    if parsed.password is not None:
        proxy["password"] = unquote(parsed.password)
    if parsed.scheme.lower() == "https":
        proxy["tls"] = True
    return proxy


def looks_like_share_link(text: str) -> bool:
    s = (text or "").strip().lower()
    return any(s.startswith(scheme) for scheme in _SHARE_SCHEMES)


def looks_like_http_proxy_uri(text: str) -> bool:
    """Return whether a single HTTP URL is clearly a proxy endpoint."""
    s = (text or "").strip()
    if "\n" in s or "\r" in s:
        return False
    try:
        parsed = urlparse(s)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False
        port = parsed.port
    except (TypeError, ValueError):
        return False
    if not port or port <= 0 or port > 65535:
        return False
    # Subscription URLs normally have a path/query. A proxy URI has an
    # explicit port and either credentials/name or no resource path.
    return bool(
        parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (parsed.path in {"", "/"} and not parsed.query)
    )


def looks_like_single_url(text: str) -> bool:
    s = (text or "").strip()
    if "\n" in s or "\r" in s:
        return False
    if "://" not in s:
        return False
    if looks_like_share_link(s):
        return False
    try:
        p = urlparse(s)
    except Exception:
        return False
    return p.scheme in {"http", "https"} and bool(p.netloc) and not looks_like_http_proxy_uri(s)


def _unique_names(proxies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, int] = {}
    out: list[dict[str, Any]] = []
    for item in proxies:
        p = dict(item)
        base = sanitize_proxy_name(p.get("name") or "node")
        n = seen.get(base, 0) + 1
        seen[base] = n
        p["name"] = base if n == 1 else f"{base}-{n}"
        out.append(p)
    return out


def try_parse_clash_yaml(text: str) -> list[dict[str, Any]] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # quick reject for pure share / base64 blobs
    if looks_like_share_link(raw.splitlines()[0].strip()):
        return None
    try:
        data = yaml.safe_load(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    proxies = data.get("proxies")
    if isinstance(proxies, list) and proxies:
        out = [p for p in proxies if isinstance(p, dict) and p.get("name") and p.get("type") and p.get("server")]
        return _unique_names(out) if out else None
    return None


def parse_share_blob(text: str) -> list[dict[str, Any]]:
    """Parse multi-line share links or base64(v2rayN) subscription body."""
    raw = (text or "").strip()
    if not raw:
        return []

    candidates = [raw]
    # Often subscription body is pure base64 of share links.
    if not any(looks_like_share_link(line.strip()) for line in raw.splitlines() if line.strip()):
        try:
            decoded = b64decode_text(raw)
            if decoded and decoded != raw:
                candidates.insert(0, decoded)
        except Exception:
            pass

    found: list[dict[str, Any]] = []
    for blob in candidates:
        # Some providers return one long line with spaces
        lines: list[str] = []
        for line in blob.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = line.strip()
            if not line:
                continue
            # also split if multiple schemes appear in one line
            # Negative lookbehind avoids splitting "vmess://" / "vless://" on nested "ss://"
            parts = re.split(
                r"(?=(?<![A-Za-z])(?:vmess|vless|trojan|hysteria2|hysteria|hy2|tuic|ssr|ss)://)",
                line,
                flags=re.IGNORECASE,
            )
            for part in parts:
                part = part.strip()
                if part:
                    lines.append(part)
        for line in lines:
            item = parse_share_link(line)
            if item:
                found.append(item)
        if found:
            break
    return _unique_names(found)


def parse_http_proxy_blob(text: str) -> tuple[list[dict[str, Any]], str]:
    """Extract one HTTP proxy URI per line and return the remaining content."""
    proxies: list[dict[str, Any]] = []
    remaining: list[str] = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = line.strip()
        if stripped and looks_like_http_proxy_uri(stripped):
            proxy = parse_http_proxy(stripped)
            if proxy:
                proxies.append(proxy)
                continue
        remaining.append(line)
    return _unique_names(proxies), "\n".join(remaining).strip()


def detect_and_parse_subscription(text: str) -> dict[str, Any]:
    """Detect content kind and return Clash Meta proxies.

    Returns:
      {
        kind: "clash_yaml" | "http_proxy_links" | "v2ray_links" | "mixed" | "empty" | "unknown",
        proxies: [...],
        count: int,
        sample: [names...],
      }
    """
    raw = (text or "").strip()
    if not raw:
        return {"kind": "empty", "proxies": [], "count": 0, "sample": []}

    candidates = [raw]
    # Some providers wrap Clash YAML or share links in pure base64.
    if "proxies:" not in raw and not any(
        looks_like_share_link(line.strip()) for line in raw.splitlines() if line.strip()
    ):
        try:
            decoded = b64decode_text(raw)
            if decoded and decoded.strip() and decoded.strip() != raw:
                candidates.append(decoded.strip())
        except Exception:
            pass

    for blob in candidates:
        http_proxies, remainder = parse_http_proxy_blob(blob)
        clash = try_parse_clash_yaml(remainder) if remainder else None
        links = parse_share_blob(remainder) if remainder else []
        other = clash or links
        if http_proxies or other:
            combined = _unique_names([*http_proxies, *(other or [])])
            if clash and http_proxies:
                kind = "mixed"
            elif clash:
                kind = "clash_yaml"
            elif links and http_proxies:
                kind = "mixed"
            elif links:
                kind = "v2ray_links"
            else:
                kind = "http_proxy_links"
            return {
                "kind": kind,
                "proxies": combined,
                "count": len(combined),
                "sample": [p.get("name") for p in combined[:8]],
            }

    return {"kind": "unknown", "proxies": [], "count": 0, "sample": []}


def proxies_to_provider_yaml(proxies: list[dict[str, Any]]) -> str:
    return yaml.safe_dump({"proxies": proxies}, allow_unicode=True, sort_keys=False)
