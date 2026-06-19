# OCI NLB Inbound + NAT Egress Runbook

Snapshot time: 2026-06-13

Purpose: record the no-delete/no-rebuild method used on Server 3 to avoid the Oracle free AMD public 50Mbps path, and define how to safely replicate it to Server 4 without touching the application runtime.

No secrets, raw node links, private keys, tokens, cookies, or OCI credential values are stored in this file.

## Current Server / Domain Authority

Use this table as the current source of truth for the Oracle proxy and domain setup.

| Role | OCI instance | Public entry | Private IP | Domain(s) | Proxy role |
| --- | --- | --- | --- | --- | --- |
| Server 3 | `instance-20260613-1403` | Shared NLB `132.226.146.175` | `10.31.0.239` | `dazhou.bond`, `www.dazhou.bond` | Server 3 Web / subscription / Reality backend |
| Server 4 proxy backend | `code` | Shared NLB `132.226.146.175` via Server 3 stream | `10.0.0.154` | `xh-ai.cyou`, `www.xh-ai.cyou` | Server 4 Reality backend on `24444/tcp` |

Operational rules:

- Do not route current Server 4 proxy traffic to `instance-20260604-1123 / 10.0.0.112` unless a future migration explicitly changes this table and revalidates the node.
- `xh-ai.cyou` / `www.xh-ai.cyou` Web and subscription traffic must stay on the Nginx HTTPS upstream `nginx_https_4443`.
- `server4-reality-443` uses public entry `xh-ai.cyou:443` with Reality SNI `www.cloudflare.com`; Server 3 Nginx stream forwards that SNI to `10.0.0.154:24444`.
- Server 4 Telegram currently keeps only the native MTProto entry on `code / 10.0.0.154`:
  - `xh-ai.cyou:18454 -> 10.0.0.154:18454` for MTProto.
  - `xh-ai.cyou:18444` Xray SOCKS was intentionally removed on 2026-06-19.
- Server 3 Telegram also keeps only the native MTProto entry:
  - `dazhou.bond:18453 -> 10.31.0.239:18453` for MTProto.
  - `dazhou.bond:18443` Xray SOCKS was intentionally removed on 2026-06-19.
- Shared subscription files live on Server 3 under `/var/www/proxy-subs/`; the `server4-reality-443` entry must match the `code` machine Xray config.

## Principle

- Keep the existing instance and primary VNIC.
- Put a public Network Load Balancer in front of the instance for inbound traffic.
- Add NLB listeners/backends for every public service port.
- Set backend source preservation to disabled, so replies can return through the NLB after route changes.
- Change the instance primary VNIC route table to a NAT Gateway route table for outbound traffic.
- Use the NLB public IP, or DNS pointing to the NLB public IP, as the public entry point.

This is the important part: the instance does not need to be deleted or recreated. The working change is a VNIC route table update plus a public NLB entry point.

## Server 3 Verified Result

- Instance: `instance-20260613-1403`
- Instance private IP: `10.31.0.239`
- Instance direct public IP: `129.146.91.250`
- VCN: `opaire-s3-nat-vcn2`
- Subnet: `opaire-s3-nat-vcn2-public-subnet`
- NLB: `server3-public-nlb`
- NLB public IP: `132.226.146.175`
- NLB private IP: `10.31.0.3`
- VNIC route table after switch: `opaire-s3-nat-vcn2-private-rt`
- NAT egress IP observed from the instance: `161.153.20.32`
- DNS entry point after cutover:
  - `dazhou.bond -> 132.226.146.175`
  - `www.dazhou.bond -> 132.226.146.175`

Configured NLB listeners/backends:

- `22/tcp -> 10.31.0.239:22`
- `80/tcp -> 10.31.0.239:80`
- `443/tcp -> 10.31.0.239:443`
- `18443/tcp -> 10.31.0.239:18443`
- `18453/tcp -> 10.31.0.239:18453`
- `24443/tcp -> 10.31.0.239:24443`

Validation evidence from Server 3:

- SSH through NLB works.
- Public HTTP/HTTPS through NLB works.
- Reality `24443/tcp` through NLB works.
- Server 2 cloud-to-cloud download from the NLB reached about `400Mbps`.
- Instance outbound IP changed from the direct instance public IP to NAT Gateway IP `161.153.20.32`.

## Safe Replication Shape For Server 4

Current Server 4 snapshot before applying this method:

- Domain: `xh-ai.cyou`
- Current DNS: `xh-ai.cyou -> 137.131.12.149`, `www.xh-ai.cyou -> 137.131.12.149`
- Private IP observed on host: `10.0.0.154`
- Current egress IP: `137.131.12.149`
- Active services:
  - `22/tcp`: SSH
  - `80/tcp`: Nginx
  - `443/tcp`: Nginx
  - `18444/tcp`: Xray SOCKS
  - `18454/tcp`: MTG
  - `24444/tcp`: Xray Reality

### 2026-06-13 Server 4 Partial Replication State

OCI limit note:

- Creating a second independent NLB failed with `LimitExceeded: max-nlb-flexible-count`.
- The account currently has one public NLB available in practice, already used by Server 3.
- Chosen low-impact workaround: reuse Server 3 public NLB for Server 4 high proxy ports only.

