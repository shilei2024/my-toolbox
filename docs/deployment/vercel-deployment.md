# Vercel 前端部署指南

## 部署边界（2026-08-09 起）

Gallery Web（`apps/gallery-web`）**只部署在 Vercel**，不部署到腾讯云服务器（见
ADR-0023）。`gallery.mindfulpenpal.com` 的 DNS 保持 CNAME → `cname.vercel-dns.com`；
腾讯云服务器只运行 Generation Service 与 `api-ai` 入口。服务器清理步骤见
[Gallery 部署：仅 Vercel](gallery-tencent-self-hosting.md)。

## 安全目标

`mindfulpenpal.com` 只由 `main` 触发 Production Deployment。所有其他分支生成 Preview，不改变生产域名。Vercel 官方将 Local、Preview、Production 分开，非 Production Branch 的 push/PR 默认生成 Preview；Production Branch 的 push/merge 才更新生产域名。[Vercel Environments](https://vercel.com/docs/deployments/environments)

## 首次配置前检查

- [ ] 当前生产项目和域名绑定已截图/导出。
- [ ] GitHub 仓库为 `shilei2024/my-toolbox`。
- [ ] Next.js Root Directory 已确认；本仓库目标为 `apps/gallery-web`。
- [ ] Production Branch 为 `main`。
- [ ] Preview 与 Production 变量完全分离。
- [ ] `develop` 有稳定 Preview URL，作为低成本 staging。
- [ ] 分支保护已要求 CI 和 Vercel 状态。

如果现有生产 Vercel 项目的 Root Directory 不是 `apps/gallery-web`，不要直接修改。先复制为新测试项目验证所有路由、域名和环境变量，得到切换批准后再操作生产项目。

## Dashboard 配置

1. 登录 Vercel，打开现有项目。
2. `Settings → Git`：确认连接正确 GitHub 仓库。
3. 将 Production Branch 设置为 `main`。
4. `Settings → Build and Deployment`：确认 Root Directory。
5. `Settings → Environment Variables`：分别配置 Development、Preview、Production。
6. 为 `develop` 配置 branch-specific Preview 变量，使其连接 staging 后端、数据库和 COS，绝不能使用生产写凭据。

成功验证：创建一个 `docs/vercel-preview-check` 分支并 push 后，应出现 Preview URL；`mindfulpenpal.com` 当前 production deployment ID 不变化。

## 本地 Preview 构建

```bash
cd apps/gallery-web
npm ci
npm run lint
npm run test:seo
npm run build
```

预期：命令全部退出 `0`，Next 输出路由清单。失败时先修复本地构建，不要通过 Vercel 重复试错。

需要 Vercel 环境时：

```bash
npx vercel link
npx vercel pull --environment=preview
npx vercel build
```

`.vercel/` 和拉取的本地变量必须被忽略，不得提交。生产变量只应由有权限的管理员在 Dashboard/受控 CLI 中管理；普通开发者不应拉取生产密钥。

## Preview 验收

- 登录、退出和 Session Cookie
- Gallery、作品详情、收藏、点赞、下载
- Pricing/Billing 使用测试 Provider
- Admin RBAC 与 `noindex`
- robots、sitemap、canonical、OG
- 移动端与桌面端
- 浏览器 console/network 无敏感字段
- Preview 后端/COS 与生产资源隔离

## 生产发布

只有 release/hotfix PR 合入 `main` 后由 Vercel Git Integration 发布。禁止开发者执行未审批的 `vercel --prod`。

发布时记录：Git SHA、SemVer tag、Vercel deployment ID、操作者、开始/结束时间和 smoke 结果。生产部署失败时，Vercel 不应把失败构建提升为生产；确认生产域名仍指向上一个健康 deployment。

## 回滚

打开 Vercel `Deployments`，选择最近一个已验证的生产 deployment，执行 Promote/Rollback，并验证域名、登录和核心页面。变量修改只影响后续 deployment，因此变量回滚后必须重新部署或提升使用正确变量构建的 deployment。[Vercel Environment Variables](https://vercel.com/docs/environment-variables)

完整事故流程见[回滚指南](../operations/rollback-guide.md)。

## 常见错误

- Preview 使用生产数据库：立即停止测试、轮换写凭据并审计影响。
- Production Branch 不是 main：修正前禁止合并 PR。
- Preview 404：检查 Root Directory 和 Next 构建输出。
- BFF 502/401：检查 Preview 的后端 URL、HMAC secret 和 Origin，不要临时关闭鉴权。
