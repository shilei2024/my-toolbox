# ADR-0004：以 ComfyUI Adapter + Tencent COS 构建首个生产生成链路

状态：Accepted  
阶段：Phase 4

## Why

在不改变 Phase 3 `ImageProvider` 契约的前提下，用 `ComfyUIProvider` 封装 HTTP、工作流节点和临时路径；用独立 `StorageProvider` 把生成与永久存储解耦。工作流采用外部不可变版本文件，成功图片统一进入腾讯云 COS，使前端只接触平台 URL，后续新增 OpenAI、Gemini、即梦等 Provider 时无需改变生成主流程。

## Alternatives Considered

- 在 Generation Service 业务层直接调用 ComfyUI API：文件最少，但 Provider 私有状态、节点和路径会污染核心层。
- 把 workflow JSON 嵌入 TypeScript：部署方便，但无法独立版本化、审计或安全回滚，历史生成也难以复现。
- 让前端直接访问 ComfyUI `/view`：省一次上传，但暴露内部 endpoint/文件名，临时输出不具备永久性。
- 继续使用 Cloudflare R2：S3 生态成熟，但已确认当前默认云为腾讯云；COS 与 CVM 同地域可降低时延和跨云流量费。
- 让 `ComfyUIProvider` 直接上传 COS：短期简单，但未来每个 Provider 都会重复存储、清理与补偿逻辑。
- WebSocket 监听 ComfyUI：实时性更高，但连接管理复杂；当前阶段选择可配置 polling，为 Phase 5 队列保持简单、可测试的 worker 边界。

## Future Impact

Phase 5 BullMQ worker 可以直接调用 Provider→Polling→Persistence 管线。Phase 6/7 可使用已保存的 workflow/provider/model/image/prompt-visibility 元数据构建 Gallery 与 SEO。Phase 9 Provider 只需实现统一接口；没有本地输出的 Provider 可直接返回 remote/base64，存储层仍统一持久化。新 workflow 必须发布新文件和 binding，不允许修改历史版本。

## Performance

与直接返回 ComfyUI 临时 URL 相比增加一次下载和一次 COS 上传，但换来可靠持久化与 CDN 能力。Loader 按 mtime/size 缓存并使用 O(1) Map 查找，参数注入与 schema 校验相对 GPU 推理耗时可忽略。轮询间隔决定状态延迟和 ComfyUI 请求量，生产默认建议 1 秒并通过环境变量调节。

## Cost

主要成本为 GPU 推理、COS 存储、PUT 请求和可能的出网/CDN 流量。CVM 与 COS 同地域减少跨地域流量；临时文件及时删除降低磁盘容量。外置工作流和统一 Provider cost 扩展点允许后续选择更便宜的模型/Provider。相比在 4 GB 协调节点强行运行模型，独立 GPU 节点成本更透明且可按需伸缩。

## Security

ComfyUI endpoint、节点、响应体、本地路径和 COS 凭证不进入前端响应。配置只从环境注入并启动时校验；生产优先使用最小权限短期 COS 凭证。下载限制在受控临时目录，远程输出只允许 HTTPS；工作流引用使用严格白名单格式，placeholder 不执行表达式。prompt 默认不写日志，全局 `/interrupt` 默认关闭，防止取消其他租户任务。

## Rollback Plan

先禁用 ComfyUI provider binding 或在 Selection Policy 中移除该候选，不改变前端。随后回滚 Generation Service 镜像和 workflow 清单；旧 `ImageProvider` 契约、Mock Provider、数据库和 COS 对象继续有效。若仅某个 workflow 失败，停用其新版本 binding 并恢复上一不可变版本。回滚不删除已生成图片和审计记录；临时目录可由受控清理任务回收。

