# Changelog

## 0.5.9 · 主站 Vercel 崩溃加固 / 2026-08-06
- **根因**：`mindfulpenpal.com` 全部路由 500（`FUNCTION_INVOCATION_FAILED`）——
  Flask 在 Vercel 冷启动时执行 `_seed_admin` 等初始化，若 `DATABASE_URL` /
  `POSTGRES_URL_*` 指向不可达数据库（localhost、已停用旧库、暂停的 Prisma
  Postgres），连接异常会让整个 serverless 函数无法启动。
- **加固**：启动阶段的数据库/工具初始化失败不再让函数崩溃，改为记录完整
  traceback 后继续启动；PostgreSQL 连接增加 5 秒 `connect_timeout`，冷启动
  失败快速返回而不是长时间挂起。
- **Prisma 池化参数兼容**：自动剥离 `DATABASE_URL` / `POSTGRES_URL_*` 中的
  `uselibpqcompat` / `pgbouncer` 查询参数——psycopg2 会以
  `invalid URI query parameter` 拒绝这类 Vercel Prisma 池化地址，导致冷启动
  直接崩溃。
- **prisma:// 协议回退**：`prisma://` 地址没有 SQLAlchemy 方言，会导致
  `Can't load plugin` 秒崩；程序现在跳过它并按
  `POSTGRES_URL_NON_POOLING → POSTGRES_URL → DATABASE_URL → SQLite` 选择
  第一个可用的 `postgresql://` 地址。
- **Suspended 恢复说明**：Vercel Prisma Postgres 免费档闲置会进入
  Suspended 状态，连接快速失败导致主站 500；排查文档补充 Resume /
  查询唤醒与 Redeploy 步骤。
- **排查文档**：`docs/deployment/environment-variables.md` 增加主站 500 排查
  步骤（Runtime Logs → 数据库地址 → 重新部署 → `/healthz` 验证）。
- **恢复**：生产环境需在 Vercel my-toolbox 检查并修正数据库变量后重新部署；
  代码修复合入 main 后同样需要一次新部署生效。

## 0.5.8 · 统一后台配置缺口修复 / 2026-08-06
- **修复生产 `/admin/gallery` 报“缺少有效的 GALLERY_INTERNAL_HMAC_SECRET”**：根因是
  `deploy/DEPLOY_GUIDE.md` §8.1 的 Vercel 原 Flask 项目配置清单漏掉
  `GALLERY_SERVICE_BASE_URL` 与 `GALLERY_INTERNAL_HMAC_SECRET`，导致生产主站未配置
  统一后台所需变量、无法读取待审核队列。
- **补齐部署文档**：DEPLOY_GUIDE §8.1、部署检查清单与上线验收开关均加入这两个变量
  （值须与 my-toolbox-gallery / Generation Service 完全一致，至少 32 字节）；
  新增 `tests/test_deploy_governance.py` 治理测试，防止文档再次漏配。
- **报错与预检更可操作**：后台未配置错误与 `flask --app app check-gallery-integration`
  预检现在直接提示“在 Vercel my-toolbox Production 配置并重新部署”。

## 0.5.7 · 集成分支同步与真实联调基线 / 2026-08-06
- **同步生产修复到集成分支**：`codex/frontend-backend-integration` 并入 main
  0.5.2–0.5.6 的全部生产修复（COS 上传签名、取消兜底落库、Jimeng Seedream 4.5
  合法尺寸缩放、Provider 失败详情安全日志、Gallery 登录预取 CORS），并并入
  ai-image 本地登录桥与一键开发链路（COS 存储层元数据键名规范化作为防御兜底）。
- **修复合入后的类型错误**：`failureDetail` 改为先提取局部常量再条件展开，
  使 Generation Service `tsc --noEmit` 通过；phase4 契约测试与线上 COS
  “不发送自定义元数据头”行为对齐。
