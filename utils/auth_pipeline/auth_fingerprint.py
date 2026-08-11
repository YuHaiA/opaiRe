import random
import uuid
from dataclasses import dataclass

from utils import config as cfg


@dataclass(frozen=True)
class BrowserFingerprintProfile:
    impersonate: str
    user_agent: str
    sec_ch_ua: str
    modern: bool


_COMPAT = BrowserFingerprintProfile(
    "chrome110",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
    '"Google Chrome";v="110", "Chromium";v="110", "Not_A Brand";v="24"',
    False,
)
_UPSTREAM = BrowserFingerprintProfile(
    "chrome",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    '"Google Chrome";v="145", "Not?A_Brand";v="8", "Chromium";v="145"',
    True,
)


def current_profile() -> BrowserFingerprintProfile:
    return _UPSTREAM if str(getattr(cfg, "AUTH_FINGERPRINT_MODE", "compat")).lower() == "upstream" else _COMPAT


def impersonate() -> str:
    return current_profile().impersonate


def token_impersonate() -> str:
    return _COMPAT.impersonate


def oai_headers(did: str, extra: dict = None, is_navigate: bool = False) -> dict:
    profile = current_profile()
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" if is_navigate else "application/json",
        "accept-language": "en-US,en;q=0.9",
        "user-agent": profile.user_agent,
        "sec-ch-ua": profile.sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document" if is_navigate else "empty",
        "sec-fetch-mode": "navigate" if is_navigate else "cors",
        "sec-fetch-site": "same-origin",
    }
    if is_navigate:
        headers["upgrade-insecure-requests"] = "1"
    if did:
        headers["oai-device-id"] = did
    if profile.modern:
        parent_id = str(random.getrandbits(64))
        headers.update({
            "traceparent": f"00-{uuid.uuid4().hex}-{format(int(parent_id), '016x')}-01",
            "x-datadog-origin": "rum",
            "x-datadog-parent-id": parent_id,
        })
    if extra:
        headers.update(extra)
    return headers
