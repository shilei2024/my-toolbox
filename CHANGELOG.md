# Changelog

## 0.9.16 · 发票递归解压兼容性修复 / 2026-08-27
- 统一“发票提取与批量打印”工作台继续复用原压缩包工具的递归能力，并按 ZIP/PDF 文件签名识别无扩展名内层文件，兼容更多发票平台下载包。
- Windows 反斜杠目录在腾讯云 Linux 环境统一规范化，深层文件名和来源路径不再因操作系统差异解析错误；无关成员不再提前占用实际解压预算。
- 将真实三层嵌套、无扩展名内包和无扩展名 PDF 纳入自动回归；生产发布明确要求重启宿主机 `mytoolbox.service`，Generation Compose 不负责 Flask 主站。

## 0.9.15 · 发票混合压缩包队列修复 / 2026-08-27
- 发票提取接口新增逐压缩包结果记录；同一批 ZIP 中部分为空、损坏或未提取到 PDF 时，前端会保留对应项目，不再静默丢失。
- 上传待处理清单改用稳定队列 ID 删除，清空时同步清理旧 DOM 与文件输入值，修复删除最后一项仍残留的问题。
- 增加多 PDF 压缩包回归测试；不改变现有上传大小、响应大小和递归解压安全限制。

## 0.9.14 · 主站首页 Hero 区块移除 / 2026-08-27
- 按确认结果直接移除首页顶部 Hero 宣传区和 AI Gallery 横幅，首页进入工具库前不再展示
  提示词式文案、能力卡片或重复入口。
- 工具库、分类导航、实时汇率、登录状态和 Gallery 独立路由能力保持不变。
- 清理对应 CSS 和移动端适配规则；不新增图片、依赖、API、数据库或部署配置，回滚只需
  恢复首页模板和全局样式。

## 0.9.13 · 报销助手品牌目录更新 / 2026-08-26
- 报销助手产品线/品牌目录替换为业务确认的 86 项清单，并严格按提供顺序编号 `01`–`86`。
- 已有用户的旧目录在首次打开报销助手时一次性升级；历史发票中的品牌名称和编号保持不变。
- 目录升级完成后仍保留产品线管理的自定义增删改能力；无数据库结构、API 或依赖变更。

## 0.9.12 · 发票工作台上传与清单交互修复 / 2026-08-26
- 移除腾讯云主站已不适用的 4MB ZIP 限制：默认单包和单批均为 20MB，并根据 Flask
  全局上传门限自动预留 multipart 开销；5MB ZIP 回归测试可正常提取。
- 待处理清单改用真实按钮和事件委托，修复逐项删除、清空待处理、删除勾选及清空全部；
  处理中锁定清单，失败或被跳过的 ZIP 会保留，错误提示不再被成功提示覆盖。
- 补强重复文件识别、进度条竞态、全选状态、CDN 依赖重试和导出 Blob 生命周期；输入格式
  与实际合并能力统一为 ZIP/PDF/JPG/PNG。
- 新增可选发票 ZIP 门限配置和部署说明；无数据库迁移或持久数据变更，回滚只需恢复上一
  版本代码并重启腾讯云 `mytoolbox` 服务。

## 0.9.11 · 发票提取与批量打印统一工作台 / 2026-08-26
- 将“批量提取PDF发票”和“批量发票打印”合并为一个首页入口，支持 ZIP、PDF、
  图片混合选择；ZIP 内 PDF 经原有递归解压和压缩炸弹防护后，直接进入统一预览队列。
- 提取后的 PDF 与本地文件共用选择、删除、单份打印、批量合并打印和 ZIP 导出流程；
  支持继续追加文件，并对展示及打印窗口中的文件名做 HTML 转义。
- 保留 `/tools/zip-extractor` 旧网址及其 `/analyze` 接口作为兼容别名，统一计入
  `invoice_printer` 用量；旧工具数据库卡片在注册表同步时自动禁用，无数据库迁移。