- **真实联调基线（线上实测）**：`gallery.mindfulpenpal.com/api/me/session` 200、
  `/api/generation/workflows` 200、`/api/generations` 401（未登录鉴权，不再是
  旧版本 404）、`/create` 200、主站登录页正常；`api-ai.mindfulpenpal.com`
  从国内网络直连仍 TLS 握手失败（curl 35），但 Vercel 边缘经 BFF 可正常到达
  后端，正式命名隧道仍是让直连稳定的下一步。

## 0.5.6 · 修复 COS 上传签名错误与取消后列表不刷新 / 2026-08-06
- **修复 COS 上传 403 SignatureDoesNotMatch**：上传图片时不再发送
  `x-cos-meta-job_id` / `x-cos-meta-output_index` 自定义元数据头
  （对象键本身已包含任务 ID 与序号，元数据无业务用途），消除
  “The Signature you specified is invalid” 签名校验失败。
- **修复取消后页面不更新**：任务轮询到达终态（已取消/失败）时自动刷新
  “最近创作”列表；从列表点击取消且任务仍在运行时会继续轮询，直到状态
  变为终态，不再出现“显示已取消但列表卡住”的现象。

## 0.5.5 · 修复生成任务取消失效 / 2026-08-06
- **取消兜底落库**：当任务处于“生成中”但队列里已没有活跃任务（worker 重启、
  任务停滞或 BullMQ 记录已过期）时，点击取消会直接把数据库状态改为
  `cancelled` 并释放预留积分，页面不再永远停在“正在停止任务…”。
- **重拾任务先落库**：worker 重新领取到已请求取消的任务时，先完成取消落库
  与积分释放，再短路跳过执行。
- **取消后防复活**：任务被取消后即使 Provider 调用已返回，也禁止被
  `markCompleted` 翻回“已完成”并二次扣费（避免用户同时得到图片和积分）。
- **测试**：新增取消兜底与“仍在信号中不兜底”两类契约测试。

## 0.5.4 · 日志增加失败详情 / 2026-08-06
- **可观测性**：`generation.failed` 与 `provider.attempt_failed` 日志新增
  `failureDetail` 字段（截断的错误消息链，不含密钥与请求体），生产排查时
  不再只能看到 `internal_error` / `provider_unknown_error` 这类笼统代码。

## 0.5.3 · 修复 即梦 Seedream 4.5 尺寸参数 / 2026-08-06
- **修复 400 InvalidParameter**：Seedream 4.5 不再支持 1K（1024x1024），
  火山方舟 API 要求总像素范围在 [2560x1440, 4096x4096] 之间；
  适配器现在会按比例保持用户选择的宽高比，自动升档到合法尺寸
  （1024x1024 → 1920x1920，768x1024 → 1664x2216）。
- **测试**：新增尺寸升档契约测试，覆盖常见预设与极端尺寸。

## 0.5.2 · Gallery 登录跨域修复 / 2026-08-06
- **修复 Gallery 登录跨域（CORS）**：主站 Flask 对受信任的 Gallery 来源（默认取
  `AI_IMAGE_EXTERNAL_URL`，可用 `GALLERY_CORS_ORIGINS` 追加）返回
  `Access-Control-Allow-Origin` / `Allow-Credentials` 并正确处理 OPTIONS 预检；
  修复从 gallery.mindfulpenpal.com 跳转 mindfulpenpal.com/login 被浏览器拦截的问题。
- **回归测试**：新增 `tests/test_gallery_cors.py`，覆盖可信来源、预检、未知来源拒绝
  与环境变量扩展来源四类场景。

## 0.5.1 · 即梦全链路优化 / 2026-08-05
- **即梦多张生成**：Seedream 单次只返回一张，Adapter 对 `count>1` 逐张扇出调用，
  用户 seed 依次递增（seed + index），平台 1–8 张契约全部可用；新增契约测试。
- **队列未配置 fail-fast**：Generation API 在 Redis/BullMQ 未配置时创建请求直接返回
  503，不再产生永远停留在 pending 的任务。
- **创作页体验**：账单接口故障不再阻塞工作流加载；任务轮询增加指数退避（2s→10s）
  并在瞬时失败后继续轮询；未登录时“开始生成”变为登录链接（`/login?next=/create`）。
