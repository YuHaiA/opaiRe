# OCI NLB Inbound + NAT Egress Runbook

Snapshot time: 2026-06-13

Purpose: record the no-delete/no-rebuild method used on Server 3 to avoid the Oracle free AMD public 50Mbps path, and define how to safely replicate it to Server 4 without touching the application runtime.

No secrets, raw node links, private keys, tokens, cookies, or OCI credential values are stored in this file.

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
