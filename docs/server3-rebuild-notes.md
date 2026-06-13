# Server 3 Rebuild Notes

Snapshot time: 2026-06-13

Purpose: record the non-secret runtime configuration needed to rebuild Server 3 after recreating the OCI instance. Raw passwords, API keys, tokens, cookies, subscription URLs, database contents, and proxy secrets are intentionally not stored here.

## Identity And Network

- Server label: Server 3
- Current public IP before rebuild: `132.226.99.236`
- New public IP after rebuild: `129.146.91.250`
- SSH user: `opc`
- Local SSH key: `C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
- Hostname: `instance-20260528-1212`
- OS: Oracle Linux Server 9.7
- Current primary private IP: `10.0.0.177`
- Current VCN/subnet before rebuild: `vcn-20260527-2027`, `10.0.0.0/24`
- Target NAT VCN: `opaire-s3-nat-vcn2`
- Target private subnet: `opaire-s3-nat-vcn2-private-subnet`, `10.31.1.0/24`
- Target private route: `0.0.0.0/0 -> NAT Gateway`
- Target public subnet if needed: `opaire-s3-nat-vcn2-public-subnet`, `10.31.0.0/24`
- Actual new instance placement observed on 2026-06-13:
  - Instance: `instance-20260613-1403`
  - Public IP: `129.146.91.250`
  - Private IP: `10.31.0.239`
  - VCN: `opaire-s3-nat-vcn2`
  - Subnet: `opaire-s3-nat-vcn2-public-subnet`
  - Route: `0.0.0.0/0 -> Internet Gateway`
  - Note: this is a public subnet placement, not the NAT private subnet placement.

## Domains

- `dazhou.bond -> 132.226.99.236`
- `www.dazhou.bond -> 132.226.99.236`
- Updated DNS observed on 2026-06-13:
  - `dazhou.bond -> 129.146.91.250`
  - `www.dazhou.bond -> 129.146.91.250`
- Update DNS only after the new public entry point is verified.

## Project Runtime

- Project path: `/home/opc/opaiRe`
- Virtual environment: `/home/opc/opaiRe/.venv`
- System Python: `Python 3.9.25`
- Venv Python: `Python 3.11.13`
- Main entry: `/home/opc/opaiRe/wfxl_openai_regst.py`
- Systemd service: `opaire-lite.service`
- Service user: `opc`
- Bind: `127.0.0.1:8000`
- Service environment:
  - `PYTHONUNBUFFERED=1`
  - `WEB_HOST=127.0.0.1`
  - `WEB_PORT=8000`
  - `WEB_PORT_STRICT=0`
  - `WEB_PORT_STRICT_WAIT_SEC=10`
- Service command: `/home/opc/opaiRe/.venv/bin/python /home/opc/opaiRe/wfxl_openai_regst.py`
- Restart policy: `Restart=on-failure`, `RestartSec=8`

## Runtime Data Paths

- `/home/opc/opaiRe/data/config.yaml`
- `/home/opc/opaiRe/data/data.db`
- `/home/opc/opaiRe/data/mihomo-pool/manual-subscription.txt`
- `/home/opc/opaiRe/data/mihomo-pool/manual-config.yaml`
- `/home/opc/opaiRe/data/mihomo-pool/mihomo-core.log`
- `/home/opc/opaiRe/data/mihomo-pool/mihomo-core.pid`
- `/home/opc/opaiRe/data/server3-web.log`
- `/home/opc/opaiRe/data/web_console.pid`

`data/config.yaml` contains sensitive runtime values; do not paste or commit the raw file.

## Nginx

- Nginx active: yes
- Main config: `/etc/nginx/conf.d/opaire.conf`
- Gzip config: `/etc/nginx/conf.d/00-gzip.conf`
- HTTP listens on `80` and redirects to HTTPS except ACME challenge.
- ACME challenge root: `/var/www/certbot`
- HTTPS listens on `443 ssl http2`.
- `server_name dazhou.bond www.dazhou.bond`
- Certificate: `/etc/letsencrypt/live/dazhou.bond/fullchain.pem`
- Certificate key: `/etc/letsencrypt/live/dazhou.bond/privkey.pem`
- Main upstream: `location / -> http://127.0.0.1:8000`
- Extra upstream: `location = /cdn-22c91d28 -> http://127.0.0.1:18003`
- Subscription aliases:
  - `/clash -> /var/www/proxy-subs/clash.yaml`
  - `/sub -> /var/www/proxy-subs/v2ray.txt`
  - `/subs/_Poi3yXpZERRuSer/clash.yaml -> /var/www/proxy-subs/clash.yaml`
  - `/subs/_Poi3yXpZERRuSer/v2ray.txt -> /var/www/proxy-subs/v2ray.txt`
