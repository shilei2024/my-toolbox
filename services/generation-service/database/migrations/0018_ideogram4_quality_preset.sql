BEGIN;

-- Switch ideogram4-t2i-v1 from the Default preset (20 steps / std 1.75) to
-- the Work-Fisher workflow's Quality preset (48 steps / mu 0 / std 1.5) and
-- match its default resolution (1376x768, 16-aligned). Provider bindings now
-- control steps/cfg/mu/std/sampler; the workflow template reads {{mu}}/{{std}}.
UPDATE ai.workflow_provider_bindings
SET provider_config = '{"steps":48,"cfg":2.0,"mu":0.0,"std":1.5,"sampler":"euler_ancestral"}'::jsonb
WHERE provider_workflow_ref = 'ideogram4-t2i-v1';

UPDATE ai.workflow_versions v
SET defaults = jsonb_set(
  jsonb_set(
    jsonb_set(v.defaults, '{width}', '1376'),
    '{height}', '768'
  ),
  '{credit_cost}', '3'
)
FROM ai.workflows w
WHERE w.id = v.workflow_id AND w.slug = 'ideogram4-t2i-v1' AND v.is_active;

COMMIT;
