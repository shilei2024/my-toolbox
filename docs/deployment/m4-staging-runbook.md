# M4 生图/生视频 Staging 验收手册（逐步执行版）

本手册按顺序执行，每步都给出命令、预期输出和验证方法。目标是把
[M4 图片/视频生成部署与回滚](m4-media-generation.md) 中的门禁变成可执行的步骤。
全程假设你已在 Staging 主机克隆仓库并创建 `services/generation-service/deploy/.env.staging`
（从 `.env.staging.example` 复制，真实值绝不提交）。

## 0. 前置确认（10 分钟）

逐项确认，缺一不可：

- [ ] Staging 主机已用 `compose.staging.yaml` 跑起 postgres / redis / migrate / api / dispatcher / worker / caddy。
- [ ] `deploy/.env.staging` 已填写：`DATABASE_URL`、`REDIS_URL`、`COS_SECRET_ID/KEY/BUCKET/REGION`、
  `GALLERY_CURSOR_SECRET`、`GALLERY_INTERNAL_HMAC_SECRET`、`GALLERY_ASSET_HOSTS`。
- [ ] `ARK_VIDEO_API_KEY` 已注入（密钥管理器中），`ARK_VIDEO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`。
- [ ] 火山方舟账号已开通视频模型并有余量；保存测试额度账单入口。
- [ ] 有测试账号（可在主站注册）；`BILLING_SIGNUP_GRANT=10`（或后台调整测试账号积分）。
- [ ] Vercel Preview 已指向 Staging API（变量见 [M1 Preview 验证](m1-vercel-preview-validation.md) §3）。
- [ ] 域名 `api-ai-staging.example.com` 已解析到 Staging 主机（用你自己的 Staging 域名替换）。

检查服务：

```sh
cd services/generation-service/deploy
docker compose --env-file .env.staging -f compose.staging.yaml ps
docker compose --env-file .env.staging -f compose.staging.yaml logs --tail=50 api dispatcher worker
curl -s https://api-ai-staging.example.com/health
```

预期：api healthy；三个进程日志出现 `gallery.api_started`、`queue.dispatcher_started`、
`queue.generation_worker_started`。任一进程缺失先修复，不要跳过。

## 1. 备份（每次变更前必做）

```sh
cd <仓库根目录>
sh services/generation-service/deploy/backup-staging.sh
```

预期输出：

```text
backup created: deploy/backups/generation-staging-20260809T150000Z.dump
```

记录这个文件名，回滚时需要。验证文件非空：

```sh
ls -lh deploy/backups/generation-staging-*.dump
```

恢复演练（推荐，至少做一次）：

```sh
container=$(docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yaml ps -q postgres)
docker cp deploy/backups/generation-staging-<时间戳>.dump "$container":/tmp/backup.dump
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yaml exec -T postgres sh -ec \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/backup.dump'
```

> `--clean --if-exists` 会覆盖现有对象；先在临时库验证 dump 可读，再对目标库执行。

## 2. 迁移 0013 / 0014

```sh
cd services/generation-service/deploy
docker compose --env-file .env.staging -f compose.staging.yaml run --rm migrate
```

预期输出包含：

```text
applying migration: 0013_media_generation.sql
applying migration: 0014_comfyui_media_workflows.sql
```

再执行一次，应全部显示 `migration already applied`（migration ledger 保证幂等）。

验证迁移结果：

```sh
docker compose --env-file .env.staging -f compose.staging.yaml exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT media_type, count(*) FROM ai.workflows GROUP BY media_type"'
docker compose --env-file .env.staging -f compose.staging.yaml exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT code, status FROM ai.providers WHERE code IN (''ark-video'',''comfyui'')"'
```

预期：`video` 至少 2 条（`api-ark-video-doubao-seedance-2-0-260128`、
`comfyui-ltx-video-v1`），两个 Provider 均为 `disabled`（fail-closed）。

## 3. 启用（先核对，再启用）

优先在统一后台操作（主站 `/admin/gallery` → Provider / 模型 / 工作流），
核对后逐项启用：

