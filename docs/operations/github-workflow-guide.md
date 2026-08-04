# GitHub 工作流与保护规则

## Pull Request 规则

所有代码通过 PR。模板位于 `/.github/PULL_REQUEST_TEMPLATE.md`，必须填写目标、Golden Rule、风险、验证、文档和回滚。

最低评审要求：

- `develop`：至少 1 名非作者 Reviewer。
- `main`：至少 1 名非作者 Reviewer；数据库、支付、认证、安全和生产部署建议 2 名。
- 敏感目录未来配置 CODEOWNERS；在真实团队/用户名确认前不提交占位 CODEOWNERS，避免错误阻断所有 PR。
- 新提交到达后撤销旧批准，所有会话必须解决。

## main 保护配置

仓库管理员进入 GitHub：`Settings → Rules → Rulesets → New branch ruleset`，目标分支选择 `main`，启用：

1. Require a pull request before merging。
2. Required approvals：1；高风险团队成熟后提高为 2。
3. Dismiss stale approvals；要求最后一次可评审 push 由其他人批准。
4. Require status checks：
   - `Python tests`
   - `Generation Service`
   - `Gallery Web`
   - `PostgreSQL integration`
   - Vercel Preview/Deployment 检查（连接项目后选择实际名称）
5. Require conversation resolution。
6. Block force pushes 和 branch deletion。
7. Require linear history；仓库统一使用 squash merge。
8. Do not allow bypassing；若当前 GitHub 套餐不支持，至少限制管理员日常绕过。

先让 CI 在 PR 中运行一次，GitHub 才会在状态检查选择器中显示 job 名称。配置后用测试 PR 验证：缺少审批或任一检查失败时 Merge 按钮必须不可用。

## develop 保护配置

创建第二个规则集，目标为 `develop`，配置与 `main` 相同，但不要求生产部署成功。必须要求四项 CI 和 Vercel Preview。

## GitHub Environments

规划两个 Environment：

| Environment | 允许来源 | 审批 | 密钥 |
| --- | --- | --- | --- |
| `staging` | `develop`、`release/*` | 可选 1 人 | 仅 staging |
| `production` | `main`、`v*` | 必须非发起人审批 | 仅 production |

禁止把生产密钥配置为普通 repository secret 后让所有 CI job 可读。生产密钥只放 `production` Environment；CI workflow 本身不引用任何部署密钥。

## GitHub Actions 安全

- workflow 顶层显式 `permissions: contents: read`。
- 第三方 Action 固定到完整 commit SHA，并用注释标记版本。
- 不使用 `pull_request_target` 执行 PR 中的代码。
- fork PR 不获得密钥。
- 生产使用 GitHub Environment 审批和分支限制。
- Dependabot 只创建 PR，仍需完整 CI 与评审。

GitHub 官方说明保护分支可要求 PR、审批、状态检查并阻止强推/删除；Environment 可限制分支并要求人工批准。参考：[Protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)、[Deployments and environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments)、[Secure use of GitHub Actions](https://docs.github.com/en/actions/reference/security/secure-use)。