Created or updated resources:

- NAT Gateway in Server 4 current VCN:
  - `server4-nat-gateway`
- NAT route table in Server 4 current VCN:
  - `server4-nat-route-table`
  - route `0.0.0.0/0 -> server4-nat-gateway`
  - route `10.31.0.0/16 -> s4-to-s3-lpg`
- VCN local peering:
  - Server 3 side: `s3-to-s4-lpg`
  - Server 4 side: `s4-to-s3-lpg`
  - peering status: `PEERED`
- Server 3 NLB public subnet route table:
  - route `10.0.0.0/16 -> s3-to-s4-lpg`
- Server 4 current default route table:
  - route `10.31.0.0/16 -> s4-to-s3-lpg`
  - original default route to Internet Gateway remains unchanged
- Server 3 NLB subnet security list:
  - added public TCP ingress for `18444`, `18454`, `24444`
- Existing Server 3 public NLB:
  - added listener `18444/tcp -> 10.0.0.154:18444`
  - added listener `18454/tcp -> 10.0.0.154:18454`
  - added listener `24444/tcp -> 10.0.0.154:24444`
  - backend sets use `is_preserve_source=false`

Validation:

- TCP checks to `132.226.146.175:18444`, `132.226.146.175:18454`, and `132.226.146.175:24444` succeeded.
- A real Xray client test through `132.226.146.175:24444` to Server 4 Reality returned HTTP `204`.
- During this partial state, Server 4 egress remains direct public IP `137.131.12.149`.
- Temporary no-DNS/no-VNIC-change speed test from Server 2 showed this is not a full bypass yet:
  - Direct `xh-ai.cyou:24444` proxy egress IP: `137.131.12.149`
  - Shared NLB `132.226.146.175:24444` proxy egress IP: `137.131.12.149`
  - Measured download range stayed around `33-46Mbps`
  - Conclusion: shared NLB inbound alone works, but full bypass still requires changing Server 4 egress to NAT or otherwise moving the full traffic path.

Important pause point:

- Do not switch Server 4 primary VNIC to `server4-nat-route-table` while `xh-ai.cyou` still points directly to `137.131.12.149`, unless a project ingress replacement is ready.
- Reason: changing the VNIC default route to NAT can break direct public `80/443` return traffic for the current project entry point.
- To complete full NAT egress without project interruption, choose one of these:
  - Move `xh-ai.cyou` public web traffic behind the existing NLB through a host-based reverse proxy on Server 3.
  - Use a separate NLB after increasing OCI `max-nlb-flexible-count`.
  - Keep project `80/443` direct and only publish Server 4 proxy nodes through shared NLB, accepting that Server 4 proxy egress remains the direct public IP until a safer ingress plan is in place.

Low-impact replication approach:

1. Do not stop `nginx`, `xray`, `mtg`, the app service, or any project process.
2. Create or reuse a NAT Gateway route table in Server 4's VCN.
3. Create a public NLB in the same VCN or in a network path that can reach Server 4 private IP.
4. Add backend sets with `is_preserve_source=false`.
5. Add NLB listeners/backends for Server 4 ports:
   - `22/tcp -> 10.0.0.154:22`
   - `80/tcp -> 10.0.0.154:80`
   - `443/tcp -> 10.0.0.154:443`
   - `18444/tcp -> 10.0.0.154:18444`
   - `18454/tcp -> 10.0.0.154:18454`
   - `24444/tcp -> 10.0.0.154:24444`
6. Open the same destination ports in the OCI security list or NSG used by the backend subnet.
7. Verify the NLB public IP first, before changing DNS or VNIC routing:
   - SSH to the NLB IP.
   - `http://NLB_IP/` with `Host: xh-ai.cyou`.
   - `https://NLB_IP/` with `Host: xh-ai.cyou`.
   - TCP checks for `18444`, `18454`, and `24444`.
8. Change Server 4 primary VNIC route table to the NAT Gateway route table.
9. SSH again through the NLB IP and verify:
   - inbound still works through NLB
   - `curl -4 https://ifconfig.me` returns the NAT Gateway egress IP
10. Only after these checks, update DNS:
   - `xh-ai.cyou -> Server 4 NLB public IP`
   - `www.xh-ai.cyou -> Server 4 NLB public IP`

## Why This Should Not Affect The Project

The application runtime is not changed by the network method:

- No project files are edited.
- No database or `data/` runtime state is touched.
- No systemd project service needs to restart.
- Nginx, Xray, MTG, and the panel can continue listening on the same local ports.
- Public clients move from direct instance IP to NLB IP only after DNS cutover.

Expected visible changes:

- Public source IPs in Nginx/app logs may become the NLB private IP instead of real client IP because source preservation is disabled.
- Outbound IP from the instance changes to the NAT Gateway egress IP after the VNIC route table switch.
- Any third-party service that allowlists the old direct public IP may need the NAT egress IP added.
- Any license, webhook, or security rule tied to the old egress IP may need review.

## Rollback

Rollback is straightforward if the instance is not deleted:

