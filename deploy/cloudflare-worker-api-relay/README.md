# Cloudflare Worker API 转发（备用方案）

## 什么时候用

当 Vercel 的 Gallery 直接访问 `api-ai.mindfulpenpal.com` 持续超时/连接失败，
而海外节点（check-host.net）和服务器本机都正常时，说明 Vercel 到上海服务器的
链路不稳定。用 Cloudflare Worker 做一层转发：

```text
Vercel Gallery -> Cloudflare Worker（边缘节点）-> api-ai.mindfulpenpal.com
```

好处：免费、不需要改 DNS、不需要动服务器，只需要把 Gallery 的
`GALLERY_SERVICE_BASE_URL` 指向 Worker 地址。

## 部署步骤（10 分钟）

1. 注册/登录 Cloudflare（免费）：https://dash.cloudflare.com
2. 左侧菜单 → **Workers & Pages** → **Create** → **Create Worker**
3. 名称随意（例如 `mindfulpenpal-api-relay`），把 `worker.js` 的内容全部粘贴进去
4. **Deploy** 部署
5. 复制 Worker 的访问地址，形如：

   ```text
   https://mindfulpenpal-api-relay.<你的子域>.workers.dev
   ```

6. 验证：浏览器打开
   `<Worker地址>/v1/generation/workflows`，预期返回 401 JSON（说明转发成功）；
7. 打开 Vercel → **my-toolbox-gallery** → Settings → Environment Variables →
   Production 和 Preview，把 `GALLERY_SERVICE_BASE_URL` 改成 Worker 地址；
8. 重新部署 Gallery，刷新 create 页面验证。

## 说明

- Worker 会原样转发方法和请求头（包括 `X-Mavis-User-Context` /
  `X-Mavis-User-Signature`），不需要改 Gallery 代码；
- 免费额度 10 万次请求/天，对当前规模足够；
- 如果以后 Vercel 到上海直连恢复稳定，把 `GALLERY_SERVICE_BASE_URL`
  改回 `https://api-ai.mindfulpenpal.com` 即可回退。
