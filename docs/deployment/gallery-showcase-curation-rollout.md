# 灵感画廊复刻 + 策展上传 · 发布与回滚

> 对应 ADR：[0039-gallery-showcase-and-curated-uploads](../adr/0039-gallery-showcase-and-curated-uploads.md)
>
> 涉及三个部署面：
> 1. **Generation Service（腾讯云服务器）**：数据库迁移 `0025`、新的 `/v1/gallery/facets` 与 `/v1/admin/curated-images*` 接口。
> 2. **Gallery Web（Vercel）**：`/gallery` 全新页面 + 新增 `/api/gallery/facets` 代理。
> 3. **主站 Flask（腾讯云服务器）**：统一后台的策展上传与编辑入口，宿主机 `mytoolbox.service`。
>
> 发布顺序：先备份、迁移并部署 Generation Service，确认 API 健康；再更新腾讯云主站 Flask 并验收后台；最后合并剩余 PR。画廊前端的 PR #99 已先行合并并在 Vercel 生产部署；后端未更新时 facets 和列表接口无法正常工作。腾讯云适配 PR #100 保持待合并，直到服务器更新和验收完成。

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
| `templates/admin/gallery.html`、`admin/gallery_admin.py`、`utils/gallery_admin_client.py` | 后台“策展上传”页签 | 腾讯云主站 `mytoolbox.service` 重启 |

## 1. 前置检查

```bash
# 本地：分支与测试
git log --oneline -3
cd services/generation-service && npm test          # 应全部通过（含 phase14）
cd ../../apps/gallery-web && npm run build          # 应产出 /gallery 静态/动态页
cd ../.. && python -m unittest tests.test_admin_gallery_routes tests.test_gallery_admin_client tests.test_gallery_cors
```

生产环境变量确认（服务器 `/etc/mindfulpenpal.production.env`）：

- `GALLERY_INTERNAL_HMAC_SECRET`（≥32 字节）在腾讯云主站、Generation Service 与 Vercel Gallery Web 中一致；
- 主站 `MAX_UPLOAD_MB` 和入口代理的请求体上限至少为 16 MB（15 MB 原图加 multipart 表单开销；仓库默认分别为 25 MB 和 30M）；Flask 发往 Generation Service 的 base64 JSON 约 20 MB，由内部路由的 24 MB 上限接收；
- `COS_*`、`GALLERY_ASSET_HOSTS`、`COS_CDN_BASE_URL` 已配置（策展图复用同一存储与 CDN）；
- `GENERATION_IMAGE` 指向镜像 digest（迁移与 api 共用同一镜像源）。

## 2. Gallery Web（Vercel；在第 3 节服务端验证通过后执行）

1. 第 3 节的迁移、服务端部署及健康检查通过后，合并 PR 到 `main`；
2. Vercel `my-toolbox-gallery` 项目（Root Directory `apps/gallery-web`，Production Branch `main`）自动构建；
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

已核对的生产布局：Generation Service 的 Compose 文件位于 `/opt/mindfulpenpal/deploy/docker-compose.production.yml`；Flask 主站位于 `/opt/mytoolbox`，由 `mytoolbox.service` 运行；PostgreSQL 运行在宿主机。环境文件分别为 `/etc/mindfulpenpal.production.env` 与 `/opt/mytoolbox/.env`。两个工作树不可混用，主站工作树有未提交的 Caddy 配置修改，更新时必须保留。

### 3.1 备份

先确认运行中的 `api` 容器实际连接 `mindfulpenpal` 宿主机数据库，再确认 `ai.images`、`public.schema_migrations` 存在且磁盘空间足够。不要从其他项目的 PostgreSQL 容器导出数据。

```bash
umask 077
release_backup_dir="/root/gallery-release-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 "$release_backup_dir"
sudo -u postgres pg_dump -Fc -d mindfulpenpal > "$release_backup_dir/mindfulpenpal.dump"
pg_restore --list "$release_backup_dir/mindfulpenpal.dump" > "$release_backup_dir/mindfulpenpal.contents"
cp -p /etc/mindfulpenpal.production.env "$release_backup_dir/generation.env"
cp -p /opt/mytoolbox/.env "$release_backup_dir/mytoolbox.env"
git -C /opt/mytoolbox diff --binary -- services/generation-service/deploy/Caddyfile.production > "$release_backup_dir/mytoolbox-caddy.patch"
git -C /opt/mytoolbox rev-parse HEAD > "$release_backup_dir/mytoolbox.commit"
git -C /opt/mindfulpenpal rev-parse HEAD > "$release_backup_dir/generation.commit"
docker inspect --format '{{.Config.Image}} {{.Image}}' mindfulpenpal-ai-production-api-1 > "$release_backup_dir/generation.image"
ls -lh "$release_backup_dir/mindfulpenpal.dump" "$release_backup_dir/mindfulpenpal.contents"
```

任一步失败即停止；备份目录只允许 root 访问，不要把 `.env` 或数据库备份传到聊天、Git 或公开存储。本次迁移是**加列 + 加索引**，不删除现有数据；备份用于满足“发布前可恢复”的要求。

