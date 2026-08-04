# AI 模块并入生产主线 · 合并 Runbook

> 本 runbook 记录 `codex/m1-generation-api` 并入生产主线的安全流程。生产 `main` 只能由 Release Manager 在独立审批后合并，任何人不允许直接推送 `main`。

## 1. 前置条件（已完成确认）

- `origin/main`（`57d5aeb`）是 AI 分支的祖先，无分叉，Git 冲突风险为零；
- M1.1 可用性补全已提交到 `codex/m1-generation-api`（`89361cf`）；
- 合并后代码已通过：Generation Service typecheck + 62 项测试、Gallery Web lint/SEO/生产构建、Python 迁移契约测试。

## 2. 备份分支（保护现场）

```bash
git fetch origin
git branch backup-main-before-ai origin/main
```

`backup-main-before-ai` 永久保留到生产稳定后再删除；期间任何人不得 rebase/force-push 该分支。

## 3. 创建 release 分支并合并

```bash
git switch -c release/0.4.0 origin/main
git merge --no-ff codex/m1-generation-api \
  -m "merge: integrate AI generation module into release/0.4.0"
```

预期：`Merge made by the 'ort' strategy`，无冲突。若出现冲突，只允许在 release 分支上解决并保留双方语义；禁止用 `--ours/--theirs` 掩盖问题。

## 4. 合并后验证（本机 + CI）

```bash
cd services/generation-service
npm run typecheck && npm test
cd ../../apps/gallery-web
npm run lint && npm run test:seo && npm run build
```

推送 release 分支后，GitHub Actions 会再跑一次完整 CI（Python、Generation、Gallery、Postgres 集成）：

```bash
git push -u origin release/0.4.0
```

## 5. 发布审批门

只有满足以下条件才允许把 release 分支合入 `main`：

- [ ] CI 四个 job 全部通过；
- [ ] [上线验收清单](../deployment/ai-merge-acceptance.md) 10 项全部通过并留档；
- [ ] 数据库备份与恢复演练完成；
- [ ] 生产 Provider、COS、Redis、镜像 digest 已由 preflight 验证；
- [ ] 独立 Reviewer 批准。

## 6. 合入 main 与生产部署

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff release/0.4.0 -m "release: MindfulPenpal AI enhanced 0.4.0"
git tag v0.4.0
git push origin main --tags
git switch develop
git merge main -m "chore: sync AI enhanced release back to develop"
git push origin develop
```

合入 `main` 后 Vercel 两个项目会自动构建；服务器按 `deploy/DEPLOY_GUIDE.md` 完成迁移与启动。

## 7. 回滚

- 前端：Vercel Promote/Rollback 到上一个健康 deployment；
- 后端：停止 dispatcher/worker/api/caddy，回退镜像 digest 后 `up -d --no-build`；
- 数据库：迁移只新增 `ai` schema，不需要 down migration；恢复用备份验证后切换 `DATABASE_URL`；
- 代码：`git revert` 只用于紧急热修复；首选把 `main` 指回 `backup-main-before-ai` 的已验证状态（需审批）。

## 8. 清理

生产稳定运行 24h 后：

```bash
git branch -d release/0.4.0
git push origin --delete release/0.4.0
```

`backup-main-before-ai` 保留到下个版本发布后再删除。