- Gzip is enabled with level `5`, min length `1024`.

### 2026-06-13 Minimal New Host Nginx State

- Nginx installed after expanding swap and disabling crashkernel/kdump.
- HTTP `80` is active and returns `dazhou.bond server3 new host ok`.
- HTTPS `443` is active with a temporary self-signed certificate under `/etc/nginx/ssl/dazhou.bond/`.
- Let’s Encrypt / certbot has not been restored yet because package availability was limited under the reduced repo set.
- `opaiRe` application upstream is not restored yet by user request; Nginx currently serves a static test page.

### 2026-06-13 NLB + NAT Route State

- Public Network Load Balancer: `server3-public-nlb`
- NLB public IP: `132.226.146.175`
- NLB private IP: `10.31.0.3`
- NLB forwards these ports to instance private IP `10.31.0.239`:
  - `22/tcp`
  - `80/tcp`
  - `443/tcp`
  - `18443/tcp`
  - `18453/tcp`
  - `24443/tcp`
- NLB listener/backend sets use `is_preserve_source = false` so backend replies can return to the NLB after the instance VNIC route is switched to NAT.
- Instance primary VNIC route table was changed to `opaire-s3-nat-vcn2-private-rt`.
- Instance outbound check after route switch returned public IP `161.153.20.32`, confirming NAT Gateway egress.
- Direct instance public IP `129.146.91.250` should no longer be treated as the service entry point.
- Service entry point should be the NLB public IP `132.226.146.175`.
- DNS propagation observed:
  - `1.1.1.1` resolves `dazhou.bond` and `www.dazhou.bond` to `132.226.146.175`.
  - `8.8.8.8` still temporarily resolved both names to `129.146.91.250`; wait for DNS propagation / TTL.
- `22/80/443` through `132.226.146.175` were verified reachable.
- `24443/tcp` is now reachable through the NLB after restoring the Xray Reality node.
- `18443/18453` are configured on the NLB but will not be reachable until the old SOCKS/MTG services are restored on the instance.

### 2026-06-13 Xray Reality Restore

- Xray `26.3.27` is installed at `/usr/local/bin/xray`.
- `xray.service` is enabled and active.
- Active Reality inbound:
  - Listen: `0.0.0.0:24443`
  - Protocol: `VLESS REALITY`
  - Flow: `xtls-rprx-vision`
  - Reality SNI/dest: `www.cloudflare.com`
- Subscription files restored:
  - `/var/www/proxy-subs/clash.yaml`
  - `/var/www/proxy-subs/v2ray.txt`
- Main subscriptions include both `server3-reality` and `server4-reality`.
- Temporary backup IP subscriptions were removed on 2026-06-13 at the user's request:
  - removed `/var/www/proxy-subs/clash-ip.yaml`
  - removed `/var/www/proxy-subs/v2ray-ip.txt`
- Subscription aliases through Nginx are working:
  - `https://dazhou.bond/clash`
  - `https://dazhou.bond/sub`
- Removed temporary aliases now return `404`:
  - `https://dazhou.bond/clash-ip`
  - `https://dazhou.bond/sub-ip`
- Current usable node entry is `dazhou.bond:24443` or NLB IP `132.226.146.175:24443`.
- Local resolver check on 2026-06-13 still showed split DNS:
  - `www.dazhou.bond -> 132.226.146.175`
  - `dazhou.bond -> 129.146.91.250`
- Subscriptions publish `dazhou.bond` as the server address.
- SELinux is enforcing; `/var/www/proxy-subs` must keep `httpd_sys_content_t` context for Nginx to read subscription files.

### 2026-06-13 Let's Encrypt Restore

- The temporary self-signed certificate was replaced with a Let's Encrypt certificate for:
  - `dazhou.bond`
  - `www.dazhou.bond`
- Certificate install paths used by Nginx:
  - `/etc/nginx/ssl/dazhou.bond/fullchain.pem`
  - `/etc/nginx/ssl/dazhou.bond/privkey.pem`
- ACME client:
  - `/home/opc/.acme.sh/acme.sh`
- ACME webroot:
  - `/var/www/certbot`