### 3.2 更新 Generation Service 工作树并构建本地镜像

```bash
cd /opt/mindfulpenpal
git status --short --branch                 # 确认没有跟踪文件修改
git fetch origin main
git merge-base --is-ancestor HEAD origin/main  # 非 0 时停止，不强行覆盖
git merge --ff-only origin/main
release_sha="$(git rev-parse --short HEAD)"
docker build -t "mindfulpenpal/generation-service:gallery-$release_sha" services/generation-service
docker image inspect --format '{{.Id}}' "mindfulpenpal/generation-service:gallery-$release_sha"
```

当前服务器使用本地 `mindfulpenpal/generation-service:0.9.7` 镜像，没有已确认的镜像仓库。把新构建的固定 tag 写入 `/etc/mindfulpenpal.production.env` 的 `GENERATION_IMAGE` 和 `POSTGRES_MIGRATION_IMAGE`（两者使用同一镜像）；不要改动其余密钥或连接串：

```
GENERATION_IMAGE=mindfulpenpal/generation-service:gallery-<release_sha>
POSTGRES_MIGRATION_IMAGE=mindfulpenpal/generation-service:gallery-<release_sha>
```

更新前记录旧镜像名称与 image ID；发布时不复用旧 tag，便于回滚。编辑完环境文件后执行 `docker compose ... config --images`，确认解析出的生产与迁移镜像均为新 tag，再运行迁移。

### 3.3 执行迁移

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile migration run --rm migrate
```

预期输出包含 `applying migration: 0025_curated_gallery.sql`，并以成功退出码结束。重复执行会跳过已应用的迁移。

验证列已存在：

```bash
sudo -u postgres psql -d mindfulpenpal -Atqc "SELECT column_name FROM information_schema.columns WHERE table_schema='ai' AND table_name='images' AND column_name IN ('origin','curated_by_user_id') ORDER BY column_name;"
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

### 3.5 更新主站 Flask

主站与 Generation Service 可能使用不同代码目录。仓库内 `deploy/mytoolbox.service` 的示例工作目录为 `/opt/mytoolbox`；登录服务器后先用 `systemctl cat mytoolbox.service` 核实实际 `WorkingDirectory`、`EnvironmentFile` 和代码发布方式，再按现有发布流程把同一已评审提交发布到主站目录。不要把 Generation Service 的 `/opt/mindfulpenpal` 目录直接当作主站目录。

```bash
sudo systemctl cat mytoolbox.service
sudo systemctl status mytoolbox.service --no-pager
# 核对当前版本、配置与备份后，按服务器既有发布方式更新主站代码。
sudo systemctl restart mytoolbox.service
sudo systemctl status mytoolbox.service --no-pager
curl -fsS -o /dev/null -w '%{http_code}\n' https://mindfulpenpal.com/admin/gallery
```

预期：服务状态 `active (running)`；未登录时后台页面重定向到登录页（通常为 302），登录管理员后可见“策展上传”。若生产代理或主站仍将请求体限制在 16 MB 以下，应先调整配置并验证，再允许上传 15 MB 图片。

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
| 后台提示 `GALLERY_INTERNAL_HMAC_SECRET` 未配置 | 腾讯云主站与 Generation Service 密钥不一致 | 两侧配置同一 ≥32 字节密钥后重启服务 |
| `/gallery` 骨架不消失 | facets 或列表接口 503 | `curl /api/gallery/facets` 看错误码；通常是 api 容器未 healthy |
| 上传 413 | 腾讯云代理或 Flask 请求体上限低于 15 MB 加表单开销，或原始图片超过 15 MB | 核对主站 `MAX_UPLOAD_MB` 与代理 `client_max_body_size` 是否均至少 16 MB；超过 15 MB 的原图先压缩 |
| 模型筛选没有新模型 | 影子上游缓存 | 缓存随 `PUBLIC_FEED_NAMESPACE` 版本号失效；等待 TTL 或重新发布一次 |

## 6. 回滚

1. **Vercel**：Gallery Web 在 Deployments 中选择上一个成功的 `main` 构建 → “Promote to Production”。
2. **腾讯云主站**：恢复上一版主站提交，保留原有未提交的 Caddy 配置修改，重启 `mytoolbox.service` 并验证登录、后台和首页。
3. **Generation Service**：把 `GENERATION_IMAGE` / `POSTGRES_MIGRATION_IMAGE` 改回备份目录 `generation.image` 记录的旧 tag，执行
   `docker compose ... --profile production up -d --no-build`。
4. **数据库**：迁移只加列，无需回滚即可与旧代码共存；确认要彻底回退时执行：

```sql
DROP INDEX IF EXISTS ai.ix_ai_images_curated_created;
ALTER TABLE ai.images
  DROP COLUMN IF EXISTS curated_by_user_id,
  DROP COLUMN IF EXISTS origin;
```

执行前先把 `origin='curated'` 的作品软删除，避免变成“无来源”的普通作品。

5. **存储**：策展对象都在 COS `curated/` 前缀下，可按前缀清理，不影响生成作品。