- 回滚：恢复两个 `tools_config.yaml` 条目、移除兼容别名注册和统一上传逻辑即可；
  不涉及持久文件、业务数据或第三方服务变更。

## 0.9.10 · 报销助手三表动态扩容 / 2026-08-25
- 取消应酬费明细、派车单、出差明细原有 9/11/17 条业务限制；数据超过母版预留行时，
  自动复制数据行样式和行高，并将合计行下移。
- 合计公式按实际数据区域动态扩展；派车单 14 条数据仍保持公里承接公式。三张表裁掉
  实际区域外的历史空白格式，并明确设置为宽、高各适配一页，避免产生分页。
- 保留原三工作表、`.xls` 文件格式和小数据量版式；无数据库、API 或依赖变更。

## 0.9.9 · 报销助手三表按日期排序 / 2026-08-25
- 应酬费明细、派车单、出差明细统一按首列日期升序稳定排列；同日数据保持原顺序，
  空日期或非法日期置于末尾。
- 页面加载、保存回显和明细 Excel 导出共用服务端排序口径；派车单在排序后重新计算
  起止公里承接，避免日期顺序变化导致里程链错误。
- 无数据库、API 结构或依赖变更；回滚只需还原报销管理器、页面模板、测试和文档。

## 0.9.8 · 主站与 Gallery 响应式体验重构 / 2026-08-21
- 主站重构为统一的响应式平台首页：新增可访问导航、双应用 Hero、AI Gallery 入口、
  横向分类导航、1–4 列自适应工具卡与多栏页脚；保留原有工具、登录、额度和汇率逻辑。
- Gallery 增加完整移动导航，不再在平板宽度直接隐藏主要入口；桌面和移动端均可返回
  主站工具箱，并保留发现、我的图片、任务、收藏、会员、账单、后台和创作入口。
- 新增可选 `MAVIS_SITE_URL`。服务端只接受 HTTPS 或本地 loopback HTTP；未配置时从
  `MAVIS_AUTH_LOGIN_URL` 推导 Origin，非法值隐藏入口且不向客户端传递登录路径。
- 无数据库/API/依赖变更；回滚只涉及模板、CSS、Header 与链接辅助函数。生产发布仍需
  Preview 的 320px / 768px / 1280px 人工验收与批准。

## 0.9.7 · 修复 H3 参考图上传入口不显示：listWorkflows 透传 mode_meta / 2026-08-15
- 根因：`workflowView()` 重建 defaults 时丢弃了迁移 0019 写入的 `mode_meta`
  与 0021 写入的 `videoResolutions`，前端 `h3Meta` 恒为 undefined，
  "单图生视频 / 多图参考视频"的上传入口与分辨率限档均未生效。
- 修复：`GenerationWorkflowView.defaults` 增加 `modeMeta` / `videoResolutions`
  字段，`workflowView()` 防御性校验后透传（DB JSONB 结构非法时降级省略，
  不影响列表接口可用性）。
- 纵深防御：create 事务内校验参考图模式（`mode_meta.maxImages>0`）必须携带
  1..maxImages 张参考图，空提交 400 且任务不落库，防止 API 直调绕过前端
  校验、任务到 ComfyUI 才失败白耗积分。
- 测试：phase13 新增集成用例——H3 三模式 modeMeta 透传（t2v=0/i2v=1/ref=3）、
  480p/720p 限档透传、普通工作流字段省略、空/超量参考图 create 拒绝且不落库。

## 0.9.6 · 视频生成体验修复：轮询不再重复执行、视频进画廊 / 2026-08-15
- 修复“任务重复执行三次”：轮询以 binding `timeout_seconds` 的 deadline 为主，
  `maxAttempts` 不再提前截断（10 分钟尝试预算曾先于 2 小时超时耗尽，抛可重试
  超时导致队列重复提交）；超时 `retryable` 严格取 binding `retryOnTimeout`；
  轮询间隔自适应升级（1s 起步，每 60 次翻倍，封顶 30s），2 小时任务不再以 1s
  频率打爆 Provider。
