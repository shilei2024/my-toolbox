#!/bin/sh
set -eu

if [ "${APP_ENV:-}" != "production" ]; then
  echo "refusing migration: APP_ENV must be production" >&2
  exit 1
fi

MIGRATIONS_DIR="${MIGRATIONS_DIR:-/migrations}"

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
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
  applied="$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM public.schema_migrations WHERE filename = '$filename'")"
  if [ "$applied" = "1" ]; then
    echo "migration already applied: $filename"
    continue
  fi

  echo "applying migration: $filename"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction --file "$migration"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "INSERT INTO public.schema_migrations (filename) VALUES ('$filename')"
done
