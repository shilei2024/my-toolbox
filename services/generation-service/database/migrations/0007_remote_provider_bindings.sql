BEGIN;

-- M1.1: make the Phase 9 remote providers operational without hand-written SQL.
-- Provider rows remain disabled by default (0004); the admin console toggles
-- status/priority. Each active workflow gets one binding per remote provider,
-- using the provider's default seeded model.
INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_model_id, provider_workflow_ref, provider_model,
  provider_config, priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT v.id, p.id, m.id, NULL, NULL, '{}'::jsonb, seed.priority, 0, 600, 2, true
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
CROSS JOIN (VALUES
  ('jimeng', 20),
  ('openai', 30),
  ('gemini', 40)
) AS seed(provider_code, priority)
JOIN ai.providers p ON p.code = seed.provider_code
JOIN ai.provider_models m ON m.provider_id = p.id AND m.is_default AND m.is_enabled
WHERE v.is_active AND w.slug IN ('portrait-v1', 'architecture-v1', 'food-v1', 'anime-v1')
ON CONFLICT (workflow_version_id, provider_id) DO NOTHING;

COMMIT;
