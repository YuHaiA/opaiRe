#!/usr/bin/env python3
"""Optional CLI helper. Prefer the web panel at /mihomo/ for daily use."""
import json
import re
import sys
import urllib.request
from pathlib import Path

CFG = Path("/opt/sub2-mihomo/config.yaml")
PROVIDER_BLOCK = """proxy-providers:
  subscription:
    type: http
    url: {url}
    path: providers/subscription.yaml
    interval: 3600
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 600
      lazy: true
"""


def main():
    if len(sys.argv) < 2:
        print("usage: set_subscription.py SUB_URL", file=sys.stderr)
        print("prefer web panel: https://tupai.cyou/mihomo/", file=sys.stderr)
        return 2
    url = sys.argv[1].strip()
    text = CFG.read_text(encoding="utf-8")
    block = PROVIDER_BLOCK.format(url=json.dumps(url))
    text2, n = re.subn(
        r"proxy-providers:\n(?:^[ \t].*\n?)+",
        block if block.endswith("\n") else block + "\n",
        text,
        count=1,
        flags=re.M,
    )
    if n != 1:
        raise SystemExit("failed to patch proxy-providers block")
    CFG.write_text(text2, encoding="utf-8")
    print("updated subscription url")
    m = re.search(r'^secret:\s*"?([^"\n]+)"?', text2, re.M)
    secret = m.group(1).strip() if m else ""

    def api(method, path, data=None):
        req = urllib.request.Request(
            "http://127.0.0.1:9090" + path,
            data=None if data is None else data.encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + secret,
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, resp.read()

    try:
        api("GET", "/version")
        api("PUT", "/configs?force=true", json.dumps({"path": str(CFG)}))
        try:
            api("PUT", "/providers/proxies/subscription")
        except Exception as exc:
            print("provider update warning:", exc)
        print("reloaded")
    except Exception as exc:
        print("api reload failed, run: sudo systemctl restart sub2-mihomo")
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