1. Point DNS back to the original instance public IP.
2. Change the primary VNIC route table back to the original Internet Gateway route table.
3. Keep or delete the NLB after traffic is confirmed back on the direct path.

Do not delete the original public IP, VNIC, route table, or instance during initial replication. Keeping them makes rollback quick.

## Critical Notes

- The NLB backend must be reachable through the instance private IP.
- Backend source preservation must stay disabled for this route shape.
- Do not change DNS until the NLB IP has been tested directly.
- Do not remove the instance public IP until the NLB and NAT path are fully verified.
- The method changes network entry/exit only; proxy node configs still need separate validation after the network cutover.

## 2026-06-13 Server 4 Full Shared-NLB + NAT Cutover

Chosen path:

- Use existing shared NLB public IP `132.226.146.175`.
- Point `xh-ai.cyou` and `www.xh-ai.cyou` DNS to `132.226.146.175`.
- Let Server 3 Nginx terminate `xh-ai.cyou` HTTPS and reverse proxy project web traffic to Server 4 over private VCN peering.
- Let Server 4 proxy high ports continue to use NLB listeners directly:
  - `132.226.146.175:18444 -> 10.0.0.154:18444`
  - `132.226.146.175:18454 -> 10.0.0.154:18454`
  - `132.226.146.175:24444 -> 10.0.0.154:24444`

Server 3 Nginx changes:

- Added `xh-ai.cyou` / `www.xh-ai.cyou` HTTP/HTTPS virtual host on Server 3.
- Copied the existing certificate files from Server 4 to Server 3:
  - `/etc/nginx/ssl/xh-ai.cyou/fullchain.cer`
  - `/etc/nginx/ssl/xh-ai.cyou/xh-ai.cyou.key`
- Server 3 HTTPS upstream for `xh-ai.cyou` proxies to:
  - `https://10.0.0.154`
- Server 3 HTTP ACME path proxies to:
  - `http://10.0.0.154`
- Enabled Server 3 SELinux boolean:
  - `httpd_can_network_connect --> on`

Server 4 VNIC route change:

- Server 4 primary VNIC was changed to:
  - `server4-nat-route-table`
- Previous direct route table:
  - `Default Route Table for vcn-20260527-2027`
- New route table includes:
  - `0.0.0.0/0 -> server4-nat-gateway`
  - `10.31.0.0/16 -> s4-to-s3-lpg`

Access safety:

- Added temporary shared-NLB SSH fallback:
  - `132.226.146.175:2224 -> 10.0.0.154:22`
- Service 4 NSG allows `10.31.0.0/16 -> 22/tcp` for this fallback path.

Validation after cutover:

- `xh-ai.cyou` and `www.xh-ai.cyou` resolved to `132.226.146.175`.
- `https://xh-ai.cyou/` returned the same application-level `405` response as the backend.
- `https://xh-ai.cyou/clash` returned `200`.
- SSH fallback through `132.226.146.175:2224` reached Server 4.
- Server 4 host egress IP changed to NAT IP:
  - `161.153.60.236`
- A real Xray client through shared NLB `132.226.146.175:24444` returned HTTP `204`.
- The proxy egress IP through Server 4 Reality is now:
  - `161.153.60.236`
- Post-cutover proxy download tests from Server 2:
  - OVH 100MB: about `108Mbps`
  - Hetzner 100MB: about `288Mbps`

Current interpretation:

- Full Server 4 bypass is active for Reality traffic when clients use `xh-ai.cyou:24444`, because DNS now points that name to the shared NLB.
- Project web traffic for `xh-ai.cyou` now enters through Server 3 NLB/Nginx and is proxied privately to Server 4.
- Server 4 application files, database, and systemd services were not modified.

## 2026-06-13 Proxy Stability Tuning

Applied server-side tuning after local Clash tests showed high variance and Server 4 performing better than Server 3 on the user's local path.

Server tuning:

- Server 3 Reality inbound now uses:
  - `tcpFastOpen: true`
  - `tcpNoDelay: true`
  - `domainStrategy: UseIPv4`
- Server 4 Reality inbound was verified with the same socket options.
- Both Server 3 and Server 4 now persist TCP tuning in:
  - `/etc/sysctl.d/99-xray-performance.conf`
- Important sysctl values:
  - `net.ipv4.tcp_slow_start_after_idle = 0`
  - `net.ipv4.ip_local_port_range = 10240 65535`
  - `net.core.somaxconn = 8192`
  - `net.core.netdev_max_backlog = 16384`
  - `bbr`, `fq`, TCP Fast Open, and MTU probing remain enabled.

Subscription tuning:

- Main Clash subscriptions on both hosts now prioritize `server4-reality` before `server3-reality` in auto-test and fallback groups.
- Main V2Ray/Base64 subscriptions on both hosts now list `server4-reality` before `server3-reality`.
- Temporary `/clash-ip` and `/sub-ip` aliases remain removed.

Validation:

- `xray run -test -config /usr/local/etc/xray/config.json` passed on both hosts.
- `xray` restarted successfully and remained active on both hosts.
- Main subscription endpoints stayed available:
  - `https://dazhou.bond/clash`
  - `https://dazhou.bond/sub`
  - `https://xh-ai.cyou/clash`
  - `https://xh-ai.cyou/sub`
