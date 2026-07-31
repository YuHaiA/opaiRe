#!/bin/bash
set -euo pipefail
URL=${1:-}
CFG=/opt/sub2-mihomo/config.yaml
if [ -z "$URL" ]; then
  echo "usage: $0 <subscription-url>" >&2
  exit 1
fi
python3 - "$CFG" "$URL" - <<'PY'
import re, sys
from pathlib import Path
cfg = Path(sys.argv[1])
url = sys.argv[2]
text = cfg.read_text(encoding="utf-8")
pat = r'(proxy-providers:\s*\n\s*sub:\s*\n(?:.*\n)*?\s*url:\s*)".*?"'
text2, n = re.subn(pat, r'\1"%s"' % url.replace("\\", r"\\").replace('"', r"\""), text, count=1)
if n != 1:
    raise SystemExit("failed to patch subscription url")
cfg.write_text(text2, encoding="utf-8")
print("updated subscription url")
PY
SECRET=$(python3 -c 'import re; from pathlib import Path; t=Path("/opt/sub2-mihomo/config.yaml").read_text(encoding="utf-8"); m=re.search(r"^secret:\s*\"([^\"]+)\"", t, re.M); print(m.group(1) if m else "")')
if curl -fsS -m 3 -H "Authorization: Bearer ${SECRET}" http://127.0.0.1:9090/version >/dev/null 2>&1; then
  curl -fsS -m 15 -X PUT "http://127.0.0.1:9090/configs?force=true" -H "Authorization: Bearer ${SECRET}" -H "Content-Type: application/json" -d "{\"path\":\"/opt/sub2-mihomo/config.yaml\"}" >/dev/null || sudo systemctl restart sub2-mihomo
  curl -fsS -m 90 -X PUT "http://127.0.0.1:9090/providers/proxies/sub" -H "Authorization: Bearer ${SECRET}" >/dev/null || true
  echo reloaded
else
  sudo systemctl restart sub2-mihomo
  echo restarted
fi
