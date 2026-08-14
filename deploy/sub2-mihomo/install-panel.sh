#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
MIHOMO_ROOT="${MIHOMO_ROOT:-/opt/sub2-mihomo}"
MIHOMO_USER="${MIHOMO_USER:-$(id -un)}"
MIHOMO_GROUP="${MIHOMO_GROUP:-$(id -gn "$MIHOMO_USER")}"
MIHOMO_DOMAIN="${MIHOMO_DOMAIN:-tupai.cyou}"
MIHOMO_URL_PATH="${MIHOMO_URL_PATH:-/mihomo}"
MIHOMO_URL_PATH="/${MIHOMO_URL_PATH#/}"
MIHOMO_URL_PATH="${MIHOMO_URL_PATH%/}"
MIHOMO_PUBLIC_BASE="${MIHOMO_PUBLIC_BASE:-https://${MIHOMO_DOMAIN}${MIHOMO_URL_PATH}}"
SUB2API_DOCKER_HOST="${SUB2API_DOCKER_HOST:-172.20.0.1}"
SUB2API_DEPLOY_DIR="${SUB2API_DEPLOY_DIR:-/home/${MIHOMO_USER}/sub2api-deploy}"
SUB2API_POSTGRES_CONTAINER="${SUB2API_POSTGRES_CONTAINER:-sub2api-postgres}"
NGINX_SNIPPET_CONFIG="${NGINX_SNIPPET_CONFIG:-/etc/nginx/snippets/mihomo.conf}"

export MIHOMO_ROOT MIHOMO_USER MIHOMO_GROUP MIHOMO_PUBLIC_BASE MIHOMO_URL_PATH
export SUB2API_DOCKER_HOST SUB2API_DEPLOY_DIR SUB2API_POSTGRES_CONTAINER

