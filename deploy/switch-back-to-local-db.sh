#!/usr/bin/env bash
#
# Switch the main site (Flask) and Generation Service back to the on-server
# PostgreSQL, then close public port 5432.
#
# Run on the Tencent server as root:
#   sudo bash deploy/switch-back-to-local-db.sh
#
# The script never prints database passwords. It backs up both env files
# before changing anything, reuses the previous local password when it can
# find it, and otherwise resets the `mavis` role to a fresh random value.
set -euo pipefail

BACKUP_SUFFIX="$(date +%Y%m%d-%H%M%S)"
PROD_ENV=/etc/mindfulpenpal.production.env
MAIN_ENV=/opt/mytoolbox/.env
DOCKER_IP="$(ip -4 addr show docker0 2>/dev/null | awk '/inet /{print $2}' | cut -d/ -f1 || true)"
DOCKER_IP="${DOCKER_IP:-172.17.0.1}"

echo "[1/9] backup environment files"
sudo cp "$PROD_ENV" "$PROD_ENV.bak-$BACKUP_SUFFIX"
if [ -f "$MAIN_ENV" ]; then
  sudo cp "$MAIN_ENV" "$MAIN_ENV.bak-$BACKUP_SUFFIX"
fi

echo "[2/9] ensure PostgreSQL is running and has data"
sudo systemctl enable postgresql >/dev/null 2>&1 || true
sudo systemctl start postgresql
USERS="$(sudo -u postgres psql -d mindfulpenpal -tAc "SELECT count(*) FROM public.users")"
AI_SCHEMA="$(sudo -u postgres psql -d mindfulpenpal -tAc "SELECT schema_name FROM information_schema.schemata WHERE schema_name='ai'")"
echo "users=$USERS ai_schema=$AI_SCHEMA"
if [ "${USERS:-0}" = "0" ]; then
  echo "ERROR: local database has no users; aborting before any switch" >&2
  exit 1
fi

echo "[3/9] prepare local DB password"
OLD_URL="$(grep -E '^export OLD_DB_URL=' /opt/mindfulpenpal/.migrate-env 2>/dev/null | head -1 | cut -d= -f2- | tr -d "'\"" || true)"
LOCAL_PW=""
case "$OLD_URL" in
  *@127.0.0.1:*|*@localhost:*|*@host.docker.internal:*)
    LOCAL_PW="$(printf '%s' "$OLD_URL" | sed -E 's#^[^:]*://[^:]+:([^@]+)@.*#\1#')"
    ;;
esac
if [ -z "$LOCAL_PW" ]; then
  LOCAL_PW="$(openssl rand -hex 24)"
  # psql -c does not interpolate variables; pipe the statement via stdin so
  # :'pw' is quoted safely without exposing the password in argv.
  sudo -u postgres psql -v ON_ERROR_STOP=1 -v pw="$LOCAL_PW" <<'SQL'
ALTER USER mavis WITH PASSWORD :'pw';
SQL
  echo "mavis password reset to a fresh random value (stored only in env files)"
fi

echo "[4/9] point both apps at the local database"
sudo env LOCAL_PW="$LOCAL_PW" python3 - <<'PY'
import os

pw = os.environ["LOCAL_PW"]
targets = [
    ("/etc/mindfulpenpal.production.env",
     f"postgresql://mavis:{pw}@host.docker.internal:5432/mindfulpenpal?sslmode=require",
     0o600),
    ("/opt/mytoolbox/.env",
     f"postgresql://mavis:{pw}@127.0.0.1:5432/mindfulpenpal",
     0o640),
]
for path, url, mode in targets:
    if not os.path.exists(path):
        continue
    lines = []
    replaced = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("DATABASE_URL="):
                lines.append(f"DATABASE_URL={url}\n")
                replaced = True
            else:
                lines.append(line)
    if not replaced:
        lines.append(f"DATABASE_URL={url}\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    os.chmod(path, mode)
PY

echo "[5/9] run database migrations (idempotent, skips already-applied)"
cd /opt/mindfulpenpal
docker compose --env-file "$PROD_ENV" \
  -f deploy/docker-compose.production.yml --profile migration run --rm migrate

echo "[6/9] restart generation services and Caddy"
docker compose --env-file "$PROD_ENV" \
  -f deploy/docker-compose.production.yml --profile production up -d \
  --force-recreate api dispatcher worker deletion-worker caddy

echo "[7/9] restart main site (systemd)"
if systemctl list-unit-files --type=service | grep -q '^mytoolbox.service'; then
  # Containers (Caddy/cloudflared) reach the host Flask via host.docker.internal,
  # which resolves to the docker bridge gateway, not 127.0.0.1. Listen on
  # 0.0.0.0 instead; public access is blocked by the security group and ufw.
  sudo sed -i 's/-b 127\.0\.0\.1:8000/-b 0.0.0.0:8000/' /etc/systemd/system/mytoolbox.service
  sudo systemctl daemon-reload
  sudo systemctl restart mytoolbox
fi

echo "[8/9] close public 5432 (host firewall + PostgreSQL listen addresses)"
sudo ufw delete allow 5432/tcp >/dev/null 2>&1 || true
# Allow Docker containers (172.16.0.0/12) to reach the main site on 8000 only.
sudo ufw allow from 172.16.0.0/12 to any port 8000 proto tcp >/dev/null 2>&1 || true
PG_CONF="$(sudo -u postgres psql -tAc 'SHOW config_file')"
echo "listen_addresses = '127.0.0.1,${DOCKER_IP}'" | sudo tee -a "$PG_CONF" >/dev/null
sudo systemctl restart postgresql

echo "[9/9] verification"
sleep 5
echo "--- main site (host) ---"
curl -s http://127.0.0.1:8000/healthz || true
echo
echo "--- generation api (container) ---"
docker compose --env-file "$PROD_ENV" -f deploy/docker-compose.production.yml \
  exec -T api node -e "fetch('http://127.0.0.1:3101/health').then(r=>console.log(r.status, r.ok)).catch(e=>console.log('ERR', e.message))" || true
echo "--- main site listener (must be 0.0.0.0:8000) ---"
sudo ss -tlnp | grep 8000 || echo "no 8000 listener"
echo "--- port 5432 listeners (must be loopback/docker only) ---"
sudo ss -tlnp | grep 5432 || echo "no 5432 listener"

echo
echo "Done. Remaining manual step: delete the TCP 5432 inbound rule in the"
echo "Tencent Cloud security group for 101.43.122.182."
