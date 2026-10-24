# ADR 0039：灵感画廊复刻与策展作品上传

## Why

公开画廊页（`gallery.mindfulpenpal.com/gallery`）此前是“作品库 + 筛选工具栏”的常规信息布局：视觉层级弱、首屏没有作品，用户要先滚动才能看到图；详情要跳页，提示词与复制动作埋在二级页面里。对比 `gallery.work-fisher.com`，后者的核心不是“更多功能”，而是三条编辑式设计原则：

1. 首屏即作品：深色舞台 + 一行文案 + 最新作品横向胶片带；
2. 作品本身承担色彩，界面保持安静（暖纸底、低饱和灰、柠檬黄只用于强调）；
3. 每件作品都附完整提示词，并在同一浮层里完成“看图 → 读提示词 → 复制/下载/收藏”。

同时，运营侧长期存在一个空白：只有“用户生成 → 审核 → 发布”这一条入库路径。想补充官方精选、外部模型（Midjourney、GPT-Image 等）或历史作品时，只能伪造生成任务，破坏计费、任务与审计语义。需要一个“管理员上传图片 + 提示词”的正规入口，并且提示词必须原样保留。

## Decision

### 画廊页面

- 用独立样式层 `src/app/gallery/gallery-showcase.css`（`sc-` 前缀）复刻参考站点的编辑式布局：深色 sticky 顶栏、深色 hero + 自动横向胶片带、暖纸色作品墙、粗体频道分栏（柠檬黄下划线）、模型/方向两组筛选 chip、最新/最多收藏排序、justified 行布局（按图片宽高比逐行计算宽度，服务端与客户端一致）。
- `/gallery` 路由使用自己的顶栏，因此根布局的 `SiteHeader` 在该路由不渲染（`SiteHeaderGate`），避免双 header。其他页面保持原导航不变。
- 作品详情改为 `<dialog>` 浮层：左侧深色舞台（上一件/下一件），右侧信息面板展示标题、模型、尺寸、提示词（可一键复制）、负面提示词、生成参数、标签、收藏/点赞/下载。原 `/gallery/[slug]` 页面保留，继续承担 SEO 落地页与分享链接。
- 筛选走服务端已有的 `/v1/gallery`，新增两个可选参数：`mediaType`（图片/视频频道）与 `sort=latest|popular`；新增 `/v1/gallery/facets` 返回模型分布与图片/视频数量，供顶部筛选面板直接渲染。`popular` 按收藏数排序，与 keyset 游标不兼容，因此只返回第一屏且不签发 cursor。

### 策展作品

- 策展作品复用 `ai.images` 这一张媒体作品表，新增 `origin`（`generated`/`curated`）与 `curated_by_user_id`，不新建平行表。审核、可见性、发布时间、点赞收藏、SEO、下载与详情接口全部复用同一条链路，前端无需区分数据来源。
- 管理员在统一后台 `/admin/gallery` 的“策展上传”页签上传图片并填写提示词；Flask 只做体积/类型/魔数校验与 base64 编码，**写库与对象存储由 Generation Service 完成**（`POST /v1/admin/curated-images`），凭证不进入 Web 层。
- 服务端用 sharp 校验真实格式（仅 JPEG/PNG/WebP），按 EXIF 摆正并丢弃元数据，生成 original / preview(1600px) / thumbnail(720px) 三份资源写入 COS 的 `curated/yyyy/mm/{slug}/` 前缀，再在一个事务中写入 `ai.images` + `ai.image_assets` + 标签 + 审计。数据库写入失败时回收已上传对象。
- 提示词按提交内容原样保存（不折叠换行、不改写参数段落），默认 `prompt_visibility='public'`，在画廊浮层与详情页展示；`workflow_name_snapshot` 保存模型展示名，直接成为前端的“模型”筛选项。
- 后台提供列表、编辑（标题/提示词/模型/标签/可见性）与下线（软删除 + 复用 `asset_deletion_tasks` 延迟回收）能力。

## Alternatives Considered

