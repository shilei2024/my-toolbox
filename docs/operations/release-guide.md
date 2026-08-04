# 发布与版本指南

## 版本规则

使用 Semantic Versioning：`MAJOR.MINOR.PATCH`。

- `v2.0.0`：破坏兼容的 API、数据或部署变化。
- `v1.1.0`：向后兼容的新功能。
- `v1.1.1`：向后兼容的缺陷或安全修复。

预发布可使用 `v1.2.0-rc.1`，但不能作为正式生产版本标签。

## 标准发布

### 1. 创建 release 分支

```bash
git fetch origin
git switch develop
git pull --ff-only origin develop
git switch -c release/1.1.0
git push --set-upstream origin release/1.1.0
```

预期：GitHub 出现 release 分支；Vercel 生成 Preview。release 分支只允许版本、文档和发布阻断修复，不再加入新功能。

### 2. 验证

完成[发布检查清单](release-checklist.md)，记录 CI run、Vercel Preview、staging 镜像 digest、数据库备份/恢复和回滚演练证据。

### 3. PR 到 main

创建 `release/1.1.0 → main` PR。只有 CI、Preview、独立审批和发布窗口全部就绪后，Release Manager 才能 squash/merge。

### 4. 创建签名/带注释 tag

```bash
git switch main
git pull --ff-only origin main
git tag -a v1.1.0 -m "MindfulPenPal v1.1.0"
git push origin v1.1.0
```

预期：GitHub Tags 出现 `v1.1.0`，它指向已合入 `main` 的提交。若 tag 指错且尚未发布，停止流程并由 Release Manager处理；已发布的 tag 不重写，创建新补丁版本。

### 5. 同步 develop

通过 `main → develop` PR 同步发布提交，不直接 push。验证 CI 后合并并删除 release 分支。

## 热修复

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c hotfix/1.1.1
```

只做最小修复并补回归测试。仍需 PR、CI、Preview、独立审批和回滚准备。发布 `v1.1.1` 后通过 PR 同步 `main → develop`。

## 谁负责

- Author：实现、测试、文档和回滚说明。
- Reviewer：独立验证影响与证据。
- Release Manager：版本号、窗口、合并、tag、部署和回滚决策。
- Operator：执行部署与健康检查。
- Database Owner：批准 migration、备份和恢复方案。

小团队可以一人兼任多个角色，但生产批准不得由部署发起人自批。
