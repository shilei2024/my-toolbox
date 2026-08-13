BEGIN;

-- MiniMax H3 全能参考工作流（Work-Fisher 原图三分支，平台拆分执行）：
-- t2v 文生视频 / i2v 单图参考 / ref 多图参考（最多 3 张，提示词用 @图片N 引用）。

INSERT INTO ai.workflows (slug, name, description, category, mode, media_type, is_enabled, sort_order)
VALUES
  ('minimax-h3-t2v-v1', 'MiniMax H3 文生视频', 'MiniMax H3 原生音视频模型：文本直接生成带同步音效的视频，支持 4/5/8/10 秒。', 'MiniMax H3', 'workflow', 'video', true, 205),
  ('minimax-h3-i2v-v1', 'MiniMax H3 单图生视频', '用一张参考图生成延续其人物与场景的视频（Ref2VA 单图参考）。', 'MiniMax H3', 'workflow', 'video', true, 206),
  ('minimax-h3-ref-v1', 'MiniMax H3 多图参考视频', '最多 3 张参考图：提示词中可用 @图片1 / @图片2 / @图片3 分别指定角色、场景与道具。', 'MiniMax H3', 'workflow', 'video', true, 207)
ON CONFLICT (slug) DO UPDATE SET
  name = EXCLUDED.name,
  description = EXCLUDED.description,
  category = EXCLUDED.category,
  mode = EXCLUDED.mode,
  media_type = EXCLUDED.media_type,
  is_enabled = EXCLUDED.is_enabled,
  sort_order = EXCLUDED.sort_order;

INSERT INTO ai.workflow_versions (workflow_id, version, input_schema, defaults, output_schema, is_active)
SELECT
  w.id,
  1,
  '{"type":"object","required":["prompt","width","height","count","durationSeconds"],"properties":{"prompt":{"type":"string","minLength":1,"maxLength":8000},"negativePrompt":{"type":"string","maxLength":8000},"width":{"type":"integer","minimum":256,"maximum":4096},"height":{"type":"integer","minimum":256,"maximum":4096},"count":{"type":"integer","minimum":1,"maximum":1},"durationSeconds":{"type":"integer","enum":[4,5,8,10]}}}'::jsonb,
  jsonb_build_object(
    'width', 1344, 'height', 768, 'count', 1,
    'visibility', 'public', 'prompt_visibility', 'public',
    'duration_seconds', seed.duration_seconds,
    'credit_cost', 8,
    'mode_meta', jsonb_build_object('key', seed.mode_key, 'label', seed.mode_label, 'maxImages', seed.max_images)
  ),
  '{"type":"object","properties":{"videos":{"type":"array","minItems":1,"maxItems":1}}}'::jsonb,
  true
FROM ai.workflows w
JOIN (VALUES
  ('minimax-h3-t2v-v1', 't2v', '文生视频', 0, 5),
  ('minimax-h3-i2v-v1', 'i2v', '单图生视频', 1, 5),
  ('minimax-h3-ref-v1', 'ref', '多图参考视频', 3, 5)
) AS seed(slug, mode_key, mode_label, max_images, duration_seconds) ON seed.slug = w.slug
ON CONFLICT (workflow_id, version) DO UPDATE SET
  input_schema = EXCLUDED.input_schema,
  defaults = EXCLUDED.defaults,
  output_schema = EXCLUDED.output_schema,
  is_active = EXCLUDED.is_active;

INSERT INTO ai.workflow_provider_bindings (
  workflow_version_id, provider_id, provider_workflow_ref, provider_model,
  provider_config, priority, estimated_cost, timeout_seconds, max_attempts, is_enabled
)
SELECT
  v.id,
  provider.id,
  w.slug,
  'minimax_h3_fl2va_int8_convrot.safetensors',
  '{}'::jsonb,
  10,
  0,
  1800,
  1,
  true
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
JOIN ai.providers provider ON provider.code = 'comfyui'
WHERE w.slug IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1') AND v.is_active
ON CONFLICT (workflow_version_id, provider_id) DO UPDATE SET
  provider_workflow_ref = EXCLUDED.provider_workflow_ref,
  provider_model = EXCLUDED.provider_model,
  provider_config = EXCLUDED.provider_config,
  timeout_seconds = EXCLUDED.timeout_seconds,
  max_attempts = EXCLUDED.max_attempts,
  is_enabled = EXCLUDED.is_enabled;

COMMIT;
