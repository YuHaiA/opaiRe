#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${1:-$(cd "$(dirname "$0")" && pwd)}"
MIHOMO_ROOT="${MIHOMO_ROOT:-/opt/sub2-mihomo}"
MIHOMO_USER="${MIHOMO_USER:-$(id -un)}"
MIHOMO_GROUP="${MIHOMO_GROUP:-$(id -gn "$MIHOMO_USER")}"
MIHOMO_DOMAIN="${MIHOMO_DOMAIN:-tupai.cyou}"
MIHOMO_URL_PATH="${MIHOMO_URL_PATH:-/mihomo}"
MIHOMO_URL_PATH="/${MIHOMO_URL_PATH#/}"
MIHOMO_URL_PATH="${MIHOMO_URL_PATH%/}"
MIHOMO_PUBLIC_BASE="${MIHOMO_PUBLIC_BASE:-https://${MIHOMO_DOMAIN}${MIHOMO_URL_PATH}}"
MIHOMO_WEB_USER="${MIHOMO_WEB_USER:-mihomo}"
SUB2API_CONTAINER="${SUB2API_CONTAINER:-sub2api}"
SUB2API_DOCKER_HOST="${SUB2API_DOCKER_HOST:-172.20.0.1}"
SUB2API_DEPLOY_DIR="${SUB2API_DEPLOY_DIR:-/home/${MIHOMO_USER}/sub2api-deploy}"
SUB2API_POSTGRES_CONTAINER="${SUB2API_POSTGRES_CONTAINER:-sub2api-postgres}"
NGINX_SITE_CONFIG="${NGINX_SITE_CONFIG:-/etc/nginx/conf.d/sub2api.conf}"
NGINX_SNIPPET_CONFIG="${NGINX_SNIPPET_CONFIG:-/etc/nginx/snippets/mihomo.conf}"

export MIHOMO_ROOT MIHOMO_USER MIHOMO_GROUP MIHOMO_DOMAIN MIHOMO_URL_PATH MIHOMO_PUBLIC_BASE
export SUB2API_CONTAINER SUB2API_DOCKER_HOST SUB2API_DEPLOY_DIR SUB2API_POSTGRES_CONTAINER
export NGINX_SITE_CONFIG NGINX_SNIPPET_CONFIG