- MiniMax H3 参考图上传入口修复：上传 UI 不再依赖“恰好注册 3 个 H3 工作流”，
  改按 `modeMeta.maxImages` 渲染，单图/多图模式均可上传、删除参考图。
- 画面比例与分辨率文案统一：图片“16:9 横图（1344×768）”、视频
  “720p 高清（1248×704）”均展示实际像素；前端 32 对齐与服务端 binding
  `align=32` 双重对齐，尺寸经 `{{width}}/{{height}}` 真实注入工作流。
- 视频作品进入画廊（迁移 0024）：`ai.images` 升级为媒体作品表
  （`media_type`/`duration_seconds`），完成时与图片同一审核（moderation）、
  可见性、发布、点赞收藏链路；画廊卡片静态显示首帧、悬停静音播放、移开复位，
  视频徽标展示时长；SEO（og:image/sitemap）仍只收录图片。
- 创作台最近任务移至右侧预览列，最新在最上；存在进行中任务时每 6 秒自动刷新
  状态；视频支持预览播放与下载入口；失败任务可一键“重新创作”。
- 测试：新增 phase13 视频画廊投影集成测试与 phase6 视频可见性断言；
  phase13 约束断言改为 PostgreSQL 错误码（23514/23505），与消息语言无关。

## 0.9.5 · H3 长任务不再误判：超时放宽到 2 小时且不自动重试 / 2026-08-13
- 根因确认：H3 720p/长视频在消费级显卡上生成超过 30 分钟，binding 超时 1800s
  导致全部 `polling_exhausted`，且 BullMQ 自动重试又在 ComfyUI 重复排队，造成
  “一次点击三个任务/三个视频”。
- H3 三个工作流：timeout_seconds=7200、max_attempts=1、
  `retryOnTimeout=false`（迁移 0023）——超时直接判失败、释放积分，不再重复生成；
  用户在 GPU 空闲后手动重试即可。
- 部署示例 `COMFYUI_POLL_MAX_ATTEMPTS=7200`（与 2 小时超时对齐）。

## 0.9.4 · 视频回传容错：下载/网络失败可重试一次 / 2026-08-13
- ComfyUI 网络/超时错误标记为可重试（此前下载超时直接判失败）。
- H3 三个工作流 `max_attempts` 提升到 2（迁移 0022）：视频生成成功但下载/COS
  转存瞬时失败时，任务自动重试一次，避免“GPU 已出片但页面失败”。
- 部署示例将 `COMFYUI_DOWNLOAD_TIMEOUT_MS` 提到 120s，覆盖慢速家庭上行。

## 0.9.3 · 防重复生成与运行中工作流视频可取消 / 2026-08-13
- 修复“点一次生成出现三个任务”：前端提交增加同步防重；服务端在创建视频任务时对
  同一用户加互斥（FOR UPDATE + 409 video_busy），一个用户同时只能有一个
  pending/running 视频任务，杜绝重复提交与 GPU 堆积。
- 修复“完成的任务不回到页面”：任务详情新增 `mode`（workflow/api），创作台与
  最近任务对运行中的工作流视频显示“取消”按钮（配合
  `COMFYUI_ALLOW_GLOBAL_INTERRUPT=true` 可真正中断 GPU）；API 模式视频仍不可取消。
- OpenAPI 与测试同步：新增视频互斥 PG 集成测试与 mode 字段断言。

## 0.9.2 · H3 卡死修复：binding 超时生效、分辨率限档 / 2026-08-13
- 修复 30 分钟无结果：轮询现在强制执行 binding `timeout_seconds`（H3=1800s），
  超时按可重试错误终止并释放积分，不再无限等待到 1 小时。
- 修复卡死兜底：reconciler 按每个工作流 binding 超时判定陈旧任务（默认下限 15
  分钟），Worker 崩溃/失联后也能收敛。
- H3 分辨率限制为 480p/720p（defaults.videoResolutions，迁移 0021），避免 1080p/2K
  在消费级显卡上超长运行或显存抖动。
