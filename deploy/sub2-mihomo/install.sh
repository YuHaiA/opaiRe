#!/bin/bash
set -euo pipefail
ROOT=/opt/sub2-mihomo
REPO_DIR=${1:-}
if [ -z "$REPO_DIR" ]; then
  echo "usage: $0 <path-to-deploy/sub2-mihomo>" >&2
  exit 1
fi

sudo mkdir -p "$ROOT/bin" "$ROOT/providers" "$ROOT/ui"
sudo chown -R ec2-user:ec2-user "$ROOT"

# mihomo binary
VER=$(curl -fsSL https://api.github.com/repos/MetaCubeX/mihomo/releases/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')
echo "mihomo $VER"
TMP=$(mktemp -d)
cd "$TMP"
curl -fL "https://github.com/MetaCubeX/mihomo/releases/download/${VER}/mihomo-linux-amd64-${VER}.gz" -o mihomo.gz
gunzip -f mihomo.gz
install -m 755 mihomo "$ROOT/bin/mihomo"
chmod +x "$ROOT/bin/mihomo"
"$ROOT/bin/mihomo" -v || true

# zashboard ui (small web panel)
ZVER=$(curl -fsSL https://api.github.com/repos/Zephyruso/zashboard/releases/latest | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"])')
echo "zashboard $ZVER"
curl -fL "https://github.com/Zephyruso/zashboard/releases/download/${ZVER}/dist-cdn-fonts.zip" -o ui.zip || curl -fL "https://github.com/Zephyruso/zashboard/releases/download/${ZVER}/dist.zip" -o ui.zip
rm -rf "$ROOT/ui"/*
python3 -c 'import zipfile; zipfile.ZipFile("ui.zip").extractall("/opt/sub2-mihomo/ui")'
# flatten if nested dist
if [ -d "$ROOT/ui/dist" ]; then
  shopt -s dotglob
  mv "$ROOT/ui/dist"/* "$ROOT/ui"/
  rmdir "$ROOT/ui/dist" || true
fi

SECRET=$(openssl rand -hex 16)
WEBPASS=$(openssl rand -hex 8)
cp "$REPO_DIR/config.yaml" "$ROOT/config.yaml"
cp "$REPO_DIR/set_subscription.py" "$ROOT/set_subscription.py"
chmod +x "$ROOT/set_subscription.py"
python3 -c 'from pathlib import Path; import sys; p=Path("/opt/sub2-mihomo/config.yaml"); t=p.read_text(encoding="utf-8"); t=t.replace("__CONTROLLER_SECRET__", sys.argv[1]); p.write_text(t, encoding="utf-8")' "$SECRET"

# empty provider placeholder so boot does not hard-fail before first successful fetch
if [ ! -f "$ROOT/providers/sub.yaml" ]; then
  printf 'proxies: []\n' > "$ROOT/providers/sub.yaml"
fi

# systemd
sudo cp "$REPO_DIR/sub2-mihomo.service" /etc/systemd/system/sub2-mihomo.service
sudo systemctl daemon-reload
sudo systemctl enable sub2-mihomo.service
sudo systemctl restart sub2-mihomo.service
sleep 1
systemctl is-active sub2-mihomo.service
curl -fsS -m 5 -H "Authorization: Bearer $SECRET" http://127.0.0.1:9090/version || true

# nginx basic auth + snippet
if ! command -v htpasswd >/dev/null 2>&1; then
  sudo dnf install -y httpd-tools >/dev/null 2>&1 || sudo yum install -y httpd-tools >/dev/null 2>&1 || true
fi
echo "$WEBPASS" | sudo htpasswd -ci /etc/nginx/mihomo.htpasswd mihomo
sudo cp "$REPO_DIR/nginx-mihomo.conf" /etc/nginx/snippets/mihomo.conf 2>/dev/null || {
  sudo mkdir -p /etc/nginx/snippets
  sudo cp "$REPO_DIR/nginx-mihomo.conf" /etc/nginx/snippets/mihomo.conf
}

# inject include into sub2api.conf 443 server before location /
sudo python3 - <<'PY'
from pathlib import Path
p = Path('/etc/nginx/conf.d/sub2api.conf')
text = p.read_text(encoding='utf-8')
inc = '    include /etc/nginx/snippets/mihomo.conf;\n'
if 'snippets/mihomo.conf' in text:
    print('nginx already includes mihomo')
else:
    marker = '    location /assets/'
    if marker in text:
        text = text.replace(marker, inc + '\n' + marker, 1)
    else:
        marker = '    location / {'
        text = text.replace(marker, inc + '\n' + marker, 1)
    p.write_text(text, encoding='utf-8')
    print('nginx include injected')
PY
sudo nginx -t
sudo nginx -s reload || sudo systemctl reload nginx || true

# docker reachability smoke
curl -fsS -m 8 -x http://127.0.0.1:7890 -o /dev/null -w 'host_proxy_http=%{http_code}\n' https://www.gstatic.com/generate_204 || echo 'host proxy smoke failed (may need subscription)'
docker exec sub2api curl -fsS -m 8 -x http://172.20.0.1:7890 -o /dev/null -w 'docker_proxy_http=%{http_code}\n' https://www.gstatic.com/generate_204 || echo 'docker proxy smoke failed (may need subscription)'

# save credentials locally on server only
umask 077
cat > "$ROOT/CREDENTIALS.txt" <<EOF
controller_secret=$SECRET
web_user=mihomo
web_pass=$WEBPASS
web_url=https://tupai.cyou/mihomo/ui/
mixed=http://127.0.0.1:7890
docker_mixed=http://172.20.0.1:7890
subscription=file-provider-default; set later via set_subscription.py
EOF
chmod 600 "$ROOT/CREDENTIALS.txt"
echo INSTALL_OK
echo "credentials: $ROOT/CREDENTIALS.txt"
