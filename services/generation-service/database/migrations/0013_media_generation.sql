BEGIN;

ALTER TABLE ai.workflows
  ADD COLUMN media_type varchar(16) NOT NULL DEFAULT 'image'
  CHECK (media_type IN ('image', 'video'));

-- Non-image outputs remain attached to the durable generation job. Images
-- keep their existing Gallery projection in ai.images/ai.image_assets.
CREATE TABLE ai.generation_assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES ai.generation_jobs(id) ON DELETE CASCADE,
  successful_attempt_id uuid REFERENCES ai.generation_attempts(id) ON DELETE SET NULL,
  media_type varchar(16) NOT NULL CHECK (media_type IN ('video')),
  position smallint NOT NULL CHECK (position >= 0),
  storage_provider varchar(32) NOT NULL,
  bucket varchar(128) NOT NULL,
  region varchar(64) NOT NULL,
  object_key varchar(1024) NOT NULL,
  asset_url text NOT NULL,
  mime_type varchar(100) NOT NULL CHECK (mime_type IN ('video/mp4', 'video/webm', 'video/quicktime')),
  byte_size bigint NOT NULL CHECK (byte_size > 0),
  width integer NOT NULL CHECK (width > 0),
  height integer NOT NULL CHECK (height > 0),
  duration_seconds numeric(8, 3) NOT NULL CHECK (duration_seconds > 0 AND duration_seconds <= 300),
  sha256 char(64) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, position),
  UNIQUE (storage_provider, bucket, object_key)
);
CREATE INDEX ix_ai_generation_assets_job ON ai.generation_assets (job_id, position);

INSERT INTO ai.providers (code, display_name, adapter_type, status, priority, capabilities)
VALUES (
  'ark-video',
  '火山方舟视频生成',
  'volcengine_ark_video',
  'disabled',
  60,
  '{"mediaTypes":["video"],"modes":["text-to-video"],"storage":"tencent_cos"}'::jsonb
)
ON CONFLICT (code) DO NOTHING;

INSERT INTO ai.provider_models (
  provider_id, model_code, display_name, capabilities, cost_config,
  is_enabled, is_default, tier, credit_cost
)
SELECT
  p.id,
  'doubao-seedance-2-0-260128',
  'Seedance 2.0 (260128)',
  '{"mediaType":"video","modes":["text-to-video"],"durations":[5,10],"maxOutputs":1,"supportsSeed":true}'::jsonb,
  '{"billing":"provider-usage","reviewBeforeEnable":true}'::jsonb,
  false,
  true,
  'member',
  20.0000
FROM ai.providers p
WHERE p.code = 'ark-video'
ON CONFLICT (provider_id, model_code) DO NOTHING;

WITH inserted_workflow AS (
  INSERT INTO ai.workflows (
    slug, name, description, category, mode, media_type, is_enabled, sort_order
  )
  VALUES (
    'api-ark-video-doubao-seedance-2-0-260128',
    'Seedance 2.0 视频',
    '火山方舟官方 API 文生视频；模型、时长、成本与参数由平台统一管理。',
    'AI 视频',
    'api',
    'video',
    false,
    210
  )
  ON CONFLICT (slug) DO UPDATE SET media_type = EXCLUDED.media_type
  RETURNING id
), workflow AS (
  SELECT id FROM inserted_workflow
  UNION ALL
  SELECT id FROM ai.workflows WHERE slug = 'api-ark-video-doubao-seedance-2-0-260128'
  LIMIT 1
), version AS (
  INSERT INTO ai.workflow_versions (
    workflow_id, version, input_schema, defaults, output_schema, is_active
  )
  SELECT
    workflow.id,
    1,
    '{"type":"object","required":["prompt","width","height","count","durationSeconds"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":256,"maximum":4096},"height":{"type":"integer","minimum":256,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":1},"durationSeconds":{"type":"integer","enum":[5,10]}}}'::jsonb,
    '{"width":1280,"height":720,"count":1,"duration_seconds":5,"visibility":"private","prompt_visibility":"hidden","credit_cost":20}'::jsonb,
    '{"type":"object","properties":{"videos":{"type":"array","minItems":1,"maxItems":1}}}'::jsonb,
    true
  FROM workflow
  ON CONFLICT (workflow_id, version) DO UPDATE SET
    input_schema = EXCLUDED.input_schema,
    defaults = EXCLUDED.defaults,
    output_schema = EXCLUDED.output_schema,
    is_active = EXCLUDED.is_active
  RETURNING id
)
INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_model_id, provider_model,
  provider_config, priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT
  version.id,
  p.id,
  m.id,
  m.model_code,
  '{"durationSeconds":5,"resolution":"720p","watermark":false,"generateAudio":false}'::jsonb,
  10,
  0,
  1800,
  1,
  true
FROM version
JOIN ai.providers p ON p.code = 'ark-video'
JOIN ai.provider_models m ON m.provider_id = p.id AND m.model_code = 'doubao-seedance-2-0-260128'
ON CONFLICT (workflow_version_id, provider_id) DO UPDATE SET
  provider_model_id = EXCLUDED.provider_model_id,
  provider_model = EXCLUDED.provider_model,
  provider_config = EXCLUDED.provider_config,
  timeout_seconds = EXCLUDED.timeout_seconds,
  max_attempts = EXCLUDED.max_attempts;

COMMIT;