- Local Clash selected `server4-reality` through the auto-test group and egressed as `161.153.60.236`.
- Local short OVH download through Clash remained only a few Mbps, so the remaining bottleneck is likely the user's local ISP path to OCI Phoenix / the shared NLB rather than Server 4 NAT egress.

## 2026-06-14 Speed Retest And Log Reduction

Additional tuning:

- Xray logs on Server 3 and Server 4 were reduced explicitly:
  - `access: none`
  - `error: none`
  - `loglevel: warning`
- Both configs were validated with:
  - `xray run -test -config /usr/local/etc/xray/config.json`
- Both `xray` services restarted successfully and remained active.

Retest results from Server 2:

- Server 3 direct host NAT egress:
  - Cachefly 100MB: about `546Mbps`
  - OVH 100MB: about `129Mbps`
- Server 4 direct host NAT egress:
  - Cachefly 100MB: about `359Mbps`
  - OVH 100MB: about `123Mbps`
- Reality proxy through shared NLB:
  - Server 3 to Cachefly 100MB: about `320-331Mbps`
  - Server 4 to Cachefly 100MB: about `306-325Mbps`
  - Server 3 to OVH 100MB: about `119Mbps`
  - Server 4 to OVH 100MB: about `108Mbps`
- Raw Server 3 NLB HTTPS download test:
  - about `253-357Mbps`
  - temporary `/usr/share/nginx/html/nlb-speed-test.bin` was removed after testing.
- Server 2 direct Cachefly baseline:
  - about `2.1Gbps`

Interpretation:

- NAT egress itself is healthy; Server 3 direct egress still reaches the `500Mbps` class to a favorable target.
- The shared public NLB / cross-cloud ingress path is currently the limiting part for Reality traffic, with a practical single-flow result around `300Mbps`.
- The previous `400Mbps` figure should be treated as a favorable high point for NLB pull testing, not a guaranteed constant for every proxy target.

## 2026-06-14 Alternate Client Entry Ports

Reason:

- Cloud-side Reality tests reached the `300Mbps` class, while the user's local / mobile path to the original high ports remained much slower.
- Additional TLS-like entry ports were added to test whether the local ISP path treats common alternate HTTPS ports better.

Server-side changes:

- Server 3 Xray now also listens on:
  - `2053/tcp`
- Server 4 Xray now also listens on:
  - `8443/tcp`
  - `2083/tcp`
  - `2087/tcp`
  - `2096/tcp`
- All added inbounds reuse the existing Reality settings for their server.

NLB changes:

- Added listeners/backends:
  - `132.226.146.175:2053 -> 10.31.0.239:2053`
  - `132.226.146.175:8443 -> 10.0.0.154:8443`
  - `132.226.146.175:2083 -> 10.0.0.154:2083`
  - `132.226.146.175:2087 -> 10.0.0.154:2087`
  - `132.226.146.175:2096 -> 10.0.0.154:2096`
- The NLB subnet security list allows these public TCP ports.
- Server 4 NSG allows `10.31.0.0/16` to reach `8443/2083/2087/2096`.
- Backend source preservation remains disabled.

Subscription changes:

- Main `/clash` and `/sub` endpoints now publish nodes in this order:
  - `server4-reality-2087`
  - `server4-reality-8443`
  - `server4-reality`
  - `server3-reality-2053`
  - `server3-reality`

Validation:

- TCP checks from Server 2 and the local machine succeeded for `2053/8443/2083/2087/2096`.
- Server 2 through `server4-reality-2087`:
  - Cachefly 100MB: about `336Mbps`
  - OVH 100MB: about `106Mbps`
- Local temporary Xray tests showed `2087` was the best of the added Server 4 ports in that run:
  - `2087`: about `41.8Mbps` to Cachefly, about `10.2Mbps` to OVH 10MB
  - `8443`: about `34.7Mbps` to Cachefly, about `10.0Mbps` to OVH 10MB
  - `2083`: about `34.2Mbps` to Cachefly, about `6.9Mbps` to OVH 10MB
  - `2096`: about `18.9Mbps` to Cachefly, about `9.2Mbps` to OVH 10MB
- A later local `2087` retest dropped to about `20Mbps`, confirming the user's local path to OCI still fluctuates significantly.

## 2026-06-14 Shared 443 SNI Entry

Reason:

- Alternate high ports improved local speed but still did not approach cloud-side results.
- A shared `443/tcp` entry was added because local/mobile networks often treat standard HTTPS more favorably than high ports.

Implementation on Server 3:

- Installed `nginx-mod-stream`.
- Fully restarted Nginx once so the stream dynamic module was loaded by the master process.
- Added `4443/tcp` to SELinux `http_port_t`.
- Public `0.0.0.0:443` is now handled by an Nginx `stream` block with `ssl_preread`.
- Existing HTTPS virtual hosts were moved behind the stream router:
  - `dazhou.bond` / `www.dazhou.bond` -> `127.0.0.1:4443`
  - `xh-ai.cyou` / `www.xh-ai.cyou` -> `127.0.0.1:4443`
- Reality SNI route:
  - `www.cloudflare.com -> 10.0.0.154:24444`

