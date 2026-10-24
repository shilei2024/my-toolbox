# 灵感画廊复刻 + 策展上传 · 发布与回滚

> 对应 ADR：[0039-gallery-showcase-and-curated-uploads](../adr/0039-gallery-showcase-and-curated-uploads.md)
>
> 涉及三个部署面：
> 1. **Generation Service（腾讯云服务器）**：数据库迁移 `0025`、新的 `/v1/gallery/facets` 与 `/v1/admin/curated-images*` 接口。
> 2. **Gallery Web（Vercel）**：`/gallery` 全新页面 + 新增 `/api/gallery/facets` 代理。
> 3. **主站 Flask（Vercel）**：统一后台的策展上传与编辑入口。
>
> 发布顺序：先备份、迁移并部署 Generation Service，确认 API 健康；再合并/发布两个 Vercel 项目。前端早于服务端发布会使 facets 与策展接口暂时不可用。

## 0. 变更清单

| 文件 | 变更 | 是否需要重启 |
| --- | --- | --- |
| `apps/gallery-web/src/app/gallery/*` | 画廊页面复刻、独立样式层 | Vercel 自动重新部署 |
| `apps/gallery-web/src/components/showcase-gallery.tsx` | 顶栏 / hero / 筛选 / justified 墙 / 详情浮层 | 同上 |
| `apps/gallery-web/src/app/api/gallery/facets/route.ts` | facets 代理 | 同上 |
| `services/generation-service/database/migrations/0025_curated_gallery.sql` | `ai.images` 新增 `origin`、`curated_by_user_id` | 迁移容器一次性执行 |
| `services/generation-service/src/admin/*` | 策展作品增删改查（审计 + 软删除） | 重建 api 镜像 |
| `services/generation-service/src/gallery/curated-image-service.ts` | sharp 转码 + COS 上传 + 补偿删除 | 同上 |
| `services/generation-service/src/gallery/*` | `mediaType` / `sort` / facets | 同上 |
| `templates/admin/gallery.html`、`admin/gallery_admin.py`、`utils/gallery_admin_client.py` | 后台“策展上传”页签 | 主站部署（Vercel my-toolbox） |

## 1. 前置检查

```bash
# 本地：分支与测试
git log --oneline -3
cd services/generation-service && npm test          # 应全部通过（含 phase14）
cd ../../apps/gallery-web && npm run build          # 应产出 /gallery 静态/动态页
cd ../.. && python -m unittest tests.test_admin_gallery_routes tests.test_gallery_admin_client tests.test_gallery_cors
```

生产环境变量确认（服务器 `/etc/mindfulpenpal.production.env`）：

- `GALLERY_INTERNAL_HMAC_SECRET`（≥32 字节）在服务器与 Vercel 两个项目完全一致；
- `COS_*`、`GALLERY_ASSET_HOSTS`、`COS_CDN_BASE_URL` 已配置（策展图复用同一存储与 CDN）；
- `GENERATION_IMAGE` 指向镜像 digest（迁移与 api 共用同一镜像源）。

## 2. Gallery Web 与主站（Vercel；在第 3 节服务端验证通过后执行）

1. 第 3 节的迁移、服务端部署及健康检查通过后，合并 PR 到 `main`；
2. Vercel `my-toolbox-gallery` 项目（Root Directory `apps/gallery-web`，Production Branch `main`）和主站 `my-toolbox` 项目自动构建；
3. 构建完成后验证：

```powershell
curl.exe -I https://gallery.mindfulpenpal.com/gallery
curl.exe https://gallery.mindfulpenpal.com/api/gallery?limit=1
curl.exe https://gallery.mindfulpenpal.com/api/gallery/facets
```

预期：

- `/gallery` 返回 200，HTML 中含 `sc-root`、`每件作品都附` 与至少一条作品卡（无作品时显示空状态）；
- `/api/gallery/facets` 返回 `{"total":N,"media":{"image":..,"video":..},"workflows":[...]}`；
- 页面无骨架卡死；`Content-Security-Policy` 仍带 nonce。

> 若 Vercel 未自动部署，到 Deployments 页面对 `main` 的最新构建执行 “Promote to Production”。

## 3. Generation Service（腾讯云服务器）

假设代码目录 `/opt/mindfulpenpal`，环境文件 `/etc/mindfulpenpal.production.env`。

### 3.1 备份

```bash
cd /opt/mindfulpenpal
# 托管 PostgreSQL / Redis：先在云控制台创建一次手动备份（或在控制台导出快照）。
# 本机容器数据库（local-infra）：
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile local-infra exec -T postgres \
  pg_dump -U mavis mindfulpenpal > /opt/mindfulpenpal/backup-$(date +%F-%H%M).sql
```

> 本次迁移是**加列 + 加索引**，不删除任何数据；备份用于满足“发布前可恢复”的硬性要求。

### 3.2 拉取已评审的功能分支并构建镜像

