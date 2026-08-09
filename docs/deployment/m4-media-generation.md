# M4 图片/视频生成部署与回滚（小白版）

本功能会影响在线创作 API 和 Worker，但迁移后的火山方舟 Provider 默认禁用。必须先在 Staging 验收，生产启用需要单独审批。

若目标是让 Gallery 调用开发电脑上的 ComfyUI，请先按[本机 ComfyUI 生图/生视频联调指南](gallery-local-comfyui.md)执行；本页其余内容仍是 Staging/生产发布门禁。

## 1. 为什么要先准备这些资源

- PostgreSQL 保存任务、积分、审计和耐久资产，是事实来源。
- Redis/BullMQ 只调度 job ID；不能用清库方式“修任务”。
- Tencent COS 保存最终视频；火山方舟返回的 URL 是临时地址。
- 火山方舟 API Key 只放在 Worker，不能放入 Vercel 或浏览器变量。

需要：已备份的 PostgreSQL、可用 Redis、COS 最小权限账号、火山方舟已开通的视频模型与测试额度、Staging 域名和 Worker。

## 2. 配置 Staging

复制 `services/generation-service/deploy/.env.staging.example`，填写已有数据库/Redis/COS变量，并增加：

```dotenv
ARK_VIDEO_API_KEY=请在密钥管理器中注入，不要提交
ARK_VIDEO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
GENERATION_VIDEO_MAX_BYTES=209715200
GENERATION_POLL_INTERVAL_MS=1000
GENERATION_POLL_MAX_ATTEMPTS=3600
```

预期：密钥文件不在 Git 状态中；`GENERATION_POLL_*` 允许最长约一小时轮询。若组织使用代理地址，生产必须是经安全评审的 HTTPS 主机。

## 3. 备份并执行迁移

先按[生产发布清单](../operations/release-checklist.md)备份并验证可恢复。Staging 容器内执行：

```sh
DATABASE_URL="$DATABASE_URL" sh /app/deploy/migrate-staging.sh
```

生产仅在审批后执行：

```sh
APP_ENV=production DATABASE_URL="$DATABASE_URL" sh /app/deploy/migrate-production.sh
```

预期输出包含 `applying migration: 0013_media_generation.sql` 和 `0014_comfyui_media_workflows.sql`，再次执行显示 `migration already applied`。成功验证：

```sql
SELECT media_type, count(*) FROM ai.workflows GROUP BY media_type;
SELECT code, status FROM ai.providers WHERE code = 'ark-video';
```

预期至少有一条 `video` workflow，且 `ark-video` 为 `disabled`。

## 3.1 Staging 可执行命令（在 Staging 主机仓库根目录执行）

先备份（失败可恢复）：

```sh
sh services/generation-service/deploy/backup-staging.sh
```

预期输出 `backup created: deploy/backups/generation-staging-<时间戳>.dump`。恢复演练：

```sh
container=$(docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yaml ps -q postgres)
docker cp deploy/backups/generation-staging-<时间戳>.dump "$container":/tmp/backup.dump
docker compose --env-file deploy/.env.staging -f deploy/compose.staging.yaml exec -T postgres sh -ec \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists /tmp/backup.dump'
```

> 正式回滚前应先恢复到临时库验证 dump 可读，再对目标库执行；`--clean --if-exists`
> 会覆盖现有对象，务必先确认容器与库名正确。

启动基础服务并执行迁移：

```sh
cd services/generation-service/deploy
docker compose --env-file .env.staging -f compose.staging.yaml up -d postgres redis
docker compose --env-file .env.staging -f compose.staging.yaml run --rm migrate
```

预期输出包含 `applying migration: 0013_media_generation.sql` 和
`0014_comfyui_media_workflows.sql`；再次执行显示 `migration already applied`。

验证迁移结果：

```sh
docker compose --env-file .env.staging -f compose.staging.yaml exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT media_type, count(*) FROM ai.workflows GROUP BY media_type"'
```

预期至少一条 `video` 且 `ark-video` Provider 为 `disabled`。

## 4. 发布与启用顺序

1. 发布兼容新字段的 Generation API/Worker。
2. 发布 Gallery Web Preview，确认生图不回归。
3. 在统一后台核对 `ark-video` 模型、会员积分价格、5/10 秒时长和内容政策。
4. 只在 Staging 依次启用视频模型、工作流和 Provider；确认工作流目录出现“生视频 / API 模型”。
5. 用测试账号生成 5 秒视频，验证状态 `pending → running → completed`、COS `videos/...` 对象、任务中心链接和积分结算。
6. 测试排队取消；运行后 UI 不应再显示取消按钮。
7. 审核日志不得出现 API Key、Authorization、临时完整响应或完整 Prompt。

生产启用前还必须用真实账单对比积分价格；不确定价格时保持 disabled。