- `acme.sh` renewal is installed in the `opc` crontab and reloads Nginx after renewal.
- External HTTPS checks for `/clash` and `/sub` returned `200` without disabling TLS verification.
- Temporary `/clash-ip` and `/sub-ip` aliases were later removed and now return `404`.

### 2026-06-13 Reality Compatibility Alignment

- Server 3 Reality SNI/dest was aligned with the previous documented Server 3/Server 4 style:
  - `www.cloudflare.com:443`
- Main and backup subscriptions were updated to publish `servername: www.cloudflare.com` for `server3-reality`.
- Legacy hidden subscription aliases were restored:
  - `https://dazhou.bond/subs/_Poi3yXpZERRuSer/clash.yaml`
  - `https://dazhou.bond/subs/_Poi3yXpZERRuSer/v2ray.txt`
- Network tuning from the previous Reality optimization was restored:
  - `net.ipv4.tcp_congestion_control = bbr`
  - `net.core.default_qdisc = fq`
  - `net.ipv4.tcp_mtu_probing = 1`
  - `net.ipv4.tcp_fastopen = 3`
- A real Xray client test from Server 2 through the Server 3 subscription returned HTTP `204`, confirming the updated Reality handshake works.

## TLS Renewal

- `certbot-renew.timer` is active.
- No user/root crontab renewal entries were found.

## Firewall And SELinux

- `firewalld` active: yes
- Active zone: `public`
- Interface: `ens3`
- Allowed services: `dhcpv6-client`, `http`, `https`, `ssh`
- Extra allowed ports:
  - `18443/tcp`
  - `18443/udp`
  - `24443/tcp`
  - `18453/tcp`
- Forwarding: enabled
- Masquerade: disabled
- SELinux: `Enforcing`
- `httpd_can_network_connect --> on`
- New host firewall has been configured with the same base public services and proxy ports.

## Listening Ports

- `22/tcp`: SSH
- `80/tcp`: Nginx
- `443/tcp`: Nginx
- `127.0.0.1:8000`: opaiRe Python app
- `127.0.0.1:7897`: Mihomo local proxy
- `127.0.0.1:9097`: Mihomo controller
- `*:1053`: Mihomo DNS
- `18443/tcp` and `18443/udp`: Xray
- `24443/tcp`: Xray
- `18453/tcp`: MTG
- `127.0.0.1:4330`: unknown local listener
- `127.0.0.1:44321`: unknown local listener

On the new host as of 2026-06-13, only SSH, Nginx `80/443`, and base system listeners are active. Xray, MTG, Mihomo, and opaiRe are not restored yet.

## Mihomo And Proxy Processes

- Mihomo binary: `/usr/local/bin/mihomo`
- Mihomo version: `Mihomo Meta v1.19.25 linux amd64`
- Mihomo command: `/usr/local/bin/mihomo -f /home/opc/opaiRe/data/mihomo-pool/manual-config.yaml`
- Xray listens on `18443/tcp`, `18443/udp`, and `24443/tcp`.
- MTG listens on `18453/tcp`.
- The MTG command contains an embedded secret-like parameter and is not copied here.

## Config Shape

`/home/opc/opaiRe/data/config.yaml` includes these non-secret structural settings:

- `reg_mode: email`
- `email_api_mode: openai_cpa`
- `mail_domains` configured
- `enable_sub_domains: true`
- `default_proxy` set
- `enable_multi_thread_reg: true`
- `reg_threads: 5`
- `clash_proxy_pool` configured
- `warp_proxy_list` length: `10`
- `use_proxy_for_email` set
- `web_password` set
- `cf_api_email` set
- `cf_api_key` set
- `cluster_node_name: NODE-1`
- `cluster_secret` set
- `disable_forced_takeover: true`

## Rebuild Checklist

1. Create the new OCI instance in `opaire-s3-nat-vcn2-private-subnet`.
2. Prepare a public entry method before DNS cutover: public NLB, reverse proxy, tunnel, or temporary public-subnet instance.
3. Install `nginx`, `firewalld`, certificate tooling, and Python 3.11/venv support.
4. Deploy project source to `/home/opc/opaiRe`.
5. Restore or regenerate required runtime data under `/home/opc/opaiRe/data`.
6. Recreate `/etc/systemd/system/opaire-lite.service`.
7. Recreate Nginx configs and TLS certificate.
8. Re-enable firewalld services/ports and SELinux boolean.
9. Reinstall/configure Mihomo, Xray, and MTG only if still needed.
10. Verify local app, Nginx, proxy ports, and public HTTPS before DNS update.
