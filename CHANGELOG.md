# Changelog

## 0.7.7 · 报销 OCR：显示百度 token 获取失败的具体原因 / 2026-08-08
- 百度 token 请求失败时（HTTP 状态、error/error_description）现在会记录日志
  并显示在页面提示里，便于区分“密钥错误/未实名/网络不通”。

## 0.7.6 · 报销 OCR：修复 PDF 发票识别失败 / 2026-08-08
- **根因**：PDF 转 JPEG 使用了不被 PyMuPDF 接受的格式名，转换失败后把
  原始 PDF 字节当图片发给百度，必然识别失败；百度接口报错此前仅记 DEBUG
  日志，原因被静默吞掉。
- **修复**：PDF 转换改用标准 "jpg" 并校验 JPEG 头，转换失败直接放弃该页，
  不再发送原始 PDF；百度接口错误改为抛给上层并显示在页面提示里
  （如服务未开通、额度用尽、图片格式错误等）。

## 0.7.5 · 报销 OCR：百度设为首选识别服务 / 2026-08-08
- 识别顺序调整为 **百度 → 腾讯云 → PaddleOCR → 手动填写**；
- 百度未配置/无结果/接口报错时，原因会直接显示在页面提示里；
- 腾讯云保留为自动备用（无需改动配置）。

## 0.7.4 · 报销助手：修复“提示已回填但实际未识别” / 2026-08-08
- **根因**：OCR 未配置或识别失败时，后端仍返回 `success=true` 且数据全空，
  前端据此提示“已回填发票及关联明细”，但表单实际为空。
- **修复**：前端改为按“实际识别到的字段”判断——有内容才提示已回填，否则
  提示“未能自动识别，请手动填写发票信息”；后端模拟降级改为
  `success=false`，语义更准确。
- **优化**：选择新发票文件时先清空上一张的识别字段，避免残留旧数据。

## 0.7.3 · 项目整理与文档同步 / 2026-08-08
- 清理本地临时产物（`quick-lru.tgz`、`.tmp` 预览图、`.gallery-next-cache`、
  `__pycache__`），`.gitignore` 补充 `.gallery-next-cache/`。
- 文档去重：`docs/README.md` 新增“文档去重说明”，明确新手部署、本地开发、
  变更记录、平台升级方案的权威入口；`docs/changelog/README.md` 标注为历史
  档案，最新变更以根 `CHANGELOG.md` 为准。
- 根 `README.md` 补充项目结构与最新能力说明。
- 无业务逻辑改动。

## 0.7.2 · 修复 Gallery Vercel 构建失败（favicon.ico 格式） / 2026-08-08
- **根因**：Phase 1 手写的 favicon.ico（纯标准库生成）不符合 ICO 规范，
  Next.js/sharp 无法解码，导致 `next build` 失败、Vercel 停留在旧部署
  （新接口如 /api/billing/redeem 一直 404）。
- **修复**：改用 Pillow 生成标准多尺寸 ICO（16/32/48/256），与
  icon.svg / 主站 favicon.svg 同设计；本地 `next build` 已验证全量通过。
- 生成脚本改为 `scripts/dev/generate-favicon.py`（需 Pillow）。

## 0.7.1 · Phase 3 基础：双积分账本 + 积分兑换码 + 创作页积分档位 / 2026-08-07
- **数据库（0010/0011）**：新增 `ai.member_credit_accounts` 会员积分账本；
  流水表增加 `account_type`（free/member）；新增兑换码表
  `ai.redemption_codes` 与会员账本的预留/结算/释放/兑换函数。
- **双账本**：会员档任务从会员账本预留/结算/释放积分（free 任务保持原账本）；
  Gallery 账单页同时显示“免费积分”与“会员积分”两个余额。
- **积分兑换码（国内支付第一步）**：主站后台新增“兑换码”页，可批量生成
  兑换码（每码固定积分）；用户在 Gallery 账单页输入兑换码，会员积分即时到账
  （写审计流水）。管理员也可在用户列表按账本调整积分。
- **创作页积分档位**：/create 新增“免费积分 / 会员积分”选择，提交时携带
  creditTier；免费档只能调用 free 模型（会员档可选全部）。
- **测试**：新增兑换码格式/到账与会员档选择策略测试。

