BEGIN;

-- Enrich the creation-catalog descriptions so every workflow card explains
-- what it does and when to prefer it (English prompts for SDXL workflows,
-- Chinese-first for the Qwen workflow).
UPDATE ai.workflows SET
  description = '写实人像：自然光影、皮肤质感与情绪捕捉。英文提示词效果最佳；中文创作请选择「中文生图」。',
  category = '人物'
WHERE slug = 'portrait-v1';

UPDATE ai.workflows SET
  description = '建筑与空间概念：材质、光线与环境氛围探索。英文提示词效果最佳。',
  category = '空间'
WHERE slug = 'architecture-v1';

UPDATE ai.workflows SET
  description = '菜品与食材的商业摄影风格。英文提示词效果最佳。',
  category = '静物'
WHERE slug = 'food-v1';

UPDATE ai.workflows SET
  description = '动漫插画：清晰线条与富有表现力的角色画面。英文提示词效果最佳。',
  category = '插画'
WHERE slug = 'anime-v1';

UPDATE ai.workflows SET
  description = 'LTX 2.3 文生视频（默认 5 秒）：平台 Worker 调用受控 ComfyUI 生成并转存腾讯 COS。'
WHERE slug = 'comfyui-ltx-video-v1';

-- Qwen-Image text-to-image workflow: strong Chinese prompt adherence.
WITH inserted_workflow AS (
  INSERT INTO ai.workflows (
    slug, name, description, category, mode, media_type, is_enabled, sort_order
  ) VALUES (
    'qwen-image-v1',
    '中文生图（Qwen）',
    'Qwen-Image 模型：中文提示词理解准确，适合中文写实、插画与创意海报创作。',
    '中文生图',
    'workflow',
    'image',
    true,
    5
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
  SELECT id FROM ai.workflows WHERE slug = 'qwen-image-v1'
  LIMIT 1
), version AS (
  INSERT INTO ai.workflow_versions (
    workflow_id, version, input_schema, defaults, output_schema, is_active
  )
  SELECT
    workflow.id,
    1,
    '{"type":"object","required":["prompt","width","height","count"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":64,"maximum":4096},"height":{"type":"integer","minimum":64,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":4}}}'::jsonb,
    '{"width":768,"height":768,"count":1,"visibility":"public","prompt_visibility":"public","credit_cost":2}'::jsonb,
    '{"type":"object","properties":{"images":{"type":"array","minItems":1,"maxItems":4}}}'::jsonb,
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
  'qwen-image-v1',
  E'Qwen\\Qwen-Image-Edit-2509_fp8_e4m3fn.safetensors',
  '{"steps":20,"cfg":2.5,"sampler":"euler","scheduler":"simple"}'::jsonb,
  10,
  0,
  900,
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