case "$MIHOMO_ROOT" in
  /*) ;;
  *) echo "MIHOMO_ROOT must be an absolute path" >&2; exit 1 ;;
esac
if [ "$MIHOMO_ROOT" = "/" ] || [ -z "$MIHOMO_URL_PATH" ]; then
  echo "unsafe MIHOMO_ROOT or MIHOMO_URL_PATH" >&2
  exit 1
fi

render_template() {
  local source="$1"
  local target="$2"
  local temp
  temp="$(mktemp)"
  python3 - "$source" "$temp" <<'PY'
import os
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:3])
text = source.read_text(encoding="utf-8")
values = {
    "__MIHOMO_ROOT__": os.environ["MIHOMO_ROOT"],
    "__MIHOMO_USER__": os.environ["MIHOMO_USER"],
    "__MIHOMO_GROUP__": os.environ["MIHOMO_GROUP"],
    "__MIHOMO_PUBLIC_BASE__": os.environ["MIHOMO_PUBLIC_BASE"],
    "__MIHOMO_URL_PATH__": os.environ["MIHOMO_URL_PATH"],
    "__SUB2API_DOCKER_HOST__": os.environ["SUB2API_DOCKER_HOST"],
    "__SUB2API_DEPLOY_DIR__": os.environ["SUB2API_DEPLOY_DIR"],
    "__SUB2API_POSTGRES_CONTAINER__": os.environ["SUB2API_POSTGRES_CONTAINER"],
}
for placeholder, value in values.items():
    text = text.replace(placeholder, value)
target.write_text(text, encoding="utf-8")
PY
  sudo install -m 0644 "$temp" "$target"
  rm -f "$temp"
}

for command in openssl python3; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing command: $command" >&2; exit 1; }
done
if ! id "$MIHOMO_USER" >/dev/null 2>&1; then
  echo "MIHOMO_USER does not exist: $MIHOMO_USER" >&2
  exit 1
fi
python3 -c 'import yaml' >/dev/null 2>&1 || {
  echo "PyYAML is required (install python3-pyyaml or pip install PyYAML)" >&2
  exit 1
}

echo "[1/7] sync panel files"
sudo install -d -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" \
  "$MIHOMO_ROOT" "$MIHOMO_ROOT/web" "$MIHOMO_ROOT/state" \
  "$MIHOMO_ROOT/providers" "$MIHOMO_ROOT/logs"
for file in manager.py v2ray_convert.py set_subscription.py; do
  sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0755 "$REPO_DIR/$file" "$MIHOMO_ROOT/$file"
done
sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0755 "$REPO_DIR/mihomoctl" "$MIHOMO_ROOT/mihomoctl"
for file in index.html app.js app.css; do
  sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0644 "$REPO_DIR/web/$file" "$MIHOMO_ROOT/web/$file"
done

echo "[2/7] initialize provider and config"
sudo -u "$MIHOMO_USER" env MIHOMO_ROOT="$MIHOMO_ROOT" python3 - <<'PY'
import os
from pathlib import Path

root = Path(os.environ["MIHOMO_ROOT"])
legacy = root / "providers" / "sub.yaml"
provider = root / "providers" / "subscription.yaml"
if legacy.exists() and not provider.exists():
    provider.write_bytes(legacy.read_bytes())
elif not provider.exists():
    provider.write_text("proxies: []\n", encoding="utf-8")
PY
if [ ! -f "$MIHOMO_ROOT/config.yaml" ]; then
  secret="$(openssl rand -hex 24)"
  sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0600 "$REPO_DIR/config.example.yaml" "$MIHOMO_ROOT/config.yaml"
  sudo -u "$MIHOMO_USER" env MIHOMO_ROOT="$MIHOMO_ROOT" CONTROLLER_SECRET="$secret" python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["MIHOMO_ROOT"]) / "config.yaml"
text = path.read_text(encoding="utf-8").replace("__CONTROLLER_SECRET__", os.environ["CONTROLLER_SECRET"])
path.write_text(text, encoding="utf-8")
PY
fi

echo "[3/7] install systemd units"
render_template "$REPO_DIR/sub2-mihomo.service" /etc/systemd/system/sub2-mihomo.service
render_template "$REPO_DIR/sub2-mihomo-panel.service" /etc/systemd/system/sub2-mihomo-panel.service

echo "[4/7] install restricted sudo helper"
temp_sudoers="$(mktemp)"
MIHOMO_ROOT="$MIHOMO_ROOT" MIHOMO_USER="$MIHOMO_USER" MIHOMO_GROUP="$MIHOMO_GROUP" \
  MIHOMO_PUBLIC_BASE="$MIHOMO_PUBLIC_BASE" MIHOMO_URL_PATH="$MIHOMO_URL_PATH" \
  SUB2API_DOCKER_HOST="$SUB2API_DOCKER_HOST" SUB2API_DEPLOY_DIR="$SUB2API_DEPLOY_DIR" \
  SUB2API_POSTGRES_CONTAINER="$SUB2API_POSTGRES_CONTAINER" \
  python3 - "$REPO_DIR/sudoers-mihomo" "$temp_sudoers" <<'PY'
import os
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8")
text = text.replace("__MIHOMO_USER__", os.environ["MIHOMO_USER"])
text = text.replace("__MIHOMO_ROOT__", os.environ["MIHOMO_ROOT"])
Path(sys.argv[2]).write_text(text, encoding="utf-8")
PY
sudo install -m 0440 "$temp_sudoers" /etc/sudoers.d/sub2-mihomo
rm -f "$temp_sudoers"
sudo visudo -cf /etc/sudoers.d/sub2-mihomo

echo "[5/7] render managed config"
sudo -u "$MIHOMO_USER" env \
  MIHOMO_PUBLIC_BASE="$MIHOMO_PUBLIC_BASE" \
  SUB2API_DOCKER_HOST="$SUB2API_DOCKER_HOST" \
  SUB2API_DEPLOY_DIR="$SUB2API_DEPLOY_DIR" \
  SUB2API_POSTGRES_CONTAINER="$SUB2API_POSTGRES_CONTAINER" \
  python3 - "$MIHOMO_ROOT" <<'PY'
import json
import sys

sys.path.insert(0, sys.argv[1])
import manager

settings = manager.ensure_layout()
print(json.dumps({
    "mixed_port": settings.get("mixed_port"),
    "node_count": settings.get("node_count"),
    "egress_count": settings.get("egress_count"),
    "secret_set": bool(manager.controller_secret()),
}, ensure_ascii=False))
PY

echo "[6/7] restart services"
sudo systemctl daemon-reload
sudo systemctl enable --now sub2-mihomo.service
sudo systemctl restart sub2-mihomo.service
sleep 1
sudo systemctl enable --now sub2-mihomo-panel.service
sudo systemctl restart sub2-mihomo-panel.service
systemctl is-active sub2-mihomo.service
systemctl is-active sub2-mihomo-panel.service

echo "[7/7] render nginx snippet"
sudo mkdir -p "$(dirname "$NGINX_SNIPPET_CONFIG")"
render_template "$REPO_DIR/nginx-mihomo.conf" "$NGINX_SNIPPET_CONFIG"
if command -v nginx >/dev/null 2>&1; then
  sudo nginx -t
  sudo nginx -s reload || sudo systemctl reload nginx || true
fi

echo PANEL_INSTALL_OK
echo "open: ${MIHOMO_PUBLIC_BASE}/"
