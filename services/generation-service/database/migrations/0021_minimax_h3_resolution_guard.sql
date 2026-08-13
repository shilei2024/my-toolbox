BEGIN;

-- H3 在消费级显卡上高分辨率会超长时间运行：只开放 480p/720p 档位（32 对齐由
-- provider align=32 保证），并显式确认 30 分钟 binding 超时。
UPDATE ai.workflow_versions v
SET defaults = jsonb_set(
  v.defaults,
  '{videoResolutions}',
  '[{"key":"480p","label":"480p","height":480},{"key":"720p","label":"720p 高清","height":704}]'::jsonb
)
FROM ai.workflows w
WHERE w.id = v.workflow_id AND w.slug IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1') AND v.is_active;

UPDATE ai.workflow_provider_bindings
SET timeout_seconds = 1800
WHERE provider_workflow_ref IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1');

COMMIT;
