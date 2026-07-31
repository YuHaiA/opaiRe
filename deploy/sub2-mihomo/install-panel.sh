#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/sub2-mihomo
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "[1/6] sync panel files"
mkdir -p "$ROOT/web" "$ROOT/state" "$ROOT/providers" "$ROOT/logs"
cp -f "$REPO_DIR/manager.py" "$ROOT/manager.py"
cp -f "$REPO_DIR/v2ray_convert.py" "$ROOT/v2ray_convert.py"
cp -f "$REPO_DIR/mihomoctl" "$ROOT/mihomoctl"
chmod 755 "$ROOT/mihomoctl"
cp -f "$REPO_DIR/web/index.html" "$REPO_DIR/web/app.js" "$REPO_DIR/web/app.css" "$ROOT/web/"
if [ -f "$REPO_DIR/set_subscription.py" ]; then
  cp -f "$REPO_DIR/set_subscription.py" "$ROOT/set_subscription.py"
  chmod +x "$ROOT/set_subscription.py"
fi

echo "[2/6] migrate provider name if needed"
python3 - <<'PY'
from pathlib import Path
root = Path('/opt/sub2-mihomo')
legacy = root / 'providers' / 'sub.yaml'
prov = root / 'providers' / 'subscription.yaml'
if legacy.exists() and not prov.exists():
    prov.write_bytes(legacy.read_bytes())
    print('migrated providers/sub.yaml -> subscription.yaml')
elif not prov.exists():
    prov.write_text('proxies: []\n', encoding='utf-8')
    print('created empty subscription.yaml')
else:
    print('subscription.yaml ready')
PY

echo "[3/6] sudoers for mihomoctl"
sudo cp "$REPO_DIR/sudoers-mihomo" /etc/sudoers.d/sub2-mihomo
sudo chmod 440 /etc/sudoers.d/sub2-mihomo
sudo visudo -cf /etc/sudoers.d/sub2-mihomo

echo "[4/6] rewrite config via manager (preserve secret)"
cd "$ROOT"
python3 - <<'PY'
import json
import sys
sys.path.insert(0, '/opt/sub2-mihomo')
import manager
settings = manager.ensure_layout()
print(json.dumps({
  'mixed_port': settings.get('mixed_port'),
  'controller': f"{settings.get('controller_host')}:{settings.get('controller_port')}",
  'node_count': settings.get('node_count'),
  'secret_set': bool(manager.controller_secret()),
}, ensure_ascii=False))
PY

echo "[5/6] systemd panel + reload core"
sudo cp "$REPO_DIR/sub2-mihomo-panel.service" /etc/systemd/system/sub2-mihomo-panel.service
sudo systemctl daemon-reload
sudo systemctl restart sub2-mihomo.service
sleep 1
sudo systemctl enable --now sub2-mihomo-panel.service
sleep 1
systemctl is-active sub2-mihomo.service
systemctl is-active sub2-mihomo-panel.service
curl -fsS -m 5 http://127.0.0.1:19099/api/status | head -c 500 || true
echo

echo "[6/6] nginx snippet"
sudo cp "$REPO_DIR/nginx-mihomo.conf" /etc/nginx/snippets/mihomo.conf
sudo nginx -t
sudo nginx -s reload || true

python3 - <<'PY'
from pathlib import Path
import re
root = Path('/opt/sub2-mihomo')
text = (root / 'config.yaml').read_text(encoding='utf-8')
m = re.search(r'^secret:\s*"?([^"\n]+)"?', text, re.M)
secret = m.group(1).strip() if m else ''
body = (
    f'controller_secret={secret}\n'
    'panel_url=https://tupai.cyou/mihomo/\n'
    'advanced_ui=https://tupai.cyou/mihomo/ui/\n'
    'mixed=http://127.0.0.1:7890\n'
    'docker_mixed=http://172.20.0.1:7890\n'
    'note=Open panel_url, paste subscription, click save. No Zashboard backend setup needed.\n'
)
(root / 'CREDENTIALS.txt').write_text(body, encoding='utf-8')
(root / 'CREDENTIALS.txt').chmod(0o600)
print('credentials refreshed')
PY

echo PANEL_INSTALL_OK
echo "open: https://tupai.cyou/mihomo/"
