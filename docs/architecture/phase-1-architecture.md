# AI Image Community — Phase 1 系统架构设计

状态：**待架构确认**  
范围：只定义系统边界、职责、调用关系、非功能要求和演进路径；不包含数据库表、API 字段或业务代码。

## 1. 架构结论

采用“**保留现有 Flask 站点 + 新建内部 Generation Service + 独立 Worker**”的渐进式架构。

- 现有 Flask/Jinja 继续承担网站入口、现有用户体系和工具导航，避免为了 AI 图片功能重写整站。
- 新建 NestJS Generation Service，作为所有图片生成请求的唯一业务入口。
- Provider 选择、重试、降级、队列、日志、计费、审计全部属于 Generation Service，不能进入前端、Flask 页面路由或具体 Provider Adapter。
- Provider Adapter 只负责把统一请求翻译成供应商协议，以及把供应商结果翻译回统一结果。
- 图片生成成功后必须先写入对象存储，再持久化元数据；应用服务器和 GPU 节点都不是永久存储。
- PostgreSQL 是业务事实来源，Redis/BullMQ 只承担短期任务调度，不能成为任务唯一记录。
- 初期采用模块化单体而非拆分大量微服务；高负载部分仅将 API 与 Worker 分进程部署，后续可水平扩容。

总体架构图见 [overall-architecture.svg](diagrams/overall-architecture.svg)。

## 2. 两个核心优势

1. **供应商可替换，业务保持稳定**：前端、Gallery、会员和计费只依赖统一 Generation API。增加 OpenAI、Gemini、即梦或更换 ComfyUI 集群时，不修改前端调用协议。
2. **治理能力集中，成本与风险可控**：路由、限流、重试、降级、内容审核、账单、审计和监控只实现一次，可按成本、健康度、能力与用户等级统一决策。

## 3. 当前系统与目标边界

### 当前状态

仓库是 Flask 3 + SQLAlchemy + Flask-Login + Jinja/Bootstrap 的工具站。现有 AI 作图模块把 Provider 类、HTTP 调用、内存任务状态、本地文件保存和路由放在同一模块中。它适合原型，但不满足持久任务、对象存储、审计、横向扩容和 Provider 隔离要求。

### 目标边界

| 边界 | 负责 | 明确不负责 |
| --- | --- | --- |
| Web Experience | 页面、表单、轮询/事件展示、SEO 渲染、用户交互 | Provider 选择、供应商密钥、重试与降级 |
| Flask Web/BFF | 复用现有登录态、页面路由、CSRF、签发内部用户上下文 | 调用 ComfyUI 或第三方图片 API |
| Generation Service | 请求校验、幂等、任务生命周期、策略路由、配额预留、审计、Gallery 元数据访问 | 执行耗时生成、永久保存临时文件 |
| Generation Worker | 消费任务、调用 Provider Adapter、上传对象存储、回写结果、触发审核 | 对外提供浏览器 API |
| Provider Adapter | 协议转换、供应商错误归一化、取消和状态查询 | 业务权限、计费规则、全局重试策略 |
| Moderation Pipeline | 提示词/图片审核、公开状态决策、人工复核入口 | 图片生成路由 |
| PostgreSQL | 用户引用、任务、图片、配置、互动、计费与审计事实 | 消息队列 |
| Redis/BullMQ | 排队、延迟重试、并发控制、短期进度事件 | 长期任务事实和账本 |
| Object Storage | 原图、缩略图、衍生图的永久对象 | 权限与业务元数据判断 |

## 4. 推荐技术栈

| 层 | 选择 | 原因 |
| --- | --- | --- |
| 现有站点 | Flask/Jinja，继续保留 | 最低迁移风险，复用现有账号和后台 |
| Generation API | NestJS + TypeScript | 模块边界、依赖注入、Provider Pattern 与 BullMQ 生态成熟 |
| Worker | NestJS standalone worker + BullMQ | 与 API 共用领域契约，但可独立扩容和部署 |
| 数据库 | PostgreSQL | 事务、JSONB、索引、全文/筛选能力适合任务与 Gallery |
| 队列/缓存 | Redis + BullMQ | 延迟重试、优先级、并发和任务事件支持完整 |
| 对象存储 | 腾讯云 COS 优先，内部 Storage Adapter | 与默认云资源统一；可替换 R2、OSS 或 S3 |
| 图片 CDN | COS 加速域名/腾讯云 CDN | 应用不代理大文件，降低带宽和 CPU 成本 |
| GPU Provider | ComfyUI 首选 | 自有工作流、成本可控；GPU 节点可按需启停 |
| 可观测性 | 结构化日志 + OpenTelemetry 接口 + Sentry/Prometheus 可选 | 先低成本落日志，保留后续扩展能力 |

Next.js 不作为 Phase 1–5 的前置依赖。到 Gallery/SEO 阶段，再根据流量和开发成本决定是否让 Next.js 接管 `/gallery`；无论页面由 Flask 还是 Next.js 渲染，都只能调用统一业务 API。

