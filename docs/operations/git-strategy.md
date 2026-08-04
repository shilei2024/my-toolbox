# Git 策略总览

## 目标

保护已在线的 `mindfulpenpal.com`，同时让功能开发、预览验证、发布和紧急修复有清晰且可恢复的路径。本项目采用轻量 GitFlow：`main` 和 `develop` 长期存在，其余分支短期存在。

## 环境映射

| Git 来源 | Vercel | 腾讯云后端 | 用途 |
| --- | --- | --- | --- |
| 本地工作区 | Local | 本地 Compose | 开发 |
| PR / `feature/*` | Preview | 不部署或临时测试环境 | 评审 |
| `develop` | 固定 Preview/自定义 Staging | staging | 集成验收 |
| `main` | Production | 仅发布流程可部署 production | 生产事实来源 |
| `vX.Y.Z` tag | 对应生产提交 | 不可变镜像/发布记录 | 审计与回滚 |

Vercel 的 Production Branch 必须为 `main`。后端生产不能因普通 `push` 自动部署，必须经过 GitHub `production` Environment 人工批准，且只允许已验证的 release tag/镜像 digest。

## 核心规则

1. 禁止直接 push、force push 或删除 `main`、`develop`。
2. 日常分支从 `develop` 创建，通过 PR 回到 `develop`。
3. `release/*` 从 `develop` 创建，只允许修复发布阻断问题；通过 PR 合入 `main`。
4. `hotfix/*` 只从 `main` 创建，通过 PR 回到 `main`，随后同步回 `develop`。
5. `main` 每次发布创建带注释的 SemVer tag。
6. Vercel Preview、CI、文档、迁移 dry-run、备份与回滚准备全部通过后才允许合并生产 PR。
7. 后端使用同一不可变镜像从 staging 晋级 production，不在 CVM 上临时构建。

## 工作流入口

- [分支策略与分支图](branch-strategy.md)
- [GitHub 工作流与保护规则](github-workflow-guide.md)
- [CI/CD 指南](ci-cd-guide.md)
- [发布指南](release-guide.md)
- [贡献指南](../../CONTRIBUTING.md)
- [生产发布检查清单](release-checklist.md)
- [回滚指南](rollback-guide.md)

## 当前启用范围

仓库已加入无部署权限的 CI、PR 模板和 Dependabot。生产 CD 暂不启用，因为生产 Dockerfile、Compose、镜像仓库、GitHub Environments 审批、CVM 部署用户和恢复演练尚未全部完成。这是上线阻断保护，不是遗漏。