```bash
git fetch origin feat/gallery-showcase-curation
git checkout --detach FETCH_HEAD
export RELEASE_SHA="$(git rev-parse --short HEAD)"

# 构建并推送（registry 地址以 .env 中的 GENERATION_IMAGE 为准）
docker build -t "$GENERATION_REGISTRY/mindfulpenpal-generation:$RELEASE_SHA" services/generation-service
docker push "$GENERATION_REGISTRY/mindfulpenpal-generation:$RELEASE_SHA"
docker inspect --format='{{index .RepoDigests 0}}' "$GENERATION_REGISTRY/mindfulpenpal-generation:$RELEASE_SHA"
```

把输出的 digest 写入 `/etc/mindfulpenpal.production.env` 的 `GENERATION_IMAGE`（同时更新 `POSTGRES_MIGRATION_IMAGE`，两者使用同一镜像）：

```
GENERATION_IMAGE=<registry>/mindfulpenpal-generation@sha256:<digest>
POSTGRES_MIGRATION_IMAGE=<registry>/mindfulpenpal-generation@sha256:<digest>
```

### 3.3 执行迁移

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile migration run --rm migrate
```

预期输出包含 `applying migration: 0025_curated_gallery.sql`，并以成功退出码结束。重复执行会跳过已应用的迁移。

验证列已存在：

```bash
psql "$DATABASE_URL" -c "\d+ ai.images" | grep -E "origin|curated_by_user_id"
```

### 3.4 滚动重启

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d --no-build
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps
```

预期：`api` 为 `healthy`，`dispatcher`、`worker`、`deletion-worker`、`caddy` 为 `running`。

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml logs --tail=50 api
```

预期出现 `gallery.api_started`，无 `unhandledRejection` / `migration` 错误。

## 4. 功能验收

1. **后台**：登录主站 → `/admin/gallery` → “策展上传”页签，上传一张 PNG 并填写提示词（含换行与参数），提交。
   - 预期：绿色提示“策展作品已发布到画廊，提示词已保存”；
   - 卡片显示缩略图、模型、发布时间，提示词以 `pre` 原样展示（保留换行）。
2. **公开页**：打开 `https://gallery.mindfulpenpal.com/gallery`
   - 顶部“模型”出现刚填写的模型名，计数 +1；
   - 点击作品卡片 → 浮层右侧显示同一段提示词（换行保留），“复制提示词”可用；
   - 图片频道 / 视频频道 / 方向 / 最多收藏筛选均能返回结果。
3. **接口**：

```bash
curl -s "https://gallery.mindfulpenpal.com/api/gallery?mediaType=image&limit=3" | head -c 400
curl -s "https://gallery.mindfulpenpal.com/api/gallery?sort=popular&limit=3" | head -c 400
```

4. **审计**：`ai.audit_logs` 中出现 `admin.curated_image_created`，`actor_type='admin'`。
5. **下线**：后台点击“下线”，作品立即从 `/gallery` 消失；`ai.asset_deletion_tasks` 生成一条记录，保留期后由 deletion-worker 回收 COS 对象。

## 5. 常见失败

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 后台提示“策展图片保存失败” | COS 凭证/桶配置错误，或图片格式不被 sharp 识别 | 检查 `COS_*` 与 api 日志 `admin.curated_image_*`；确认是 JPEG/PNG/WebP |
| 后台提示 `GALLERY_INTERNAL_HMAC_SECRET` 未配置 | Vercel 与服务器密钥不一致 | 两侧配置同一 ≥32 字节密钥后重新部署 |
| `/gallery` 骨架不消失 | facets 或列表接口 503 | `curl /api/gallery/facets` 看错误码；通常是 api 容器未 healthy |
| 上传 413 | 主站 Vercel Function 请求体超过 4.5 MB，或图片超过后台 4 MB 上限 | 压缩图片至 4 MB 以下；大文件需另行设计直传 COS，不要单纯调高 `MAX_UPLOAD_MB` |
| 模型筛选没有新模型 | 影子上游缓存 | 缓存随 `PUBLIC_FEED_NAMESPACE` 版本号失效；等待 TTL 或重新发布一次 |

## 6. 回滚

1. **Vercel**：Gallery Web 与主站 Flask 两个项目分别在 Deployments 中选择上一个成功的 `main` 构建 → “Promote to Production”。
2. **服务器**：把 `GENERATION_IMAGE` / `POSTGRES_MIGRATION_IMAGE` 改回上一个 digest，执行
   `docker compose ... --profile production up -d --no-build`。
3. **数据库**：迁移只加列，无需回滚即可与旧代码共存；确认要彻底回退时执行：

```sql
DROP INDEX IF EXISTS ai.ix_ai_images_curated_created;
ALTER TABLE ai.images
  DROP COLUMN IF EXISTS curated_by_user_id,
  DROP COLUMN IF EXISTS origin;
```

执行前先把 `origin='curated'` 的作品软删除，避免变成“无来源”的普通作品。

4. **存储**：策展对象都在 COS `curated/` 前缀下，可按前缀清理，不影响生成作品。