- 运维建议：单 ComfyUI + 并发 1 场景设置 `COMFYUI_ALLOW_GLOBAL_INTERRUPT=true`，
  取消运行中任务时才能真正中断 GPU，避免残留任务阻塞后续生成。

## 0.9.1 · MiniMax H3 尺寸 32 对齐与视频参数重设计 / 2026-08-13
- 服务端：ComfyUI Provider 支持 binding `align`（32），H3 三个工作流启用，
  请求宽高自动对齐到 32 的倍数（迁移 0020），消除
  “width and height must be divisible by 32” 报错。
- 前端：视频参数改为「画面比例 + 分辨率（480p/720p/1080p/2K）+ 视频时长」，
  宽高按比例与 32 对齐计算；工作流可通过 defaults.videoResolutions 定制档位。
- 单测新增尺寸对齐用例；Generation 94 项、Gallery lint/构建全部通过。

## 0.9.0 · MiniMax H3 全能参考视频（文生/单图/多图） / 2026-08-13
- 新增三个 MiniMax H3 视频工作流（迁移 0019）：`minimax-h3-t2v-v1` 文生视频、
  `minimax-h3-i2v-v1` 单图生视频、`minimax-h3-ref-v1` 多图参考视频（最多 3 张，
  提示词用 @图片1/@图片2/@图片3 引用），保留 Work-Fisher 原工作流分支全部节点。
- 参考图全链路：前端上传 → Generation API 校验并转存 COS 临时对象 → Worker 下载并
  上传 ComfyUI `/upload/image` → 注入 LoadImage 后执行；任务结束后清理临时对象。
- 平台能力：StorageProvider 新增 `download`；ComfyUI 客户端新增 `uploadImage`；
  占位符支持带数字 token（ref_image_0/1/2）；创建接口 body 上限提升至 6MB。
- 创作台：默认创作方式改为 **API 模型**，工作流为可选；MiniMax H3 以一张
  “全能参考视频”卡片 + 三种模式开关展示，单图/多图模式支持参考图上传与预览。
- 真实验证：三种模式均通过平台全链路（API → 队列 → Worker → 本机 ComfyUI →
  COS），各 8 积分结算；文生/单图/多图分别产出 1024×576 MP4。

## 0.8.7 · 报销助手优化：招待费礼品类别与派车单汇总 / 2026-08-12
- 招待费（应酬费明细）新增“礼品”费用类别，与“餐费”“其他”并列；新增/编辑
  发票的关联应酬费明细与“应酬费明细表”中的费用类别改为下拉选择，历史自定义
  类别值仍保留显示，避免数据丢失。
- 新增发票的费用类别下拉去掉“未分类”“通讯费”“福利”；编辑历史发票时若原
  类别属于以上分类仍保留原值，列表筛选仍可查看全部分类。
- 周期汇总“车辆费用”行按派车单的“公里 + 过桥费 + 停车费”合计汇总；同一产品
  线已有车辆类发票时以派车单为准（与封面及费用分类表导出口径一致），汇总卡片
  金额同步更新。

## 0.8.6 · Ideogram 4 切回 Quality 预设 / 2026-08-10
- Provider 绑定新增 `mu`/`std` 采样参数（仅服务端 binding 可控）。
- `ideogram4-t2i-v1` 从 Default（20 步）切回 Work-Fisher 原工作流的 Quality
  预设（48 步 / mu 0 / std 1.5），默认分辨率 1376×768，积分 3；
  对齐本地运行的效果与耗时。

## 0.8.5 · Ideogram 4 文生图工作流 / 2026-08-10
- 新增 `ideogram4-t2i-v1` 工作流（迁移 0017）：Ideogram 4 双模型 CFG 引导 +
  Ideogram4Scheduler（Default：20 步 / mu 0 / std 1.75）+ euler_ancestral；
  基于【Work-Fisher】Ideogram4半自动文生图V2 简化，擅长版式、文字与写实构图。