Current behavior:

- Web traffic to `https://dazhou.bond/` and `https://xh-ai.cyou/` remains available through the shared `443` entry.
- Reality clients using `xh-ai.cyou:443` and SNI `www.cloudflare.com` reach Server 4 Reality.
- Because both existing Reality nodes use `servername: www.cloudflare.com`, only one backend can own that SNI on shared `443`; Server 4 is currently selected.

Subscription order:

- Main `/clash` and `/sub` endpoints now publish nodes in this order:
  - `server4-reality-443`
  - `server4-reality-2087`
  - `server4-reality-8443`
  - `server4-reality`
  - `server3-reality-2053`
  - `server3-reality`

Validation:

- `https://dazhou.bond/` returned `200`.
- `https://xh-ai.cyou/` returned `200`.
- Main `/clash` and `/sub` endpoints contain the updated node order.
- Server 2 through `xh-ai.cyou:443` Reality:
  - Cachefly 100MB: about `338Mbps`
  - OVH 100MB: about `110Mbps`
- Local temporary Xray through `xh-ai.cyou:443` Reality:
  - Cachefly 100MB: about `34Mbps`
  - OVH 10MB: about `20.5Mbps`
- Local Clash Verge was refreshed and currently selects `server4-reality-443` in rule mode.

## 2026-06-14 Hysteria2 UDP 443 Trial

Reason:

- Cloud-side Reality tests stayed in the `300Mbps+` class, but local and mobile clients remained much slower.
- A Hysteria2 / QUIC entry was added as a UDP-path comparison without replacing the existing Reality nodes.

Implementation on Server 4:

- Installed Hysteria `v2.9.2`.
- Created `hysteria-server.service` with `/etc/hysteria/config.yaml`.
- The service listens on `:443/udp`.
- Hysteria uses a private copy of the existing `xh-ai.cyou` certificate under `/etc/hysteria/tls/`; the Nginx certificate files were not modified.
- Server 4 firewalld allows `443/udp`.
- Hysteria bandwidth settings were raised to `500Mbps / 500Mbps`.

OCI changes:

- Added NLB UDP listener/backend:
  - `132.226.146.175:443/udp -> 10.0.0.154:443/udp`
- Added NLB subnet ingress for public `443/udp`.
- Added Server 4 NSG ingress from `10.31.0.0/16` to `443/udp`.
- TCP `443` remains unchanged and continues to serve the Nginx stream / Reality SNI path.

Subscription changes:

- Main Clash subscriptions now publish `server4-hy2-443` before the Reality nodes.
- Main V2Ray/Base64 `/sub` endpoints remain unchanged because Hysteria2 is not a VLESS URI.

Current Clash order:

- `server4-hy2-443`
- `server4-reality-443`
- `server4-reality-2087`
- `server4-reality-8443`
- `server4-reality`
- `server3-reality-2053`
- `server3-reality`

Validation:

- Local Hysteria Windows `v2.9.2` client connected to `xh-ai.cyou:443/udp` with UDP enabled.
- `https://dazhou.bond/` returned `200`.
- `https://xh-ai.cyou/` returned `200`.
- `https://dazhou.bond/clash` and `https://xh-ai.cyou/clash` both contain `server4-hy2-443`.
- Local HY2 speed tests after raising bandwidth:
  - Cloudflare 50MB: about `46Mbps`; local direct baseline for the same test was about `10.8Mbps`.
  - OVH 100MB: about `42-43Mbps`.
  - Cachefly 100MB: about `46-51Mbps`, but one run ended early around 10 seconds, so this value is less reliable.

Conclusion:

- Hysteria2 improves the local HTTPS-style test path, but it still does not reach `100Mbps+`.
- The remaining bottleneck appears to be the user's local/mobile path into the OCI Phoenix NLB rather than Server 4 NAT egress or the cloud-side proxy stack.

### 2026-06-14 HY2 Follow-Up Tests

Subscription update:

- `server4-hy2-443` now includes:
  - `up: 500 Mbps`
  - `down: 500 Mbps`
  - `fast-open: true`
- Both public Clash endpoints were verified to contain those fields:
  - `https://dazhou.bond/clash`
  - `https://xh-ai.cyou/clash`

Server 2 cloud-side HY2 validation:

- Cachefly 100MB: about `199Mbps`
- Cloudflare 50MB: about `222Mbps`
- OVH 100MB: about `74Mbps`
- This proves Server 4 HY2, OCI NLB UDP 443, and NAT egress are not capped at `50Mbps`.

Local HY2 validation:

- Four parallel Cloudflare 50MB downloads aggregated about `49.5Mbps`; the local limit is not only single-stream behavior.
- No-bandwidth / BBR client mode tested lower, about `31Mbps` to Cloudflare 50MB.
- `80Mbps` Brutal client mode also tested lower, about `27.6Mbps` to Cloudflare 30MB.
- The published `500Mbps / 500Mbps` HY2 settings are the best tested local HY2 settings so far.

Cloudflare Tunnel comparison:

- A temporary local-only Server 4 `VLESS WS` inbound and account-less `trycloudflare.com` tunnel were tested.
- Server 4 UDP socket buffers were raised so cloudflared's QUIC receive-buffer warning disappeared.
- Local VLESS WS through the quick tunnel reached only about `40-41Mbps` to Cloudflare 50MB, below HY2.
- The quick tunnel was stopped after testing, and the temporary `cf-vless-ws-local` Xray inbound was removed.

Follow-up direction:

- Reaching the user's target speed from mobile likely requires a better nearby ingress / relay path rather than more OCI-only tuning.

### 2026-06-14 Alternate HY2 UDP Ports

Purpose:

- Check whether the user's local network is specifically limiting `443/udp`, and whether another UDP entry port can exceed the roughly `50Mbps` local ceiling.

Tests:

- Direct Server 4 public IP `137.131.12.149:443/udp`:
  - Local HY2 client timed out during handshake.
  - This path is unusable or the old public IP is no longer a valid entry.
- Temporary HY2 `9443/udp` through the shared NLB:
  - Server 2 cloud-side client connected successfully and reached about the `160Mbps` class to Cloudflare 20MB.
  - Local client timed out during handshake.
  - This suggests the user's local path treats this UDP high port worse than `443/udp`.
- Temporary HY2 `53/udp` through the shared NLB:
  - Local client connected successfully.
  - Cloudflare 50MB was about `33Mbps`, below the current `443/udp` HY2 entry.

Cleanup:

- Removed temporary Server 4 Hysteria services and configs for `53/8443/9443`.
- Removed temporary NLB `53/udp` and `9443/udp` listeners/backend sets.
- Removed temporary NLB subnet and Server 4 NSG UDP rules for `53/8443/9443`.
- Kept only the production `s4-hy2-udp-443` listener/backend.

Conclusion:

- For the current local network, HY2 `443/udp` remains the best tested OCI entry.
- Changing UDP ports inside OCI does not bridge the gap between local results and cloud-side `200Mbps+` results.

### 2026-06-14 Existing AWS Ingress And PMTU Checks

AWS ingress tests:

- Server 1 (`mycodexy.duckdns.org` / `18.118.93.106`) served a temporary 100MB file over an SSH tunnel:
  - Local download: about `42.6Mbps`.
- Server 2 (`mysuby.duckdns.org` / `3.22.185.140`) served a temporary 100MB file over an SSH tunnel:
  - Local download: about `40.0Mbps`.
- Temporary `/tmp/codex-speed-*` files and Python HTTP servers were removed after testing.
- Existing AWS Server 1 / Server 2 are not materially better local ingress points than OCI HY2.

HY2 PMTU test:

- Temporarily changed Server 4 Hysteria `disablePathMTUDiscovery` from `false` to `true`.
- Local Cloudflare 50MB test stayed around `46Mbps`, so this did not improve throughput.
- Restored `disablePathMTUDiscovery: false` and restarted `hysteria-server`.

Conclusion:

- The currently controlled ingress options, including OCI NLB, Cloudflare quick tunnel, and the existing AWS hosts, do not reach the cloud-side `200Mbps+` results from the user's local network.
- A materially faster result likely requires a new nearby ingress / relay with better local access and a strong path to OCI or the target network.

## 2026-06-18 NAT Reassignment And Proxy Recovery

Context:

- Server 4 / code instance was reachable through the Server 3 jump host, but its private IP had changed from the older documented `10.0.0.154` to `10.0.0.112`.
- Several Nginx upstreams and NLB backend sets still referenced `10.0.0.154`, which caused web proxy timeouts and stale proxy node failures.
- The local OCI API config was restored on the workstation so NLB and security-list state could be inspected and updated safely.

Current verified instance identity:

- Server 3:
  - Hostname: `instance-20260613-1403`
  - Private IP: `10.31.0.239`
  - Shared NLB public IP: `132.226.146.175`
  - NAT egress observed from host: `161.153.20.32`
- Server 4 / code:
  - Hostname: `instance-20260604-1123`
  - Current private IP: `10.0.0.112`
  - Previous stale private IP: `10.0.0.154`

Applied fixes:

- Updated Server 3 Nginx `xh-ai.cyou` reverse proxy upstream from stale `10.0.0.154` to current `10.0.0.112`.
- Added `xh-ai.cyou` subscription routes on Server 3 so subscription paths are served directly by the shared subscription files instead of falling through to the web app:
  - `https://xh-ai.cyou/clash`
  - `https://xh-ai.cyou/sub`
  - `https://xh-ai.cyou/subs/_Poi3yXpZERRuSer/clash.yaml`
  - `https://xh-ai.cyou/subs/_Poi3yXpZERRuSer/v2ray.txt`
- Restored Xray on Server 4 and verified it listens on `0.0.0.0:24444/tcp`.
- Updated shared NLB backend `s4-tcp-24444` to `10.0.0.112:24444`.
- Added/verified the Server 4 subnet rule allowing Server 3 subnet `10.31.0.0/16` to reach TCP `24444`.
- Updated shared NLB SSH fallback backend `s4-ssh-22` from stale `10.0.0.154:22` to `10.0.0.112:22`.

Current public entries:

- Server 3 SSH:
  - `132.226.146.175:22 -> 10.31.0.239:22`