- **认证页防缓存**：登录/注册/退出页面强制 `Cache-Control: private, no-store`，
  修复 CDN 缓存旧 CSRF token 导致表单提交 400 的问题。
- **真实即梦冒烟**：新增 `npm run smoke:jimeng`（支持 `--health`），只输出安全字段，
  不打印 API key；生产服务器可用其完成 Provider 级连通性与生成验证。
- **统一后台并入主线**：上一分支的 `/admin/gallery` 统一后台随本次发布一起合入 main。

## 0.5.0 · 统一管理后台 / 2026-08-05
- **合并两个后台**：`mindfulpenpal.com/admin` 成为唯一管理入口，新增 AI 作图模块
  （`/admin/gallery`），覆盖概览、内容审核、Provider、工作流、生成任务与审计记录；
  `gallery.mindfulpenpal.com/admin` 配置 `MAVIS_ADMIN_URL` 后 307 重定向到主站，
  Gallery 导航栏向管理员显示“后台”入口。
- **Flask 签名直连**：新增 `utils/gallery_admin_client.py`，用与 Next.js BFF 相同的
  60 秒 HMAC Admin Context 调用 Generation Service `/v1/admin/*`，服务端 RBAC、
  乐观锁与审计不变；新增 `GALLERY_SERVICE_BASE_URL` / `GALLERY_INTERNAL_HMAC_SECRET`
  配置与预检项。
- **权限与降级**：非管理员访问统一后台返回 403；管理服务未配置/不可用时页面友好降级，
  不泄露密钥与内网信息。
- **测试与文档**：新增签名客户端与后台路由契约测试；更新 Phase 8 架构、部署、环境变量、
  上线验收文档。

## 0.4.4 · 优化 / 2026-08-04
- **回跳统一与加固**：注册、登录、退出共用 `_safe_next_url` 白名单，注册/登录页之间透传 `next`；
  拒绝控制字符、反斜杠、携带账号密码的绝对地址，防止开放重定向变体。
- **桥接配置可审计**：Flask 新增 `flask --app app check-gallery-integration` 预检 CLI，
  Gallery 新增 `scripts/check-bridge-config.ts` 预检脚本，只报告变量名/状态，不输出密钥。
- **契约测试**：新增 `tests/test_gallery_round_trip.py`，覆盖注册→回跳→会话内省→退出全链路、
  伪造 `next` 拒绝、内省 fail-closed 与预检退出码；Gallery 新增桥接配置检查单测。
- **文档与模板**：`.env.example` 补充 `SESSION_COOKIE_SECURE`；部署/验收文档补充预检命令与验收项。

## 0.4.3 · 修复 / 2026-08-04
- **修复登录桥路径**：Flask introspection 路由实际为 `/internal/gallery/session`，
  部署文档此前误写为 `/auth/internal/gallery/session`，导致 Gallery 登录桥一直 404
  （`bridge:"error"`）；现保留 `/auth/internal/gallery/session` 兼容别名，并修正文档。

## 0.4.2 · 优化 / 2026-08-04
- **登录/登出回跳优化**：从 Gallery 点击登录，登录成功后回到 Gallery 原页面；Flask 通过
  `AI_IMAGE_EXTERNAL_URL` 域名白名单校验绝对跳转地址，防止开放重定向。
- **性能优化**：同一请求内 Gallery 对主站 introspection 只调用一次（React cache 去重），
  减少 `/admin` 等页面的重复鉴权延迟。

## 0.4.1 · 热修 / 2026-08-04
- **修复 Vercel 只读文件系统忽略 `DATABASE_URL`**：删除 `POSTGRES_URL_*` 后站点曾静默
  回退到空的内存 SQLite，导致老账号消失、无法登录；现在 `POSTGRES_URL_*` 与
  `DATABASE_URL`（postgres 开头）任一存在都会连接外部 PostgreSQL，并新增回归测试。
- **加固 Gallery 登录桥**：introspection 超时 3s → 10s；`/api/me/session` 新增
  `bridge` 状态（ok / guest / unconfigured / error），服务器日志输出失败原因（不打印密钥）。
