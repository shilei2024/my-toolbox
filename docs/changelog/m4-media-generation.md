# M4 · Gallery 图片/视频生成（生图/生视频）

## 已交付

- 统一媒体契约：`ai.workflows.media_type`（image/video）、目录 API 双维度过滤
  （mediaType × mode）、`GET /v1/generation/workflows` 带视频时长/尺寸约束。
- 视频生产链路：火山方舟异步视频 Adapter（创建/查询/取消）、5/10 秒时长白名单、
  流式受限下载、COS `videos/` 耐久化与 `ai.generation_assets`；复用既有队列、
  积分、审计与任务中心，浏览器只提交 `workflowSlug`。
- 本机 ComfyUI：ComfyUI Adapter 扩展为图片/视频共用 Provider，支持 Video Helper
  Suite MP4 输出、LTX 2.3 API workflow、服务端随机 seed 与 server-owned 模型/采样
  参数；迁移 0014 默认 fail-closed。
- Gallery Web：`/create` 生图/生视频切换、视频时长选择与结果播放；任务中心显示
  图片/视频分类与 owner-only 视频输出；运行中视频不接受用户取消。
- 部署资产：`.env.production.example` / `.env.staging.example` 补齐视频与 ComfyUI
  变量、preflight 支持仅视频 Provider、本机 ComfyUI 联调指南与 M4 部署/回滚文档。

## 验证

- Generation Service typecheck + 93 项单元/契约测试通过（含 Ark Adapter、
  VideoPersistenceService、ComfyUI 视频输出与工作流加载）。
- Gallery Web lint + 15 项测试 + Next.js 生产构建通过；Python 116 项测试通过。
- 本地真实链路：ComfyUI 生图与 960×544、24 FPS、121 帧、约 5.04 秒 LTX 视频；
  结果均上传 COS、写入耐久资产并完成积分结算。

## 待 Staging/生产验收

1. 备份并迁移 0013/0014（生产 dry-run 后执行）。
2. 在统一后台启用视频 Provider/模型/工作流，只允许测试账号生成。
3. 验证视频完成、COS 转存、任务中心播放、积分结算与排队取消。
4. 对账上游账单与平台积分价格，确认成本可控后按灰度放量。
5. 审核日志与公开接口不得出现 API Key、临时 URL 或完整 Prompt。

## 回滚

先禁用视频 workflow/model/provider 阻止新任务，等待运行任务终态，再回滚
Web/Worker/API 镜像；保留 `media_type`、`generation_assets`、账本与 COS 对象。
