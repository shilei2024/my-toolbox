BEGIN;

-- 视频作品进入公共画廊（与图片同一页面、同一审核流程）。
-- ai.images 从“图片表”升级为“媒体作品表”：视频完成时同样投影一行
-- (media_type='video')，复用既有的审核、可见性、发布时间、点赞收藏与
-- SEO 查询链路；视频文件本体仍存 ai.generation_assets / ai.image_assets
-- (variant='original')，画廊卡片静态显示首帧、悬停播放。
ALTER TABLE ai.images
  ADD COLUMN media_type varchar(16) NOT NULL DEFAULT 'image'
    CHECK (media_type IN ('image', 'video')),
  ADD COLUMN duration_seconds integer
    CHECK (duration_seconds IS NULL OR (duration_seconds > 0 AND duration_seconds <= 300));

COMMENT ON COLUMN ai.images.media_type IS '作品媒体类型：image=图片，video=视频（视频复用同一审核与发布链路）';
COMMENT ON COLUMN ai.images.duration_seconds IS '视频时长（秒），仅 media_type=video 时有值';

COMMIT;
