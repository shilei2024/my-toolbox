# Phase 6 配置手册

所有密钥由部署环境注入，不写入仓库、数据库或浏览器 bundle。

## Generation Service / Gallery API

| 环境变量 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `DATABASE_URL` | 是 | — | PostgreSQL 连接串 |
| `REDIS_URL` | 否 | No-op cache | Gallery 缓存；可与 BullMQ Redis 同实例但应使用独立 key prefix/容量监控 |
| `GALLERY_HOST` | 否 | `127.0.0.1` | 监听地址 |
| `GALLERY_PORT` | 否 | `3101` | 监听端口 |
| `GALLERY_TRUST_PROXY` | 否 | `false` | 仅在可信反向代理后设置 `true` |
| `GALLERY_CURSOR_SECRET` | 是 | — | 至少 32 bytes；签名分页 cursor |
| `GALLERY_INTERNAL_HMAC_SECRET` | 是 | — | 至少 32 bytes；必须与 Next.js 相同 |
| `GALLERY_ASSET_HOSTS` | 是 | — | 允许公开展示的 COS/CDN hostname，逗号分隔 |
| `GALLERY_CACHE_TTL_SECONDS` | 否 | `30` | Guest 公共数据缓存 TTL |
| `GALLERY_PRIVATE_URL_TTL_SECONDS` | 否 | `300` | COS 私有签名 URL TTL |
| `GALLERY_DELETION_RETENTION_SECONDS` | 否 | `86400` | 软删除到物理清理的保留期 |
| `GALLERY_DELETION_POLL_MS` | 否 | `30000` | 删除 worker 轮询间隔 |
| `GALLERY_DELETION_BATCH_SIZE` | 否 | `20` | 单次领取任务数 |
| `GALLERY_DELETION_RETRY_BASE_SECONDS` | 否 | `60` | 删除失败退避基数，最大 3600 秒 |
| `COS_SECRET_ID` | 是 | — | 腾讯云密钥，使用最小权限子账号 |
| `COS_SECRET_KEY` | 是 | — | 腾讯云密钥 |
| `COS_SECURITY_TOKEN` | 否 | — | 临时凭证 token |
| `COS_BUCKET` | 是 | — | 默认 COS bucket |
| `COS_REGION` | 是 | — | COS region |
| `COS_CDN_BASE_URL` | 否 | COS endpoint | 公开 CDN 根地址 |

不要为 `GALLERY_ASSET_HOSTS` 配置通配符或用户可控域名。生产建议 bucket 默认私有，公开内容通过受控 CDN 域名提供，私有内容只使用短时签名 URL。

## Next.js Gallery SSR / BFF

| 环境变量 | 必填 | 说明 |
| --- | --- | --- |
| `GALLERY_SERVICE_BASE_URL` | 是 | Gallery API 内部地址；必须 HTTPS，只有 loopback 可使用 HTTP |
| `GALLERY_INTERNAL_HMAC_SECRET` | 是 | 与 Generation Service 相同，至少 32 bytes |
| `MAVIS_AUTH_INTROSPECTION_URL` | 是（登录功能） | Flask `/internal/gallery/session` 的 HTTPS/loopback 地址 |
| `GALLERY_INTROSPECTION_SECRET` | 是（登录功能） | 与 Flask 相同，至少 32 bytes |
| `GALLERY_PUBLIC_ORIGIN` | 生产必填 | 写请求允许的站点 origin，例如 `https://www.mindfulpenpal.com` |

## Flask

| 环境变量 | 必填 | 说明 |
| --- | --- | --- |
| `GALLERY_INTROSPECTION_SECRET` | 是 | 与 Next.js 相同；不要与 Flask `SECRET_KEY` 或内部 HMAC secret 复用 |

建议分别生成三个独立 32+ byte 随机值：cursor、Next→Service HMAC、Next→Flask introspection。轮换 HMAC 时采用短双密钥窗口或同步部署，避免身份链路短暂中断。
