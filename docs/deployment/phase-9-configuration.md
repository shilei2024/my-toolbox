# Phase 9 多 Provider 配置

## 运行时环境变量

远程 Provider 全部未配置时，Generation Service 仍可只运行 ComfyUI。任一远程 Provider 设置 API key 后，共享限制和对应 Base URL 都必须存在。

```dotenv
REMOTE_PROVIDER_REQUEST_TIMEOUT_MS=180000
REMOTE_PROVIDER_MAX_RESPONSE_BYTES=67108864

OPENAI_API_KEY=secret-manager-injected
OPENAI_BASE_URL=https://api.openai.com/v1

GEMINI_API_KEY=secret-manager-injected
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1

JIMENG_API_KEY=secret-manager-injected
JIMENG_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
```

代码不提供 Endpoint、timeout 或响应上限默认值，避免错误地域、代理或成本策略被静默接受。生产由腾讯云密钥管理/容器 secret 注入 API key；不得提交 `.env`。

## 数据库发布步骤

1. migration 创建 disabled Provider 和首批模型。
2. 运维设置 Provider `secret_ref` 为密钥引用标识，仅用于审计，不放明文。
3. 为 workflow version 创建 binding，并选择 `provider_model_id`。
4. 配置 `estimated_cost`、`timeout_seconds`、`max_attempts` 和 binding priority。
5. 先在管理后台启用 Provider，再灰度启用 binding。

新 binding 推荐同时保留 `provider_model` 文本快照，便于历史查询；运行时以 `provider_model_id -> model_code` 为准。

## Binding 配置白名单

| Provider | `provider_config` 可用字段 |
| --- | --- |
| OpenAI | `quality`: auto/low/medium/high；`moderation`: auto/low；`background`: auto/opaque |
| Gemini | `imageSize`: 512/1K/2K/4K |
| 即梦 | `watermark`: boolean；`guidanceScale`: 1–10；`optimizePromptMode`: standard/fast |

未知字段不会自动透传给第三方 API。新增参数必须在 Adapter 中显式验证、测试和记录，防止数据库配置变成任意请求注入通道。

## 路由建议

- 默认：ComfyUI priority 10，即梦 30，OpenAI 40，Gemini 50；值越小越优先。
- 质量敏感 workflow 可以通过 binding priority 覆盖全局顺序。
- `degraded` 只由健康检查写入；管理员只手工切 active/disabled。
- 首次上线将每个远程 binding `max_attempts` 设为 1，观察 429/5xx 和成本后再提高。
- Provider 凭证存在不等于自动启用；Registry、数据库 Provider、model 和 binding 四层都必须可用。
