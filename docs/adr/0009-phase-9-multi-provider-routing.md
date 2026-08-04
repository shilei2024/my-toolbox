# ADR-0009：薄 Provider Adapter、模型目录与安全故障转移

状态：Accepted  
阶段：Phase 9

## Why

平台需要接入 OpenAI、Gemini 和即梦，同时维持“前端永远不知道供应商”的边界。选择每家一个薄 REST Adapter 实现既有 `ImageProvider`，由数据库 Model Registry 保存模型身份，由 Registry/Selection Policy/MultiProviderExecutor 统一路由、重试和回退。所有输出仍进入通用校验与腾讯云 COS，供应商 SDK、临时 URL、凭证和响应类型不进入业务层。

## Alternatives Considered

- 前端直接调用各家 API：减少后端代码，但会暴露 Provider、凭证和计费逻辑，无法统一审计与回退。
- 在 Generation Service 业务代码中写 `if provider === ...`：初期快，但每加一家都会修改核心流程，拒绝采用。
- 引入所有官方 SDK：开发便利，但 SDK 类型、升级节奏和依赖树会侵入服务；当前 REST 契约很小，使用原生 Fetch 更稳定。
- 统一要求供应商临时 URL：响应更小，但 URL 有过期、签名泄露和 SSRF/下载域风险；选择 Base64 后统一写 COS。
- 任意失败都自动回退：可用性看似更高，但可能绕过内容政策、重复生成和重复计费，因此只回退明确安全的错误类别。
- 把最新模型写死在 Adapter：部署简单，但模型升级需要改代码；改由 versioned migration + binding 发布。
- 立即支持所有 Provider 图生图和批量：能力面更大，但输入图片下载、安全和每家数量语义不一致；Phase 9 先诚实声明 text-to-image、单输出能力。

## Future Impact

新增 Ideogram、Flux、Recraft 等只需实现 `ImageProvider`、注册配置并发布 provider/model/binding 数据。Phase 10 支付可以根据 binding estimate、Provider usage 和安全 attempt trace 结算积分。后续可加入分布式 health refresher、Provider 并发 limiter、地域/合规路由和真实成本报表，不改变前端。图生图扩展需要新增受控输入资产加载器，而不是让 Adapter 任意抓取用户 URL。

## Performance

远程 Provider 为同步 HTTP，省去轮询；Base64 会比二进制增加约三分之一传输与短期内存，但消除了第二次临时 URL 下载和域名验证。响应采用流式上限读取。候选排序为内存操作；Catalog 查询可在 worker 启动和配置刷新时缓存。故障转移会增加失败请求延迟，因此重试次数和总调用数均有上限。

## Cost

自有 ComfyUI 仍可保持第一优先，第三方 Provider 默认 disabled。定价不写进 Adapter，由 model/binding cost config 管理。明确 429/5xx 才允许有界重试；不确定 timeout/network outcome 不自动回退，减少重复账单。新增模型表和查询成本可忽略，主要新增成本是实际第三方图片调用。

## Security

API key 只来自 worker 环境/secret manager，数据库只存引用。每个 Adapter 白名单化参数和响应，限制响应字节，验证 Base64、格式和实际尺寸；错误响应、凭证、prompt 与图片内容不写日志。内容政策和业务 validation 不跨 Provider fallback。Provider/Model 复合外键阻止跨供应商错误绑定，disabled Provider 在数据库和 Registry 两层排除。

## Rollback Plan

先在管理后台禁用新 Provider，再禁用 workflow binding，即可立即回到 ComfyUI；前端和 Gallery 无需回滚。随后回滚 worker/Generation Service 镜像。`provider_models` 和 nullable `provider_model_id` 与旧代码向后兼容，可保留。确需移除时使用新的 forward migration，并先解除 binding 引用；已生成 COS 资产和业务记录不删除。不确定超时任务人工对账，不自动重放。
