BEGIN;

-- Enforce the mode boundary: `workflow` mode may only route through ComfyUI,
-- and `api` mode may only route through remote provider models. Migration 0007
-- added remote-provider fallback bindings to legacy workflow-mode workflows
-- (jimeng/openai/gemini) before the mode concept existed; with ComfyUI
-- disabled, routing silently fell through to a vendor. Disable those legacy
-- fallbacks so workflow-mode generation fails closed instead of switching
-- providers, and keep API-mode workflows away from ComfyUI.
UPDATE ai.workflow_provider_bindings wb
SET is_enabled = false
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
WHERE wb.workflow_version_id = v.id
  AND w.mode = 'workflow'
  AND wb.provider_id <> (SELECT id FROM ai.providers WHERE code = 'comfyui');

UPDATE ai.workflow_provider_bindings wb
SET is_enabled = false
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
WHERE wb.workflow_version_id = v.id
  AND w.mode = 'api'
  AND wb.provider_id = (SELECT id FROM ai.providers WHERE code = 'comfyui');

COMMIT;
