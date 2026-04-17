# Linux Mihomo Deployment Guide

## Scope

This document records the current deployment model for the `feature/mihomo` branch.
It targets:

- Ubuntu 24.04
- Python backend
- Mihomo single-instance controller
- Nginx reverse proxy
- systemd-managed services

The goal is to make the server reproducible without relying on ad-hoc terminal history.

## Current Server Topology

Current server:

- Host: `3.142.201.151`
- Domain: `mycodexy.duckdns.org`
- OS: Ubuntu 24.04

Project layout:

- Project root: `/home/ubuntu/opaiRe`
- Git branch: `feature/mihomo`
- Remote: `origin = https://github.com/YuHaiA/opaiRe.git`

Runtime layout:

- Project venv: `/home/ubuntu/opaiRe/.venv`
- Backend service: `opaire.service`
- Mihomo binary: `/usr/local/bin/mihomo`
- Mihomo service: `mihomo-pool.service`
- Mihomo pool root: `/opt/mihomo-pool`
- Nginx site: `/etc/nginx/sites-available/mycodexy.duckdns.org`

Ports:

- App backend: `127.0.0.1:8000`
- Mihomo mixed proxy: `127.0.0.1:7897`
- Mihomo controller API: `127.0.0.1:42001`
- Nginx public entry: `:80`

## Required Packages

Install base packages:

```bash
sudo apt-get update
sudo apt-get install -y git curl python3 python3-venv python3-pip build-essential unzip nginx software-properties-common
```

Install Python 3.11 from deadsnakes:

```bash
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
```

Why Python 3.11:

- The repository contains `utils/auth_core.cpython-311-x86_64-linux-gnu.so`
- The Linux compiled extension is built for CPython 3.11

## Clone Project

```bash
cd ~
git clone https://github.com/YuHaiA/opaiRe.git opaiRe
cd opaiRe
git checkout feature/mihomo
```

## Create Virtual Environment

```bash
cd ~/opaiRe
rm -rf .venv
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## App Service

Create `/etc/systemd/system/opaire.service`:

```ini
[Unit]
Description=opaiRe web console
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/opaiRe
ExecStart=/home/ubuntu/opaiRe/.venv/bin/python /home/ubuntu/opaiRe/wfxl_openai_regst.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now opaire.service
```

Check:

```bash
sudo systemctl status opaire.service --no-pager
curl -I http://127.0.0.1:8000
```

## Install Mihomo

Install latest stable Linux amd64 compatible build:

```bash
python3 - <<'PY'
import json
import urllib.request
import gzip
import shutil
import os

with urllib.request.urlopen('https://api.github.com/repos/MetaCubeX/mihomo/releases', timeout=30) as r:
    releases = json.load(r)
release = next(x for x in releases if not x.get('prerelease'))
asset = next(a for a in release.get('assets', []) if (a.get('name') or '').startswith('mihomo-linux-amd64-compatible-') and (a.get('name') or '').endswith('.gz'))
with urllib.request.urlopen(asset['browser_download_url'], timeout=120) as r:
    data = r.read()
with open('/tmp/mihomo.gz', 'wb') as f:
    f.write(data)
with gzip.open('/tmp/mihomo.gz', 'rb') as src, open('/tmp/mihomo', 'wb') as dst:
    shutil.copyfileobj(src, dst)
os.chmod('/tmp/mihomo', 0o755)
PY

sudo mv /tmp/mihomo /usr/local/bin/mihomo
sudo mkdir -p /etc/mihomo /var/lib/mihomo
/usr/local/bin/mihomo -v
```

## Mihomo Single-Instance Layout

Create directories:

```bash
sudo mkdir -p /opt/mihomo-pool/config_1 /opt/mihomo-pool/providers
sudo chown -R ubuntu:ubuntu /opt/mihomo-pool /var/lib/mihomo
```

Create `/opt/mihomo-pool/pool.env`:

```bash
cat > /opt/mihomo-pool/pool.env <<'EOF'
COUNT=1
SUB_URL=
SECRET=replace-me-with-random-secret
IMAGE=mihomo-single
EOF
```

Base config file `/opt/mihomo-pool/config_1/config.yaml`:

```yaml
mixed-port: 7897
allow-lan: false
bind-address: 127.0.0.1
mode: rule
log-level: info
external-controller: 127.0.0.1:42001
secret: replace-me-with-random-secret
dns:
  enable: true
  listen: 127.0.0.1:1053
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
proxy-groups:
  - name: 节点选择
    type: select
    proxies:
      - DIRECT
rules:
  - MATCH,节点选择
```

## Mihomo Update Script

Create `/opt/mihomo-pool/update_pool.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

POOL_DIR=/opt/mihomo-pool
ENV_FILE="$POOL_DIR/pool.env"
CONFIG_DIR="$POOL_DIR/config_1"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
source "$ENV_FILE"

mkdir -p "$CONFIG_DIR" "$POOL_DIR/providers"
TEST_URL="http://www.gstatic.com/generate_204"

if [[ -n "${SUB_URL:-}" ]]; then
cat > "$CONFIG_FILE" <<CFG
mixed-port: 7897
allow-lan: false
bind-address: 127.0.0.1
mode: rule
log-level: info
external-controller: 127.0.0.1:42001
secret: ${SECRET}
dns:
  enable: true
  listen: 127.0.0.1:1053
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
proxy-providers:
  main:
    type: http
    url: "${SUB_URL}"
    path: ./providers/main.yaml
    interval: 86400
    health-check:
      enable: true
      url: ${TEST_URL}
      interval: 300
