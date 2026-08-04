# ADR-0013：轻量 GitFlow、Vercel Preview 与不可变后端发布晋级

状态：Accepted

## Why

`mindfulpenpal.com` 已在生产运行，前端托管于 Vercel，后端计划部署到腾讯云 CVM。仓库需要同时支持日常迭代、稳定预览、版本发布和紧急修复，并防止普通 push、未验证构建或错误环境变量影响生产。

决定采用 `main`/`develop` 双长期分支和短期 `feature`、`release`、`hotfix`、`docs`、`chore` 分支。Vercel 只有 `main` 是 Production Branch，其余分支为 Preview；`develop` Preview 作为低成本 staging。后端未来由 CI 构建一次不可变镜像，同一 digest 从 staging 人工晋级 production。当前先启用无部署权限 CI，生产 CD 等 Docker/Compose 和恢复门禁完成后再启用。

## Alternatives Considered

- Trunk-based + feature flags：分支更简单，但当前生产保护、自动测试成熟度和发布能力不足，`main` 高频合并会直接触发 Vercel 生产。
- 完整经典 GitFlow：隔离强，但长期 release 分支和大量合并会增加小团队成本；因此采用短生命周期的轻量版本。
- 每个环境重新构建镜像：实现简单，但 staging 与 production 产物可能不同，无法证明生产运行的是已验证产物。
- CVM 上 `git pull` 并本地构建：初期方便，但不可复现、回滚慢且要求生产服务器持有源码/构建工具。
- 立即添加 SSH 自动部署：当前缺少生产镜像、Compose 和完整进程入口，会扩大密钥与误部署风险。

## Future Impact

所有功能先进入 `develop`，release/hotfix PR 才能进入 `main`。GitHub required checks 和 Vercel Preview 成为合并门禁。Docker 基础完成后新增 Build/Deploy workflow，但必须使用 GitHub Environments、人工审批、同一 digest 晋级和部署证据。若团队与测试成熟到适合 trunk-based，应通过新 ADR 迁移。

## Performance

CI 增加 Python、两个 Node 项目和 PostgreSQL 集成验证时间；并行 job 降低总等待。依赖缓存减少重复安装。运行时性能不受影响；同一镜像晋级减少环境差异导致的故障。

## Cost

使用 GitHub-hosted CI、Vercel 原生 Preview 和 `develop` 分支 Preview 作为 staging，避免当前购买额外 Vercel Custom Environment。CI 分钟与 Preview 构建产生有限成本；可在积累数据后按路径优化，但不能牺牲 required checks。

## Security

CI 默认 `contents: read`，不读取部署密钥，Action 固定完整 SHA。生产 secrets 仅进入受保护 GitHub Environment/Vercel Production/CVM secret store。禁止 `pull_request_target` 执行不可信代码，禁止在日志和 Compose 中写密钥。分支规则阻止直接 push、强推和删除。

## Rollback Plan

CI 配置错误可回滚 workflow 文件，不影响正在运行的生产版本。Vercel 将生产域名提升回已验证 deployment；后端恢复上一个镜像 digest。数据库使用向后兼容 migration 或恢复到新实例，COS 使用版本恢复。若分支模型阻碍交付，可用新 ADR 调整，但不得取消 `main` 生产保护和审批准入。
