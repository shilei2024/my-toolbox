BEGIN;

CREATE SCHEMA IF NOT EXISTS ai;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TYPE ai.provider_status AS ENUM ('active', 'degraded', 'disabled');
CREATE TYPE ai.job_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled');
CREATE TYPE ai.attempt_status AS ENUM ('pending', 'running', 'succeeded', 'failed', 'cancelled');
CREATE TYPE ai.image_visibility AS ENUM ('public', 'private');
CREATE TYPE ai.prompt_visibility AS ENUM ('public', 'hidden');
CREATE TYPE ai.moderation_status AS ENUM ('pending', 'manual_review', 'approved', 'rejected');
CREATE TYPE ai.asset_variant AS ENUM ('original', 'preview', 'thumbnail');

CREATE FUNCTION ai.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TABLE ai.providers (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  code varchar(64) NOT NULL UNIQUE,
  display_name varchar(128) NOT NULL,
  adapter_type varchar(64) NOT NULL,
  status ai.provider_status NOT NULL DEFAULT 'disabled',
  priority integer NOT NULL DEFAULT 100 CHECK (priority >= 0),
  base_url text,
  secret_ref varchar(255),
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(capabilities) = 'object'),
  config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(config) = 'object'),
  cost_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(cost_config) = 'object'),
  consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
  last_health_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai.workflows (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug varchar(128) NOT NULL UNIQUE,
  name varchar(128) NOT NULL,
  description text NOT NULL DEFAULT '',
  category varchar(64) NOT NULL,
  cover_image_url text,
  is_enabled boolean NOT NULL DEFAULT false,
  sort_order integer NOT NULL DEFAULT 100,
  created_by_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai.workflow_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_id uuid NOT NULL REFERENCES ai.workflows(id) ON DELETE CASCADE,
  version integer NOT NULL CHECK (version > 0),
  input_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(input_schema) = 'object'),
  defaults jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(defaults) = 'object'),
  output_schema jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(output_schema) = 'object'),
  is_active boolean NOT NULL DEFAULT false,
  created_by_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workflow_id, version)
);

CREATE UNIQUE INDEX uq_ai_workflow_one_active_version
  ON ai.workflow_versions (workflow_id) WHERE is_active;

CREATE TABLE ai.workflow_provider_bindings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow_version_id uuid NOT NULL REFERENCES ai.workflow_versions(id) ON DELETE CASCADE,
  provider_id uuid NOT NULL REFERENCES ai.providers(id) ON DELETE RESTRICT,
  provider_workflow_ref varchar(255),
  provider_model varchar(128),
  provider_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provider_config) = 'object'),
  priority integer NOT NULL DEFAULT 100 CHECK (priority >= 0),
  estimated_cost numeric(14, 6) CHECK (estimated_cost IS NULL OR estimated_cost >= 0),
  timeout_seconds integer NOT NULL DEFAULT 300 CHECK (timeout_seconds BETWEEN 1 AND 7200),
  max_attempts integer NOT NULL DEFAULT 2 CHECK (max_attempts BETWEEN 1 AND 10),
  is_enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (workflow_version_id, provider_id)
);

