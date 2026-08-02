# Phase 4：首个生产 Provider（ComfyUI）

状态：**完成并通过本地契约/集成测试**  
范围：只扩展 Phase 3 Provider 契约，不修改前端请求模型和 `ImageProvider` 接口。

## 目标与边界

Phase 4 把 ComfyUI 作为第一个生产级 `ImageProvider`，而不是把平台改造成“ComfyUI 专用系统”。Generation Service 只依赖 Provider、轮询和存储抽象；ComfyUI 的 API、节点、工作流 JSON 与本地输出路径只存在于 ComfyUI Adapter 内。

本阶段不包含 BullMQ、Gallery UI、SEO 页面、支付、积分或多 Provider fallback，这些仍按路线图留给后续阶段。

## 组件职责

| 组件 | 职责 | 禁止承担 |
| --- | --- | --- |
| `ComfyUIProvider` | 实现既有 Provider 契约、加载并注入工作流、映射状态和错误 | 返回内部路径、改变前端协议 |
| `ComfyUIClient` | `/prompt`、`/history/{id}`、`/view`、超时、重试、认证和取消 | 业务路由、COS 上传 |
| `WorkflowLoader` | 从外部目录加载 `name-vN.json`、schema 校验、缓存、摘要 | 在代码内保存工作流 |
| `PlaceholderInjector` | 递归注入白名单参数并保持数字类型 | 执行任意表达式、静默接受缺失参数 |
| `PollingService` | 把异步状态收敛为成功、失败、取消或超时 | 识别 ComfyUI 私有响应 |
| `StorageProvider` | 统一上传、删除和公网 URL 返回 | 暴露供应商密钥 |
| `TencentCOSStorage` | 首个永久存储实现 | 把 COS 逻辑写入 Provider |
| `ImagePersistenceService` | 临时文件物化、COS 上传、补偿删除、临时清理 | 永久保留 ComfyUI 输出 |

## 生产生成链路

1. Generation Service 根据 Phase 3 的 Registry/Selection Policy 取得 Provider 与 binding。
2. `ComfyUIProvider` 按 binding 中的 `providerWorkflowRef` 加载固定版本文件，例如 `portrait-v1.json`。
3. 注入 prompt、seed、尺寸、模型与采样参数；缺失或未知占位符返回类型化错误。
4. Client 提交 `/prompt`，轮询 `/history/{prompt_id}`，完成后通过 `/view` 下载到受控临时目录。
5. Provider 校验真实图片尺寸，只向通用管线返回临时的 `local-file` 输出。
6. 持久化服务把图片上传至腾讯云 COS，成功或失败均删除临时文件；多图中途失败时删除此前已上传对象。
7. 面向外部的响应只可包含 COS/CDN URL，不得包含 ComfyUI endpoint、节点、文件名或本地路径。

详见[生成时序图](./diagrams/phase-4-generation-sequence.svg)。

## 工作流版本与可复现性

- 文件引用只能是 `name-vN`，对应 `/workflows/name-vN.json`；修改行为必须发布新版本，禁止覆盖旧文件。
- Loader 记录 `workflowName`、`workflowVersion` 和原始文件 SHA-256 digest。
- Phase 2 数据库通过不可变 `workflow_version_id`、generation 快照字段、provider/model metadata 保存复现上下文。
- 示例工作流：`portrait-v1`、`anime-v1`、`food-v1`、`architecture-v1`。生产前需用 ComfyUI 的“Export (API)”结果替换示例 checkpoint，并保留占位符。
- 缓存以文件 mtime 与大小失效，支持部署后热读取；生产发布仍推荐不可变文件名和原子镜像发布。

## 状态、取消和错误

| 外部状态 | ComfyUI 判断 | 行为 |
| --- | --- | --- |
| `queued/running` | history 尚无结果或执行未完成 | 按环境变量间隔继续轮询 |
| `succeeded` | completed 且至少有一个 output image | 下载、验证、上传 COS |
| `failed` | execution error 或完成后无图片 | 映射为安全 `ProviderError` |
| `cancelled` | 调用方 signal 中止或取消成功 | 停止轮询并返回取消状态 |

取消首先向 `/queue` 发送指定 prompt id 的删除请求。`/interrupt` 会影响当前全局任务，因此默认关闭，仅在专用 ComfyUI 实例且明确接受影响时启用。原始响应体、堆栈、node id 和路径永不进入客户端错误。

## 日志与元数据

结构化日志包含 generation id、provider、workflow、总耗时、上传/存储耗时、重试序号和安全失败码。默认不记录 prompt；`GENERATION_LOG_PROMPTS` 只有在审计、访问控制和数据保留策略都配置后才允许开启。

成功结果保留 provider、workflow name/version/digest、model、实际尺寸、存储对象键、时间与 Phase 2 的 prompt visibility/slug 快照，为后续 Gallery 和 SEO 提供数据，不在本阶段构建 UI。

## 扩展点

- 新图片 Provider 只需实现既有 `ImageProvider`，不依赖 WorkflowLoader 或本地文件。
- 新对象存储只需实现 `StorageProvider`；S3、R2、OSS、MinIO 不影响 Provider。
- `ProviderBinding.providerModel` 与 `providerConfig` 是 Phase 9 Model Registry 的接入点。
- Phase 5 可在 Generation Service 外层加入 BullMQ；本阶段的 Provider、Polling、Persistence 可直接作为 worker 执行单元。

## 验证结论

- Phase 3 契约测试继续通过。
- 新增占位符、WorkflowLoader、配置、HTTP 重试/认证错误、Provider→Polling→COS、取消、超时和补偿清理测试。
- TypeScript `strict`、`exactOptionalPropertyTypes` 检查通过。

架构决策见 [ADR-0004](../adr/0004-phase-4-comfyui-cos-production-provider.md)。
