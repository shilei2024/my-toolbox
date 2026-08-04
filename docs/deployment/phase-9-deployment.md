# Phase 9 部署与回滚手册

## 部署顺序

1. 备份 PostgreSQL，在同版本临时实例完整 dry-run migration 0001–0004。
2. 执行 `0004_multi_provider.sql`；确认三个 Provider 均为 disabled。
3. 将 API key 通过 secret manager 注入 worker，并配置显式 Base URL、timeout、响应上限。
4. 部署 Generation Service，但保持新 Provider disabled；执行 health check 和无费用配置校验。
5. 为一个内部 workflow 添加单一新 binding，`max_attempts=1`、低流量灰度。
6. 在管理后台启用对应 Provider，验证实际 Provider、模型、COS 对象和 generation attempt 元数据。
7. 逐步提高流量，再配置第二候选；验证 429/5xx 才触发 fallback，content policy 不触发。

## 上线检查

- 前端生成请求和 Redis payload 不包含 Provider、model、Endpoint 或 API key；
- Gallery 永久 URL 来自腾讯云 COS，不是 OpenAI/Google/火山临时 URL；
- Admin API 只返回 `secretConfigured`，不返回 secret reference；
- 日志不含 prompt、Authorization、Base64 或供应商错误 body；
- 监控各 Provider success rate、429、5xx、ambiguous timeout、成本/图、fallback rate；
- 对 `all_providers_exhausted`、content policy 异常下降和重复计费告警。

## 回滚

1. 在 Phase 8 管理后台把新 Provider 设为 disabled；Registry 刷新后立即从路由排除。
2. 禁用相关 workflow binding，保留 ComfyUI binding；无需改前端或重新发布 Gallery。
3. 回滚 Generation Service 镜像。`provider_models` 表和 nullable `provider_model_id` 可安全留存，旧代码继续使用 `provider_model`。
4. 如必须撤销 schema，先确保没有 binding 引用 `provider_model_id`，再通过新的 forward migration 删除复合外键、字段、trigger 和表；不要修改 0004 历史文件。
5. 已完成图片和 COS 对象是业务事实，不随 Provider 回滚删除。疑似不确定超时的任务先按 request id 与供应商账单人工核对，不自动补发。
