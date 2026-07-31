#!/usr/bin/env bash
# Register host Mihomo as Sub2API proxy and bind accounts (Server1-style shared sticky egress).
set -euo pipefail
DEPLOY_DIR=${DEPLOY_DIR:-/home/ec2-user/sub2api-deploy}
PROXY_NAME=${PROXY_NAME:-host-mihomo-sticky}
PROXY_HOST=${PROXY_HOST:-172.20.0.1}
PROXY_PORT=${PROXY_PORT:-7890}
PROXY_PROTO=${PROXY_PROTO:-http}

cd "$DEPLOY_DIR"
set -a
# shellcheck disable=SC1091
source .env
set +a

echo "[1/4] ensure mihomo listening for docker"
curl -fsS -m 8 -x "http://${PROXY_HOST}:${PROXY_PORT}" -o /dev/null -w "docker_proxy=%{http_code}\n" https://www.gstatic.com/generate_204

echo "[2/4] upsert proxy row"
PROXY_ID=$(docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" sub2api-postgres \
  psql -U "${POSTGRES_USER:-sub2api}" -d "${POSTGRES_DB:-sub2api}" -v ON_ERROR_STOP=1 -Atc \
  "WITH existing AS (
      SELECT id FROM proxies
      WHERE deleted_at IS NULL AND host='${PROXY_HOST}' AND port=${PROXY_PORT} AND protocol='${PROXY_PROTO}'
      ORDER BY id LIMIT 1
   ), updated AS (
      UPDATE proxies p
      SET name='${PROXY_NAME}', status='active', fallback_mode='none', updated_at=now()
      FROM existing e
      WHERE p.id=e.id
      RETURNING p.id
   ), inserted AS (
      INSERT INTO proxies (name, protocol, host, port, status, fallback_mode)
      SELECT '${PROXY_NAME}', '${PROXY_PROTO}', '${PROXY_HOST}', ${PROXY_PORT}, 'active', 'none'
      WHERE NOT EXISTS (SELECT 1 FROM existing)
      RETURNING id
   )
   SELECT id FROM updated
   UNION ALL
   SELECT id FROM inserted
   LIMIT 1;")
echo "proxy_id=${PROXY_ID}"
if [ -z "${PROXY_ID}" ]; then
  echo "failed to create/find proxy" >&2
  exit 1
fi

echo "[3/4] bind accounts without proxy"
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" sub2api-postgres \
  psql -U "${POSTGRES_USER:-sub2api}" -d "${POSTGRES_DB:-sub2api}" -v ON_ERROR_STOP=1 -c \
  "UPDATE accounts
   SET proxy_id = ${PROXY_ID}, updated_at = now()
   WHERE deleted_at IS NULL AND proxy_id IS NULL;"

docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" sub2api-postgres \
  psql -U "${POSTGRES_USER:-sub2api}" -d "${POSTGRES_DB:-sub2api}" -c \
  "SELECT COUNT(*) AS total,
          COUNT(*) FILTER (WHERE proxy_id = ${PROXY_ID}) AS bound_sticky,
          COUNT(*) FILTER (WHERE proxy_id IS NULL) AS still_no_proxy
   FROM accounts WHERE deleted_at IS NULL;"

echo "[4/4] optional UPDATE_PROXY_URL + restart app to refresh cache"
python3 - <<PY
from pathlib import Path
host = "${PROXY_HOST}"
port = "${PROXY_PORT}"
p = Path('.env')
lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
out = []
seen = False
for line in lines:
    if line.startswith('UPDATE_PROXY_URL='):
        if seen:
            continue
        seen = True
        out.append(f'UPDATE_PROXY_URL=http://{host}:{port}')
    else:
        out.append(line)
if not seen:
    out.append(f'UPDATE_PROXY_URL=http://{host}:{port}')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('UPDATE_PROXY_URL=http://%s:%s' % (host, port))
PY
if command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d sub2api
elif docker compose version >/dev/null 2>&1; then
  docker compose up -d sub2api
else
  docker restart sub2api
fi
for i in 1 2 3 4 5 6 7 8 9 10; do
  st=$(docker inspect sub2api --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' 2>/dev/null || true)
  [ "$st" = "healthy" ] && break
  sleep 2
done
curl -fsS -m 8 http://127.0.0.1:8080/health || true
echo
echo WIRE_OK proxy=http://${PROXY_HOST}:${PROXY_PORT} id=${PROXY_ID}
