#!/usr/bin/env bash
#
# migrate-db-to-managed.sh - dump the current PostgreSQL and restore it into a
# managed PostgreSQL (Neon / Vercel Postgres). Never prints credentials.
#
# Usage:
#   export OLD_DB_URL='postgresql://...'   # current local database
#   export NEW_DB_URL='postgresql://...'   # empty managed database
#   sh deploy/migrate-db-to-managed.sh
#
# Retry on a failed/empty target:
#   CLEAN_TARGET=1 sh deploy/migrate-db-to-managed.sh
#
set -euo pipefail

: "${OLD_DB_URL:?set OLD_DB_URL to the current database URL}"
: "${NEW_DB_URL:?set NEW_DB_URL to the managed database URL}"

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
psql "$NEW_DB_URL" -c "SELECT count(*) AS users FROM public.users;"
psql "$NEW_DB_URL" -c "SELECT count(*) AS public_tables FROM information_schema.tables WHERE table_schema='public';"
psql "$NEW_DB_URL" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name='ai';"

echo "[4/4] done. dump kept at: $DUMP_FILE"
echo "Next: update Vercel and server DATABASE_URL to the managed URL (see docs/deployment/database-exposure-fix-managed-postgres.md)"
