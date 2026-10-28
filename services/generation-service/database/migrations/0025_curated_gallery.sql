BEGIN;

-- 策展作品（Curated works）：管理员在统一后台直接上传"图片 + 提示词"。
--
-- 设计取舍：策展作品复用 ai.images 这一张"媒体作品表"，而不是再建一张
-- 独立表。这样审核、可见性、发布时间、点赞收藏、SEO、下载与详情接口全部
-- 复用同一条链路，Gallery 前端不需要区分数据来源；差异只体现在：
--   origin = 'curated'          表示不是由生成任务产出
--   job_id / provider_id / workflow_version_id 为 NULL（生成任务的外键）
--   provider_code_snapshot 记录策展来源（manual/imported 等）
--   workflow_name_snapshot 记录模型展示名，用于前端的"模型"筛选
--   prompt 字段原样保留上传时填写的提示词（含负面提示词），不参与改写
ALTER TABLE ai.images
  ADD COLUMN origin varchar(16) NOT NULL DEFAULT 'generated'
    CHECK (origin IN ('generated', 'curated')),
  ADD COLUMN curated_by_user_id integer REFERENCES public.users(id) ON DELETE SET NULL;

COMMENT ON COLUMN ai.images.origin IS '作品来源：generated=生成任务产出，curated=后台策展上传';
COMMENT ON COLUMN ai.images.curated_by_user_id IS '策展上传的管理员用户 id（origin=curated 时有值）';

-- 后台"策展作品"列表按创建时间倒序读取，单独建一个部分索引。
CREATE INDEX ix_ai_images_curated_created
  ON ai.images (created_at DESC, id DESC)
  WHERE origin = 'curated' AND deleted_at IS NULL;

COMMIT;
