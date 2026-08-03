# AI Image Community — Phase 3 Provider 抽象层

状态：**实现完成，待阶段确认**  
范围：统一 Provider 领域契约、能力路由、Registry、错误模型与 Mock Provider。

## 1. 设计目标

Generation Service 的业务层只依赖 `ImageProvider`，不能导入 ComfyUI、OpenAI、Gemini、即梦等 SDK 或响应类型。浏览器请求中没有 Provider 名称、API Key、base URL 或供应商模型路由字段。

Phase 3 核心代码保持框架无关。未来 NestJS 通过依赖注入装配 Registry、数据库 binding repository 和具体 Adapter；领域契约本身不依赖 NestJS。

## 2. 统一契约

`ImageProvider` 规定所有 Adapter 必须实现：

- `generate()`：提交生成，允许同步成功或返回异步任务。
- `cancel()`：尽力取消供应商任务。
- `getStatus()`：轮询供应商任务并返回统一状态。
- `healthCheck()`：供路由与运维检查健康度。
- `estimateCost()`：在提交前给出统一币种的估算成本。

统一输入包括：

- Job ID 与版本化 Workflow 引用。
- text-to-image / image-to-image 模式。
- Prompt、Negative Prompt、尺寸、数量、Seed。
- Provider 无关的扩展参数。
- request ID、attempt ID、deadline 和 AbortSignal。

Provider binding 来自服务端数据库，包含 Provider code、Provider workflow 引用、模型、非敏感配置、优先级、成本、超时和最大尝试次数。它不会由浏览器提交。

## 3. 结果与状态

Provider 输出统一为三种来源：

- Base64 内容。
- 远程临时 URL。
- Worker 本地临时文件。

三种结果最终都由后续 Asset/Storage 流程校验并上传腾讯云 COS。Adapter 返回的 URL 永远不能直接成为永久 Gallery URL。

Provider 状态统一为：

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

Generation Service 再把它映射到 Phase 2 的公开 Job 状态机。

## 4. 能力声明与选择策略

每个 Provider 声明：

- 支持的生成模式、Workflow 类型和模型。
- 最小/最大宽高及最大输出数量。
- 是否支持 Seed、取消和状态轮询。
- 当前 availability 与 Provider 级优先级。

`ProviderSelectionPolicy` 只返回满足请求能力和启用 binding 的候选列表，排序规则为：

1. `active` 优先于 `degraded`，`disabled` 被排除。
2. Workflow binding 优先级。
3. Provider 全局优先级。
4. 预计成本。
5. Provider code，作为稳定的最终排序条件。

调用者保留完整候选列表，Phase 4/5 可以按顺序执行 retry/fallback，无需修改 Provider Adapter。

## 5. 标准错误模型

错误分类固定为：

- `configuration`
- `authentication`
- `validation`
- `content_policy`
- `rate_limit`
- `timeout`
- `unavailable`
- `upstream`
- `cancelled`
- `unsupported`
- `unknown`

默认只有 `rate_limit/timeout/unavailable/upstream` 可重试。未知异常会被转换为固定安全消息，原始异常只保留在 `cause`，不会通过安全日志记录或 API 返回，防止 Token、URL 签名和 Provider 原始响应泄露。

## 6. Registry

`ProviderRegistry` 使用稳定 code 注册 Adapter：

- 拒绝空 code。
- 拒绝重复注册，防止启动顺序覆盖真实 Provider。
- 对未知 Provider 明确失败，不静默回退到默认供应商。
- 可列出或注销 Adapter，方便测试与未来动态装配。

“未知 Provider 自动使用默认 Provider”的旧模式被明确禁止，因为它会造成错误计费、隐私区域错误和不可解释的 fallback。

## 7. Mock Provider

Mock Provider 是 Phase 3 的参考实现与契约测试基准：

- 支持同步和异步两种模式。
- 支持确定性时钟、轮询、完成和取消。
- 支持注入标准 ProviderError。
- 返回零成本估算及固定图片输出。
- 不进行网络请求，不依赖 Provider SDK。

Phase 4 的 ComfyUI Adapter 必须复用同一套契约测试，不允许为 ComfyUI 增加业务层特例。

## 8. 文件结构

```text
services/generation-service/
├── database/migrations/0001_initial.sql
├── src/providers/
│   ├── capabilities.ts
│   ├── errors.ts
│   ├── image-provider.ts
│   ├── index.ts
│   ├── mock.provider.ts
│   ├── registry.ts
│   ├── selection-policy.ts
│   └── types.ts
├── test/provider-contract.test.ts
├── package.json
├── package-lock.json
└── tsconfig.json
```

## 9. 与旧 Flask AI 作图模块的关系

> 状态（2026-08）：旧 Flask `tools/ai_image` 已被移除，AI 作图入口切换为可配置的外部链接（指向独立部署的 Generation Service + Gallery Web）。本节保留历史说明。

旧实现 `tools/ai_image/__init__.py` 曾包含 Provider、HTTP 路由、内存任务和本地文件保存，是渐进迁移对象。切换顺序：

1. Phase 4 完成 ComfyUI Adapter。
2. Phase 5 完成持久任务与 BullMQ。
3. Flask 改为调用内部 Generation API。
4. 验证新链路后删除旧 Provider 和 `_TASKS` 内存状态。

替换落地方式（2026-08 已执行）：

- 删除 `tools/ai_image/`、`templates/tools/ai_image/` 及 `/tools/ai-image` 路由注册。
- `tools_config.yaml` 中 `ai_image` 改为外部入口（`external_url` 字段）：为空时首页隐藏，填入新链路 Gallery 地址并重启后自动显示并跳转。
- 工具注册机制（`tools/__init__.py` / `models.Tool.external_url`）支持任意外部链接工具，后续可复用。

## 10. Phase 3 验收标准

- [x] 浏览器侧 Generation Request 不含 Provider、密钥或 base URL。
- [x] `ImageProvider` 覆盖 generate/cancel/getStatus/healthCheck/estimateCost。
- [x] Registry 拒绝重复和未知 Provider。
- [x] 能力过滤和候选排序不依赖具体 Provider 类。
- [x] Provider 错误经过统一分类、重试判断和安全脱敏。
- [x] Mock Provider 覆盖同步、异步、轮询和取消。
- [x] TypeScript strict 类型检查通过。
- [x] Provider 契约测试及现有 Python 回归测试通过。

### 验证记录

- TypeScript strict 类型检查：通过。
- Provider 契约测试：8/8 通过。
- Phase 2 Schema 与现有报销模块回归测试：23/23 通过。
- npm dependency audit：0 个已知漏洞。
- 测试全程使用 Mock Provider，没有调用外部图片服务。

## 11. Phase 4 输入边界

Phase 4 只新增 ComfyUI Adapter、Workflow JSON 模板解析、ComfyUI HTTP/WebSocket 客户端、输出下载和契约测试。仍不接 BullMQ；生产异步调度留到 Phase 5。
