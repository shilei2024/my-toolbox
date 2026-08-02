# Git 与 CI/CD 基础变更记录

## 交付

- 建立轻量 GitFlow、分支职责、合并权限、分支图和 Conventional Commits 规范。
- 新增 GitHub PR 模板、Dependabot 和无生产部署权限的 CI。
- CI 覆盖 Python、Generation Service、Gallery Web、PostgreSQL 18 migrations 和 Phase 6–10 集成测试。
- 定义 GitHub rulesets、required checks、Vercel Preview/Production、GitHub Environments 和 secrets 边界。
- 新增 Vercel、腾讯云 CVM、环境变量、发布、回滚和两套检查清单。
- 新增 CONTRIBUTING 和 ADR-0013。

## 安全边界

- 未推送、合并、创建远端分支或触发线上部署。
- CI 不读取任何部署/生产密钥，production CD 保持禁用。
- 后端必须在生产 Dockerfile、Compose、完整进程入口和恢复演练完成后才能启用 CD。

## 验证

- 本地 Python、Generation Service、Gallery Web 等价检查通过。
- GitHub Actions/Dependabot YAML、治理测试和仓库 Markdown 链接检查通过。

## 回滚

删除或回滚 `.github` 治理文件和新增文档即可停止 CI，不影响当前 Vercel/CVM 运行版本。已配置的 GitHub/Vercel 控制台规则必须由管理员按变更记录单独恢复。
