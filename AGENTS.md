# Project Notes For Codex

## Server Mapping

- Primary deployment server for this project:
  - Hostname: `mycodexy.duckdns.org`
  - Current resolved IP when last checked: `18.118.93.106`
  - SSH login user: `ubuntu`
  - Remote project path: `/home/ubuntu/opaiRe`

## SSH Key Location

- Use this SSH private key for connecting to the deployment server:
  - `C:\Users\admin\Desktop\file\sub2.pem`
- Do **not** use `tg.pem` for this server unless the user explicitly says the target changed.

## Proven SSH Command

- Server login command:
  - `ssh -i C:\Users\admin\Desktop\file\sub2.pem ubuntu@mycodexy.duckdns.org`

## Deployment Preference

- If the user asks to sync or deploy this project to the server, prefer:
  1. Connect with `sub2.pem`
  2. Target `/home/ubuntu/opaiRe`
  3. Preserve remote runtime/state directories when appropriate:
     - `.git`
     - `data`
     - `.venv`
     - `.codex`
- When server-side `git fetch` is broken, prefer local-to-server file sync over repeated HTTPS git retries.

## Remote Git TLS Issue

- Current known issue on the server:
  - Running git against remote `origin` over HTTPS may fail with:
  - `gnutls_handshake() failed: The TLS connection was non-properly terminated.`
- Current working workaround:
  - Sync project files from local machine to `/home/ubuntu/opaiRe` over SSH using `sub2.pem`.
- Better long-term fix:
  - Configure a GitHub-capable SSH key on the server
  - Switch remote from HTTPS to SSH, for example:
  - `git remote set-url origin git@github.com:YuHaiA/opaiRe.git`
- Do not assume this long-term fix is already configured unless verified on the server.

## Data File Drops

- If the user asks to upload local `wen*` files from Downloads to the server, place them into:
  - `/home/ubuntu/opaiRe/data/`

## Local Context

- Local workspace path:
  - `C:\Users\admin\Desktop\opaiRe`
