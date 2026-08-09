BEGIN;

-- The adapter remains provider-neutral at the platform boundary, but can now
-- consume both SaveImage and Video Helper Suite output records.
UPDATE ai.providers
SET capabilities = capabilities || '{"mediaTypes":["image","video"],"modes":["text-to-image","text-to-video"],"storage":"tencent_cos"}'::jsonb
WHERE code = 'comfyui';

WITH inserted_workflow AS (
  INSERT INTO ai.workflows (
    slug, name, description, category, mode, media_type, is_enabled, sort_order
  ) VALUES (
    'comfyui-ltx-video-v1',
    '本机 LTX 2.3 文生视频',
    '通过平台 Worker 调用受控的本机 ComfyUI LTX 2.3 工作流，完成后转存腾讯 COS。',
    'AI 视频',
    'workflow',
    'video',
    false,
    200
  )
  ON CONFLICT (slug) DO UPDATE SET
    mode = EXCLUDED.mode,
    media_type = EXCLUDED.media_type
  RETURNING id
), workflow AS (
  SELECT id FROM inserted_workflow
  UNION ALL
  SELECT id FROM ai.workflows WHERE slug = 'comfyui-ltx-video-v1'
  LIMIT 1
), version AS (
  INSERT INTO ai.workflow_versions (
    workflow_id, version, input_schema, defaults, output_schema, is_active
  )
  SELECT
    workflow.id,
    1,
    '{"type":"object","required":["prompt","width","height","count","durationSeconds"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":256,"maximum":1280},"height":{"type":"integer","minimum":256,"maximum":1280},"count":{"type":"integer","minimum":1,"maximum":1},"durationSeconds":{"type":"integer","enum":[5]}}}'::jsonb,
    '{"width":960,"height":544,"count":1,"duration_seconds":5,"visibility":"private","prompt_visibility":"hidden","credit_cost":5}'::jsonb,
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
  workflow_version_id, provider_id, provider_workflow_ref, provider_model,
  provider_config, priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT
  version.id,
  provider.id,
  'comfyui-ltx-video-v1',
  'ltx-2.3-22b-distilled-1.1-fp8mixed.safetensors',
  '{"fps":24,"cfg":1,"durationSeconds":5}'::jsonb,
  10,
  0,
  3600,
  1,
  true
FROM version
JOIN ai.providers provider ON provider.code = 'comfyui'
ON CONFLICT (workflow_version_id, provider_id) DO UPDATE SET
  provider_workflow_ref = EXCLUDED.provider_workflow_ref,
  provider_model = EXCLUDED.provider_model,
  provider_config = EXCLUDED.provider_config,
  timeout_seconds = EXCLUDED.timeout_seconds,
  max_attempts = EXCLUDED.max_attempts,
  is_enabled = EXCLUDED.is_enabled;

COMMIT;
