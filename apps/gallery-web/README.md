# Mavis Gallery Web

Phase 6–8 的 Next.js App Router 前端、BFF、SEO 与 Admin 控制面。浏览器只访问同源 `/api/*`；服务端验证 Flask 会话后，为 Generation Service 签发短时内部身份上下文。前端不感知任何图片生成 Provider。

## 本地运行

```powershell
npm.cmd install
npm.cmd run dev
```

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

## 验证

```powershell
npm.cmd run lint
.\node_modules\.bin\tsc.cmd --noEmit
npm.cmd run test:seo
npm.cmd run build
```
