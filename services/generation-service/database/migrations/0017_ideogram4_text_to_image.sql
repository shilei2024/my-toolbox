BEGIN;

-- Ideogram 4 text-to-image workflow (Work-Fisher graph, platform-simplified):
-- dual-model CFG with the unconditional model, Ideogram4 scheduler (Default
-- preset: steps 20, mu 0, std 1.75), euler_ancestral sampler.
WITH inserted_workflow AS (
  INSERT INTO ai.workflows (
    slug, name, description, category, mode, media_type, is_enabled, sort_order
  ) VALUES (
    'ideogram4-t2i-v1',
    '文生图（Ideogram 4）',
    'Ideogram 4 高质量文生图：擅长版式、文字与写实构图，英文提示词效果最佳。',
    '英文生图',
    'workflow',
    'image',
    true,
    6
  )
  ON CONFLICT (slug) DO UPDATE SET
    name = EXCLUDED.name,
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    mode = EXCLUDED.mode,
    media_type = EXCLUDED.media_type,
    is_enabled = EXCLUDED.is_enabled,
    sort_order = EXCLUDED.sort_order
  RETURNING id
), workflow AS (
  SELECT id FROM inserted_workflow
  UNION ALL
  SELECT id FROM ai.workflows WHERE slug = 'ideogram4-t2i-v1'
  LIMIT 1
), version AS (
  INSERT INTO ai.workflow_versions (
    workflow_id, version, input_schema, defaults, output_schema, is_active
  )
  SELECT
    workflow.id,
    1,
    '{"type":"object","required":["prompt","width","height","count"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":256,"maximum":4096},"height":{"type":"integer","minimum":256,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":1}}}'::jsonb,
    '{"width":1024,"height":1024,"count":1,"visibility":"public","prompt_visibility":"public","credit_cost":2}'::jsonb,
    '{"type":"object","properties":{"images":{"type":"array","minItems":1,"maxItems":1}}}'::jsonb,
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
  'ideogram4-t2i-v1',
  'ideogram4_fp8_scaled.safetensors',
  '{"steps":20,"cfg":2.0,"sampler":"euler_ancestral"}'::jsonb,
  10,
  0,
  1200,
  2,
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
