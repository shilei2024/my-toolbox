# ADR 0025: Gallery 复用 Generation 闭环扩展图片与视频

## Status

Accepted — 2026-08-09.

## Why

Gallery 已有成熟的图片工作流、Provider、队列、积分、COS、任务中心和 BFF。视频生成是长任务且输出体积更大；若另建视频任务表、队列、计费或后台，会制造双写、一致性和运维成本。另一方面，直接把视频塞进图片 Gallery 表会混淆审核、缩略图、转码、互动和 SEO 语义。

## Decision

1. `ai.workflows` 增加 `media_type=image|video`，同一工作流目录和 Generation API 通过可选媒体过滤扩展；浏览器仍只提交 `workflowSlug`。
2. Provider 执行契约扩展为媒体生成契约，显式声明媒体类型；图片适配器保持原行为，新增火山方舟异步视频适配器。
3. 图片继续写入 `ai.images` / `ai.image_assets` 并进入现有 Gallery；视频先写入通用 `ai.generation_assets`，仅通过 owner-scoped 任务/创作 API 返回。
4. 视频成功后必须先转存 COS，再原子完成任务和积分结算。Provider 临时 URL 不是业务事实。
5. Ark 视频 Provider、模型与工作流默认禁用；配置凭据、Staging 验收和管理员启用全部完成后才可见。

## Alternatives Considered

1. 独立 Video Service、表和队列：隔离明显，但会复制任务、积分、审计、取消、重试和部署，在当前规模下成本过高。
2. 把视频直接存入 `ai.images`：改动较小，但会破坏表名和字段语义，并迫使公共 Gallery 立即承担视频转码/封面/SEO。
3. 前端直连方舟：拒绝；会暴露密钥与 Provider 契约，也无法保证长任务、转存、积分和审计一致性。

## Future Impact

公共视频 Gallery 应在封面、转码、审核、播放统计和 SEO 策略明确后，以媒体展示投影或专用视频内容表接入；任务与底层耐久资产无需重建。第二个非图片模块接入时，再评估把 `generation_assets` 提升为跨模块资产服务。

## Performance

视频流式下载到受控临时目录并上传 COS，设置响应大小与超时上限，避免占用大量 Node.js 堆内存。队列仍只传 job ID，长任务并发由现有 Worker 配置控制。

## Cost

不新增基础设施。视频推理成本由工作流版本积分价格和 Provider binding 管理；默认禁用与时长白名单防止意外消费。

## Security

Ark API Key 只存在 Worker 环境；BFF 与内部 HMAC 边界不变。只接受 HTTPS 输出 URL、允许的视频 MIME、受限体积和受控临时路径。视频输出暂不进入公共 feed，错误继续脱敏。

## Rollback Plan

禁用视频 workflow/model/provider，停止新建任务，再回滚 Web 与服务镜像。加法数据库结构和已有 job/asset 记录保留；不降级或删除已计费事实。COS 对象通过生命周期/审计流程处理。
