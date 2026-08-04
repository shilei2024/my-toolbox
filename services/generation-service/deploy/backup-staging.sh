#!/bin/sh
set -eu

backup_dir="${1:-./deploy/backups}"
mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yaml \
  exec -T postgres sh -ec 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$backup_dir/generation-staging-$timestamp.dump"

echo "backup created: $backup_dir/generation-staging-$timestamp.dump"
