# 环境变量与密钥管理指南

## 环境隔离

| 环境 | 前端变量 | 后端变量 | 数据资源 |
| --- | --- | --- | --- |
| Local | `.env.local`，Git 忽略 | `.env`，Git 忽略 | 本地/专用开发资源 |
| Testing | GitHub workflow 非敏感临时值 | GitHub service container 临时值 | 每次 CI 新建 |
| Staging | Vercel Preview/branch variables | `/etc/mindfulpenpal.staging.env` 或 staging secret store | staging DB/Redis/COS |
| Production | Vercel Production variables | `/etc/mindfulpenpal.production.env` 或腾讯云 Secret Manager | production 独占 |

环境之间不得共享数据库、Redis DB、COS Bucket/写前缀、支付密钥、HMAC secret 或 Provider API key。

## 存放位置

- `.env.example`：只保存变量名、安全示例和说明。
- Vercel：Next 构建/运行变量按 Development、Preview、Production 分区。
- GitHub repository variables：非敏感 CI 配置。
- GitHub Environment secrets：未来 staging/production 部署凭据；production 必须审批后才能读取。
- CVM：权限 `0600` 的 env 文件或腾讯云 Secret Manager 注入。
- Docker Compose：只引用变量名/`env_file`，不写真实值。

Vercel 变量变更只应用于之后的新 deployment，不会修改已经存在的 deployment。[Vercel Environment Variables](https://vercel.com/docs/environment-variables)

## 分类规则

公开变量仅限明确允许进入浏览器的信息。任何以 `NEXT_PUBLIC_` 开头的变量都会进入前端 bundle，禁止存放：

- 数据库/Redis URL
- HMAC、Session、Webhook secret
- Provider、COS、支付 Secret Key
- 内网主机名/IP

服务端变量包括：

- Flask：`SECRET_KEY`、`DATABASE_URL`、管理员 bootstrap、限流和 Session 配置。
- Gallery/Billing：数据库、Redis、Viewer HMAC、Cursor、Stripe/支付 Provider。
- Generation：Redis/BullMQ、Provider、ComfyUI、COS、超时/并发和日志配置。
- Next Server Runtime：Gallery 内网 URL、HMAC、Auth introspection；这些不能加 `NEXT_PUBLIC_`。

完整业务变量分别见 [Phase 4–10 配置文档](README.md)。

M1.1 新增服务端变量：

| 变量 | 归属 | 默认 | 说明 |
| --- | --- | --- | --- |
| `BILLING_SIGNUP_GRANT` | Generation API（Billing） | `10` | 新用户首次账户汇总时发放的一次性积分；`0` 关闭 |
| `GALLERY_DEFAULT_MODERATION` | Generation Worker | `pending` | 新图片审核状态；`approved` 会直接发布公开图片 |
| `MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL` | Next Server Runtime | 无 | Flask 登录/退出页 HTTPS URL，Gallery 登录入口依赖前者 |

## 主站 ↔ Gallery 登录桥接变量

Flask 主站与 Vercel Gallery Web 通过共享 Cookie 与签名会话内省识别同一登录态。这些变量缺失或值不合法时，首页 AI 入口自动隐藏、Gallery 回退为游客（fail closed）。

| 变量 | 归属 | 默认 | 说明 |
| --- | --- | --- | --- |
| `AI_IMAGE_EXTERNAL_URL` | Flask 主站 | 空 | Gallery 公网 HTTPS URL（如 `https://gallery.example.com/create`）；未配置时首页隐藏 AI 作图入口 |
| `GALLERY_INTROSPECTION_SECRET` | Flask + Vercel | 空 | 内部会话内省共享密钥，至少 32 个 UTF-8 字节；只保存在服务端，禁止 `NEXT_PUBLIC_` |
| `APP_BASE_URL` | Flask 主站 | `http://localhost:8000` | 主站公网 HTTPS Origin；预检用它校验双方同处 `SESSION_COOKIE_DOMAIN` 之下 |
| `SESSION_COOKIE_DOMAIN` | Flask 主站 | 空 | 双方共享受控父域（如 `.example.com`）；`*.vercel.app` 无法共享业务 Cookie |
| `SESSION_COOKIE_SECURE` | Flask 主站 | `false` | 生产必须为 `true`；Gallery 为 HTTPS 时预检直接失败 |
| `MAVIS_AUTH_INTROSPECTION_URL` | Vercel | 空 | Flask 内部会话检查 HTTPS URL（`/internal/gallery/session`） |
| `MAVIS_AUTH_LOGIN_URL` | Vercel | 空 | Flask 登录页 HTTPS URL；未配置时 Gallery 隐藏登录入口 |
| `MAVIS_AUTH_LOGOUT_URL` | Vercel | 空 | Flask 退出页 HTTPS URL；可选，未配置时隐藏退出入口 |

### 统一管理后台变量

主站 Flask 后台直连 Generation Service 管理 API，使用与 Next.js BFF 相同的 HMAC 契约；Gallery 不再维护独立后台。

| 变量 | 归属 | 默认 | 说明 |
| --- | --- | --- | --- |
| `GALLERY_SERVICE_BASE_URL` | Flask 主站 | 空 | Generation Service 公网 HTTPS API Origin（与 Vercel 侧同名变量一致） |
| `GALLERY_INTERNAL_HMAC_SECRET` | Flask 主站 + Generation Service | 空 | 管理上下文签名密钥，至少 32 个 UTF-8 字节，与 Vercel 侧一致 |
| `MAVIS_ADMIN_URL` | Vercel（服务端） | 空 | 统一后台地址（如 `https://mindfulpenpal.com/admin/gallery`）；配置后 Gallery `/admin` 自动重定向 |
| `NEXT_PUBLIC_MAVIS_ADMIN_URL` | Vercel（公开） | 空 | 同一后台地址，供 Gallery 导航栏对管理员显示“后台”入口；不含敏感信息 |

### 预检命令（不输出密钥）

Flask 主站：

```bash
flask --app app check-gallery-integration
```

每项输出以 `[PASS]` 或 `[FAIL]` 开头，只报告变量名与状态；任一 `[FAIL]` 时退出码为 1。输出永远不包含密钥正文或完整内网地址。

Gallery Web：

```bash
cd apps/gallery-web
node --experimental-strip-types scripts/check-bridge-config.ts
```

同样只报告变量名与状态，退出码 0 表示桥接配置就绪。

## 新增变量流程

1. 选择通用、供应商无关的命名；Provider 特有变量限制在 Adapter。
2. 在 `.env.example` 或对应配置文档加入空值/安全示例。
3. 启动时校验必填、类型、URL、范围和组合关系，错误时 fail closed。
4. 先配置 staging，再部署；验证后由双人复核配置 production。
5. 不在日志打印值；只记录 `configured: true/false`。

## 轮换流程

1. 创建新凭据，旧凭据暂时有效。
2. 更新 staging 并验证。
3. 更新 production secret store，创建新 deployment/滚动后端。
4. 确认全部实例使用新凭据。
5. 禁用旧凭据并审计访问。
6. 记录操作者、时间、影响和验证，不记录密钥正文。

## 泄露处理

立即撤销/轮换，而不是只从 Git 删除；检查 Git 历史、Actions/Vercel 日志、构建产物和访问日志。必要时停止相关 Provider 和支付能力，并按安全事件流程通知负责人。
