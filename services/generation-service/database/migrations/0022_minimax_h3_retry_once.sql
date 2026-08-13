BEGIN;

-- ComfyUI 视频生成成功后，下载/转存环节的瞬时网络失败可重试一次，避免
-- “视频已生成但任务失败”且无法挽回。
UPDATE ai.workflow_provider_bindings
SET max_attempts = 2
WHERE provider_workflow_ref IN ('minimax-h3-t2v-v1','minimax-h3-i2v-v1','minimax-h3-ref-v1');

COMMIT;