- 本机实测 1024×1024 正常出图；绑定参数由服务端 binding 控制。

## 0.8.4 · Qwen 中文生图工作流与创作目录简介 / 2026-08-10
- 新增 `qwen-image-v1` 工作流（迁移 0016）：Qwen-Image + 集成采样器，中文提示词
  理解准确；本机实测中文提示词 768×768 正常出图。绑定参数 steps=20 / cfg=2.5 /
  euler / simple，由服务端 binding 控制。
- 工作流目录：补齐每个工作流的用途简介（SDXL 工作流标注英文提示词更佳，中文
  创作推荐 Qwen）；前端工作流卡片增加“已选”标识与选中态。
- 修正 ComfyUI 集成节点所需的 VAE/CLIP 模型名（`QWEN\qwen_image_vae` 等）。

## 0.8.3 · 强制 workflow/API 模式 Provider 边界 / 2026-08-10
- 新增迁移 `0015_workflow_mode_provider_boundaries.sql`：`workflow` 模式只允许
  绑定 ComfyUI，`api` 模式只允许绑定远程厂商模型；禁用 0007 遗留的跨厂商
  fallback binding，避免 ComfyUI 不可用时生图工作流静默改走即梦/OpenAI/Gemini。
- 修正根目录 `deploy/.env.production.example` 中 `COMFYUI_WORKFLOW_DIR` 为
  `/app/workflows`（与 Dockerfile 一致）。

## 0.8.2 · 本机/Staging ComfyUI 视频冒烟脚本 / 2026-08-09
- 新增 `npm run smoke:comfyui`：通过内部签名 API 提交一条 5 秒私有视频任务并
  轮询到终态，覆盖 API、队列、Worker、ComfyUI 与 COS 全链路；支持
  `SMOKE_API_BASE_URL` 指向 Staging、`SMOKE_USER_ID` 指定测试账号，不打印密钥与完整 Prompt。
- 本机真实复验：任务 `906ed7fe` 完成，960×544 / 5.000s / 1.80MB MP4 已转存 COS，
  积分 reserve→settle 只结算一次，失败任务全部 release；ComfyUI 以文件重定向
  启动避免 tqdm stderr `[Errno 22]`，Worker 直接以 node 启动避免沙箱网络拦截 COS。

## 0.8.1 · M4 上线前修复与发布补全 / 2026-08-09
- **修复 Gallery 生产构建阻断**：`auth-links.ts` 残留 `safeNext` 调用导致
  `next build` 类型检查失败，改为统一使用抽出的 `safeAuthReturnUrl`。
- **修复容器工作流路径**：部署 env 示例的 `COMFYUI_WORKFLOW_DIR` 从
  `/app/src/workflows` 改为与 Dockerfile 一致的 `/app/workflows`，避免容器内
  ComfyUI workflow 加载失败；root `.env.example` 补齐 ComfyUI 变量。
- **preflight 支持视频 Provider**：只配置火山方舟视频密钥时也能通过
  “至少一个真实 Provider”检查，并校验 `ARK_VIDEO_BASE_URL`。
- **CI 修复与补全**：`DATABASE_URL: sqlite:///:memory:` 裸标量导致 workflow YAML
  解析失败（main 自 0.7.17 起 CI 全红），加引号修复；Gallery 任务从仅跑 SEO
  测试改为运行完整单测；phase9 PG 集成测试适配新增 `ark-video` Provider；
  新增 phase13 PG 集成测试覆盖 `ai.generation_assets` 与 fail-closed 媒体工作流。
  发布 runbook 同步最新验证命令与 0001–0014 迁移范围。

## 0.8.0 · Gallery 图片/视频统一工作流与 ComfyUI/Ark 视频闭环 / 2026-08-09
- **统一媒体契约**：工作流新增 `media_type`，目录 API 支持图片/视频与
  workflow/API 双维度过滤；创建 API 仍只接受 `workflowSlug`，Provider 和模型留在服务端 binding。