case "$MIHOMO_ROOT" in
  /*) ;;
  *) echo "MIHOMO_ROOT must be an absolute path" >&2; exit 1 ;;
esac
if [ "$MIHOMO_ROOT" = "/" ] || [ -z "$MIHOMO_URL_PATH" ]; then
  echo "unsafe MIHOMO_ROOT or MIHOMO_URL_PATH" >&2
  exit 1
fi

for command in curl gzip openssl python3; do
  command -v "$command" >/dev/null 2>&1 || { echo "missing command: $command" >&2; exit 1; }
done
if ! id "$MIHOMO_USER" >/dev/null 2>&1; then
  echo "MIHOMO_USER does not exist: $MIHOMO_USER" >&2
  exit 1
fi
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  if command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3-pyyaml
  elif command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update
    sudo apt-get install -y python3-yaml
  else
    echo "PyYAML is required" >&2
    exit 1
  fi
fi

sudo install -d -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" \
  "$MIHOMO_ROOT/bin" "$MIHOMO_ROOT/providers" "$MIHOMO_ROOT/ui"

case "$(uname -m)" in
  x86_64|amd64) mihomo_arch=amd64 ;;
  aarch64|arm64) mihomo_arch=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac

echo "[1/5] install latest Mihomo"
mihomo_version="$(curl -fsSL https://api.github.com/repos/MetaCubeX/mihomo/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
temp_dir="$(mktemp -d)"
trap 'rm -rf "$temp_dir"' EXIT
chmod 0755 "$temp_dir"
curl -fL "https://github.com/MetaCubeX/mihomo/releases/download/${mihomo_version}/mihomo-linux-${mihomo_arch}-${mihomo_version}.gz" -o "$temp_dir/mihomo.gz"
gzip -dc "$temp_dir/mihomo.gz" > "$temp_dir/mihomo"
sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0755 "$temp_dir/mihomo" "$MIHOMO_ROOT/bin/mihomo"
"$MIHOMO_ROOT/bin/mihomo" -v

echo "[2/5] install latest Zashboard"
zashboard_version="$(curl -fsSL https://api.github.com/repos/Zephyruso/zashboard/releases/latest | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
curl -fL "https://github.com/Zephyruso/zashboard/releases/download/${zashboard_version}/dist-cdn-fonts.zip" -o "$temp_dir/ui.zip" || \
  curl -fL "https://github.com/Zephyruso/zashboard/releases/download/${zashboard_version}/dist.zip" -o "$temp_dir/ui.zip"
chmod 0644 "$temp_dir/ui.zip"
sudo -u "$MIHOMO_USER" env UI_ZIP="$temp_dir/ui.zip" UI_ROOT="$MIHOMO_ROOT/ui" python3 - <<'PY'
import os
import shutil
import zipfile
from pathlib import Path

root = Path(os.environ["UI_ROOT"])
for child in root.iterdir():
    if child.is_dir() and not child.is_symlink():
        shutil.rmtree(child)
    else:
        child.unlink()
with zipfile.ZipFile(os.environ["UI_ZIP"]) as archive:
    archive.extractall(root)
nested = root / "dist"
if nested.is_dir():
    for child in nested.iterdir():
        shutil.move(str(child), root / child.name)
    nested.rmdir()
PY

echo "[3/5] create panel credentials"
web_password=""
refresh_credentials=0
if [ ! -f /etc/nginx/mihomo.htpasswd ] || [ ! -f "$MIHOMO_ROOT/CREDENTIALS.txt" ]; then
  refresh_credentials=1
  if ! command -v htpasswd >/dev/null 2>&1; then
    if command -v dnf >/dev/null 2>&1; then
      sudo dnf install -y httpd-tools
    elif command -v apt-get >/dev/null 2>&1; then
      sudo apt-get update
      sudo apt-get install -y apache2-utils
    fi
  fi
  web_password="$(openssl rand -hex 12)"
  if [ -f /etc/nginx/mihomo.htpasswd ]; then
    printf '%s\n' "$web_password" | sudo htpasswd -i /etc/nginx/mihomo.htpasswd "$MIHOMO_WEB_USER"
  else
    printf '%s\n' "$web_password" | sudo htpasswd -ci /etc/nginx/mihomo.htpasswd "$MIHOMO_WEB_USER"
  fi
fi

echo "[4/5] install core, panel, systemd and nginx snippet"
bash "$REPO_DIR/install-panel.sh"

if [ -f "$NGINX_SITE_CONFIG" ]; then
  sudo env NGINX_SITE_CONFIG="$NGINX_SITE_CONFIG" NGINX_SNIPPET_CONFIG="$NGINX_SNIPPET_CONFIG" python3 - <<'PY'
import os
from pathlib import Path

site = Path(os.environ["NGINX_SITE_CONFIG"])
snippet = os.environ["NGINX_SNIPPET_CONFIG"]
text = site.read_text(encoding="utf-8")
include = f"    include {snippet};\n"
if snippet not in text:
    for marker in ("    location /assets/", "    location / {"):
        if marker in text:
            text = text.replace(marker, include + "\n" + marker, 1)
            site.write_text(text, encoding="utf-8")
            break
    else:
        raise SystemExit(f"cannot find nginx insertion point in {site}")
PY
  sudo nginx -t
  sudo nginx -s reload || sudo systemctl reload nginx || true
else
  echo "warning: nginx site config not found: $NGINX_SITE_CONFIG" >&2
  echo "include this file in the HTTPS server block: $NGINX_SNIPPET_CONFIG" >&2
fi

echo "[5/5] smoke tests and local-only credentials"
curl -fsS -m 8 -x http://127.0.0.1:7890 -o /dev/null -w 'host_proxy_http=%{http_code}\n' https://www.gstatic.com/generate_204 || \
  echo "host proxy smoke skipped until nodes are imported"
if command -v docker >/dev/null 2>&1 && docker inspect "$SUB2API_CONTAINER" >/dev/null 2>&1; then
  docker exec "$SUB2API_CONTAINER" curl -fsS -m 8 -x "http://${SUB2API_DOCKER_HOST}:7890" -o /dev/null \
    -w 'docker_proxy_http=%{http_code}\n' https://www.gstatic.com/generate_204 || \
    echo "docker proxy smoke skipped until nodes are imported"
fi

if [ "$refresh_credentials" = "1" ]; then
  controller_secret="$(sudo -u "$MIHOMO_USER" env MIHOMO_ROOT="$MIHOMO_ROOT" python3 - <<'PY'
import os
import re
from pathlib import Path

text = (Path(os.environ["MIHOMO_ROOT"]) / "config.yaml").read_text(encoding="utf-8")
match = re.search(r'^secret:\s*["\x27]?([^"\x27\n]+)', text, re.MULTILINE)
print(match.group(1).strip() if match else "")
PY
)"
  umask 077
  credentials_temp="$(mktemp)"
  {
    printf 'controller_secret=%s\n' "$controller_secret"
    printf 'web_user=%s\n' "$MIHOMO_WEB_USER"
    printf 'web_pass=%s\n' "$web_password"
    printf 'panel_url=%s/\n' "$MIHOMO_PUBLIC_BASE"
    printf 'advanced_ui=%s/ui/\n' "$MIHOMO_PUBLIC_BASE"
    printf 'mixed=http://127.0.0.1:7890\n'
    printf 'docker_mixed=http://%s:7890\n' "$SUB2API_DOCKER_HOST"
  } > "$credentials_temp"
  sudo install -o "$MIHOMO_USER" -g "$MIHOMO_GROUP" -m 0600 "$credentials_temp" "$MIHOMO_ROOT/CREDENTIALS.txt"
  rm -f "$credentials_temp"
fi

echo INSTALL_OK
echo "panel: ${MIHOMO_PUBLIC_BASE}/"
echo "credentials (server only): $MIHOMO_ROOT/CREDENTIALS.txt"
