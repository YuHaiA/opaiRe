import random
import uuid
from dataclasses import dataclass

from utils import config as cfg


@dataclass(frozen=True)
class BrowserFingerprintProfile:
    mode: str
    impersonate: str
    user_agent: str
    sec_ch_ua: str
    sec_ch_ua_full: str
    include_modern_headers: bool
    include_trace_headers: bool


_COMPAT_PROFILE = BrowserFingerprintProfile(
    mode="compat",
    impersonate="chrome110",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/110.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="110", "Chromium";v="110", "Not_A Brand";v="24"',
    sec_ch_ua_full="",
    include_modern_headers=False,
    include_trace_headers=False,
)

_UPSTREAM_PROFILE = BrowserFingerprintProfile(
    mode="upstream",
    impersonate="chrome",
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    sec_ch_ua='"Google Chrome";v="145", "Not?A_Brand";v="8", "Chromium";v="145"',
    sec_ch_ua_full='"Chromium";v="145.0.0.0", "Not:A-Brand";v="99.0.0.0", "Google Chrome";v="145.0.0.0"',
    include_modern_headers=True,
    include_trace_headers=True,
)


def current_profile() -> BrowserFingerprintProfile:
    mode = str(getattr(cfg, "AUTH_FINGERPRINT_MODE", "compat") or "compat").strip().lower()
    if mode == "upstream":
        return _UPSTREAM_PROFILE
    return _COMPAT_PROFILE


def impersonate() -> str:
    return current_profile().impersonate


def sentinel_impersonate() -> str:
    return current_profile().impersonate


def token_impersonate() -> str:
    return current_profile().impersonate


def _make_trace_headers() -> dict[str, str]:
    trace_id = str(random.getrandbits(64))
    parent_id = str(random.getrandbits(64))
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": parent_id,
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": trace_id,
    }


def oai_headers(did: str, extra: dict = None, is_navigate: bool = False) -> dict:
    profile = current_profile()
    if is_navigate:
        headers = {
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": profile.user_agent,
            "sec-ch-ua": profile.sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if profile.include_modern_headers:
            headers.update({
                "sec-ch-ua-arch": '"x86_64"',
                "sec-ch-ua-bitness": '"64"',
                "sec-ch-ua-full-version-list": profile.sec_ch_ua_full,
                "sec-ch-ua-model": '""',
                "sec-ch-ua-platform-version": '"10.0.0"',
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "same-origin",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1",
            })
    else:
        headers = {
            "accept": "application/json",
            "accept-language": "en-US,en;q=0.9",
            "user-agent": profile.user_agent,
            "sec-ch-ua": profile.sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        }
        if profile.include_modern_headers:
            headers.update({
                "content-type": "application/json",
                "priority": "u=1, i",
                "sec-ch-ua-arch": '"x86_64"',
                "sec-ch-ua-bitness": '"64"',
                "sec-ch-ua-full-version-list": profile.sec_ch_ua_full,
                "sec-ch-ua-model": '""',
                "sec-ch-ua-platform-version": '"10.0.0"',
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            })

    if did:
        headers["oai-device-id"] = did
    if profile.include_trace_headers:
        headers.update(_make_trace_headers())
    if extra:
        headers.update(extra)
    return headers
