# ADR 0026: 本机 ComfyUI 通过 Generation Worker 接入 Gallery

## Status

Accepted — 2026-08-09.

## Why

Gallery 需要调用开发者电脑上的 ComfyUI 完成生图和生视频，但浏览器直连 8188 会暴露工作流、模型和本机服务，也绕过队列、积分、审计、Provider 路由与耐久存储。平台已经有 Generation API、PostgreSQL outbox、BullMQ、Worker 和 COS，因此应把 ComfyUI 保持为 Worker 侧 Provider Adapter。

## Decision

1. Gallery 仍只提交 `workflowSlug` 和工作流白名单参数；ComfyUI 地址、模型、工作流文件与采样配置全部由 Worker/binding 控制。
2. ComfyUI Adapter 同时声明 image/video 能力；图片读取 `outputs.images`，Video Helper Suite MP4 读取 `outputs.gifs`/`outputs.videos`。
3. Worker 下载 ComfyUI 输出并上传腾讯 COS 后才完成任务。ComfyUI 临时 URL 和本机文件都不是业务事实来源。
4. 本机 ComfyUI 只监听 loopback。生产中的远程 ComfyUI 必须放在私网或受控网络，并经过鉴权、TLS、容量和内容安全评审。
5. LTX 视频 workflow 和 binding 迁移默认禁用；本地启用不改变生产状态。

## Alternatives Considered

1. 浏览器直接调用 ComfyUI：实现快，但暴露本机端口和服务端控制，且绕过平台一致性，拒绝。
2. 新建独立 Video Service：会复制任务、积分、审计、队列和存储，当前规模成本过高。
3. 把 ComfyUI 输出 URL 直接写入任务：地址短期且不可审计，无法保证长期展示，拒绝。
4. 开发期只用 Mock：成本最低，但不能证明模型、VHS 输出、COS 和播放器真实兼容，不能作为完整验收。

## Future Impact

后续图生图、图生视频、音频、OCR 等 ComfyUI 工作流可继续通过同一 placeholder/binding 契约接入。若 Worker 与 ComfyUI 分离到不同机器，只改变受控 Provider endpoint，不改变浏览器、任务、积分和资产契约。

## Performance

LTX 是长时 GPU 任务。并发由 BullMQ Worker 控制，轮询有上限，视频下载有大小和超时限制；输出使用流式落盘/上传，避免占用 Node.js 大对象内存。模型加载和 121 帧推理耗时必须进入 Staging 容量基线。

## Cost

开发期复用本机 GPU 和现有 PostgreSQL/Redis/COS，不新增常驻服务。生产成本由 GPU Worker、COS 存储/流量和工作流积分价格覆盖；工作流默认禁用可避免意外消耗。

## Security

8188 不得公网暴露。浏览器不能提交 Provider、endpoint、模型或工作流路径；日志不记录密钥和完整 Prompt。COS 凭据只在 Worker 环境并使用最小权限。回环 HTTP 例外只用于相同 localhost origin，生产仍要求 HTTPS。

## Rollback Plan

禁用 LTX workflow/binding 或整个 ComfyUI Provider，阻止新任务；等待在途任务终态并核对积分与 COS。代码和 Worker 可回滚，但保留数据库迁移、任务、账本、审计和耐久资产，不执行破坏性清理。

