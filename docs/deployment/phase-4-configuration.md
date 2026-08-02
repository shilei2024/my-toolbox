# Phase 4 配置手册

所有运行参数只从环境变量读取。服务启动时使用 `loadPhase4Config()` 一次性校验；缺失、非法 URL、相对路径或错误类型会让启动失败，避免带着隐含默认值运行。

## 环境变量

| 变量 | 必填 | 示例/说明 |
| --- | --- | --- |
| `COMFYUI_BASE_URL` | 是 | 内网或受保护网关地址；不得下发前端 |
| `COMFYUI_AUTH_TOKEN` | 否 | 网关 Bearer token，不写日志 |
| `COMFYUI_HEADERS_JSON` | 是 | 自定义字符串 header 的 JSON 对象；无则 `{}` |
| `COMFYUI_REQUEST_TIMEOUT_MS` | 是 | JSON API 单次请求超时，正整数 |
| `COMFYUI_DOWNLOAD_TIMEOUT_MS` | 是 | 图片下载超时，正整数 |
| `COMFYUI_RETRY_COUNT` | 是 | 429/5xx/网络错误的重试次数，可为 0 |
| `COMFYUI_RETRY_DELAY_MS` | 是 | 重试间隔，可为 0 |
| `COMFYUI_POLL_INTERVAL_MS` | 是 | history 轮询间隔，正整数 |
| `COMFYUI_POLL_MAX_ATTEMPTS` | 是 | 最大轮询次数，正整数 |
| `COMFYUI_ALLOW_GLOBAL_INTERRUPT` | 是 | 推荐 `false`；开启后取消会调用 `/interrupt` |
| `COMFYUI_WORKFLOW_DIR` | 是 | 容器内绝对路径，只读挂载 workflow 文件 |
| `COMFYUI_DOWNLOAD_DIR` | 是 | 容器内绝对临时目录，与持久化服务临时根一致 |
| `COS_SECRET_ID` | 是 | 腾讯云凭证；生产推荐临时密钥/实例角色注入 |
| `COS_SECRET_KEY` | 是 | 腾讯云凭证；不得提交仓库或输出日志 |
| `COS_SECURITY_TOKEN` | 否 | 使用临时密钥时设置 |
| `COS_BUCKET` | 是 | 包含 APPID 的完整 bucket 名称 |
| `COS_REGION` | 是 | 例如 `ap-shanghai` |
| `COS_CDN_BASE_URL` | 否 | 配置后返回 CDN URL，否则返回 COS HTTPS URL |
| `GENERATION_LOG_PROMPTS` | 是 | 默认及推荐值 `false` |

## `.env` 模板

```dotenv
COMFYUI_BASE_URL=http://comfyui.internal:8188
COMFYUI_AUTH_TOKEN=
COMFYUI_HEADERS_JSON={}
COMFYUI_REQUEST_TIMEOUT_MS=15000
COMFYUI_DOWNLOAD_TIMEOUT_MS=60000
COMFYUI_RETRY_COUNT=2
COMFYUI_RETRY_DELAY_MS=500
COMFYUI_POLL_INTERVAL_MS=1000
COMFYUI_POLL_MAX_ATTEMPTS=600
COMFYUI_ALLOW_GLOBAL_INTERRUPT=false
COMFYUI_WORKFLOW_DIR=/app/workflows
COMFYUI_DOWNLOAD_DIR=/app/tmp/comfyui

COS_SECRET_ID=replace-at-deploy-time
COS_SECRET_KEY=replace-at-deploy-time
COS_SECURITY_TOKEN=
COS_BUCKET=replace-with-bucket-appid
COS_REGION=ap-shanghai
COS_CDN_BASE_URL=
GENERATION_LOG_PROMPTS=false
```

此模板只说明键名，不应保存真实密钥。生产环境通过 Tencent Cloud Secret Manager、实例角色/临时凭证或 CI/CD 密钥注入。

## 推荐初始值

- 轮询：1 秒、最多 600 次；总上限约 10 分钟，并与 binding 的 deadline 对齐。
- HTTP：API 15 秒、图片 60 秒、2 次重试、500 ms 间隔。
- 临时目录：独立 volume，限制容量，进程用户可写，其他用户不可读。
- ComfyUI headers/token：仅在 TLS 或可信内网中传输；跨公网必须使用 HTTPS 网关。