- **新建 `gallery_showcase_items` 表**：能完全隔离生成链路，但详情、点赞、收藏、SEO、下载、审核都要复制一套逻辑，与平台“共享基础设施”原则冲突。策展作品与生成作品在公开语义上完全一致，因此合并存储更合适。
- **只做前端视觉改造，不做上传**：改动最小，但运营无法补充官方精选，用户提出的“上传图片和提示词”需求无法满足。
- **Flask 直传 COS**：少一次服务跳转，但会把 COS 凭证带到 Web 层，违反“浏览器/Web 层不接触存储凭证”的边界。
- **multipart 直传 Generation Service**：需要新增 `@fastify/multipart` 依赖并处理流式校验；当前后台是低频人工操作，主站 [Vercel Function 的请求上限为 4.5 MB](https://vercel.com/docs/functions/limitations#request-body-size)，因此后台文件限制为 4 MB。Generation Service 内部仍设置 15 MB 上限及 24 MB 按路由 bodyLimit。
- **保留 CSS 瀑布流**：实现简单，但参考站点的视觉核心是“逐行对齐的图片墙”，瀑布流会破坏横向对齐的节奏。

## Future Impact

- `origin` 字段为后续“用户投稿”“外部作品导入”留出入口：扩展枚举值即可，无需改表结构。
- facets 接口可继续扩展标签、作者维度，前端筛选面板已按“行 + chips”结构组织。
- 若后续需要提示词版本历史，可在 `ai.images` 之外增加 append-only 的 prompt revisions 表，不影响当前读路径。

## Performance

- 列表查询仍走 `ix_ai_gallery_feed_v2` 部分索引；新增的 `mediaType` 条件只在该索引结果上过滤，`popular` 排序在列表规模内可接受（首页 24 条）。
- facets 为两次聚合查询，结果按公共列表缓存版本号缓存（Redis TTL 与列表一致），内容变更时随 `PUBLIC_FEED_NAMESPACE` 一起失效。
- 策展上传为低频操作，sharp 三次转码（原图重整 + 预览 + 缩略图）在 15MB 上限内为秒级；上传结果不参与列表渲染阻塞。
- 画廊首屏 SSR 直接输出作品墙与聚合数据，无额外客户端请求瀑布。

## Cost

- 无新增服务、无新增付费依赖：sharp、COS SDK、Fastify 均为既有依赖。
- 存储成本：每张策展图约 1.1–1.4 倍原图体积（原图 + webp 预览 + 缩略图），按运营上传频率可忽略。
- 无新增定时任务；下线回收复用既有 `gallery:deletion-worker`。

## Security

- 上传仅允许 `admin` 角色：Flask 侧 `@admin_required`，服务端再次校验签名上下文中的 `role=admin` 与 `userId`（双保险，不信任前端）。
- 文件按魔数 + sharp 解析双重校验，仅接受 JPEG/PNG/WebP；后台上传上限 4 MB，内部 API 硬上限 15 MB；EXIF 与自定义元数据被剥离，避免泄露设备/软件信息。
- 提示词按纯文本存储与 `pre` 渲染，不解析 HTML；标签 slug 清洗后入库。
- 所有写操作写入 `ai.audit_logs`（actor=admin），下线走软删除 + 延迟回收，可追溯、可恢复。
- 上传接口只暴露在带 HMAC 签名的内部上下文中，公网不能直接调用。

## Rollback Plan

1. 前端与后台：Gallery Web、主站 Flask 两个 Vercel 项目分别回滚到前一个成功部署；`/gallery` 恢复旧版作品库布局，后台策展上传入口消失。
2. 服务端：回滚 Generation Service 镜像/代码并重启 `api` 容器；新增路由消失，旧的画廊接口行为不变。
3. 数据库：`0025_curated_gallery.sql` 只做加列与加索引，向后兼容；回滚代码后旧版本会忽略 `origin`/`curated_by_user_id`，已发布的策展作品仍能正常展示与审核。若必须彻底回退，可执行：
   ```sql
   DROP INDEX IF EXISTS ai.ix_ai_images_curated_created;
   ALTER TABLE ai.images DROP COLUMN IF EXISTS curated_by_user_id, DROP COLUMN IF EXISTS origin;
   ```
   删除前需先清理 `origin='curated'` 的作品（软删除即可），否则这些行会变成“无来源”的普通作品。
4. 存储：策展对象位于 `curated/` 前缀，可按前缀整体清理，不影响生成作品对象。
