#!/bin/sh
set -eu

if [ "${APP_ENV:-}" != "production" ]; then
  echo "refusing migration: APP_ENV must be production" >&2
  exit 1
fi

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

# Fail fast instead of hanging forever when a stale transaction holds DDL locks.
export PGOPTIONS="${PGOPTIONS:-} -c lock_timeout=30000"

# psql/libpq rejects Vercel Prisma pooler query parameters (uselibpqcompat /
# pgbouncer); rebuild the URL without them so separators stay valid.
DB_BASE="${DATABASE_URL%%\?*}"
DB_QUERY="${DATABASE_URL#*\?}"
if [ "$DB_QUERY" = "$DATABASE_URL" ]; then DB_QUERY=""; fi
KEPT=""
if [ -n "$DB_QUERY" ]; then
  IFS='&'
  for part in $DB_QUERY; do
    case "$part" in
      uselibpqcompat=*|pgbouncer=*) ;;
      *) KEPT="${KEPT}${KEPT:+&}${part}" ;;
    esac
  done
  unset IFS
fi
if [ -n "$KEPT" ]; then DB_URL="${DB_BASE}?${KEPT}"; else DB_URL="$DB_BASE"; fi

psql "$DB_URL" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in "${MIGRATIONS_DIR}"/*.sql; do
  filename="$(basename "$migration")"
  case "$filename" in
    *"'"*) echo "invalid migration filename" >&2; exit 1 ;;
  esac
  applied="$(psql "$DB_URL" -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM public.schema_migrations WHERE filename = '$filename'")"
  if [ "$applied" = "1" ]; then
    echo "migration already applied: $filename"
    continue
  fi

  echo "applying migration: $filename"
  psql "$DB_URL" -v ON_ERROR_STOP=1 --single-transaction --file "$migration"
  psql "$DB_URL" -v ON_ERROR_STOP=1 -c "INSERT INTO public.schema_migrations (filename) VALUES ('$filename')"
done