- **视频生产链路**：新增火山方舟异步视频 Adapter、5/10 秒白名单、流式受限下载、
  COS `videos/` 耐久化与 `ai.generation_assets`；视频任务复用既有队列、积分、审计和任务中心。
- **本机 ComfyUI**：ComfyUI Adapter 扩展为图片/视频共用 Provider，支持 Video Helper Suite
  MP4 输出、LTX 2.3 API workflow、服务端随机 seed 和 server-owned 模型/采样参数；新增默认禁用的迁移与完整本地联调指南。
- **Gallery Web**：`/create` 增加生图/生视频切换、视频时长与结果播放；视频暂为 owner-only，
  不进入公共图片 Gallery。运行中视频不接受用户取消，避免上游继续计费而平台退款；任务进入终态后会刷新积分余额。
- **本地登录与可靠性**：仅对相同 loopback origin 允许 HTTP 登录回跳并允许 Next.js dev origin；修复失败结算 SQL 中 PostgreSQL enum/text 参数类型推断冲突。
- **安全发布**：Provider/模型/工作流迁移后默认 fail-closed，必须经过 Staging 真凭据、成本和内容安全验收再启用。
- **真实链路验证**：Gallery 页面已完成本机 ComfyUI 生图和 960×544、24 FPS、121 帧、约 5.04 秒 LTX 视频；两类结果均上传 COS、写入耐久资产并完成积分结算。

## 0.7.20 · 修复 /create 整页打开时被 CSP 拦截 / 2026-08-09
- **根因**：`/create` 被静态预渲染，而 CSP 中间件只在动态渲染时把 nonce 注入
  页面脚本；静态 HTML 的脚本没有 nonce，配合 `strict-dynamic` CSP 后所有脚本
  被浏览器拦截，页面停留在静态骨架。从画廊页内部点击“开始创作”是客户端导航，
  脚本已加载所以正常——这解释了“主站卡片进不去、画廊页点创作正常”。
- **修复**：`/create` 改为 `force-dynamic` 动态渲染，nonce 正常注入；生产构建
  路由清单中 `/create` 由 Static 变为 Dynamic。

## 0.7.19 · 生图「工作流 / API」分开 + 默认公开到画廊 / 2026-08-09
- **创作目录分离**：`ai.workflows` 新增 `mode`（workflow/api）；每个已启用的
  Provider 模型自动生成一个 API 模式工作流（绑定唯一模型），`/create` 以
  「工作流 / API 模型」两个 Tab 分开选择；`GET /v1/generation/workflows` 支持
  `?mode=workflow|api` 过滤，统一后台工作流卡片显示模式标签。Provider 默认
  disabled，未启用前 API 模式不会出现在创作目录。
- **默认公开**：新任务的作品可见性与 Prompt 默认均为公开（前端初始值、
  workflow defaults、服务端解析回退三层一致）；历史私有/隐藏作品不回填。
- **主站入口修复**：主站 `/create`、`/gallery` 由 404 改为 302 跳转到独立部署的
  Gallery（`AI_IMAGE_EXTERNAL_URL` 未配置时保持 404 fail-closed），避免用户从
  主站路径或旧书签进入时打不开。
- **文档与验证**：新增 ADR-0024；OpenAPI、M1 架构与 changelog 同步；Generation
  Service typecheck + 测试、Gallery lint/测试/生产构建通过。

## 0.7.18 · Gallery 仅部署 Vercel，撤销腾讯云自托管 / 2026-08-09
- **决策**：`gallery.mindfulpenpal.com` 保持 CNAME → Vercel；腾讯云服务器不再运行
  Gallery 容器（ADR-0023 覆盖 ADR-0022）。
- **代码**：删除 `apps/gallery-web/Dockerfile` 与 `.dockerignore`，移除
  `next.config.ts` 的 `output: "standalone"`；`deploy/docker-compose.production.yml`
  移除 gallery 服务与 Caddy 依赖；`Caddyfile.production` 移除 Gallery 站点；
  `deploy/.env.production.example` 移除 `GALLERY_WEB_*` 等服务器端变量。
