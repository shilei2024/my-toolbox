BEGIN;

-- Creation catalog mode: 'workflow' is the curated style workflow; 'api' is a
-- direct provider API model. The browser workbench separates the two groups,
-- while the Generation API keeps one backward-compatible catalog contract.
ALTER TABLE ai.workflows
  ADD COLUMN mode varchar(16) NOT NULL DEFAULT 'workflow'
  CHECK (mode IN ('workflow', 'api'));

-- New generations default to public gallery visibility and public prompt
-- display. Existing curated workflows follow the same defaults; users can
-- still opt into private/hidden on the workbench.
UPDATE ai.workflow_versions v
SET defaults = jsonb_set(
  jsonb_set(COALESCE(v.defaults, '{}'::jsonb), '{visibility}', '"public"'::jsonb),
  '{prompt_visibility}', '"public"'::jsonb
)
FROM ai.workflows w
WHERE v.workflow_id = w.id;

-- API-mode workflows: one per enabled provider model. Providers stay disabled
-- by default, so these entries remain hidden from the creation catalog until
-- an admin enables the provider (listWorkflows fails closed). Each API
-- workflow is bound to exactly one provider model; the queue/worker pipeline
-- is unchanged because the job still references a workflow version.
WITH candidates AS (
  SELECT
    p.id AS provider_id,
    m.id AS model_id,
    p.code AS provider_code,
    m.model_code,
    m.display_name,
    m.credit_cost,
    ('api-' || p.code || '-' || regexp_replace(lower(m.model_code), '[^a-z0-9-]+', '-', 'g')) AS slug
  FROM ai.provider_models m
  JOIN ai.providers p ON p.id = m.provider_id
  WHERE m.is_enabled
), inserted AS (
  INSERT INTO ai.workflows (slug, name, description, category, mode, is_enabled, sort_order)
  SELECT
    c.slug,
    c.display_name,
    p.display_name || ' 官方 API 模型，直连生成图片；模型与参数由平台统一管理。',
    'API 模型',
    'api',
    true,
    CASE c.provider_code
      WHEN 'jimeng' THEN 130
      WHEN 'openai' THEN 110
      WHEN 'gemini' THEN 120
      ELSE 100
    END
  FROM candidates c
  JOIN ai.providers p ON p.id = c.provider_id
  ON CONFLICT (slug) DO NOTHING
  RETURNING id, slug
), versions AS (
  INSERT INTO ai.workflow_versions (workflow_id, version, input_schema, defaults, output_schema, is_active)
  SELECT
    inserted.id,
    1,
    CASE candidates.provider_code
      WHEN 'openai' THEN '{"type":"object","required":["prompt","width","height","count"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":512,"maximum":3840},"height":{"type":"integer","minimum":512,"maximum":3840},"count":{"type":"integer","minimum":1,"maximum":1}}}'::jsonb
      ELSE '{"type":"object","required":["prompt","width","height","count"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":512,"maximum":4096},"height":{"type":"integer","minimum":512,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":1}}}'::jsonb
    END,
    jsonb_build_object(
      'width', 1024,
      'height', 1024,
      'count', 1,
      'visibility', 'public',
      'prompt_visibility', 'public',
      'credit_cost', COALESCE(candidates.credit_cost, 1)
    ),
    '{"type":"object","properties":{"images":{"type":"array","minItems":1,"maxItems":1}}}'::jsonb,
    true
  FROM inserted
  JOIN candidates ON candidates.slug = inserted.slug
  RETURNING id, workflow_id
)
INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_model_id, provider_workflow_ref,
  provider_model, provider_config, priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT
  versions.id,
  candidates.provider_id,
  candidates.model_id,
  NULL,
  candidates.model_code,
  '{}'::jsonb,
  10,
  0,
  600,
  2,
  true
FROM versions
JOIN inserted ON inserted.id = versions.workflow_id
JOIN candidates ON candidates.slug = inserted.slug
ON CONFLICT (workflow_version_id, provider_id) DO NOTHING;

COMMIT;
