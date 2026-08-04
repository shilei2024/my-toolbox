# M1 Vercel Preview 与 Generation Staging 验证

## 目的与边界

Vercel 只部署 `apps/gallery-web`。Generation API、Dispatcher、Worker、PostgreSQL、Redis 与 COS 必须在独立 Staging 环境；Preview 不得指向生产数据库、Redis、COS 或写凭据。

## 1. 数据库

备份 Staging 后按编号应用到 `0007_remote_provider_bindings.sql`。预期新增四个 workflow，ComfyUI/Mock Provider 默认均为 `disabled`，并为 OpenAI/Gemini/即梦 准备默认模型绑定。回滚采用禁用目录项，不删除已引用数据。

## 2. 后端进程

```bash
cd services/generation-service
npm ci
npm run typecheck
npm test
npm run gallery:start
npm run generation:dispatcher
npm run generation:worker
```

三个启动命令由 systemd/容器作为独立进程运行。成功日志分别包含 `gallery.api_started`、`queue.dispatcher_started`、`queue.generation_worker_started`。

Staging Mock：设置 `APP_ENV=staging`、`GENERATION_ALLOW_MOCK_PROVIDER=true`，并只在 Staging 数据库将 `mock` Provider 改为 `active`。Production 必须为 `APP_ENV=production` 且禁用 Mock。

Worker 新增变量：`GENERATION_TEMP_DIR`、`GENERATION_POLL_INTERVAL_MS`、`GENERATION_POLL_MAX_ATTEMPTS`、`GENERATION_REMOTE_DOWNLOAD_TIMEOUT_MS`、`GENERATION_PROVIDER_RETRY_BASE_MS`、`GENERATION_PROVIDER_MAX_TOTAL_CALLS`。Dispatcher 使用 `GENERATION_OUTBOX_POLL_MS`。API 使用 `GENERATION_DEFAULT_CREDIT_COST`。其余 Redis/BullMQ、COS、ComfyUI 与远程 Provider 变量沿用 Phase 4/5/9。

Worker 审核变量：`GALLERY_DEFAULT_MODERATION=pending|approved`（`approved` 仅用于快速验收公开画廊）。API 计费变量：`BILLING_SIGNUP_GRANT=10`（新用户首次汇总时发放；`0` 关闭）。

启用 ComfyUI 时还必须设置实际已安装的 `COMFYUI_DEFAULT_MODEL`；可选调节 `COMFYUI_DEFAULT_STEPS`、`COMFYUI_DEFAULT_CFG`、`COMFYUI_DEFAULT_SAMPLER`、`COMFYUI_DEFAULT_SCHEDULER`。默认采样参数仅是起点，模型文件名绝不在代码中猜测。

## 3. Vercel Preview 变量

- `GALLERY_SERVICE_BASE_URL`：Staging API HTTPS 网关。
- `GALLERY_INTERNAL_HMAC_SECRET`：与 Staging API 相同，至少 32 bytes。
- `MAVIS_AUTH_INTROSPECTION_URL`：Staging Flask `/auth/internal/gallery/session`。
- `GALLERY_INTROSPECTION_SECRET`：与 Staging Flask 相同。
- `GALLERY_PUBLIC_ORIGIN`：Preview 固定 Origin/branch alias。
- `MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL`：Staging Flask 的登录/退出页 HTTPS URL。

这些变量都禁止添加 `NEXT_PUBLIC_` 前缀。

Staging Flask 设置 `AI_IMAGE_EXTERNAL_URL=https://<preview-branch-alias>/create` 后重启，会在工具箱首页显示 AI 作图入口。变量为空或不是绝对 HTTPS URL 时入口自动隐藏。

共享登录要求 Flask 与 Gallery 使用同一受控父域：例如 `tools.staging.example.com` 与 `ai.staging.example.com`，Flask 设置 `SESSION_COOKIE_DOMAIN=.staging.example.com`、`SESSION_COOKIE_SECURE=true`。不要把 Cookie Domain 设到包含不受控子域的范围；普通 `*.vercel.app` Preview 无法读取业务域 Cookie，因此应使用受控 branch alias。切换前检查悬空 DNS，避免子域接管。

## 4. 构建

```bash
cd apps/gallery-web
npm ci
npm run lint
npm run test:seo
npm run build
npx vercel pull --environment=preview
npx vercel build
```

预期 `/create` 为静态页面，三个 Generation BFF 路由为动态 Route Handlers。

## 5. Preview 验收

1. 未登录能访问创作页但不能提交；登录后显示共享账户积分。
1. 新注册用户首次打开创作页/账单后积分到账（`signup_grant`），重复访问不重复发放。
2. 同一个 Idempotency-Key 重试只产生一个任务和一笔预留。
3. 状态收敛为 pending → running → completed，作品链接可打开，COS 与 asset 记录一致。
4. 排队/运行取消最终变为 cancelled，未消费积分释放。
5. 暂停 Redis 时 job/outbox 仍在 PostgreSQL；恢复 Dispatcher 后继续执行。
6. 浏览器 Console/Network 不出现 Provider、数据库、Redis、COS 密钥或堆栈。
7. `mindfulpenpal.com` 的 production deployment ID 不变化。

## 常见失败、恢复与回滚

- 没有工作流：Provider 仍 disabled、缺 binding 或 `0007` 未应用。
- 一直 pending：检查 Dispatcher、outbox `published_at` 与 Redis。
- 一直 running：检查 Worker、Provider、COS；不要手工改 completed。
- 401：检查 Flask introspection 和两个独立 HMAC secret。
- 积分不足：只通过 Staging 管理后台审计调整，不直接 UPDATE 账本。

回滚：隐藏 Flask AI 工具入口，停止 Dispatcher，优雅关闭 Worker，回滚后端镜像和 Vercel Preview；禁用 Provider/Workflow，保留业务与审计数据。
