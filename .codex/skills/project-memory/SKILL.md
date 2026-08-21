---
name: project-memory
description: Durable project memory for opaiRe. Use this skill to recover stable architecture, deployment constraints, operating conventions, and long-lived decisions without depending on old chat sessions.
---

# Project Memory

## Project goal

- `opaiRe` is a registration management system with a single-page web console and a Python backend.
- Core responsibilities include registration workflow control, mailbox / OTP resources, account inventory, cloud warehouse maintenance, proxy / Mihomo operations, notifications, and team / admin operations.
- The repository also carries private Codex operation notes for the user's deployment and proxy infrastructure.

## Current architecture

- Main launcher: `wfxl_openai_regst.py`.
- Frontend entry: `index.html`.
- Frontend assets: `static/css/`, `static/js/`.
- Backend routes: `routers/`.
- Shared utilities and integrations: `utils/`.
- Runtime data and configs: `data/`.
- Tests: `tests/`.
- Deployment assets: `deploy/`, `Dockerfile`, `docker-compose*.yml`.
- Project maintenance summary: `SYSTEM.md`.
- Private Codex operation records: `.codex/docs/`.

## Stable conventions

- Keep durable architecture and server facts in `SYSTEM.md`; keep it short and factual.
- Keep Codex-facing operation records under `.codex/docs/`, not public root-level docs.
- `.codex/docs/` should retain useful records but remove long command dumps, repeated experiments, and obsolete runbook bloat.
- Never store secrets, raw proxy links, private keys, API keys, tokens, cookies, raw subscriptions, or database contents in docs or memory.
- Prefer modular changes over stacking logic into large entry files.
- Test artifacts belong in `tests/`; temporary operation files belong in `.codex/tmp/` and should be cleaned after their result is summarized.
- Do not assume local config equals server runtime config; verify live server state first.

## Important decisions

- Web port supports `WEB_PORT` / `PORT`; `WEB_PORT_STRICT` exists for fixed-port deployments.
- Proxy settings and subscription behavior depend on saved server-side config; verify remote `data/config.yaml` before blaming UI state.
- Linux single-core Mihomo issues often come from drift between `data/config.yaml`, `data/mihomo-pool/manual-config.yaml`, and real listening ports.
- Mobile UI changes should account for `index.html`, `static/css/`, and `static/js/` together.
- Cloud inventory pagination is frontend-sliced after merged fetch to avoid repeated multi-platform aggregation.
- Server-side git over HTTPS may fail with `gnutls_handshake()`; if so, prefer SSH/file sync rather than repeated HTTPS retries.
- The upstream GitHub default branch was reset to a license-only `master` history on 2026-08-21. Do not merge it into opaiRe; absorb verified release tags instead.
- When syncing to remote Git, include project `.codex` files when they contain durable project docs or skills; do not ignore them by habit.
- A registration `batch_id` must not suppress ordinary mail-domain fallback when domain runtime control is disabled. Only skip fallback when runtime control is enabled and a worker truly lacks a preallocated domain.
- Concurrent Grok registration workers need distinct physical egress IPs. Multiple local ports mapped to the same upstream node do not reduce Grok/Castle IP risk.
- Recycle the shared Grok browser after the configured job count or idle timeout, and shut the browser pool down when a task stops. Closing only per-job browser contexts is insufficient on memory-constrained hosts.
- For restart-tolerant deployments, keep authentication tokens signed by a persisted local secret and let Nginx serve the page shell/static assets directly while the Python backend restarts.

## Deployment and server memory

- Local workspace: `C:\Users\admin\Desktop\opaiRe`.
- Server 1:
  - Public web domain: `https://kaikj.bond/`.
  - SSH/source host: `18.118.93.106` (`mycodexy.duckdns.org` is the legacy direct hostname).
  - User: `ubuntu`.
  - Project path: `/home/ubuntu/opaiRe`.
  - SSH key: `C:\Users\yu\Desktop\file\sub2.pem`.
- Server 2:
  - Host: `mysuby.duckdns.org`.
  - User: `ec2-user`.
  - Typical shape: Nginx `80/443` to Docker app on `127.0.0.1:8080`.
  - SSH key: `C:\Users\admin\Desktop\file\sub2.pem`.
