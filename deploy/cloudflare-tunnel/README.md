# Cloudflare Tunnel 快速验证（525 错误根治）

## 为什么用隧道

Cloudflare 边缘直连上海服务器时 TLS 握手失败（Error 525），说明"海外大云网络 → 大陆
服务器"的入站链路不稳定。隧道反其道而行：**服务器主动向外连 Cloudflare**，请求从
Cloudflare 边缘经隧道直接送到服务器内部，不再经过不稳定的入站 TLS。

## 快速验证（临时隧道，10 分钟）

在服务器上执行：

```bash
cd /opt/mindfulpenpal
docker run -d --name cloudflared-test --restart unless-stopped \
  --network mindfulpenpal-ai-production_mindfulpenpal-ai \
  cloudflare/cloudflared tunnel --no-autoupdate --url http://api:3101
```

等 30 秒后取出临时地址：

```bash
docker logs cloudflared-test 2>&1 | grep -o "https://[-a-zA-Z0-9.]*trycloudflare.com" | head -1
```

把输出的地址（形如 `https://xxx.trycloudflare.com`）填到 Vercel → my-toolbox-gallery →
Environment Variables → Production 的 `GALLERY_SERVICE_BASE_URL`，重新部署 Gallery，
刷新 create 页面。

- 如果 `/api/generation/workflows` 变成 200 → 隧道方案有效；
- 如果还是失败 → 说明出站到 Cloudflare 也被限制，改用海外小 VPS 转发方案。

验证完清理：

```bash
docker rm -f cloudflared-test
```

## 下一步（验证通过后）

临时地址每次重启会变，正式使用需要配置**命名隧道**并绑定 `api-ai.mindfulpenpal.com`
（DNS 记录改成 CNAME 指向隧道）。验证通过后告诉我，我给出正式配置的完整步骤。