## 0.7.0 · Phase 2：模型配置中心、计分规则、注册赠送可配、模型分级 / 2026-08-07
- **数据库（0009）**：`ai.provider_models` 新增 `tier`（free/member）与
  `credit_cost`（单张积分）；`ai.generation_jobs` 新增 `credit_tier`。
- **模型配置中心**：Gallery 后台新增“模型与计分”面板——每个 Provider 下列出
  模型，可编辑积分档位（free/member）、单张积分、默认模型、启停；
  后端新增 `PATCH /v1/admin/provider-models/:id` 与审计日志。
- **计分规则**：创建任务时优先按工作流 `defaults.pricing` 的
  `"{宽}x{高}"` 定价 × 张数计算预留积分，未配置则回退原
  `credit_cost × 张数`。
- **注册赠送积分后台可配**：主站后台 → 系统设置新增“新用户注册赠送积分”；
  Generation Service 优先读取同一数据库 `public.settings` 中的
  `signup_credit_grant`，未配置时回退环境变量。
- **模型分级 gating**：免费档任务只能选择 `tier=free` 的模型；会员档任务
  可选全部模型（双账本结算在 Phase 3 实施）。
- **会员工具无限使用**：主站 users.plan 为 member/pro/vip 时，普通小工具
  不再受每日免费次数限制；后台用户列表可直接设置会员等级。
- **测试**：新增选择策略分级过滤测试；Phase 8 管理端模型更新覆盖。

## 0.6.1 · 报销发票 OCR 修复（腾讯云识别）与 Phase 2/3 方案 / 2026-08-07
- **修复发票无法识别**：根因是未配置任何 OCR 后端（百度密钥缺失、
  PaddleOCR 未安装），接口一直走“模拟降级”返回空字段。新增腾讯云
  增值税发票识别适配器（TC3-HMAC-SHA256 签名，仅用 requests，无新增
  SDK），识别顺序：腾讯云 → 百度 → PaddleOCR → 模拟降级。
- **配置**：新增 `OCR_SECRET_ID` / `OCR_SECRET_KEY`（可复用
  COS_SECRET_ID/KEY，子账号需有 ocr:VatInvoiceOCR 权限）。
- **测试**：新增 TC3 签名与发票字段映射单测。
- **方案**：platform-upgrade-plan.md 细化 Phase 2（模型配置中心、按
  尺寸/张数计分、注册赠送后台可配）与 Phase 3（微信/支付宝支付分档路径、
  双积分账本、模型分级）设计。

## 0.6.0 · Phase 1：昵称、统一图标、AI 入口、COS 按用户名归档、后台用户管理 / 2026-08-07
- **昵称（#5）**：users 新增 nickname（幂等迁移）；`/profile` 页面可设置昵称；
  主站头部、Gallery 头部、画廊作品署名都优先显示昵称，未设置时显示注册邮箱；
  设置昵称自动同步 ai.user_profiles。
- **统一小图标（#7）**：设计同一科技风图标（紫→青渐变 M + 星芒），主站
  `static/img/favicon.svg` 与 Gallery `app/icon.svg` / `app/favicon.ico` 一致；
  新增纯标准库生成脚本 `scripts/dev/generate-favicon.py`。
- **生图预览居中（#6）**：Gallery 预览区按实际画幅居中显示、完整展示不裁剪，
  并保持所选宽高比。
- **AI 入口卡片（#1）**：主站首页新增“AI 生图 · 画廊展示”Hero 卡片，
  含开始创作 / 浏览画廊入口；两站同步紫青渐变科技风设计令牌（#2 基础）。
- **COS 按用户名归档（#4）**：新上传对象键改为
  `images/{用户名}/{jobId}/{序号}.ext`（用户名取邮箱本地部分 + 用户 ID），
  存量对象不变；桶策略文档同步为 `images/*`。
- **后台用户管理（#3 部分）**：用户列表新增昵称设置、AI 积分查看与调整
  （写 ai.credit_ledger_entries 审计）、删除用户（停用 + 匿名化，保留历史）。
- 方案文档：`docs/development/platform-upgrade-plan.md`（8 项需求与 Phase 2/3 规划）。

