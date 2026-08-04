# Changelog

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
