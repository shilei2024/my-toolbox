BEGIN;

-- M1 publishes stable, provider-agnostic workflows. Providers remain disabled
-- until staging/production credentials and health checks have been verified.
INSERT INTO ai.providers (code, display_name, adapter_type, status, priority, capabilities)
VALUES
  ('comfyui', 'ComfyUI', 'comfyui', 'disabled', 10, '{"modes":["text-to-image"],"storage":"tencent_cos"}'::jsonb),
  ('mock', 'Preview Mock Provider', 'mock', 'disabled', 999, '{"modes":["text-to-image"],"non_production_only":true}'::jsonb)
ON CONFLICT (code) DO NOTHING;

INSERT INTO ai.workflows (slug, name, description, category, is_enabled, sort_order)
VALUES
  ('portrait-v1', '质感人像', '自然光影与细腻人物表现。', '人物', true, 10),
  ('architecture-v1', '建筑概念', '空间、材质与环境氛围探索。', '空间', true, 20),
  ('food-v1', '食物摄影', '适合菜品与食材视觉表达。', '静物', true, 30),
  ('anime-v1', '动漫插画', '清晰线条与富有表现力的角色画面。', '插画', true, 40)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO ai.workflow_versions (workflow_id, version, input_schema, defaults, output_schema, is_active)
SELECT w.id, 1,
  '{"type":"object","required":["prompt","width","height","count"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":64,"maximum":4096},"height":{"type":"integer","minimum":64,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":4}}}'::jsonb,
  jsonb_build_object('width', 1024, 'height', 1024, 'count', 1, 'visibility', 'private', 'credit_cost', 1),
  '{"type":"object","properties":{"images":{"type":"array","minItems":1,"maxItems":4}}}'::jsonb,
  true
FROM ai.workflows w
WHERE w.slug IN ('portrait-v1', 'architecture-v1', 'food-v1', 'anime-v1')
ON CONFLICT (workflow_id, version) DO NOTHING;

INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_workflow_ref, provider_model, provider_config,
  priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT v.id, p.id,
  CASE w.slug
    WHEN 'portrait-v1' THEN 'portrait-v1'
    WHEN 'architecture-v1' THEN 'architecture-v1'
    WHEN 'food-v1' THEN 'food-v1'
    ELSE 'anime-v1'
  END,
  NULL, '{}'::jsonb, 10, 0, 600, 2, true
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
JOIN ai.providers p ON p.code = 'comfyui'
WHERE v.is_active AND w.slug IN ('portrait-v1', 'architecture-v1', 'food-v1', 'anime-v1')
ON CONFLICT (workflow_version_id, provider_id) DO NOTHING;

INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_workflow_ref, provider_model, provider_config,
  priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT v.id, p.id, w.slug, 'mock-v1', '{}'::jsonb, 999, 0, 30, 1, true
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
JOIN ai.providers p ON p.code = 'mock'
WHERE v.is_active AND w.slug IN ('portrait-v1', 'architecture-v1', 'food-v1', 'anime-v1')
ON CONFLICT (workflow_version_id, provider_id) DO NOTHING;

COMMIT;