- **文档**：新增 ADR-0023；`gallery-tencent-self-hosting.md` 改为“已撤销 + 服务器
  清理指南”；腾讯云两篇部署指南、Cloudflare 隧道文档、Vercel 部署指南与 ADR 索引
  同步更新。

## 0.7.17 · 修复 CI 三个任务失败 / 2026-08-09
- **Gallery Web / Generation Service 依赖审计失败**：
  - Gallery：postcss 间接依赖的 `nanoid@3.3.16` 命中高危
    GHSA-2v37-7h3g-55p8，通过 overrides 固定为 `3.3.17`。
  - Generation：`image-size` 无修复版本（ICNS / JXL / HEIF 解析器存在死循环
    DoS），改用 `sharp` 读取图片尺寸，覆盖 Base64 输出与 ComfyUI 本地文件两条
    路径；三个同步 Provider 调用点改为 `await`。
- **Python 测试套件失败**：
  - `config.py` 此前只接受 Postgres 形式的 `DATABASE_URL`，导致
    `sqlite:///:memory:` 被忽略、unittest 进程共享 `instance/app.db`，admin id
    断言变得依赖执行顺序；现在 `sqlite://` 也作为合法覆盖值。
  - 新增 `tests/__init__.py` 并让 CI 使用 `--top-level-directory .`，配合
    `DATABASE_URL=sqlite:///:memory:` 保证测试隔离。
  - 腾讯云 OCR 错误不再把上游 `Message` 拼进异常，避免泄漏响应内容。
- **验证**：Python 112 项测试全部通过；Generation Service typecheck + 87 项
  测试通过；Gallery lint / 生产构建通过；两个项目 `npm install` 审计均为
  0 漏洞。

## 0.7.16 · 修复 Gallery 页面显示不完整（CSP 拦截流式渲染）/ 2026-08-09
- **根因**：`next.config.ts` 静态设置的 CSP `default-src 'self'` 会拦截 Next.js
  App Router 流式渲染用来揭示正文的内联脚本（`$RS` 等），页面打开后停留在头部 +
  加载骨架；`img-src` 同时也会拦截腾讯云 COS/CDN 作品图。
- **修复**：新增 `apps/gallery-web/src/proxy.ts`，用 Next.js 16 Proxy 为每次请求
  生成随机 nonce，并写入请求/响应 CSP 头；Next.js 自动把 nonce 应用到框架脚本、
  页面 JS 与内联脚本。`style-src` 保留 `'unsafe-inline'`（React 内联样式），
  `img-src` 放开 `https:`（Generation Service 已按 `GALLERY_ASSET_HOSTS` 白名单
  校验资源 URL）。
- **验证**：生产构建、单测通过；本地生产模式 + mock Gallery API + 无头浏览器确认
  流式占位节点被移除、作品卡片正常渲染、控制台无 CSP 违规。

## 0.7.15 — M5 unified queue observability / 2026-08-09
- Connected the existing bounded BullMQ/Redis queue snapshot to the unified admin control plane at `GET /v1/admin/queue` and the BFF at `GET /api/admin/queue`.
- Added an on-demand Queue Monitoring tab showing Redis latency, workers, backlog, active/delayed jobs, and retained terminal counts; it is read-only and admin-only.
- Added safe `admin.queue_attention` logging for an unavailable queue or queued work without workers, while returning 503 when monitoring is unconfigured. See ADR-0021.

## 0.7.14 — M3 task-center foundation / 2026-08-09
- Added an additive, source-adapter task summary contract over the existing PostgreSQL-backed Generation Service task record; no dual-write table or queue state was introduced.
- Added signed, authenticated `GET /v1/tasks` and Gallery BFF `GET /api/tasks`, plus the user-facing Gallery `/tasks` center with task state, credit settlement, errors, and result links.
- Documented the one-source cursor boundary and the future multi-source adapter path in ADR-0020.

