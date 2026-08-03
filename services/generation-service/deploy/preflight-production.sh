#!/bin/sh
set -eu

env_file="${1:-/etc/mindfulpenpal.production.env}"
if [ ! -f "$env_file" ]; then
  echo "preflight failed: production environment file does not exist" >&2
  exit 1
fi

get_value() {
  key="$1"
  line="$(grep -m 1 "^${key}=" "$env_file" || true)"
  printf '%s' "${line#*=}"
}

require_value() {
  key="$1"
  value="$(get_value "$key")"
  if [ -z "$value" ]; then
    echo "preflight failed: missing $key" >&2
    exit 1
  fi
  case "$value" in
    *replace_*|*example.com*|*example.invalid*)
      echo "preflight failed: $key still contains a placeholder" >&2
      exit 1
      ;;
  esac
}

for key in \
  APP_ENV PRODUCTION_RELEASE_APPROVED GENERATION_IMAGE POSTGRES_MIGRATION_IMAGE CADDY_IMAGE \
  GENERATION_API_DOMAIN DATABASE_URL REDIS_URL GALLERY_CURSOR_SECRET GALLERY_INTERNAL_HMAC_SECRET \
  GALLERY_ASSET_HOSTS COS_SECRET_ID COS_SECRET_KEY COS_BUCKET COS_REGION BILLING_PUBLIC_BASE_URL; do
  require_value "$key"
done

if [ "$(get_value APP_ENV)" != "production" ]; then
  echo "preflight failed: APP_ENV must be production" >&2
  exit 1
fi
if [ "$(get_value PRODUCTION_RELEASE_APPROVED)" != "true" ]; then
  echo "preflight failed: explicit production release approval is absent" >&2
  exit 1
fi
if [ "$(get_value GENERATION_ALLOW_MOCK_PROVIDER)" != "false" ]; then
  echo "preflight failed: mock provider must be disabled" >&2
  exit 1
fi

for key in GENERATION_IMAGE POSTGRES_MIGRATION_IMAGE CADDY_IMAGE; do
  value="$(get_value "$key")"
  if ! printf '%s' "$value" | grep -Eq '@sha256:[[:xdigit:]]{64}$'; then
    echo "preflight failed: $key must use an immutable sha256 digest" >&2
    exit 1
  fi
done

case "$(get_value DATABASE_URL)" in
  postgres://*|postgresql://*) ;;
  *) echo "preflight failed: DATABASE_URL must be a PostgreSQL URL" >&2; exit 1 ;;
esac
case "$(get_value REDIS_URL)" in
  rediss://*) ;;
  *) echo "preflight failed: production REDIS_URL must use TLS (rediss://)" >&2; exit 1 ;;
esac

if [ -z "$(get_value COMFYUI_BASE_URL)" ] && \
   [ -z "$(get_value OPENAI_API_KEY)" ] && \
   [ -z "$(get_value GEMINI_API_KEY)" ] && \
   [ -z "$(get_value JIMENG_API_KEY)" ]; then
  echo "preflight failed: configure at least one real generation provider" >&2
  exit 1
fi

if [ -n "$(get_value COMFYUI_BASE_URL)" ]; then
  for key in COMFYUI_DEFAULT_MODEL COMFYUI_WORKFLOW_DIR COMFYUI_DOWNLOAD_DIR; do
    require_value "$key"
  done
fi
for provider in OPENAI GEMINI JIMENG; do
  if [ -n "$(get_value "${provider}_API_KEY")" ]; then
    require_value "${provider}_BASE_URL"
  fi
done

if command -v stat >/dev/null 2>&1; then
  permissions="$(stat -c '%a' "$env_file" 2>/dev/null || true)"
  if [ -n "$permissions" ] && [ "$permissions" != "600" ] && [ "$permissions" != "400" ]; then
    echo "preflight failed: environment file permissions must be 600 or 400" >&2
    exit 1
  fi
fi

echo "production preflight passed; no secret values were printed"