## 0.5.14 · 热修：工具注册启动失败（NameError）导致全站工具 404 / 2026-08-07
- **根因**：0.5.12 引入的“残留工具自动禁用”逻辑引用了未定义的
  `entries` 变量（`NameError`），`sync_tool_registry` 在启动时抛异常，
  `register_tools` 被跳过，重启后所有 `/tools/*` 页面都返回 404。
- **修复**：把 `_load_yaml_config(app)` 结果赋给 `entries` 后再循环；
  同时残留工具判定同时按工具 id 与路由双重兜底，避免 id 与路由不一致的
  残留行（如 doc-viewer）漏网。
- **回归测试**：`tests/test_tool_registry_sync.py` 会直接触发该路径，
  防止再次出现启动期工具加载失败。

## 0.5.13 · 修复 /favicon.ico 404 控制台报错 / 2026-08-07
- **根因**：浏览器每次打开页面都会自动请求 `/favicon.ico`，而站点只提供
  `/static/img/favicon.svg`，导致每个页面控制台都出现
  `Failed to load resource: 404`（不影响页面显示）。
- **修复**：新增 `/favicon.ico` 路由，302 重定向到已有的 SVG 图标。
- **测试**：新增 `tests/test_favicon_route.py`。

## 0.5.12 · 修复主站工具死链（doc-viewer 404）/ 2026-08-07
- **根因**：`tools_config.yaml` 是工具的唯一样式来源，但 `sync_tool_registry`
  只做“新增/更新”，不会禁用数据库中残留的旧工具行；残留的
  `doc-viewer` 仍显示在首页，点击进入 `/tools/doc-viewer` 返回 404。
- **修复**：同步工具清单时，YAML 中不存在的已启用工具会被自动禁用，
  首页不再渲染死链（保留数据行，不删除）。
- **测试**：新增 `tests/test_tool_registry_sync.py`，覆盖残留工具禁用与
  已配置工具保持启用两类场景。

## 0.5.11 · 本地开发启动诊断与安全加固 / 2026-08-07
- **dev-up 前置检查**：启动前明确检查 Python 虚拟环境（`.venv`）与 npm 是否
  存在，缺失时直接给出修复命令，不再静默拉起一个立刻死掉的服务，避免
  “网站起不来”且无任何提示。
- **端口与 URL 一致性**：`dev-up.ps1` 现在以 `-RefreshUrls` 调用
  `setup-local-env.ps1`，HOST/PORT/APP_BASE_URL 与各服务 URL 始终对齐，
  不会被残留的旧 `.env`（例如 `PORT=8000` + `APP_BASE_URL=example.com`）
  带偏。
- **本地库安全开关**：新增 `setup-local-env.ps1 -SetLocalDbUrl`，一键把
  Flask 与 Generation Service 的 `DATABASE_URL` 指向本地库
  （127.0.0.1:5433/mavis_dev）；dev-up 检测到外部数据库地址时给出强警告，
  防止本地开发误操作生产数据。
- **文档**：`local-development-bridge.md` 增加本机前置条件（Node 22+、
  Python venv、Redis、本地 PostgreSQL）与对应故障排查项。

## 0.5.10 · 数据库操作量优化（避免打满托管库免费额度）/ 2026-08-06
- **Dispatcher 出站队列空闲退避**：连续空转时轮询间隔从 1 秒指数退避到
  `GENERATION_OUTBOX_IDLE_MAX_MS`（默认 30 秒），队列出现消息时立即恢复；
  空闲查询量从约 8.6 万次/天降到约 2,900 次/天。
- **主站运行设置 TTL 缓存**：`apply_runtime_settings` 从“每个请求查一次库”
  改为进程内缓存（`RUNTIME_SETTINGS_TTL_SECONDS` 默认 30 秒），管理员保存后
  强制立即刷新；数据库不可用时也不再每请求重试。
- **冷启动 schema 探针**：schema 已存在时跳过 `db.create_all()` 的反射检查
  （生产可设 `AUTO_CREATE_SCHEMA=false` 完全跳过），每次冷启动减少 10–30 次
  查询；库不可用时仍按既有兜底继续启动。
- **回迁服务器本地库脚本**：新增 `deploy/switch-back-to-local-db.sh`，一键把
  主站 Flask 与 Generation Service 切回腾讯云本机 PostgreSQL、跑幂等迁移、
  重启服务并关闭 5432 公网监听；自带双环境文件备份，不打印任何密码。

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