## 5. Generation Service 内部模块

Generation Service 初期是一个可独立部署的**模块化单体**，模块间通过接口协作：

- `Generation`: 创建、取消、查询任务，维护状态机与幂等键。
- `Routing Policy`: 根据工作流能力、Provider 健康度、成本上限、用户等级和管理员策略选择候选 Provider。
- `Provider Registry`: 注册 Adapter 与能力描述，不包含业务路由规则。
- `Workflow Catalog`: 将公开 workflow ID 映射到版本化的内部工作流定义；不把 ComfyUI JSON 暴露给浏览器。
- `Asset`: 校验输出、上传对象存储、生成对象键和衍生图。
- `Gallery`: 管理图片公开性、Prompt 可见性和读模型。
- `Moderation`: 生成前 Prompt 检查、生成后图片审核及人工复核状态。
- `Entitlement/Billing`: 配额检查、额度预留、结算、失败释放；Phase 10 接支付时不改生成主流程。
- `Audit`: 记录管理操作、路由决策、Provider 调用和敏感数据访问。
- `Admin`: Provider、Workflow、路由策略和运行状态的受控管理入口。

## 6. 核心调用链

1. 登录用户在 Generate 页面提交“工作流 + 参数 + 隐私设置”，浏览器不提交 Provider 名称或密钥。
2. Flask/BFF 验证现有会话并向 Generation Service 传递签名用户上下文；未来 Next.js 也使用同一认证网关契约。
3. Generation Service 校验权限、内容与幂等键，预留额度，在 PostgreSQL 创建 `pending` 任务。
4. 写库成功后通过可靠投递机制进入 BullMQ；API 立即返回公开 job ID。
5. Worker 原子领取任务，将状态变为 `running`，Routing Policy 选择 Provider，Adapter 发起生成。
6. 对可重试错误按策略退避；达到阈值后选择满足同一能力约束的 fallback Provider。每次尝试均单独记录。
7. Worker 校验图片，上传对象存储，创建图片元数据并触发审核；本地临时文件在成功上传和校验后删除。
8. 任务进入 `completed` 或 `failed`；配额完成结算或释放。浏览器通过轮询起步，未来可升级 SSE/WebSocket。
9. 只有 `public + approved` 图片进入公开 Gallery 和 SEO 页面；隐藏 Prompt 只向 owner/admin 返回，私有图片不进入公开索引。

## 7. 任务状态与可靠性原则

公开任务状态限定为：`pending → running → completed | failed | cancelled`。

- `completed` 必须意味着对象已持久化、图片元数据已提交，不能只表示 Provider 返回成功。
- 状态迁移由服务端控制，客户端请求不能直接设置任务状态。
- 每个创建请求带幂等键，防止刷新、超时重试造成重复扣费和重复生成。
- PostgreSQL 保存任务事实；BullMQ job 丢失时可由 reconciliation 扫描恢复。
- Worker 使用租约/心跳防止永久 `running`；超时任务可安全重新入队。
- 取消采用“请求取消 + Adapter 尽力取消 + Worker 提交前再次检查”的协作语义，不承诺所有供应商都能立即停止计费。
- 重试只针对超时、限流和临时 5xx；参数错误、鉴权错误和审核拒绝不自动重试。
- fallback 必须满足工作流能力、尺寸、隐私区域与成本上限，不能无条件换 Provider。

## 8. Provider 解耦规则

统一 Provider 能力契约至少表达：生成、取消、查询状态、健康检查、支持的模型/尺寸/工作流类型和成本估算。具体方法签名在 Phase 3 定义。

强制约束：

- 浏览器响应可以展示“实际生成模型/Provider”作为图片元数据，但不能用它控制路由。
- Provider API key 只存在于服务端密钥存储/环境变量，不写数据库明文、不返回前端。
- 业务代码只依赖领域请求/结果和标准错误分类，不依赖 ComfyUI prompt ID、OpenAI response ID 等供应商对象。
- 原始供应商响应可加密/脱敏后用于审计，但不能成为核心业务表的唯一数据格式。
- Workflow 使用稳定公开 ID + 不可变版本；Provider Adapter 负责解析相应版本。

## 9. 安全与隐私基线

- 外网只暴露 Web/BFF 或 API Gateway；Generation Service、Redis、PostgreSQL、Worker 和 ComfyUI 位于私网。
- Flask 到 Generation Service 使用短时签名 token 或 mTLS，并传递 user ID、role、request ID；不能信任浏览器自报身份。
- 下载默认使用 CDN/签名 URL。私有图片不能依靠“难猜 URL”，必须经过授权或短时签名。
- Prompt、负面 Prompt 和工作流参数按隐私级别字段级过滤；日志默认不输出完整隐藏 Prompt。
- Provider 回调必须验签、防重放；后台写操作要求 admin 权限、CSRF/二次确认和审计记录。
- 上传/输出校验 MIME、真实文件头、像素上限和文件大小；对象键由服务端生成。
- 内容审核采用“生成前文本 + 生成后图片”双阶段，公开发布默认 fail-closed。
- 为删除、封禁、DMCA、数据导出和审计保留可追踪的业务流程。

