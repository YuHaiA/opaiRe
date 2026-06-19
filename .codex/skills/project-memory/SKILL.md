---
name: project-memory
description: Durable project memory for opaiRe. Use this skill to recover stable architecture, deployment constraints, operating conventions, and long-lived decisions without depending on old chat sessions.
---

# Project Memory

## Project goal

- `opaiRe` is a registration management system with a single-page web console and a Python backend.
- Core responsibilities include registration workflow control, account inventory, mailbox resource management, cloud credential inventory, proxy/Clash operations, and team account administration.
- The project also includes deployment and server operations for a primary project server and a relay server.

## Current architecture

- Main frontend entry: `index.html`
- Frontend split assets:
  - `static/css/index.css`
  - `static/js/index.js`
- Backend routes: `routers/`
- Shared utilities and integrations: `utils/`
- Runtime data and configs: `data/`
- Tests: `tests/`
- Deployment assets: `deploy/`, `docker-compose.yml`, `docker-compose2.yml`
- Main runtime launcher / app entry behavior is centered around `wfxl_openai_regst.py`

## Stable conventions

- Keep inventory-style pages on fixed-height panels with internal table scrolling instead of page-level overflow.
- Reuse `.data-panel` and `.data-table-scroll` for new table-heavy views.
- Prefer modular changes over stacking more logic into large entry files.
- New or changed functionality should be reflected in `SYSTEM.md`.
- Codex-facing operation docs live under `.codex/docs/`, not root-level `docs/`; keep project source directories focused on application code.
- Test artifacts should stay inside `tests/` or another clearly isolated test directory.
- Do not assume local config equals server runtime config; verify live server state first when debugging Server 1.

## Important decisions

- Web port supports environment configuration via `WEB_PORT` or `PORT`.
- `WEB_PORT_STRICT` exists for fixed-port server deployments where automatic port fallback is not acceptable.
- Clash subscription switching must update the active target instance immediately and keep the visible strategy groups aligned with the selected subscription.
- Clash subscription fetching falls back to direct server connection when configured proxy access is unavailable.
- The proxy settings page updates `config.default_proxy`, and the subscription update path also reads `default_proxy`; when server behavior looks wrong, verify the saved server-side `data/config.yaml` value before assuming the UI failed.
- For Linux single-core Mihomo, runtime problems often come from drift between `data/config.yaml`, `data/mihomo-pool/manual-config.yaml`, and the real listening ports; troubleshooting should compare all three instead of trusting only the panel display.
- Mobile UI behavior has been progressively split out of inline HTML into `static/css/index.css` and `static/js/index.js`; future mobile adjustments should consider all three frontend surfaces together.
- Cloud inventory pagination is handled from frontend-sliced merged data after fetch, avoiding repeated multi-platform aggregation on every page change.
- When `Sub2API` automatic health checking is disabled, replenishment logic still reads the full cloud inventory directly; this path is intentionally used for stock decisions and remains sensitive to timeout-heavy or unstable local network conditions.
- Server 1 Git sync has been restored to the normal repository-driven path: `/home/ubuntu/opaiRe` remains a valid Git worktree, `origin` uses HTTPS, `git fetch` and `git pull --ff-only origin main` work, and `.git/info/exclude` hides the extra `.venv-31113-ssl351/` directory so runtime-only environments do not keep the worktree dirty.
- Server 1 public web traffic currently goes through Nginx to `127.0.0.1:8001`; unlike the lightweight Oracle hosts, this machine is not using the `8000` single-process panel shape as its public upstream.
- Server 1 now serves `/static/` and `/assets/` directly from Nginx with gzip and cache headers instead of proxying those large files through the Python app. When page entry feels slow there, inspect Nginx static delivery before blaming the app process.

## Deployment and server memory

- Local workspace path: `C:\Users\admin\Desktop\opaiRe`
- Server 1:
  - Host: `mycodexy.duckdns.org`
  - User: `ubuntu`
  - Project path: `/home/ubuntu/opaiRe`
- Server 2:
  - Host: `mysuby.duckdns.org`
  - User: `ec2-user`
  - Reverse proxy target: `http://127.0.0.1:8080`
