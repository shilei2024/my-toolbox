# M1 AI 功能生产配置（人工填写版）

> 状态：**配置已可准备，生产发布仍为 No-Go**。本文不会把未完成 Staging、备份恢复和回滚验证的版本切入真实流量。仓库根目录 `AGENTS.md` 与生产发布清单的强制门禁不能由口头“跳过测试”覆盖。

## 1. 目标与边界

本配置把 AI 生图作为 Toolbox Platform 的一个模块上线，共用认证、积分、任务、存储和审计能力。生产服务器只运行 Generation API、任务分发器、Worker、删除 Worker 和 Caddy；PostgreSQL、Redis、COS 均使用独立生产资源。

Golden Rule 结论：

1. **会影响生产网站**：只在独立域名和显式发布批准后接入；默认模板 `PRODUCTION_RELEASE_APPROVED=false`，普通 `docker compose up` 也不会启动带 `production` profile 的服务。
2. **可被未来 AI 模块复用**：任务、Provider、队列、COS、鉴权和积分契约均为平台级能力。
3. **成本更低的可行方案**：4 核 4GB 主机只承载无状态应用进程，避免在小主机上同时维护生产 PostgreSQL/Redis；并发从 1 开始。
4. **小白可维护**：真实值只需按下面三张清单手动填入，预检脚本只报告变量名，不打印密钥。
5. **符合长期架构**：数据库是业务事实源，Redis 不是唯一账本，COS 是持久存储，镜像按 digest 发布。

## 2. 需要你手动准备的信息

不要把以下真实值发送到聊天、提交到 Git 或写入工单。服务器配置文件固定放在 `/etc/mindfulpenpal.production.env`，属主为 `root`、权限为 `600`。

### 2.1 服务器与域名

| 配置项 | 你需要填写的内容 | 要求 |
| --- | --- | --- |
| `GENERATION_API_DOMAIN` | Generation API 的生产子域名 | 例如 `api-ai.<你的主域名>`；DNS A/AAAA 指向应用服务器 |
| `GENERATION_IMAGE` | Generation Service 镜像 | 必须是 `仓库@sha256:摘要`，不能用 `latest` |
| `POSTGRES_MIGRATION_IMAGE` | PostgreSQL migration 客户端镜像 | 必须固定 sha256 digest |
| `CADDY_IMAGE` | Caddy 镜像 | 必须固定 sha256 digest |
| 防火墙 | 入站端口 | 22 仅允许运维固定 IP；80/443 对公网；数据库、Redis、3101 不对公网 |
| DNS/TLS | A/AAAA、证书签发 | 先确认没有悬空记录；Caddy 通过 80/443 自动申请 TLS |

不要在仓库或 Vercel 中保存 SSH 密码/私钥。后续如需自动部署，应在本机 `~/.ssh/config` 建立不含秘密的主机别名，再单独保管私钥。

### 2.2 托管 PostgreSQL 与 Redis

| 配置项 | 要求 |
| --- | --- |
| `DATABASE_URL` | 独立生产库、独立低权限应用用户、TLS、自动备份；不能复用 Staging 数据库 |
| `REDIS_URL` | 生产专用、TLS URL（`rediss://`）、持久化/备份、`noeviction`；不能复用 Staging Redis |
| 备份 ID | 发布前创建 PostgreSQL 可恢复备份，人工记录备份 ID 和时间点，不写入 `.env` |

当前已有本地环境审计结果显示：`REDIS_URL` 尚未配置。生产发布前必须先购买/创建托管 Redis 并填入，不能用 4GB 应用服务器上的临时 Redis 替代。

### 2.3 腾讯 COS

| 配置项 | 你在腾讯云控制台填写/复制的内容 |
| --- | --- |
| `COS_BUCKET` | 完整 Bucket 名称（通常包含 AppId 后缀） |
| `COS_REGION` | Bucket 所在地域代码 |
| `COS_SECRET_ID` / `COS_SECRET_KEY` | 独立 CAM 子账号密钥，不使用主账号永久密钥 |
| `COS_SECURITY_TOKEN` | 只有使用临时 STS 凭证时填写 |
| `COS_CDN_BASE_URL` | 已配置 HTTPS 和回源的 CDN 自定义域名；暂未启用 CDN 时可留空 |
| `GALLERY_ASSET_HOSTS` | 允许返回给浏览器的 COS/CDN 主机名白名单，多个用英文逗号分隔 |

CAM 权限只授予生产 Bucket 或生产前缀所需的对象上传、读取/签名访问和删除能力，不授予列出全部 Bucket、修改 Bucket 策略或访问其他环境的权限。当前代码实际写操作是 `PutObject` 和 `DeleteObject`；私有图由服务端生成短时签名 URL。建议启用 Bucket 版本控制、服务端加密、生命周期规则和访问日志。

现有环境中 COS Bucket/地域/密钥已检测到配置，但不会复制、输出或自动上传这些值。`COS_CDN_BASE_URL` 当前为空；如果直接使用 COS HTTPS 域名，需要把该域名加入 `GALLERY_ASSET_HOSTS`。

### 2.4 独立随机密钥与 AI Provider

| 配置项 | 要求 |
| --- | --- |
| `GALLERY_CURSOR_SECRET` | 至少 32 随机字节，不能与其他密钥复用 |
| `GALLERY_INTERNAL_HMAC_SECRET` | 至少 32 随机字节；Generation Service 与 Vercel Production 填同一个值 |
| Provider | 至少配置一个真实 Provider：OpenAI、Gemini、即梦或内网 ComfyUI |
| `GENERATION_ALLOW_MOCK_PROVIDER` | 生产固定为 `false` |