- **文档修正**：`GALLERY_INTROSPECTION_SECRET` 只在 Vercel 两个项目间共享，
  服务器环境文件不需要配置；Vercel Production Branch 新版入口说明。
- **部署验证**：页脚显示版本号，便于确认线上是否为最新构建。

## 0.4.0 — 进行中 / 2026-08-04
- **CI 修复**: 修复 `0007_remote_provider_bindings.sql` 的 FROM 子句别名顺序问题
  （`seed` 别名需在 JOIN 条件之前定义），PR #3 四个 CI job 全部通过
- **部署资产（已有服务器场景）**: compose 支持 `host.docker.internal` 连接本机
  PostgreSQL；Redis 仅内网发布（`ALLOW_PLAINTEXT_REDIS` 显式开关）；本机构建镜像
  可用 `ALLOW_LOCAL_IMAGE_TAGS` 显式放行；Dockerfile 支持 `NPM_REGISTRY` 国内源
  构建参数；迁移脚本支持 `MIGRATIONS_DIR` 直接用本机 psql 执行
- **新文档**: [已有服务器与 COS 的生产部署（数据库搬迁版）](docs/deployment/tencent-existing-server-setup.md)

## 0.3.0 — 进行中
- **M1.1 AI 作图可用性补全**: 新用户首次汇总自动发放一次性积分
  （`BILLING_SIGNUP_GRANT`，默认 10，幂等账本）；迁移 `0007` 为四个 workflow
  补齐 OpenAI/Gemini/即梦 默认模型绑定；Worker 支持 `GALLERY_DEFAULT_MODERATION`
  决定生成即发布还是人工审核；Gallery Web 新增 `/login`、`/logout`、
  `/api/me/session` 与导航头登录入口（`MAVIS_AUTH_LOGIN_URL` / `MAVIS_AUTH_LOGOUT_URL`）
- **AI 作图迁移新链路**: 移除旧 Flask 工具 `tools/ai_image`（含模板、路由、
  Pollinations/OpenAI provider 配置面板），首页入口改为可配置外部链接
  （`tools_config.yaml` 的 `ai_image.external_url`，指向独立部署的
  Generation Service + Gallery Web）；未配置 URL 时首页自动隐藏，填入地址
  并重启后自动显示并跳转。工具注册机制新增 `external_url` 字段，可复用于
  任意外部链接工具
- **图片压缩**: 显示"原图 → 压缩后"大小对比 + 节省百分比 + 实际尺寸
- **PDF 拆分**: 支持用 `;` 分隔多段范围 (如 `1-3; 5; 7-9`)，每段生成独立 PDF，
  页面展示文件列表 (含页数 + 单独下载)
- **新增工具 PDF 加水印**: 给 PDF 每页盖半透明斜向文字水印，可调字号/颜色/
  透明度/旋转角度;用 PIL 生成水印图 + pypdf 叠加，无需 reportlab 依赖

## 0.2.0 — 2026-07-19
- 所有"生成新文件"的工具（PDF 合并 / PDF 拆分 / 图片压缩 / AI 作图）改为在页面内
  展示结果：图片工具显示缩略图，PDF 工具显示文件名 + 大小，统一提供"下载"和"在新标签
  打开"按钮。无 JS 时仍按原方式直接下载文件。

## 0.1.0 — 初始版本

基于 PRD 的最小可用实现：

- 用户体系：匿名（3 次/工具 终身）+ 注册（10 次/工具/天）+ 管理员（∞）
- 4 个工具：PDF 合并 / PDF 拆分 / AI 作图 / 图片压缩
- 后台：仪表盘（Chart.js）、用户管理、工具启停、日志筛选、站点设置
- 插件化：所有工具均为独立 Blueprint
- 安全：CSRF、密码哈希、文件类型 / 大小校验、限速、cookie 签名
- 部署：Gunicorn + systemd + Nginx（参考 `deploy/`）+ logrotate + SQLite 备份脚本
- 配置：`.env` 全部参数化
