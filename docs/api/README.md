# API 文档

## 边界

浏览器只访问 Next.js BFF。Generation Service 的 `/v1/*`、Flask 的 `/internal/*`、ComfyUI 和 Provider 凭据不得直接暴露给浏览器。内部请求使用已签名 Viewer Context；写操作必须携带明确的同源 `Origin`，并同时检查登录态与角色。BFF 对管理、兑换和创建生成请求提供额外的本地节流；Generation Service 的共享限流仍是权威控制。

## 浏览器可访问的 Next.js BFF

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/gallery` | 公开 Gallery 列表 |
| GET | `/api/gallery/:slug` | 作品详情 |
| GET | `/api/me/images` | 当前用户作品 |
| GET | `/api/me/favorites` | 当前用户收藏 |
| PUT/DELETE | `/api/images/:id/favorite` | 收藏切换 |
| PUT/DELETE | `/api/images/:id/like` | 点赞切换 |
| DELETE | `/api/images/:id` | 软删除本人作品 |
| POST | `/api/images/:id/download` | 获取下载授权 |
| GET | `/api/billing/summary` | 余额、会员和套餐摘要 |
| POST | `/api/billing/checkout` | 创建支付会话 |
| POST | `/api/billing/portal` | 创建客户门户会话 |
| GET | `/api/tasks` | 当前用户的平台任务中心 |
| GET | `/api/admin/queue` | 管理员队列监控摘要 |
| GET/PATCH | `/api/admin/*` | 管理控制面 BFF |

## 内部 Gallery/Billing API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 内网健康检查 |
| GET | `/v1/gallery`、`/v1/gallery/:slug` | Gallery 查询 |
| GET | `/v1/seo/images` | Sitemap/SEO 内部数据源 |
| GET | `/v1/me/images`、`/v1/me/favorites` | 用户私有查询 |
| PUT/DELETE | `/v1/images/:id/favorite`、`like` | 用户行为 |
| DELETE | `/v1/images/:id` | 软删除 |
| POST | `/v1/images/:id/download` | 下载授权与审计 |
| GET/POST | `/v1/billing/*` | Billing 摘要、Checkout、Portal |
| GET | `/v1/tasks` | 任务摘要；当前注册图像生成来源 |
| GET | `/v1/admin/queue` | 管理员只读队列健康与积压指标 |
| GET/PATCH | `/v1/admin/*` | 管理控制面 |

## Generation API

浏览器端 BFF 为 `GET /api/generation/workflows`、`POST /api/generations`、`GET/DELETE /api/generations/:id`。内部对应 `/v1/generation/workflows` 与 `/v1/generations/*`，机器可读契约见 [openapi-generation-v1.yaml](openapi-generation-v1.yaml)。创建必须携带 `Idempotency-Key`，且只接受服务端签名的登录用户上下文。

## Task Center API

`GET /api/tasks` 通过 BFF 返回当前用户的任务摘要；内部对应
`GET /v1/tasks`。响应仅包含模块、稳定任务键、状态、时间、积分结算、
安全错误码与输出链接。当前仅接入图像生成来源，游标沿用该来源的签名
keyset cursor；后续模块接入时由 Task Center 统一扩展分页契约。

## Webhook

`POST /v1/billing/webhooks/:provider` 是唯一可按精确路径公开的 Billing 入站接口。必须使用原始 body 验签、限制 body 大小、幂等落库并快速返回；复杂处理不得阻塞 HTTP 响应。

Generation API 已完成代码与契约测试；真实 Staging 数据库、队列、COS 与 Provider 集成验收仍按部署清单执行。