使用远程 Provider 时填写对应 `*_API_KEY` 和 `*_BASE_URL`。使用 ComfyUI 时必须放在私网/VPN 后，并填写 `COMFYUI_BASE_URL`、认证信息、工作流目录和默认模型；不得把 ComfyUI 端口直接暴露到公网。

## 3. 服务器人工配置步骤

以下命令只是发布 Runbook，本次不会远程执行。

1. 在服务器创建只允许 root 读取的文件：

   ```bash
   sudo install -o root -g root -m 600 /dev/null /etc/mindfulpenpal.production.env
   sudoedit /etc/mindfulpenpal.production.env
   ```

   以 `services/generation-service/deploy/.env.production.example` 为字段清单，逐项手动填写，不要直接上传本地 `.env`。

2. 在代码发布目录运行不输出密钥的预检：

   ```bash
   cd /opt/mindfulpenpal/services/generation-service/deploy
   sh ./preflight-production.sh /etc/mindfulpenpal.production.env
   ```

   预期输出：`production preflight passed; no secret values were printed`。如失败，只修复输出中点名的变量，不要把环境文件内容粘贴到终端日志。

3. 只有发布清单全部完成、获得发布批准后，才把 `PRODUCTION_RELEASE_APPROVED` 改为 `true`，然后拉取固定镜像：

   ```bash
   docker compose --env-file /etc/mindfulpenpal.production.env \
     -f compose.production.yaml --profile production pull
   ```

4. 记录数据库备份 ID 和旧镜像 digest，由数据库负责人执行一次 migration：

   ```bash
   docker compose --env-file /etc/mindfulpenpal.production.env \
     -f compose.production.yaml --profile migration run --rm migrate
   ```

5. migration 成功且抽查通过后启动应用：

   ```bash
   docker compose --env-file /etc/mindfulpenpal.production.env \
     -f compose.production.yaml --profile production up -d --no-build
   docker compose --env-file /etc/mindfulpenpal.production.env \
     -f compose.production.yaml --profile production ps
   ```

   预期 `api` 为 `healthy`，其他服务为 `running`。日志中不得出现密钥、完整 Prompt、内部堆栈或客户数据。

## 4. Vercel Production 手动变量

在 `my-toolbox-gallery` 项目的 **Settings → Environment Variables → Production** 中手动添加：

| 变量 | 生产值 |
| --- | --- |
| `GALLERY_SERVICE_BASE_URL` | `https://<GENERATION_API_DOMAIN>` |
| `GALLERY_INTERNAL_HMAC_SECRET` | 与服务器同名变量完全一致 |
| `MAVIS_AUTH_INTROSPECTION_URL` | 已上线 Flask 的内部会话检查 HTTPS URL |
| `GALLERY_INTROSPECTION_SECRET` | Flask 与 Gallery 专用的另一把独立密钥 |
| `GALLERY_PUBLIC_ORIGIN` | Gallery 最终生产 HTTPS Origin，不带路径 |

这些值只选择 **Production**，不要误加到 Preview/Development。环境变量更改后必须生成一个新 deployment；不要把未经验证的 Preview 直接重新构建成不同产物，正式发布应提升同一已验证产物。

现有 Flask 生产站点还需由你手动设置：

- `AI_IMAGE_EXTERNAL_URL=https://<Gallery 生产域名>/create`
- `SESSION_COOKIE_DOMAIN=.<受控父域名>`（仅当 Flask 与 Gallery 确实共享受控父域）
- `SESSION_COOKIE_SECURE=true`
- 与 `GALLERY_INTROSPECTION_SECRET` 配对的内部鉴权密钥

普通 `*.vercel.app` 域名不能共享你的业务域 Cookie；正式共用用户必须绑定受控业务域名。

## 5. 当前 No-Go 阻断项

下列任一项未完成都不能切生产流量：

- 生产托管 PostgreSQL、TLS Redis 和 COS 已隔离，且连接凭证最小权限；
- 至少一个真实 AI Provider 配置完成，Mock 已关闭；
- 数据库备份成功并记录可恢复 ID，恢复演练和回滚负责人明确；
- 同一个镜像 digest 已完成 Staging 真实链路验证；
- 登录、创建任务、扣减积分、队列消费、COS 落盘、图库查询、取消/失败补偿完成验收；
- 旧 Vercel deployment ID、旧后端镜像 digest、DNS/TLS 和监控告警已记录。

## 6. 回滚

应用故障时停止扩量，把 `GENERATION_IMAGE` 改回已记录的旧 digest，再用 `--no-build` 启动；Vercel 使用上一已验证 deployment 的 Rollback/Promote。不要执行 `down -v`，不要删除数据库、Redis/COS 数据，也不要用破坏性 down migration。数据库问题优先冻结写入，把备份恢复到新实例验证后再切换连接。

## 7. 生产配置资产

- `services/generation-service/deploy/compose.production.yaml`：生产 profile，只有不可变镜像，无本地 PostgreSQL/Redis。
- `services/generation-service/deploy/.env.production.example`：只含变量名和占位符。
- `services/generation-service/deploy/preflight-production.sh`：检查缺失值、占位符、TLS Redis、镜像 digest、Mock 和显式批准，不输出真实值。
- `services/generation-service/deploy/migrate-production.sh`：带 migration ledger 的一次性迁移入口。
- `services/generation-service/deploy/Caddyfile.production`：TLS 反向代理和基础安全响应头。