CREATE TABLE ai.generation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  workflow_version_id uuid NOT NULL REFERENCES ai.workflow_versions(id) ON DELETE RESTRICT,
  selected_provider_id uuid REFERENCES ai.providers(id) ON DELETE SET NULL,
  idempotency_key varchar(128),
  status ai.job_status NOT NULL DEFAULT 'pending',
  prompt text NOT NULL CHECK (char_length(prompt) BETWEEN 1 AND 8000),
  negative_prompt text NOT NULL DEFAULT '' CHECK (char_length(negative_prompt) <= 8000),
  input_params jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(input_params) = 'object'),
  requested_width integer NOT NULL CHECK (requested_width BETWEEN 64 AND 8192),
  requested_height integer NOT NULL CHECK (requested_height BETWEEN 64 AND 8192),
  requested_count smallint NOT NULL DEFAULT 1 CHECK (requested_count BETWEEN 1 AND 8),
  visibility ai.image_visibility NOT NULL DEFAULT 'public',
  prompt_visibility ai.prompt_visibility NOT NULL DEFAULT 'public',
  moderation_status ai.moderation_status NOT NULL DEFAULT 'pending',
  priority integer NOT NULL DEFAULT 100 CHECK (priority >= 0),
  credits_reserved numeric(14, 4) NOT NULL DEFAULT 0 CHECK (credits_reserved >= 0),
  credits_charged numeric(14, 4) NOT NULL DEFAULT 0 CHECK (credits_charged >= 0),
  estimated_cost numeric(14, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
  actual_cost numeric(14, 6) NOT NULL DEFAULT 0 CHECK (actual_cost >= 0),
  error_code varchar(64),
  error_message text,
  cancel_requested_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_ai_job_user_idempotency
  ON ai.generation_jobs (user_id, idempotency_key)
  WHERE user_id IS NOT NULL AND idempotency_key IS NOT NULL;
CREATE INDEX ix_ai_jobs_user_created ON ai.generation_jobs (user_id, created_at DESC);
CREATE INDEX ix_ai_jobs_status_created ON ai.generation_jobs (status, created_at);

CREATE TABLE ai.generation_attempts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES ai.generation_jobs(id) ON DELETE CASCADE,
  provider_id uuid NOT NULL REFERENCES ai.providers(id) ON DELETE RESTRICT,
  binding_id uuid REFERENCES ai.workflow_provider_bindings(id) ON DELETE SET NULL,
  attempt_no smallint NOT NULL CHECK (attempt_no > 0),
  status ai.attempt_status NOT NULL DEFAULT 'pending',
  external_request_id varchar(255),
  provider_model varchar(128),
  request_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(request_snapshot) = 'object'),
  response_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(response_snapshot) = 'object'),
  error_class varchar(64),
  error_code varchar(128),
  error_message text,
  retryable boolean NOT NULL DEFAULT false,
  estimated_cost numeric(14, 6) NOT NULL DEFAULT 0 CHECK (estimated_cost >= 0),
  actual_cost numeric(14, 6) NOT NULL DEFAULT 0 CHECK (actual_cost >= 0),
  queued_at timestamptz NOT NULL DEFAULT now(),
  started_at timestamptz,
  finished_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, attempt_no)
);

CREATE INDEX ix_ai_attempts_provider_created ON ai.generation_attempts (provider_id, created_at DESC);
CREATE INDEX ix_ai_attempts_external_request ON ai.generation_attempts (provider_id, external_request_id)
  WHERE external_request_id IS NOT NULL;

