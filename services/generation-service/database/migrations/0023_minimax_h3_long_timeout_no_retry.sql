BEGIN;

-- H3 在消费级显卡上生成 720p/长视频可能超过 30 分钟：binding 超时放宽到 2 小时，
-- 并禁止超时后自动重试（否则每次重试都会在 ComfyUI 再排一个任务，导致 GPU 堆积）。
UPDATE ai.workflow_provider_bindings
SET provider_config = '{"align":32,"retryOnTimeout":false}'::jsonb,
    timeout_seconds = 7200,
    max_attempts = 1
WHERE provider_workflow_ref IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1');

COMMIT;
