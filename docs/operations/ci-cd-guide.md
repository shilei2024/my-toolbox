# CI/CD 指南

## 当前 CI

`/.github/workflows/ci.yml` 在指向 `main`、`develop` 的 PR，以及两个分支的 push 上运行，且不读取部署密钥、不写仓库、不部署环境。

| Job | 检查 |
| --- | --- |
| Python tests | 安装锁定清单、`pip check`、35 项 Python 测试 |
| Generation Service | `npm ci`、typecheck、53 项测试、生产依赖 audit |
| Gallery Web | lint、SEO 测试、Next production build、生产依赖 audit |
| PostgreSQL integration | PostgreSQL 18、migration 0001–0005、Phase 6–10 集成测试 |

CI 使用固定 Python 3.12、Node 22.18 和完整 Action commit SHA。job 名称保持唯一，因为它们会成为分支保护的 required checks。

## 安全分阶段 CD

### Stage A：当前状态

- Vercel Git Integration 负责 Preview；只有 `main` 可成为 Production Branch。
- 后端仅记录手动 staging/production Runbook。
- 没有自动生产部署 workflow。

### Stage B：后端构建就绪后

前置条件：生产 Dockerfile、多架构/目标架构测试、Compose、healthcheck、非 root 用户、镜像漏洞扫描全部完成。

CI 为每个提交构建一次镜像：

```text
ghcr.io/shilei2024/my-toolbox:<git-sha>
```

镜像 tag 只用于可读性，部署记录同时保存不可变 digest：

```text
ghcr.io/shilei2024/my-toolbox@sha256:...
```

### Stage C：staging

`develop` 或 `release/*` 经 Environment 审批后，将该 digest 部署到 staging。执行 migration dry-run、smoke、集成和回滚演练。

### Stage D：production

Release Manager 选择已经在 staging 验证的同一 digest，使用 `workflow_dispatch` 触发。`production` Environment 要求非发起人批准；部署前再次显示版本、digest、迁移和备份 ID。不得重新构建镜像。

## 为什么不直接 SSH 自动部署

当前仓库还缺少生产镜像和 Compose。提前加入持有 CVM 密钥的 workflow 会扩大攻击面，并可能把未经验证的目录结构部署到线上。先建立只读 CI 与人工 Runbook，等基础设施满足门禁后再新增 CD，是更低成本且可恢复的方案。

## 失败处理

- Install/Lint/Typecheck/Test/Build 失败：修复分支，不允许降低检查标准后合并。
- audit 失败：确认是否为生产依赖、影响范围与可用修复；例外必须有安全负责人批准、到期日和 ADR/issue。
- PostgreSQL migration 失败：修复 migration，在新空库和生产备份恢复库重跑；禁止在生产试错。
- Vercel Preview 失败：查看 build log，确认 Root Directory 和 Preview 变量；不影响当前生产 deployment。

## 后续增强

- Python 生成 hash/lock 后启用阻断式 `pip-audit`。
- Docker 就绪后加入 SBOM、镜像扫描和签名。
- 配置 dependency review；该功能是否可用取决于仓库类型和 GitHub 套餐。
- 测试稳定后按路径拆分耗时任务，但 required check 名称必须保持稳定。
