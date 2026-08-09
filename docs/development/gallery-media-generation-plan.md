# Gallery 图片/视频创作工作流实施计划

状态：实现与本地验证完成，PR #28 已确认合入（`codex/gallery-generation-workflows`），
CI 全绿（Gallery/Generation/Python/PostgreSQL 集成含 phase13 + Vercel Preview）；
合入后进入 Staging 真凭据/成本/内容安全验收（可执行命令见 M4 部署文档 §3.1/§4.2）。

## 目标与验收标准

在现有 Gallery Web、Generation Service、PostgreSQL、BullMQ、Provider Registry、积分和 COS 链路上增加视频生成，且不复制任务、计费、存储或管理后台。验收标准：

1. 工作流目录可按 `mediaType=image|video` 与 `mode=workflow|api` 过滤，旧调用保持兼容。
2. 浏览器仍只提交 `workflowSlug`；服务端从版本化工作流和 binding 解析 Provider/模型。
3. 图片创建、查询、取消、积分结算、Gallery 展示无回归。
4. 视频任务可通过同一创建、查询、取消、队列和 Worker 链路调用火山方舟视频 API，将临时视频转存 COS，并在所有者创作页播放。
5. 视频 Provider、模型和工作流默认禁用；没有凭据或后台启用时不出现在目录中。
6. 类型检查、单元/契约测试、Next.js lint/build 通过；生产发布仍需 Preview/Staging 真凭据验收。

## Golden Rule 结论

1. **生产影响**：会增加数据库迁移、Worker Provider 和前端契约，但全部为向后兼容字段/表；视频入口 fail-closed，生产需单独审批启用。
2. **未来复用**：媒体类型、通用输出、持久化和任务输出契约可供后续音频/OCR 使用；图片 Gallery 的互动与 SEO 仍保持图片模块边界。
3. **低成本方案**：复用现有 Fastify、PostgreSQL、BullMQ、COS、Vercel BFF 和统一 Worker，不新增服务、队列或付费依赖。
4. **初学者部署**：只新增明确的环境变量、迁移和既有 npm 启动入口；部署文档提供预期结果、验证、故障与回滚。
5. **长期架构**：浏览器不感知 Provider，PostgreSQL 仍是事实来源，高风险状态幂等且可审计，符合平台边界。

## 架构与数据/API 变更

- `ai.workflows.media_type` 标记工作流输出媒体类型。
- 新增 `ai.generation_assets` 保存非 Gallery 图片的通用持久化输出；现有 `ai.images` / `ai.image_assets` 保持不变，避免高风险重写图片 Gallery。
- Generation Provider 契约扩展为图片/视频输出；Provider 能力显式声明支持的媒体类型与模式。
- 火山方舟视频适配器使用创建、查询、取消任务 API，成功后立即把临时 URL 转存 COS。
- `GET /v1/generation/workflows` 新增可选 `mediaType`；工作流和任务响应新增 `mediaType`，任务响应新增通用 `outputs`，原 `images` 字段保留。
- Next.js BFF 继续使用 Route Handler、同源校验和签名 Viewer Context；`/create` 增加图片/视频选择和视频结果播放。

## 影响文件

- 数据库：`services/generation-service/database/migrations/0013_media_generation.sql`
- Provider/流水线：`src/providers/`、`src/remote-providers/`、`src/pipeline/`、`src/queue/`
- API：`src/generation/`、`src/gallery/http-server.ts`、`docs/api/openapi-generation-v1.yaml`
- Web：`apps/gallery-web/src/components/generation-workbench.tsx`、生成类型与 BFF 路由
- 运维：Generation Service 环境变量示例、部署/排错说明
- 测试：新增媒体契约、Ark 视频适配器、工作流过滤和回归测试

## 风险与控制

- **成本失控**：视频工作流/Provider 默认禁用、一次只允许一个输出、时长白名单、积分成本由工作流版本配置。
- **大文件/内存**：视频下载流式落盘并设置字节上限，不把完整视频载入进程内存。
- **临时 URL 失效**：Worker 在任务成功后同步转存 COS，数据库只记录耐久对象。
- **重复计费**：继续使用用户幂等键、PostgreSQL job/outbox 和既有结算函数；Provider 重试受总调用上限约束。
- **私有内容泄漏**：视频输出只从 owner-scoped generation/task API 返回，本阶段不进入公共 Gallery feed。
- **Provider 变化**：适配器只实现官方稳定的创建/查询/取消边界，模型由数据库 binding 管理。

## 测试与发布

1. Generation Service 类型检查和全部单元测试。
2. PostgreSQL 迁移集成测试（有测试数据库时）。
3. Gallery Web lint、TypeScript、测试和 production build。
4. Vercel Preview + Staging Worker 使用测试账号生成短视频，验证取消、失败退款、COS 转存和回放。
5. 生产前备份数据库，先迁移，再发布兼容 API/Worker/Web，最后在统一后台启用 Provider/模型/工作流。

预计工作量：代码与单元测试 1–2 个工程日；Staging 真 Provider、成本参数与内容审核验收另需 0.5–1 个工程日。

## 回滚

先在统一后台禁用视频工作流/模型/Provider并停止新视频任务，再回滚 Web 和 Worker/API 镜像。`media_type` 与 `generation_assets` 为加法迁移，回滚期间保留数据；只在确认没有旧镜像依赖且已备份后，才通过单独迁移删除。已转存 COS 的对象按审计记录和生命周期策略处理，不直接批量删除。
