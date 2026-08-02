# 贡献指南

开始前先阅读 [`AGENTS.md`](AGENTS.md)、[Golden Rule](docs/architecture/engineering-principles.md) 和 [Git 策略](docs/operations/git-strategy.md)。生产网站已经在线，禁止直接在 `main` 开发或推送未完成代码。

## 第一次准备

```bash
git clone git@github.com:shilei2024/my-toolbox.git
cd my-toolbox
git fetch origin
git switch develop
git pull --ff-only origin develop
```

预期结果：当前分支为 `develop`，工作区干净。若远端尚未建立 `develop`，由仓库管理员按[分支策略](docs/operations/branch-strategy.md)创建并保护；普通贡献者不要自行从未知提交创建它。

## 创建工作分支

```bash
git switch develop
git pull --ff-only origin develop
git switch -c feature/short-description
```

文档和维护任务分别使用 `docs/*`、`chore/*`。线上紧急问题由发布负责人从 `main` 创建 `hotfix/*`。

## 提交规范

使用 Conventional Commits：

```text
feat(gallery): add private image filter
fix(billing): prevent duplicate credit settlement
docs(deploy): add COS rollback steps
refactor(provider): share timeout validation
perf(gallery): reduce public feed query cost
test(queue): cover duplicate delivery
chore(deps): update PostgreSQL client
ci(actions): add PostgreSQL integration gate
build(web): pin production runtime
style(admin): align empty state spacing
```

一个提交只表达一个目的。不要把格式化、依赖升级和业务功能混在同一提交；不要提交 `.env`、密钥、数据库 dump、用户上传或构建产物。

## 本地验证

```bash
python -m unittest discover -s tests -p "test_*.py"

cd services/generation-service
npm ci
npm run typecheck
npm test

cd ../../apps/gallery-web
npm ci
npm run lint
npm run test:seo
npm run build
```

预期结果：所有命令退出码为 `0`。若缺少依赖，先在相应目录执行文档指定的安装命令；不得通过删除测试或降低检查级别“修复”CI。

## 提交 Pull Request

```bash
git push --set-upstream origin feature/short-description
```

在 GitHub 创建目标为 `develop` 的 PR，完整填写模板，等待 CI、Vercel Preview 和独立评审。功能分支不得直接合并到 `main`。发布、热修复和回滚流程见[发布指南](docs/operations/release-guide.md)。