proxy-groups:
  - name: 节点选择
    type: select
    use:
      - main
    proxies:
      - DIRECT
  - name: 自动选择
    type: url-test
    use:
      - main
    url: ${TEST_URL}
    interval: 300
rules:
  - MATCH,节点选择
CFG
else
cat > "$CONFIG_FILE" <<CFG
mixed-port: 7897
allow-lan: false
bind-address: 127.0.0.1
mode: rule
log-level: info
external-controller: 127.0.0.1:42001
secret: ${SECRET}
dns:
  enable: true
  listen: 127.0.0.1:1053
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  nameserver:
    - https://1.1.1.1/dns-query
    - https://8.8.8.8/dns-query
proxy-groups:
  - name: 节点选择
    type: select
    proxies:
      - DIRECT
rules:
  - MATCH,节点选择
CFG
fi

pkill -TERM -u ubuntu -f '/usr/local/bin/mihomo -d /var/lib/mihomo -f /opt/mihomo-pool/config_1/config.yaml' || true
sleep 2
systemctl --no-pager --full status mihomo-pool.service | sed -n '1,12p'
```

Make executable:

```bash
chmod +x /opt/mihomo-pool/update_pool.sh
```

## Mihomo Status Script

Create `/opt/mihomo-pool/status_pool.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
echo '=== pool.env ==='
cat /opt/mihomo-pool/pool.env || true
echo
echo '=== service ==='
systemctl --no-pager --full status mihomo-pool.service | sed -n '1,12p' || true
echo
echo '=== controller ==='
curl -s http://127.0.0.1:42001/version || true
```

Make executable:

```bash
chmod +x /opt/mihomo-pool/status_pool.sh
```

## Mihomo systemd Service

Create `/etc/systemd/system/mihomo-pool.service`:

```ini
[Unit]
Description=Single Mihomo pool service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
ExecStart=/usr/local/bin/mihomo -d /var/lib/mihomo -f /opt/mihomo-pool/config_1/config.yaml
Restart=always
RestartSec=5
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mihomo-pool.service
```

Check:

```bash
curl -s -H 'Authorization: Bearer YOUR_SECRET' http://127.0.0.1:42001/version
ss -ltnp | grep -E ':42001|:7897'
```

## Application Config Alignment

Key application config values in `data/config.yaml`:

```yaml
default_proxy: http://127.0.0.1:7897

clash_proxy_pool:
  enable: true
  client_type: mihomo
  api_url: http://127.0.0.1:42001
  test_proxy_url: http://127.0.0.1:7897
  group_name: 节点选择
  secret: YOUR_SECRET
```

`host.docker.internal` compatibility:

```bash
grep -q '^127.0.0.1 host.docker.internal$' /etc/hosts || echo '127.0.0.1 host.docker.internal' | sudo tee -a /etc/hosts > /dev/null
```

This is used because some existing API helper logic still resolves controller endpoints through `host.docker.internal`.

## Nginx Reverse Proxy

Create `/etc/nginx/sites-available/mycodexy.duckdns.org`:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name mycodexy.duckdns.org;

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

Enable:

```bash
sudo ln -sf /etc/nginx/sites-available/mycodexy.duckdns.org /etc/nginx/sites-enabled/mycodexy.duckdns.org
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

## Firewall / Security Group

On AWS Security Group:

- Allow `TCP 80`
- Allow `TCP 443` if you plan to add HTTPS later

Ubuntu local firewall (`ufw`) can remain inactive if AWS security group is correctly configured.

## Update Workflow

Current branch update path:

1. Push local code to GitHub:

```bash
git push origin feature/mihomo
```

2. On server, use the built-in **From GitHub Update** button in the panel
3. If new code was pulled, manually restart the project service

Manual equivalent:

```bash
cd ~/opaiRe
git fetch origin
git pull --rebase origin feature/mihomo
sudo systemctl restart opaire.service
```

## Important Runtime Limitation

The registration flow depends on `utils/auth_core`.

Repository currently contains these binaries:

- `auth_core.cpython-311-x86_64-linux-gnu.so`
- `auth_core.cpython-311-aarch64-linux-gnu.so`
- `auth_core.cpython-311-darwin.so`
- `auth_core.pyd`

Server was switched to Python 3.11 to match the Linux extension ABI.

However, **the Linux extension still does not successfully behave as a normal importable runtime component on the current Ubuntu host**, so:

- Panel
- Mihomo management
- CPA/Sub2API warehouse management

are suitable to run on Linux now,

but the **full registration flow may still be blocked by `utils.auth_core` behavior** and should be treated separately.

## Quick Validation Commands

Check backend:

```bash
sudo systemctl status opaire.service --no-pager
curl -I http://127.0.0.1:8000
```

Check Mihomo:

```bash
sudo systemctl status mihomo-pool.service --no-pager
curl -s -H "Authorization: Bearer YOUR_SECRET" http://127.0.0.1:42001/version
curl -s -H "Authorization: Bearer YOUR_SECRET" http://127.0.0.1:42001/providers/proxies | head
```

Check public entry:

```bash
curl -I http://127.0.0.1
curl -I -H 'Host: mycodexy.duckdns.org' http://127.0.0.1
```

## Current Effective Values On This Server

At the time of writing:

- Domain: `mycodexy.duckdns.org`
- Mihomo secret: `031c82ff44230921e59ec3bc9cdb6b20`
- Controller: `127.0.0.1:42001`
- Mixed proxy: `127.0.0.1:7897`
- App backend: `127.0.0.1:8000`
