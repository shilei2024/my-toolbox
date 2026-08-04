BEGIN;

CREATE TABLE ai.provider_models (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider_id uuid NOT NULL REFERENCES ai.providers(id) ON DELETE CASCADE,
  model_code varchar(128) NOT NULL,
  display_name varchar(128) NOT NULL,
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(capabilities) = 'object'),
  cost_config jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(cost_config) = 'object'),
  is_enabled boolean NOT NULL DEFAULT true,
  is_default boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (provider_id, model_code),
  UNIQUE (provider_id, id)
);

CREATE UNIQUE INDEX uq_ai_provider_one_default_model
  ON ai.provider_models (provider_id) WHERE is_default AND is_enabled;
CREATE INDEX ix_ai_provider_models_enabled
  ON ai.provider_models (provider_id, model_code) WHERE is_enabled;

ALTER TABLE ai.workflow_provider_bindings
  ADD COLUMN provider_model_id uuid;

ALTER TABLE ai.workflow_provider_bindings
  ADD CONSTRAINT fk_ai_binding_provider_model
  FOREIGN KEY (provider_id, provider_model_id)
  REFERENCES ai.provider_models(provider_id, id)
  ON DELETE RESTRICT;

CREATE TRIGGER trg_ai_provider_models_updated BEFORE UPDATE ON ai.provider_models
  FOR EACH ROW EXECUTE FUNCTION ai.touch_updated_at();

INSERT INTO ai.providers (code, display_name, adapter_type, status, priority, capabilities)
VALUES
  ('openai', 'OpenAI Images', 'openai_images', 'disabled', 40,
    '{"modes":["text-to-image"],"storage":"tencent_cos"}'::jsonb),
  ('gemini', 'Google Gemini Image', 'gemini_image', 'disabled', 50,
    '{"modes":["text-to-image"],"storage":"tencent_cos"}'::jsonb),
  ('jimeng', '即梦 / Seedream', 'volcengine_seedream', 'disabled', 30,
    '{"modes":["text-to-image"],"storage":"tencent_cos"}'::jsonb)
ON CONFLICT (code) DO NOTHING;

INSERT INTO ai.provider_models (provider_id, model_code, display_name, capabilities, cost_config, is_default)
SELECT p.id, seed.model_code, seed.display_name, seed.capabilities, seed.cost_config, true
FROM (
  VALUES
    ('openai', 'gpt-image-2-2026-04-21', 'GPT Image 2 (2026-04-21)',
      '{"maxOutputs":1,"supportsSeed":false}'::jsonb,
      '{"billing":"provider-usage"}'::jsonb),
    ('gemini', 'gemini-3.1-flash-image', 'Gemini 3.1 Flash Image',
      '{"maxOutputs":1,"supportsSeed":false}'::jsonb,
      '{"billing":"provider-usage"}'::jsonb),
    ('jimeng', 'doubao-seedream-4-5-251128', 'Seedream 4.5 (251128)',
      '{"maxOutputs":1,"supportsSeed":true}'::jsonb,
      '{"billing":"provider-usage"}'::jsonb)
) AS seed(provider_code, model_code, display_name, capabilities, cost_config)
JOIN ai.providers p ON p.code = seed.provider_code
ON CONFLICT (provider_id, model_code) DO NOTHING;

COMMIT;