## 0.7.13 — Phase D code quality and governance / 2026-08-09
- Centralized session-authorized staged-download writes for seven file tools, with path-component rejection and upload-root containment regression coverage.
- Declared the owner-scoped persisted reimbursement export API as the maintained web contract; retained the incompatible legacy POST export payload only as a temporary compatibility boundary.
- Removed obsolete Flask AI-provider variables from the root example and README; image-generation configuration remains in the Generation Service example.
- Retained the tested queue observability primitive for M5 instead of deleting a reusable operational contract. See ADR-0019.

## 0.7.12 — Phase C performance and resource bounds / 2026-08-09
- Scoped Gallery interaction invalidation to the affected artwork detail, removed unnecessary image row locks for interactions/download grants, and retained full public-feed invalidation for deletion or moderation.
- Prevented Generation Workbench polling after unmount and Gallery Explorer stale-response races; anonymous BFF requests now skip session introspection when the Flask session cookie is absent.
- Increased safe sitemap keyset batches from 1,000 to 5,000 entries, reducing cross-service calls without incorrect cursor parallelism.
- Added configurable PDF file-count and page-count resource limits across PDF processing tools. See ADR-0018.

## 0.7.11 — Phase B generation reliability / 2026-08-09
- Made queue cancellation terminal-state safe: pending jobs are removed/signalled before final settlement, and removed or missing queue jobs release credits through the existing idempotent ledger path.
- Added bounded stale-running-job reconciliation, provider health checks with PostgreSQL-backed degraded routing, and worker environment controls for both loops.
- Added delayed Stripe Checkout and owned PaymentIntent success normalization so asynchronous payments reach the existing idempotent credit workflow.
- Moved ComfyUI model and sampling controls fully to server-side catalog bindings, and made remote timeout/network failures retryable for provider failover. See ADR-0017.

## 0.7.10 — Phase A Web / BFF security hardening / 2026-08-09
- Restored CSRF protection for reimbursement and ZIP write routes; anonymous reimbursement ownership now comes only from the signed Flask session.
- Scoped invoice preview and OCR to the attachment owner, validated file IDs before lookup, and added pre-decompression ZIP bomb limits.
- Bound staged tool downloads to the issuing browser session with short-lived authorization and upgraded published result names to 128-bit randomness; replaced `mktemp`.
- Restricted `/diag` to DEBUG/admin, added Gallery anti-framing and transport/content-type headers, made BFF writes fail closed without `Origin`, and added BFF role guards, rate limiting, and error-code allowlisting.
- Added regression coverage for CSRF, owner isolation, OCR path traversal, and ZIP compression bombs. See ADR-0016.

## 0.7.9 · 修复自定义配额用户登录后首页崩溃 / 2026-08-08
- **根因**：`User.custom_limit_map` 在 `custom_limits` 非空时误返回 `None`
  （JSON 解析代码被并入 `display_name`），登录后首页渲染 `remaining_for()`
  抛 `AttributeError`，表现为非管理员账号登录后无法进入网站。
- **修复**：将解析逻辑移回 `custom_limit_map`，`display_name` 只保留昵称逻辑；
  新增回归测试覆盖“带自定义配额的用户可正常登录并渲染首页”。
- **测试加固**：`tests/run_tests.py` 强制使用内存数据库，避免环境变量
  导致测试误写本地 `instance/app.db`。

## 0.7.8 · 报销 OCR 闭环与项目收尾整理 / 2026-08-08
- **OCR 问题闭环**：百度密钥填错已修正，发票上传 → OCR → 回填链路验证通过；
  识别顺序为 百度 → 腾讯云 → 手动填写，失败原因直接显示在页面。
- **收尾整理**：清理本地构建缓存（`.next.bak.*`）、测试报告
  （`tests/test_report.*`）、Python 缓存（`__pycache__`）与 `.tmp`；
  工作区与 origin/main 完全同步，无未提交改动。

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
