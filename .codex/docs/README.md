# Codex Project Operation Docs

This directory stores local Codex-facing operation records for `opaiRe`.

These files are intentionally kept under `.codex/docs/` instead of the public project root so the application code stays cleaner and operational notes remain separated from source code.

## Index

- `2026-06-19-fix-summary.md`
  - Current Oracle proxy/domain authority table.
  - Server 3 / Server 4 proxy backend repair notes.
  - `xh-ai.cyou` Reality subscription and TG simplification notes.
- `oci-nlb-nat-runbook.md`
  - OCI shared NLB + NAT routing runbook.
  - Current Server 3 / Server 4 backend mapping.
  - Reality, MTProto, and NLB backend maintenance notes.
- `server3-rebuild-notes.md`
  - Server 3 rebuild checklist and runtime shape.
  - Nginx, Xray, MTG, TLS, firewall, SELinux, and opaiRe service notes.
- `new-computer-handoff.md`
  - Local workspace handoff for a new computer.
  - Source/data boundaries and Git hygiene notes.

## Rules

- Do not store secrets, raw proxy links, private keys, tokens, cookies, database dumps, or raw subscription URLs here.
- Put temporary scripts, downloaded binaries, SDK extracts, and speed-test artifacts under `.codex/tmp/` and clean them after use.
- Keep durable facts in these docs and summarize high-impact changes in `SYSTEM.md`.