- Server 3:
  - OCI instance: `instance-20260613-1403`.
  - Public entry: shared NLB `132.226.146.175`.
  - Private IP: `10.31.0.239`.
  - Domains: `dazhou.bond`, `www.dazhou.bond`.
  - User: `opc`.
  - Project path: `/home/opc/opaiRe`.
  - Preferred deployment: lightweight source deployment, not Docker by default.
  - Preserve remote `data/`, `.venv`, `.codex`, and runtime state.
- Server 4:
  - Current authoritative proxy backend: OCI instance `code`.
  - Private IP: `10.0.0.154`.
  - Public entry: shared NLB `132.226.146.175` via Server 3 / NLB routing.
  - Domains: `xh-ai.cyou`, `www.xh-ai.cyou`.
  - User: `opc` via Server 3 ProxyCommand.
  - SSH key: `C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`.
  - Do not use `instance-20260604-1123 / 10.0.0.112` as Server 4 proxy backend unless explicitly reverified and migrated.

## Current proxy / Telegram facts

- `dazhou.bond`, `www.dazhou.bond`, `xh-ai.cyou`, and `www.xh-ai.cyou` resolve to shared NLB `132.226.146.175`.
- Server 3 publishes shared subscription files from `/var/www/proxy-subs/`.
- Server 4 Reality 443 path: client connects `xh-ai.cyou:443`, Reality SNI `www.cloudflare.com`, Server 3 stream forwards to `10.0.0.154:24444`.
- Telegram should remain independent from local Mihomo and third-party nodes when requested.
- Local TG links file: `C:\Users\admin\Desktop\file\tg-links.txt`; it contains secrets/passwords and must not be pasted into chat/docs.
- Current TG direct entries: MTProto on `18453/18454`, authenticated SOCKS5 on `18443/18444`.
- 2026-06-20 local SOCKS5 tests exceeded `3MB/s`; MTProto stayed around `900KB/s`, so Telegram App should test SOCKS5 first.

## Service 6 resource controls

- Service 6 is a memory-constrained opaiRe deployment; verify live capacity before changing its limits.
- The deployed opaiRe systemd guard uses `MemoryHigh=1.34G`, `MemoryMax=1.53G`, and `MemorySwapMax=1G` so browser OOM pressure does not freeze SSH, Nginx, or Mihomo.
- Its Grok browser pool is capped at two workers, idles out after 60 seconds, and recycles after four jobs.
- The Mihomo core and panel have separate memory ceilings of `384M` and `192M`; their proxy/controller ports should remain loopback-only behind Nginx authentication.
- Service 6's Nginx serves the homepage/static assets directly and proxies backend APIs, reducing the impact of a backend restart.

## Known issues

- Local-to-OCI Phoenix / NLB routing can be the real speed bottleneck; cloud-to-cloud tests may not reflect local Telegram speed.
- `index.html` remains large; keep future frontend changes scoped and consider extracting adjacent logic.
- Sub2API full inventory reads can be timeout-heavy on unstable local networks.
- Old docs and memory may contain outdated Server 4 references; prefer `SYSTEM.md` and `.codex/docs/oracle-proxy-current.md`.
- Camoufox `WebExtensions` memory growth has previously triggered a host-wide OOM on Service 6. Preserve browser recycling and systemd memory controls when absorbing upstream or redeploying.

## Open follow-ups

- Keep reducing coupling in large frontend and launcher files when touching adjacent logic.
- Keep local project version aligned with upstream release tags during upstream sync work.
- Current aligned upstream release is `v18.1.4` (`7abf465`).
- Keep `.codex/docs/` concise but not empty: retain current-state and history summaries, remove junk.
- For session cleanup, first migrate durable facts into this project memory and `SYSTEM.md`, then archive only old project-related sessions.

## Safe cleanup notes

- Preserve runtime/state directories such as `.git`, `data`, `.venv`, and `.codex` during server sync unless explicitly instructed otherwise.
- `.codex/tmp/` can be emptied after useful results are summarized.
- Do not delete global Codex sessions or archived sessions unless they are clearly project-related and durable facts have been migrated.
- Prefer archiving old Codex project threads over deleting them from global history.