## 4.1 启用（统一后台优先，SQL 只作可审计的等价操作）

Staging 专用；生产必须走变更审批，不得照抄：

```sql
UPDATE ai.providers SET status = 'active' WHERE code = 'ark-video';
UPDATE ai.provider_models SET is_enabled = true WHERE model_code = 'doubao-seedance-2-0-260128';
UPDATE ai.workflows SET is_enabled = true WHERE slug = 'api-ark-video-doubao-seedance-2-0-260128';
```

若 Staging Worker 直连本机 ComfyUI（按[本机联调指南](gallery-local-comfyui.md)配置），
额外启用：

```sql
UPDATE ai.providers SET status = 'active' WHERE code = 'comfyui';
UPDATE ai.workflows SET is_enabled = true WHERE slug = 'comfyui-ltx-video-v1';
```

模型与 binding 已在迁移 0014 中启用，不需要额外开启。启用后确认
`/create` 的“生视频 / API 模型”目录出现对应工作流。

## 4.2 端到端验收

1. 用测试账号登录 Gallery → `/create` → 生视频 → API 模型 → Seedance 2.0，
   提交 5 秒任务。
2. 预期状态 `pending → running → completed`；运行中不再显示取消按钮。
3. 核对任务、耐久资产与积分结算：

```sql
SELECT j.status, j.credits_reserved, j.credits_charged,
       a.object_key, a.mime_type, a.byte_size, a.duration_seconds
FROM ai.generation_jobs j
LEFT JOIN ai.generation_assets a ON a.job_id = j.id
WHERE j.user_id = <测试用户id>
ORDER BY j.created_at DESC LIMIT 10;
```

4. 核对积分账本（成功只结算一次，失败/取消只释放一次）：

```sql
SELECT * FROM ai.credit_ledger_entries
WHERE user_id = <测试用户id>
ORDER BY created_at DESC LIMIT 20;
```

5. 核对审计日志不包含密钥、Authorization、完整 Prompt 或临时完整响应：

```sql
SELECT action, resource_type, resource_id, created_at
FROM ai.audit_logs ORDER BY created_at DESC LIMIT 20;
```

6. 查看 Worker 日志，预期出现任务完成、资产持久化与积分结算，不出现敏感字段：

```sh
docker compose --env-file .env.staging -f compose.staging.yaml logs -f worker
```

7. 在 COS 控制台确认 `videos/<owner>/<job>/0.mp4`，抽查时长与 FPS。

8. 测试排队取消：pending 任务可取消且积分释放；进入 running 后 UI 不再提供取消。

## 5. 常见失败

| 现象 | 原因 | 恢复 |
| --- | --- | --- |
| 生视频 Tab 数量为 0 | Provider 仍 disabled、Worker 没有 Key 或模型未启用 | 检查统一后台与 Worker 环境；不要前端写死模型 |
| `No eligible provider` | binding 档位/状态不匹配或 Adapter 未注册 | 检查 `ark-video`、模型 tier、API Key，重启 Worker |
| 长任务 polling exhausted | 轮询总时长不足 | 提高 `GENERATION_POLL_MAX_ATTEMPTS` 后重启；先确认上游任务状态 |
| 视频下载超限 | 输出大于 `GENERATION_VIDEO_MAX_BYTES` | 评估实际成本/磁盘/COS 后调整，禁止直接取消上限 |
| COS 上传失败 | CAM、Bucket、Region、磁盘空间或网络 | 恢复权限/空间后重试；数据库任务不能手工标完成 |
| 运行中无法取消 | 上游不保证 running 取消 | 属于成本保护设计，等待完成；不得手工退款后放任上游计费 |

## 6. 回滚

1. 在统一后台禁用视频 workflow/model/provider，阻止新任务。
2. 等待运行任务终态，核对积分与上游账单。
3. 回滚 Gallery Web、Worker 和 API 镜像。
4. 保留 `media_type`、`generation_assets`、任务、账本和 COS 对象；它们是审计事实。

仅在确认所有旧镜像兼容、完成数据库备份并通过变更审批后，才编写新的反向迁移。不要直接 `DROP TABLE`，也不要批量删除 COS。

## 6.1 回滚 SQL（与统一后台禁用等价，先执行再回滚镜像）

```sql
UPDATE ai.workflows SET is_enabled = false WHERE media_type = 'video';
UPDATE ai.provider_models SET is_enabled = false
  WHERE provider_id IN (SELECT id FROM ai.providers WHERE code IN ('ark-video', 'comfyui'));
UPDATE ai.providers SET status = 'disabled' WHERE code IN ('ark-video', 'comfyui');
```

等待运行任务终态并核对上游账单后再回滚 Web/Worker/API 镜像；保留
`media_type`、`generation_assets`、账本与 COS 对象。
