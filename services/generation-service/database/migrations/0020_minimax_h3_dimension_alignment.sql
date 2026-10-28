BEGIN;

-- MiniMax H3 conditioning requires width/height to be multiples of 32. The
-- provider rounds request dimensions when the binding declares align.
UPDATE ai.workflow_provider_bindings
SET provider_config = '{"align":32}'::jsonb
WHERE provider_workflow_ref IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1');

COMMIT;