## 10. 部署拓扑与低成本策略

### 起步部署

- 现有 Flask 实例保持不变。
- 一台低配 CPU 主机运行 Generation API、Worker、PostgreSQL 和 Redis（生产上使用独立进程与持久卷）。
- ComfyUI 放在按需 GPU 云主机；无任务时关机或缩容。
- 腾讯云 COS 保存原图与缩略图，腾讯云 CDN 或 COS 加速域名直接分发。

### 扩容顺序

1. 先将 Worker 与 Web/API 分机，避免 GPU/API 延迟拖垮页面请求。
2. 再增加 Worker 副本，并按 Provider/工作流设置独立并发和队列。
3. PostgreSQL 切托管或独立节点，Redis 切高可用；API 保持无状态横向扩容。
4. Gallery 流量上升后增加 CDN 缓存、读副本/搜索索引；不提前引入 Elasticsearch。
5. 多地域需求出现后，再按数据合规与 Provider 区域拆分 Worker 池。

## 11. 可观测性与审计

每次请求贯穿 `request_id / job_id / attempt_id / user_id`，至少记录：

- 任务状态迁移及操作者。
- Provider 路由候选、最终选择和 fallback 原因。
- 排队时间、生成时间、上传时间、审核时间和端到端耗时。
- Provider 错误分类、重试次数、取消结果和健康状态。
- 估算成本、实际成本、额度预留/结算/释放。
- 管理员对 Provider、Workflow、策略、图片和用户的变更。

日志中不得记录 API key、签名 URL 查询串、完整隐藏 Prompt 或原始支付凭据。

## 12. 十阶段实施路线

| 阶段 | 内容 | 预计代码量 | 完成门槛 |
| --- | --- | --- | --- |
| Phase 1 | 系统架构设计（无代码） | ⭐ | 边界、职责、调用链、技术决策和风险确认 |
| Phase 2 | 数据库设计 + ER 图 | ⭐⭐ | 迁移可回滚；约束、索引、隐私与审计模型通过测试 |
| Phase 3 | Provider 抽象层 | ⭐⭐ | 契约测试 + Mock Provider；业务层无供应商依赖 |
| Phase 4 | ComfyUI 接入 | ⭐⭐⭐ | 真实/模拟工作流端到端、取消、超时与输出校验通过 |
| Phase 5 | Redis/BullMQ 队列 | ⭐⭐⭐ | 重试、幂等、崩溃恢复、并发和取消测试通过 |
| Phase 6 | Gallery 系统 | ⭐⭐⭐⭐ | 权限、隐私、互动、分页、对象存储与删除流程通过 |
| Phase 7 | SEO 页面 | ⭐⭐ | SSR 元数据、canonical、OG、JSON-LD、sitemap 验证通过 |
| Phase 8 | 管理后台 | ⭐⭐⭐ | RBAC、Provider/Workflow 管理和审计测试通过 |
| Phase 9 | 多 Provider（OpenAI、Gemini、即梦等） | ⭐⭐⭐⭐ | Adapter 契约、能力路由、fallback 与成本策略通过 |
| Phase 10 | 支付、积分、会员体系 | ⭐⭐⭐⭐ | 账本一致性、幂等回调、退款/补偿和并发扣减通过 |

每阶段只推进一个目标：设计/实现 → 自动化测试 → 集成验证 → 回归测试 → 阶段验收。上一阶段未确认，不进入下一阶段。

## 13. Phase 1 验收检查

- [x] 前端不知道并且不能指定实际 Provider。
- [x] Provider 选择、重试、队列、fallback、日志、计费、审计集中在 Generation Service。
- [x] 现有 Flask 站点有清晰的渐进接入路径，无需先重写整站。
- [x] PostgreSQL、Redis 与对象存储职责互不混淆。
- [x] 图片永久保存、临时文件清理和公开审核顺序明确。
- [x] 用户、隐私、管理员与删除权限边界明确。
- [x] 单机低成本起步与横向扩容路径均成立。
- [x] 后续十个阶段的依赖顺序和完成门槛明确。

## 14. 需要确认的架构决策

进入 Phase 2 前，请确认以下默认方案：

1. 保留现有 Flask 站点，不立即重写；新建独立 NestJS Generation Service。
2. PostgreSQL 作为业务事实来源，Redis/BullMQ 仅作队列；腾讯云 COS 作为首选对象存储。
3. ComfyUI 是默认低成本 Provider，第三方 Provider 仅用于能力补充或故障降级。
4. Gallery/SEO 到 Phase 6–7 再决定继续 Flask SSR，还是由 Next.js 渐进接管 `/gallery`。
