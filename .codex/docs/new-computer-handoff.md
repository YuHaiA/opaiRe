# New Computer Handoff

Snapshot date: 2026-06-14

Purpose: give a fresh development machine enough non-sensitive context to continue this project from GitHub without copying local runtime data.

## What This Repository Contains

- Source code for the opaiRe web console and Python backend.
- Frontend entry points and assets:
  - `index.html`
  - `static/js/app.js`
  - `static/css/`
- Backend routes and utilities:
  - `routers/`
  - `utils/`
  - `luckmail/`
- Deployment and runtime templates:
  - `Dockerfile`
  - `docker-compose.yml`
  - `docker-compose2.yml`
  - `config.example.yaml`
- Project memory and operation notes:
  - `SYSTEM.md`
  - `.codex/docs/server3-rebuild-notes.md`
  - `.codex/docs/oci-nlb-nat-runbook.md`

## What Is Intentionally Not Uploaded

- `data/`
- `config.yaml`
- SQLite databases
- Logs
- License / HWID files
- API keys, tokens, cookies, passwords, raw proxy links, and local runtime credentials
- Local virtual environments and Python cache folders

If a new computer needs to run the project, create its own local `data/config.yaml` from `config.example.yaml` or copy runtime data through a private channel only when explicitly intended.

## Current Code State

- The local working tree is being pushed to `origin/main` on `git@github.com:YuHaiA/opaiRe.git`.
- The effective app version in the current code path is aligned to `v16.1.1`.
- The default example registration mode is `email`.
- Recent code changes include:
  - registration pipeline updates in `utils/auth_pipeline/`
  - Image2API integration cleanup in `utils/integrations/image2api_client.py`
  - SMS first-signup helper functions for 5SIM, HeroSMS, and SmsBower
  - frontend setting display updates in `index.html` and `static/js/app.js`
  - updated compiled `auth_core` artifacts for supported platforms

## Runtime Shape

- Main local entry:
  - `python wfxl_openai_regst.py`
- Default web URL:
  - `http://127.0.0.1:8000`
- Install dependencies:
  - `pip install -r requirements.txt`
- Runtime config should live under `data/config.yaml`.
- Local runtime data should remain outside Git.

## Server Notes

The durable operation record is in `SYSTEM.md` and `.codex/docs/`. Those files describe the important server and network work at a high level, including:

- Server 3 rebuild notes.
- OCI NLB inbound plus NAT egress runbook.
- Server 3 / Server 4 proxy and subscription routing decisions.
- Known lightweight deployment constraints.

The docs intentionally avoid storing raw secrets. Treat any host paths, IP addresses, domains, and operational notes as infrastructure context, not as a replacement for private credentials.

## First Steps On A New Computer

1. Clone the repository.
2. Install the expected Python version for the target OS.
3. Create a virtual environment.
4. Run `pip install -r requirements.txt`.
5. Create `data/config.yaml` from `config.example.yaml`.
6. Fill private credentials locally.
7. Start the app with `python wfxl_openai_regst.py`.
8. Read `SYSTEM.md` before making changes, because it records the recent architecture and operations history.

## Git Hygiene

- Keep `data/` ignored.
- Do not commit runtime databases, account inventory, local configs, proxy subscriptions, logs, or credential files.
- When changing behavior, update `SYSTEM.md` in the same commit.
- Put future operational notes under `.codex/docs/` instead of scattering them in the project root.