- Server 4 SSH fallback:
  - `132.226.146.175:2224 -> 10.0.0.112:22`
- Server 4 Reality:
  - `xh-ai.cyou:24444 -> shared NLB -> 10.0.0.112:24444`
- Server 3 Reality:
  - `dazhou.bond:2053 -> shared NLB / Server 3 -> 10.31.0.239:2053`
- Server 3 MTProto:
  - `132.226.146.175:18453 -> 10.31.0.239:18453`

Current subscription state:

- `https://xh-ai.cyou/clash` and `https://dazhou.bond/clash` both return the same Clash subscription.
- The published Clash subscription currently contains two verified Reality nodes:
  - `server4-reality-24444`
  - `server3-reality-2053`
- Raw node secrets, UUIDs, private keys, and direct encoded subscription links remain intentionally excluded from this repository.

Validation:

- `132.226.146.175:2224` reaches Server 4 and reports hostname `instance-20260604-1123`.
- `132.226.146.175:24444`, `132.226.146.175:2053`, `132.226.146.175:18453`, and `132.226.146.175:443` are reachable from the workstation.
- Temporary Xray client validation from Server 3 returned HTTP `204` through both published nodes:
  - `server4-reality-24444`: about `0.081s`
  - `server3-reality-2053`: about `0.153s`
- Server-side subscription fetch is fast, while workstation-side fetch can vary by several seconds; when proxy protocol tests pass but the local client shows no delay, first refresh or re-import the Clash subscription to clear stale nodes.

Known stale NLB entries:

- Some old backend sets still point to `10.0.0.154` for legacy ports `2083`, `2087`, `2096`, `8443`, `18444`, `18454`, and UDP `443`.
- Server 4 was not listening on those legacy ports during the 2026-06-18 recovery, so they were not republished in the active subscription.
- Do not treat old subscriptions or old port nodes as valid unless those services are explicitly restored on `10.0.0.112` and revalidated with a real client test.

## 2026-06-19 Server 4 NLB Drift Repair And 443 Subscription Restore

Context:

- The user reported that `xh-ai.cyou` had been moved during new-machine recovery and that the proxy nodes no longer matched the earlier working shape.
- Live DNS still resolves `xh-ai.cyou`, `www.xh-ai.cyou`, and `dazhou.bond` to the shared NLB public IP `132.226.146.175`.
- Server 4 is still reachable through the shared NLB SSH fallback and reports hostname `instance-20260604-1123`.
- Server 4 current private IP remains `10.0.0.112`.
- Server 4 current NAT egress observed from the host is `129.146.42.246`; do not assume older NAT egress IPs are stable after route or instance repair.

Applied fixes:

- Rechecked Server 3 Nginx stream and HTTPS reverse proxy. All active `xh-ai.cyou` upstreams now point to `10.0.0.112`.
- Replaced stale shared NLB backend entries that still referenced `10.0.0.154` with `10.0.0.112` for:
  - `2083/tcp`
  - `2087/tcp`
  - `2096/tcp`
  - `8443/tcp`
  - `18444/tcp`
  - `18454/tcp`
  - `443/udp`
- Restored the published Server 4 Reality subscription entry from the high public port shape back to the earlier shared-443 shape:
  - `server4-reality-443`
  - `xh-ai.cyou:443`
  - Reality SNI `www.cloudflare.com`
  - Server 3 Nginx stream routes that SNI to `10.0.0.112:24444`.
- Updated Server 3 public subscription files:
  - `/var/www/proxy-subs/clash.yaml`
  - `/var/www/proxy-subs/v2ray.txt`

Current public subscription state:

- `https://xh-ai.cyou/clash` and `https://dazhou.bond/clash` publish:
  - `server4-reality-443`
  - `server3-reality-2053`
- `https://xh-ai.cyou/sub` and `https://dazhou.bond/sub` publish V2Ray-compatible entries for the same two Reality nodes.

Validation:

- Public subscription fetch:
  - `https://xh-ai.cyou/clash` returned `200`.
  - `https://dazhou.bond/clash` returned `200`.
- Temporary Xray client validation from Server 3 returned HTTP `204`:
  - `server4-reality-443`: about `0.333s`
  - `server3-reality-2053`: about `0.186s`
- NLB backend health after the repair:
  - `s4-tcp-24444`: `OK`, backend `10.0.0.112:24444`
  - `s4-ssh-22`: `OK`, backend `10.0.0.112:22`
  - `s4-hy2-udp-443`: `OK`, backend `10.0.0.112:443`
  - legacy alternate TCP ports and Server 4 TG TCP ports point to `10.0.0.112`, but remain `CRITICAL` because Server 4 is not currently listening on those services.

Important current limitation:

- Server 4 currently listens on Nginx `443/tcp` and Xray `24444/tcp`.
- Server 4 does not currently have active `hysteria-server` or `mtg` services, and it is not listening on `18444/tcp` or `18454/tcp`.
- Do not republish HY2 or Server 4 TG direct entries until those services are explicitly restored and revalidated.

## 2026-06-19 Server 4 TG NLB Backend Repair

Context:

- After restoring the authoritative Server 4 proxy backend to `code / 10.0.0.154`, Server 4 TG links still failed from the public side.
- Live checks showed `code` was healthy locally:
  - `xray` listens on `18444/tcp,udp`.
  - `mtg` listens on `18454/tcp`.
  - Server 3 can reach `10.0.0.154:18444` and `10.0.0.154:18454` over the private network.
- Public checks failed for:
  - `xh-ai.cyou:18444`
  - `xh-ai.cyou:18454`

Root cause:

- Shared NLB backend sets for Server 4 TG still pointed at the stale instance IP `10.0.0.112`.

Applied repair:

- `s4-tcp-18444` now has backend `10.0.0.154:18444`.
- `s4-tcp-18454` now has backend `10.0.0.154:18454`.
- Both backend sets keep source preservation disabled.

Validation:

- NLB backend health:
  - `s4-tcp-18444`: `OK`
  - `s4-tcp-18454`: `OK`
- Public TCP checks:
  - `dazhou.bond:18453`: reachable
  - `dazhou.bond:18443`: reachable
  - `xh-ai.cyou:18454`: reachable
  - `xh-ai.cyou:18444`: reachable
- Local Telegram link file remains structurally correct:
  - `C:\Users\admin\Desktop\file\tg-links.txt`
  - No raw TG secrets are stored in this repository.

## 2026-06-19 Server 4 TG Protocol Simplification

Decision:

- Keep only Server 4 MTProto for Telegram app direct use.
- Remove Server 4 SOCKS because MTProto is Telegram-native and has a smaller purpose-specific exposure surface.

Applied changes:

- Removed the `18444` SOCKS inbound from `code / 10.0.0.154` Xray config and restarted `xray`.
- Removed `18444/tcp` and `18444/udp` from Server 4 firewalld.
- Deleted all backends from shared NLB backend set `s4-tcp-18444`.
- Kept `s4-tcp-18454 -> 10.0.0.154:18454`.
- Updated local Telegram link file:
  - `C:\Users\admin\Desktop\file\tg-links.txt`
  - The `xh-ai.cyou:18444` SOCKS link was removed.
  - The `xh-ai.cyou:18454` MTProto link remains.

Validation:

- `xh-ai.cyou:18454` TCP is reachable.
- `xh-ai.cyou:18444` TCP is not reachable, as expected.
- `s4-tcp-18454` backend health is `OK`.
- `s4-tcp-18444` backend set is empty.

## 2026-06-19 Server 3 TG Protocol Simplification

Decision:

- Match Server 4 behavior: keep only MTProto for Telegram app direct use.
- Remove Server 3 SOCKS.

Applied changes:

- Removed the `18443` SOCKS inbound from Server 3 Xray config and restarted `xray`.
- Removed `18443/tcp` and `18443/udp` from Server 3 firewalld.
- Deleted all backends from shared NLB backend set `bs-18443`.
- Kept `bs-18453 -> 10.31.0.239:18453`.
- Updated local Telegram link file:
  - `C:\Users\admin\Desktop\file\tg-links.txt`
  - The `dazhou.bond:18443` SOCKS link was removed.
  - The `dazhou.bond:18453` MTProto link remains.

Validation:

- `dazhou.bond:18453` TCP is reachable.
- `dazhou.bond:18443` TCP is not reachable, as expected.
- `bs-18453` backend health is `OK`.
- `bs-18443` backend set is empty.

## 2026-06-19 xh-ai Web Log SSE Repair

Symptom:

- The xh-ai page showed an empty "real-time logs" terminal even though the backend service was running.
- Internal backend testing on `code / 10.0.0.154` showed `/api/logs/stream` returned SSE `data:` lines.
- External testing through `https://xh-ai.cyou/api/logs/stream` returned no `data:` lines before the repair.

Root cause:

- The xh-ai public path is layered:
  - Client -> shared NLB `132.226.146.175`
  - Server 3 Nginx stream / HTTPS virtual host
  - Server 3 Nginx reverse proxy to `10.0.0.154`
  - Server 4/code local Nginx -> `127.0.0.1:8000`
- The generic Server 3 xh-ai reverse proxy used `proxy_pass https://10.0.0.154`, which worked for normal pages but did not stream SSE logs reliably through the extra HTTPS proxy layer.

Applied repair:

- Added a precise Server 3 Nginx location for xh-ai logs:
  - `location = /api/logs/stream`
  - `proxy_pass http://10.0.0.154/api/logs/stream`
  - `proxy_buffering off`
  - `proxy_cache off`
  - `proxy_read_timeout 3600s`
  - `proxy_send_timeout 3600s`
  - `gzip off`
  - `X-Accel-Buffering: no`
- The rest of xh-ai traffic still uses the existing generic reverse proxy.
- Nginx backup created on Server 3:
  - `/etc/nginx/conf.d/xh-ai-proxy.conf.bak-sse-20260619-123123`

Validation:

- Internal SSE test through `127.0.0.1:8000/api/logs/stream` returned `data:` lines.
- External SSE test through `https://xh-ai.cyou/api/logs/stream` returned `data:` lines after reload.
- `https://xh-ai.cyou/`, `https://xh-ai.cyou/clash`, and `https://xh-ai.cyou/sub` continued returning `200`.