- `ark-video` Provider：`active`
- 模型 `doubao-seedance-2-0-260128`：`is_enabled = true`
- 工作流 `api-ark-video-doubao-seedance-2-0-260128`：`is_enabled = true`
- 积分价格：工作流默认 `credit_cost = 20`；时长 5/10 秒；视频 `visibility=private`
- （可选）本机 ComfyUI：`comfyui` Provider `active`，工作流 `comfyui-ltx-video-v1` 启用

如果后台暂不可用，SQL 是等价且可审计的操作（只允许在 Staging 执行）：

```sql
UPDATE ai.providers SET status = 'active' WHERE code = 'ark-video';
UPDATE ai.provider_models SET is_enabled = true WHERE model_code = 'doubao-seedance-2-0-260128';
UPDATE ai.workflows SET is_enabled = true WHERE slug = 'api-ark-video-doubao-seedance-2-0-260128';
```

验证目录出现：用测试账号打开 Vercel Preview 的 `/create`，确认出现
“生视频 / API 模型”Tab。内部 `/v1/generation/workflows` 需要 BFF 签名的 Viewer
Context，不要用浏览器或 curl 直接访问。

## 4. 端到端验收（测试账号）

### 4.1 提交任务

1. 登录 Vercel Preview Gallery（同一父域共享登录）。
2. `/create` → 切到“生视频” → “API 模型” → 选 Seedance 2.0。
3. 选 1280×720、5 秒，输入安全的测试 Prompt（如“夕阳下的海边，镜头缓慢推进”）。
4. 提交，记录任务 ID（页面显示任务号前 8 位）。

预期状态：`pending → running → completed`；运行中页面和任务中心都不显示“取消”按钮。

### 4.2 核对数据库（事实来源）

```sql
SELECT j.id, j.status, j.credits_reserved, j.credits_charged,
       a.object_key, a.mime_type, a.byte_size, a.duration_seconds
FROM ai.generation_jobs j
LEFT JOIN ai.generation_assets a ON a.job_id = j.id
WHERE j.user_id = <测试用户id>
ORDER BY j.created_at DESC LIMIT 10;
```

预期：1 条 `completed` 任务，`credits_charged=20.0000`，1 条 `videos/<owner>/<job>/0.mp4`
资产（`video/mp4`，约 5.000 秒）。

核对 reservation 收敛：

```sql
SELECT generation_job_id, amount, charged_amount, status, settled_at
FROM ai.credit_reservations
WHERE generation_job_id = '<任务uuid>' ;
```

预期：`status='settled'`、`charged_amount=20.0000`、`settled_at` 有值；没有长期 `active`。

核对账本（成功只结算一次）：

```sql
SELECT entry_type, delta_available, delta_reserved, source_type, source_ref, created_at
FROM ai.credit_ledger_entries
WHERE user_id = <测试用户id>
ORDER BY created_at DESC LIMIT 20;
```

预期每个任务恰好一条 `generation_reserve` 和一条 `generation_settle`；取消任务则是
`generation_release`。

### 4.3 Worker 日志

```sh
docker compose --env-file .env.staging -f compose.staging.yaml logs --tail=200 worker
```

预期：任务完成、资产持久化、积分结算相关日志；不出现 `Authorization`、
API Key、完整 Prompt 或上游完整响应。

### 4.4 COS 与播放

1. 腾讯云 COS 控制台打开 Staging Bucket，确认 `videos/<owner>/<job>/0.mp4` 存在。
2. 回到 Gallery 任务中心，点“查看结果”应能播放；Vercel Preview 的 CSP 与
   `GALLERY_ASSET_HOSTS` 允许该 CDN 域名。
3. 下载抽查：文件大小 > 0，时长约 5 秒，分辨率 1280×720。

### 4.5 失败与取消演练（至少各一次）

- **排队取消**：连续提交 2 个任务，立刻取消第 1 个（pending）→ 变为 `cancelled`，
  reservation 释放，账本出现 `generation_release`。
- **运行中不可取消**：提交第 3 个任务，running 时确认 UI 无取消按钮、API 拒绝取消。
- **失败释放**：临时停掉 Worker（`docker compose stop worker`）后提交任务，恢复 Worker；
  若轮询超时/上游失败，任务应进入 `failed` 且 reservation 释放。不要手工把任务改为 completed。