- Server 3:
  - Host/IP: `132.226.99.236`
  - User: `opc`
  - Intended role: lightweight Oracle E2 test / panel server
  - Recommended project path: `/home/opc/opaiRe`
  - Preferred deployment mode: source deployment in a Python 3.11 virtual environment, not Docker
  - Known runtime sizing: about `1GB` RAM with `/swapfile-oci` expanded to `4G`; total swap observed about `4.5GiB`
  - Current lightweight service: `opaire-lite.service`
  - Service binding: `127.0.0.1:8000`
  - Current reverse proxy: `nginx` on host ports `80` and `443`, proxying HTTPS traffic to `http://127.0.0.1:8000`
  - Domain: `dazhou.bond` and `www.dazhou.bond`
  - TLS certificate: Let's Encrypt under `/etc/letsencrypt/live/dazhou.bond/`
  - Renewal timer: `certbot-renew.timer`
  - OS firewalld allows `http` and `https`; public access also requires OCI VCN / security list inbound `80/tcp` and `443/tcp`.
  - Preferred access method: SSH tunnel with `ssh -i C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key -L 8000:127.0.0.1:8000 opc@132.226.99.236`
  - Keep Server 3 conservative: Web panel and light management only; avoid Docker, Watchtower, browser workers, Clash-heavy tasks, and high-concurrency registration.
  - Server 3 updates should be in-place source overlays that preserve remote runtime state, especially `data/data.db`, `data/config.yaml`, `data/mihomo-pool`, `.venv`, and `.codex`.
  - Do not upload local `data/` to Server 3 during normal updates. The remote `data/` directory contains config, license / HWID state, and runtime state.
  - A source overlay on the same Server 3 host should not make the project look like a new machine; deleting or replacing `data/data.db` can cause license / HWID mismatch.
- Server 4:
  - Host/IP: `137.131.12.149`
  - User: `opc`
  - Current project on this host is **not** `opaiRe`; the user states Server 4 is now deployed with the desktop `local-oci` project.
  - Do not assume `/home/opc/opaiRe`, `opaire-lite.service`, `data/config.yaml`, Mihomo layout, or any `opaiRe`-specific runtime path on Server 4 unless re-verified live.
  - Treat Server 4 as out of scope for routine `opaiRe` deployment/sync operations unless the user explicitly asks to inspect or repurpose it.
- Preferred SSH key for both servers: `C:\Users\admin\Desktop\file\sub2.pem`
- Preferred SSH key for Server 3: `C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
- Preferred SSH key for Server 4: `C:\Users\admin\Desktop\file\ssh-key-2026-05-27.key`
- For Server 1, prefer server-side Git update / pull when Git is healthy.
- If server-side HTTPS git fetch fails with TLS termination errors, prefer syncing project files over SSH instead of retrying broken HTTPS fetches.
- When the user says `detect 2`, they mean Server 2 (`mysuby.duckdns.org`).
- When the user says `detect 3`, they mean Server 3 (`132.226.99.236`).
- When the user says `detect 4`, they mean Server 4 (`137.131.12.149`).
- Server 1 runtime troubleshooting should treat these as source of truth first:
  - `/home/ubuntu/opaiRe/data/config.yaml`
  - live systemd service state
  - live listening ports and runtime logs
- If Server 1 shows `22` reachable but SSH fails during banner exchange, treat it as a runtime/host-health problem first, not a Git or local-code problem; check `sshd`, service startup order, system load, disk, and OOM signals from a cloud console if SSH remains unavailable.

## Known issues

- Server-side git over HTTPS may fail with `gnutls_handshake() failed: The TLS connection was non-properly terminated.`
- Local workspace config cannot be treated as authoritative for Server 1 without explicit sync verification.
- `index.html` remains large, so frontend changes should be reviewed carefully for opportunities to keep responsibilities split across static assets.
- `Sub2API` full inventory reads are heavy enough to hit local timeout or DNS-resolution failures even when remote warehouse access otherwise looks normal.

## Open follow-ups

- Continue reducing coupling in large frontend and launcher files when touching adjacent logic.
- Keep local project version aligned with upstream release tags during upstream sync work.
- When mobile UI changes continue, verify the interaction across `index.html`, `static/css/index.css`, and `static/js/index.js` together.
- Keep server cleanup behavior conservative: prefer logs, caches, and Python cache directories; avoid touching live runtime/state directories unless a task explicitly requires it.
- For Server 3 and Server 4, prefer uploading a slim source package or using Git plus a remote venv. Exclude `.git`, local `.venv`, local `data`, `__pycache__`, test artifacts, and heavy runtime data unless explicitly needed.

## Safe cleanup notes

- Only consider archiving or deleting old sessions after durable project facts have been migrated here.
- Do not store secrets, tokens, cookies, or raw logs in project memory.
- Keep durable server / network operation records in `.codex/docs/`; do not scatter runbooks in the public project root.
- `.codex/tmp/` is for temporary binaries, SDK extracts, speed-test files, and probe configs. It can be emptied after the useful result has been summarized into `SYSTEM.md` or `.codex/docs/`.
- Preserve runtime/state directories such as `.git`, `data`, `.venv`, and `.codex` during server sync work unless a task explicitly requires otherwise.
- For project-local cleanup, prefer removing `.codex/tmp/` extracted upstream trees and project-local archive bundles before touching any global Codex session store. Global `~/.codex/archived_sessions` should only be pruned when project ownership of those sessions is clear.
- When cleaning `opaiRe` session history in the Codex app, archive old project-related threads after stable memory has been migrated, and keep the current active thread unarchived unless the user explicitly asks to archive it too.
