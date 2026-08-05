# M1 Generation 生产闭环

## 已交付

- `/create` 创作工作台与 Vercel 同源 BFF。
- 工作流列表、任务创建、查询和协作取消 API。
- PostgreSQL 幂等创建、积分预留/结算/释放、Outbox 与审计。
- 可运行的 Dispatcher 与 BullMQ Worker。
- Provider attempt、COS 资产与 Gallery 图片持久化。
- 四个稳定 workflow；Provider 默认 disabled，Mock 强制非生产。
- OpenAPI、架构、ADR、Preview 部署与回滚文档。

## 验证

- Generation Service typecheck 与 62 项测试通过。
- Gallery Web ESLint 与 Next.js 生产构建通过。

## M1.1 可用性补全

解决 M1 代码完成后仍无法开箱使用的四个缺口：

- 新用户积分：`BILLING_SIGNUP_GRANT`（默认 10）在用户首次打开账户汇总时幂等发放 `signup_grant`，新注册用户不再因 0 积分无法创建任务；设为 `0` 可完全关闭。
- 远端 Provider 绑定：新增 `0007_remote_provider_bindings.sql`，为四个 workflow 补齐 OpenAI / Gemini / 即梦 的默认模型绑定（Provider 默认仍为 disabled），管理员只需在后台启用即可路由，无需手写 SQL。
- 发布策略：`GALLERY_DEFAULT_MODERATION=pending|approved`（默认 pending）。`approved` 时公开图片在生成完成时直接写入 `published_at`，便于 Staging 快速验收；生产默认仍要求人工审核。
- 登录入口：Gallery Web 新增 `/login`、`/logout` 跳转路由、`/api/me/session` 会话路由和导航头登录/账号入口，通过 `MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL` 指向既有 Flask 登录页，修复定价页 `/login` 404 与访客无法发现登录入口的问题。

验证：Generation Service typecheck + 62 项测试、Gallery Web ESLint + SEO 测试 + 生产构建、Python 迁移契约测试 14 项全部通过。

## M1.2 创作工作台反馈闭环

解决"生成完成后只能看外链、失败后只能重填表单"的两个体验缺口：

- **最近任务列表**：`GET /v1/generations` 返回当前用户的最近生成任务（默认 24，最大 50），支持签名 keyset 游标分页与可选 `status` 过滤；任务只按 owner 可见，游标带 scope 与 HMAC，防跨用户遍历与篡改。
- **Prompt 回填**：`GenerationView` 增加 `prompt` / `negativePrompt`（仅用户本人与管理员可见），失败任务可在工作台一键回填原参数后重新创作，避免手工复制丢失参数。
- **内嵌预览**：任务完成后工作台直接通过既有 Gallery BFF（`/api/gallery/{slug}`）获取资产 URL 并内嵌展示图片，不再只有"查看作品"外链；最近任务面板同时显示完成缩略图。
- **历史任务操作**：最近任务面板支持点击查看状态、对排队/运行中任务发起取消、对失败任务回填重试；取消仍走原有幂等协作取消链路，积分释放逻辑不变。

实现边界：列表查询直接落在 `ai.generation_jobs`（PostgreSQL 事实源），不新增表、不引入新基础设施；游标复用 Gallery 签名编解码器，BFF 仅透传。该能力是未来 M3 平台任务中心在生成模块内的模块级前身，暂不做跨模块抽象。

验证：Generation Service typecheck + 65 项测试（新增列表权限/校验/游标/HTTP 契约）。Gallery Web ESLint + 11 项测试 + Next.js 生产构建。

## 待 Staging 验证

需要真实 PostgreSQL、Redis、COS、共享 Flask Session 和 Provider 才能完成数据库/对象存储/Vercel Preview 端到端验收。Preview 清单与发布批准完成前，生产发布为 No-Go。

## Staging 部署资产

- 增加非 root Node 容器镜像、隔离 PostgreSQL/Redis、API/Dispatcher/Worker 三进程 Compose 与 Caddy HTTPS 入口。
- 增加带迁移账本的单次迁移器、PostgreSQL 备份脚本和 4 CPU / 4 GB 低并发资源上限。
- 增加不含真实凭据的 Staging 环境模板和初学者部署、验证、恢复与回滚手册。