CREATE TABLE ai.images (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid REFERENCES ai.generation_jobs(id) ON DELETE SET NULL,
  successful_attempt_id uuid REFERENCES ai.generation_attempts(id) ON DELETE SET NULL,
  creator_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  provider_id uuid REFERENCES ai.providers(id) ON DELETE SET NULL,
  workflow_version_id uuid REFERENCES ai.workflow_versions(id) ON DELETE SET NULL,
  slug varchar(255) NOT NULL UNIQUE,
  title varchar(180) NOT NULL DEFAULT '',
  description text NOT NULL DEFAULT '',
  prompt text NOT NULL,
  negative_prompt text NOT NULL DEFAULT '',
  provider_code_snapshot varchar(64) NOT NULL,
  model_snapshot varchar(128),
  workflow_name_snapshot varchar(128) NOT NULL,
  seed bigint,
  width integer NOT NULL CHECK (width BETWEEN 1 AND 32768),
  height integer NOT NULL CHECK (height BETWEEN 1 AND 32768),
  sampler varchar(128),
  cfg numeric(8, 3),
  steps integer CHECK (steps IS NULL OR steps BETWEEN 1 AND 1000),
  generation_ms integer CHECK (generation_ms IS NULL OR generation_ms >= 0),
  visibility ai.image_visibility NOT NULL DEFAULT 'public',
  prompt_visibility ai.prompt_visibility NOT NULL DEFAULT 'public',
  moderation_status ai.moderation_status NOT NULL DEFAULT 'pending',
  like_count integer NOT NULL DEFAULT 0 CHECK (like_count >= 0),
  favorite_count integer NOT NULL DEFAULT 0 CHECK (favorite_count >= 0),
  comment_count integer NOT NULL DEFAULT 0 CHECK (comment_count >= 0),
  download_count integer NOT NULL DEFAULT 0 CHECK (download_count >= 0),
  published_at timestamptz,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ai_gallery_feed
  ON ai.images (published_at DESC, id)
  WHERE visibility = 'public' AND moderation_status = 'approved' AND deleted_at IS NULL;
CREATE INDEX ix_ai_images_creator_created ON ai.images (creator_user_id, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE TABLE ai.image_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  variant ai.asset_variant NOT NULL,
  storage_provider varchar(32) NOT NULL DEFAULT 'tencent_cos',
  bucket varchar(128) NOT NULL,
  region varchar(64) NOT NULL,
  object_key varchar(1024) NOT NULL,
  public_url text,
  mime_type varchar(100) NOT NULL,
  byte_size bigint NOT NULL CHECK (byte_size > 0),
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  sha256 char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (storage_provider, bucket, object_key),
  UNIQUE (image_id, variant)
);

CREATE TABLE ai.tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug varchar(80) NOT NULL UNIQUE,
  name varchar(80) NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ai.image_tags (
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES ai.tags(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (image_id, tag_id)
);
CREATE INDEX ix_ai_image_tags_tag ON ai.image_tags (tag_id, image_id);

CREATE TABLE ai.likes (
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (image_id, user_id)
);
CREATE INDEX ix_ai_likes_user_created ON ai.likes (user_id, created_at DESC);

CREATE TABLE ai.favorites (
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  user_id integer NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (image_id, user_id)
);
CREATE INDEX ix_ai_favorites_user_created ON ai.favorites (user_id, created_at DESC);

CREATE TABLE ai.comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  parent_id uuid REFERENCES ai.comments(id) ON DELETE CASCADE,
  body text NOT NULL CHECK (char_length(body) BETWEEN 1 AND 2000),
  moderation_status ai.moderation_status NOT NULL DEFAULT 'pending',
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_comments_image_created ON ai.comments (image_id, created_at)
  WHERE deleted_at IS NULL;

CREATE TABLE ai.download_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  image_id uuid NOT NULL REFERENCES ai.images(id) ON DELETE CASCADE,
  user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  asset_id uuid REFERENCES ai.image_assets(id) ON DELETE SET NULL,
  ip_hash char(64),
  user_agent_hash char(64),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_downloads_image_created ON ai.download_logs (image_id, created_at DESC);
CREATE INDEX ix_ai_downloads_user_created ON ai.download_logs (user_id, created_at DESC)
  WHERE user_id IS NOT NULL;

CREATE TABLE ai.moderation_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid REFERENCES ai.generation_jobs(id) ON DELETE CASCADE,
  image_id uuid REFERENCES ai.images(id) ON DELETE CASCADE,
  stage varchar(32) NOT NULL CHECK (stage IN ('prompt', 'image', 'manual')),
  provider varchar(64),
  decision ai.moderation_status NOT NULL,
  reason_codes jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reason_codes) = 'array'),
  details jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
  reviewer_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (job_id IS NOT NULL OR image_id IS NOT NULL)
);
CREATE INDEX ix_ai_moderation_job ON ai.moderation_events (job_id, created_at) WHERE job_id IS NOT NULL;
CREATE INDEX ix_ai_moderation_image ON ai.moderation_events (image_id, created_at) WHERE image_id IS NOT NULL;

CREATE TABLE ai.audit_logs (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id uuid,
  actor_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  actor_type varchar(32) NOT NULL CHECK (actor_type IN ('user', 'admin', 'service', 'worker', 'system')),
  action varchar(128) NOT NULL,
  resource_type varchar(64) NOT NULL,
  resource_id varchar(128),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  ip_hash char(64),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_audit_resource ON ai.audit_logs (resource_type, resource_id, created_at DESC);
CREATE INDEX ix_ai_audit_actor ON ai.audit_logs (actor_user_id, created_at DESC)
  WHERE actor_user_id IS NOT NULL;

CREATE TABLE ai.system_settings (
  key varchar(128) PRIMARY KEY,
  value jsonb NOT NULL,
  description text NOT NULL DEFAULT '',
  secret_ref varchar(255),
  updated_by_user_id integer REFERENCES public.users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (jsonb_typeof(value) IN ('object', 'array', 'string', 'number', 'boolean'))
);

CREATE TABLE ai.outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  aggregate_type varchar(64) NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type varchar(128) NOT NULL,
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  available_at timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ix_ai_outbox_pending ON ai.outbox_events (available_at, created_at)
  WHERE published_at IS NULL;

CREATE TRIGGER trg_ai_providers_updated BEFORE UPDATE ON ai.providers
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_workflows_updated BEFORE UPDATE ON ai.workflows
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_bindings_updated BEFORE UPDATE ON ai.workflow_provider_bindings
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_jobs_updated BEFORE UPDATE ON ai.generation_jobs
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_images_updated BEFORE UPDATE ON ai.images
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_comments_updated BEFORE UPDATE ON ai.comments
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();
CREATE TRIGGER trg_ai_settings_updated BEFORE UPDATE ON ai.system_settings
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();

COMMIT;
