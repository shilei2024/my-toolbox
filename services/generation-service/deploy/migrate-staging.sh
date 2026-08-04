#!/bin/sh
set -eu

psql "$DATABASE_URL" -v ON_ERROR_STOP=1 <<'SQL'
CREATE TABLE IF NOT EXISTS public.schema_migrations (
  filename text PRIMARY KEY,
  applied_at timestamptz NOT NULL DEFAULT now()
);
SQL

for migration in /migrations/*.sql; do
  filename="$(basename "$migration")"
  applied="$(psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -tAc "SELECT 1 FROM public.schema_migrations WHERE filename = '$filename'")"
  if [ "$applied" = "1" ]; then
    echo "migration already applied: $filename"
    continue
  fi

  echo "applying migration: $filename"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction --file "$migration"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "INSERT INTO public.schema_migrations (filename) VALUES ('$filename')"
done

