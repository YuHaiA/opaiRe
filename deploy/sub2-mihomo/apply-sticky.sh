#!/usr/bin/env bash
set -euo pipefail
ROOT=/opt/sub2-mihomo
cd "$ROOT"
python3 - <<'PY'
import sys
sys.path.insert(0, '/opt/sub2-mihomo')
import manager
settings = manager.ensure_layout()
# force default selected group path to STICKY after rewrite
print('config rewritten', settings.get('mixed_port'), 'nodes', settings.get('node_count'))
print(manager.reload_core())
# prefer STICKY in PROXY group
try:
    print(manager.select_proxy('STICKY', 'PROXY'))
except Exception as exc:
    print('select warning', exc)
print(manager.status_payload().get('current'), manager.status_payload().get('running'))
PY
