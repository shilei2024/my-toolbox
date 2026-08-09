# Mavis Gallery Web

Phase 6–8 的 Next.js App Router 前端、BFF、SEO 与 Admin 控制面。浏览器只访问同源 `/api/*`；服务端验证 Flask 会话后，为 Generation Service 签发短时内部身份上下文。前端不感知任何图片生成 Provider。

## 本地运行

```powershell
npm.cmd install
npm.cmd run dev
```

完整本地链路（Flask 主站 + Gallery + Generation API/Dispatcher/Worker）请使用仓库根目录脚本：

```powershell
.\scripts\dev\setup-local-env.ps1   # 补齐三份 .env（幂等，不覆盖已有值）
.\scripts\dev\dev-up.ps1            # 启动全部服务
.\scripts\dev\dev-health.ps1        # 健康检查（含登录桥）
.\scripts\dev\dev-down.ps1          # 停止全部服务
```

详细说明与端口规划见 [`docs/deployment/local-development-bridge.md`](../../docs/deployment/local-development-bridge.md)。

运行前配置：

- `GALLERY_SERVICE_BASE_URL`
- `GALLERY_INTERNAL_HMAC_SECRET`
- `MAVIS_AUTH_INTROSPECTION_URL`
- `GALLERY_INTROSPECTION_SECRET`
- `GALLERY_PUBLIC_ORIGIN`
- `MAVIS_AUTH_LOGIN_URL`（登录入口；可选 `MAVIS_AUTH_LOGOUT_URL`）

完整变量、信任边界和部署顺序见 `../../docs/deployment/phase-6-configuration.md` 与 `../../docs/deployment/phase-6-deployment.md`。

Phase 7 SEO 规则和部署检查见 `../../docs/architecture/phase-7-seo-pages.md` 与 `../../docs/deployment/phase-7-deployment.md`。

Phase 8 管理边界和部署检查见 `../../docs/architecture/phase-8-admin-console.md` 与 `../../docs/deployment/phase-8-deployment.md`。

图片/视频统一创作台、媒体工作流筛选和视频 owner-only 输出见
`../../docs/architecture/m4-media-generation.md` 与 `../../docs/deployment/m4-media-generation.md`。
Gallery 调用本机 ComfyUI 的完整启动、模型、依赖、验收和回滚步骤见
`../../docs/deployment/gallery-local-comfyui.md`。

## 验证

```powershell
npm.cmd run lint
.\node_modules\.bin\tsc.cmd --noEmit
npm.cmd run test:seo
npm.cmd run build
```
