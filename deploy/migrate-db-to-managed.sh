#!/usr/bin/env bash
#
# migrate-db-to-managed.sh - dump the current PostgreSQL and restore it into a
# managed PostgreSQL (Neon / Vercel Postgres). Never prints credentials.
#
# Usage:
#   export OLD_DB_URL='postgresql://...'   # current local database
#   export NEW_DB_URL='postgresql://...'   # empty managed database
#   bash deploy/migrate-db-to-managed.sh
#
# Retry on a failed/empty target:
#   CLEAN_TARGET=1 bash deploy/migrate-db-to-managed.sh
#
set -euo pipefail

: "${OLD_DB_URL:?set OLD_DB_URL to the current database URL}"
: "${NEW_DB_URL:?set NEW_DB_URL to the managed database URL}"

# Prisma-generated URLs may include uselibpqcompat, which libpq 16 (pg_dump/psql)
# rejects as an unknown query parameter. Strip it from both URLs before use.
sanitize_url() {
  local value="$1"
  value="$(printf '%s' "$value" | sed 's/[?&]uselibpqcompat=[^&]*//')"
  # If the removed parameter was the first one, restore the ? before remaining params.
  value="$(printf '%s' "$value" | sed 's#\(://[^?]*\)&#\1?#')"
  printf '%s' "$value"
}
OLD_DB_URL="$(sanitize_url "$OLD_DB_URL")"
NEW_DB_URL="$(sanitize_url "$NEW_DB_URL")"

# Long-lived connections across the public internet can be silently dropped by
# middleboxes. Ask libpq to send TCP keepalives so a dead connection fails fast
# instead of hanging forever.
append_conn_param() {
  local url="$1" param="$2"
  case "$url" in
    *"${param%%=*}"=*) printf '%s' "$url" ;;
    *"?"*) printf '%s&%s' "$url" "$param" ;;
    *) printf '%s?%s' "$url" "$param" ;;
  esac
}
OLD_DB_URL="$(append_conn_param "$OLD_DB_URL" "keepalives=1")"
OLD_DB_URL="$(append_conn_param "$OLD_DB_URL" "keepalives_idle=30")"
NEW_DB_URL="$(append_conn_param "$NEW_DB_URL" "keepalives=1")"
NEW_DB_URL="$(append_conn_param "$NEW_DB_URL" "keepalives_idle=30")"

# Avoid hanging forever when a statement is blocked (e.g., by live app
# connections holding locks on the managed database). A blocked statement now
# fails after 2 minutes instead of waiting indefinitely.
export PGOPTIONS="-c lock_timeout=120000 -c statement_timeout=300000"

BACKUP_DIR="${BACKUP_DIR:-/opt/mindfulpenpal/backups}"
mkdir -p "$BACKUP_DIR"
DUMP_FILE="$BACKUP_DIR/mindfulpenpal-before-managed-$(date +%Y%m%d-%H%M%S).dump"

echo "[1/4] dumping current database -> $DUMP_FILE"
pg_dump --no-owner --no-privileges -Fc "$OLD_DB_URL" -f "$DUMP_FILE"

echo "[2/4] restoring into managed database (this may take a few minutes)"
if [ "${CLEAN_TARGET:-0}" = "1" ]; then
  pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error -d "$NEW_DB_URL" "$DUMP_FILE"
else
  pg_restore --no-owner --no-privileges --exit-on-error -d "$NEW_DB_URL" "$DUMP_FILE"
fi

echo "[3/4] verifying"
verify_query() {
  local label="$1" sql="$2" attempt=1
  while [ "$attempt" -le 3 ]; do
    if psql "$NEW_DB_URL" -c "$sql"; then
      return 0
    fi
    echo "[verify] $label: attempt $attempt failed (likely connection issue); retrying in 2s..." >&2
    attempt=$((attempt + 1))
    sleep 2
  done
  echo "[verify] $label: failed after 3 attempts" >&2
  return 1
}
verify_query "users" "SELECT count(*) AS users FROM public.users;"
verify_query "public_tables" "SELECT count(*) AS public_tables FROM information_schema.tables WHERE table_schema='public';"
verify_query "ai_schema" "SELECT schema_name FROM information_schema.schemata WHERE schema_name='ai';"

echo "[4/4] done. dump kept at: $DUMP_FILE"
echo "Next: update Vercel and server DATABASE_URL to the managed URL (see docs/deployment/database-exposure-fix-managed-postgres.md)"
