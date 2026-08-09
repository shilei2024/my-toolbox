# ADR 0024: 生图创作目录「工作流 / API」分离与公开默认值

## Status

Accepted — 2026-08-09.

## Why

`/create` 过去把所有创作方式混在同一个工作流列表中，用户无法区分「平台编排的
ComfyUI 风格工作流」和「直连官方模型的 API 模型」；同时新任务默认
`visibility=private`、`promptVisibility=hidden`，与「作品默认公开到画廊、Prompt
默认公开」的产品目标相反，导致用户漏选时作品不会进入公开画廊。

## Decision

1. `ai.workflows` 新增 `mode`（`workflow` | `api`）：既有的四个风格工作流保持
   `workflow`；每个已启用的 Provider 模型自动生成一个 `api` 模式工作流，绑定且
   仅绑定该 Provider + 该模型。`GET /v1/generation/workflows` 返回带 `mode` 的
   完整目录，并支持可选 `?mode=workflow|api` 过滤；`/create` 以「工作流 / API
   模型」两个 Tab 分开选择。
2. API 模式复用现有 workflow version + binding + 队列/Worker 流水线，不新增
   任务表、不引入第二套任务语义；浏览器仍然只提交 `workflowSlug`，服务端目录与
   校验不变。Provider 保持默认 disabled，因此 API 模式在管理员启用 Provider 前
   不会出现在创作目录（fail-closed）。
3. 默认值统一为公开：前端初始状态、workflow version defaults 的
   `visibility` 与 `prompt_visibility`、仓库解析回退全部改为 `public`。历史已创建
   的私有/隐藏作品不回填，尊重用户既有选择。

## Alternatives Considered

1. 新增独立 `ai.generation_api_models` 表与「无 workflow」任务：更彻底地把 API
   模式从工作流解耦，但需要改动 `generation_jobs.workflow_version_id NOT NULL`、
   Worker claim、Gallery 快照等多处契约，风险与迁移成本远高于收益；工作流版本化
   输入 schema + binding 已经能表达「直连某个模型」。
2. 仅前端分组、后端不区分 mode：UI 能分开，但 API 目录、后台审计和未来按
   mode 的策略（如限流、定价）缺少稳定标识，不满足长期架构。

## Future Impact

未来新 Provider 模型启用时自动出现 API 创作方式；按 mode 扩展限流、定价或展示
策略无需改表结构。若未来出现真正无 workflow 的任务类型，可在不破坏现有目录
契约的前提下新增任务来源抽象。

## Performance

目录查询仅多返回一列并可按 mode 走索引过滤；API 模式任务与现有任务共用队列、
Worker 与存储，不增加基础设施或额外往返。

## Cost

不新增服务、表或依赖。唯一数据成本是每启用模型多一行 workflow + version +
binding（PostgreSQL 内极低），以及迁移 0012 的一次性 UPDATE。

## Security

API 模式没有把 Provider 密钥、模型 endpoint 或内部路由暴露给浏览器；创建请求仍
只接受 `workflowSlug`，Provider/model 选择始终在服务端 binding 中解析。mode 查询
参数走既有 HMAC Viewer Context 与 BFF 白名单。默认公开只影响新任务默认值，
不改变审核门禁（`GALLERY_DEFAULT_MODERATION`）与私有作品权限。

## Rollback Plan

回滚 Next.js 工作台 Tab 与默认值即可恢复旧 UI；Generation Service 可回滚
`mode` 字段与过滤逻辑（旧版本忽略多余字段）。数据库迁移 0012 只新增列与目录
数据：若需撤销，删除 API 模式 workflow（其 job/image 引用为空时可删；如已有
任务引用则保留并禁用），`mode` 列可保留或通过新迁移删除。Provider 与既有
workflow 数据不受影响。