## 5. 成本对账

### 5.1 平台侧定价

```sql
SELECT w.slug, wb.estimated_cost, v.defaults->>'credit_cost' AS credit_cost
FROM ai.workflow_versions v
JOIN ai.workflows w ON w.id = v.workflow_id
JOIN ai.workflow_provider_bindings wb ON wb.workflow_version_id = v.id
WHERE w.media_type = 'video';
```

### 5.2 上游任务映射

```sql
SELECT j.id, a.external_request_id, a.status AS attempt_status,
       a.actual_cost, j.credits_charged
FROM ai.generation_jobs j
JOIN ai.generation_attempts a ON a.job_id = j.id
WHERE j.user_id = <测试用户id>
ORDER BY j.created_at DESC LIMIT 10;
```

用 `external_request_id`（火山方舟任务 ID）到方舟控制台/账单核对单条视频金额。

### 5.3 定价结论

记录：1 积分 ≈ ？元（运营定价）；单条 5 秒视频成本 = 上游账单金额 + COS 存储/流量。
要求：`credit_cost × 积分单价 ≥ 单条成本 × (1 + 平台毛利/损耗系数)`。

不确定时保持 Provider disabled，先与财务/运营确认价格再启用。

## 6. 生产发布审批与灰度

1. 更新 [生产发布检查清单](../operations/release-checklist.md)，逐项勾选。
2. 备份生产库，在恢复库上 dry-run 0013/0014（用 `migrate-production.sh` 逻辑验证）。
3. 生产审批通过后：先发布 Generation API/Worker 镜像（兼容旧数据），再执行生产迁移，
   最后确认 Gallery（Vercel main 已含本功能）不回归生图。
4. 生产保持视频 disabled；用内部账号在线上完成一次与 Staging 相同的验收。
5. 灰度放量：内部账号 → 1% → 10% → 50% → 100%。

每个阶段观察：生成成功率、失败队列、积分差异、Provider 成本、COS 错误率、
Redis 内存、数据库连接池。任一账本差异立即停止扩量。

## 7. 回滚预案

先阻止新任务（等价于统一后台禁用）：

```sql
UPDATE ai.workflows SET is_enabled = false WHERE media_type = 'video';
UPDATE ai.provider_models SET is_enabled = false
  WHERE provider_id IN (SELECT id FROM ai.providers WHERE code IN ('ark-video', 'comfyui'));
UPDATE ai.providers SET status = 'disabled' WHERE code IN ('ark-video', 'comfyui');
```

然后：

1. 等待运行任务终态，核对 reservation、ledger 与上游账单。
2. 回滚 Web/Worker/API 镜像（记录旧 digest）。
3. 保留 `media_type`、`generation_assets`、任务、账本与 COS 对象；不反向 DROP。
4. 只有确认旧镜像兼容、完成备份并通过审批后，才考虑编写反向迁移。

## 常见失败速查

| 现象 | 首先检查 | 恢复 |
| --- | --- | --- |
| 生视频 Tab 为 0 | Provider/模型/工作流是否已启用；Preview 变量 | 后台启用后刷新；不写死前端模型 |
| 一直 pending | Dispatcher、outbox、Redis | 看 `docker compose logs dispatcher`；恢复进程 |
| 一直 running | Worker、ComfyUI/方舟、COS | 看 Worker 日志；按 job 审计重试，禁止手工改 completed |
| `No eligible provider` | binding/模型/档位/API Key | 检查数据库状态与 Worker 环境后重启 Worker |
| 视频轮询超时 | `GENERATION_POLL_MAX_ATTEMPTS`、上游状态 | 先查上游账单，再调大轮询；不得盲目重提 |
| COS 上传失败 | Region/Bucket/CAM/磁盘 | 恢复权限与空间；上传成功前不得标完成 |
| 401/403 | HMAC、时间偏差、Cookie 域 | 同步时间，核对 Preview 与 Staging 两组 secret |
| 积分不足 | `BILLING_SIGNUP_GRANT`、后台调整 | 只通过后台审计调整，不直接 UPDATE 账本 |
