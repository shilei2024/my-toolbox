# 打通 Gallery 创作闭环：Cloudflare 隧道完整手册（2026-08-06 最新）

> 适用场景：Vercel 的 Gallery 调用 `api-ai.mindfulpenpal.com` 持续 503
> （`fetch failed` / 超时），而海外节点、服务器本机都能访问；Cloudflare 直连时出现
> **Error 525（TLS 握手失败）**。说明海外大型云网络直连上海服务器不稳定，需要用
> Cloudflare Tunnel 让服务器主动外连。

## 0.5 重要前提（先读，避免被误导）

- **Worker ≠ 站点**：只创建 Worker（`xxx.workers.dev`）并没有把域名加入 Cloudflare。
  Worker 仍是从 Cloudflare 边缘访问上海服务器，遇到 525 时 Worker 一样会失败，
  所以 **Worker 转发解决不了 525**；
- **快速隧道（第 2 节）不需要站点、不需要改 DNS**，现在就能验证；
- **正式命名隧道（第 3 节）才需要把 `mindfulpenpal.com` 加入 Cloudflare（免费站点）**，
  由 Cloudflare 管理 DNS 并给 `api-ai` 提供稳定 CNAME。

## 0.6 当前进度（2026-08-06）

- ✅ 快速隧道已验证：`trycloudflare.com` 地址访问 `/v1/generation/workflows` 返回 401，
  说明隧道方案有效；
- ❌ Gallery 线上 `/api/generations` 返回 404：原因是线上部署跑的是旧版本代码
  （Production Branch 不是 main，或最新部署未成功）；
- ✅ 下一步：先修 Vercel 部署版本（见第 5 节第 0 条），再建站点、配正式命名隧道。

## 0. 已经完成、不需要重做的部分

- 服务器 `DATABASE_URL` 已切换到 Prisma（含 `uselibpqcompat=true&sslmode=require`）；
- 本地 PostgreSQL 已停用，5432 公网已关闭；
- API / dispatcher / worker 已重启并稳定（`DB_OK`、无崩溃循环）；
- 集成分支 `codex/frontend-backend-integration` 已包含代码修复：
  - 数据库连接超时 5s → 15s（可配置）+ TCP 保活；
  - dispatcher 断连不再崩溃，指数退避重试；
  - Gallery BFF 超时 8s → 30s（可配置）+ 底层错误原因日志；
  - Cloudflare Worker 转发（备用）和隧道文档。

## 1. 把域名加入 Cloudflare（创建站点）——正式方案才需要

如果只是想先验证隧道能不能通，直接跳到第 2 节，这一节不用做。

1. Cloudflare 控制台 → **Add a site** → 输入 `mindfulpenpal.com` → 选 **Free** 套餐；
2. Cloudflare 给出两个 nameserver（形如 `xxx.ns.cloudflare.com`、
   `yyy.ns.cloudflare.com`），记下来；
3. 打开 Namecheap → Domain List → Manage → **Nameservers** → 改成这两个 → 保存；
4. 等待几分钟到几小时，Cloudflare 站点状态变为 **Active**；
5. 站点 Active 后再做下面的 SSL 和 DNS 设置。

### 1.1 SSL 模式与 DNS 记录（站点 Active 后）

1. 打开 Cloudflare Dashboard → 你的站点 → **SSL/TLS → Overview**：
   加密模式设为 **Full (strict)**，保存；
2. 打开 **DNS → Records**，确认/修正三条记录：

   | 名称 | 类型 | 内容 | 代理 |
   | --- | --- | --- | --- |
   | `mindfulpenpal.com` | CNAME | `cname.vercel-dns.com` | 开或关均可 |
   | `gallery` | CNAME | `cname.vercel-dns.com` | 开或关均可 |
   | `api-ai` | **删除**（稍后用隧道 CNAME 替代） | - | - |

3. 保存后立即确认 https://mindfulpenpal.com 和 https://gallery.mindfulpenpal.com
   都能打开（防止 DNS 迁移把主站弄挂）。

## 2. 快速验证隧道（临时地址，10 分钟，零配置）

SSH 登录服务器：

```bash
cd /opt/mindfulpenpal
docker run -d --name cloudflared-test --restart unless-stopped \
  --network mindfulpenpal-ai-production_mindfulpenpal-ai \
  cloudflare/cloudflared tunnel --no-autoupdate --url http://api:3101
```

等 30 秒，取临时地址：

```bash
docker logs cloudflared-test 2>&1 | grep -o "https://[-a-zA-Z0-9.]*trycloudflare.com" | head -1
```

把地址填到 Vercel → **my-toolbox-gallery** → Settings → Environment Variables →
**Production** 的 `GALLERY_SERVICE_BASE_URL`（例如 `https://xxx.trycloudflare.com`），
保存后自动重新部署。刷新 `gallery.mindfulpenpal.com/create`：

- `/api/generation/workflows` 返回 200 → 隧道方案有效，进入第 3 步；
- 仍失败 → 出站到 Cloudflare 也被限制，改用海外小 VPS 转发（见第 6 节）。

验证完先清理：

```bash
docker rm -f cloudflared-test
```

## 3. 正式命名隧道（长期稳定地址）

> 前提：已经完成第 1 节（域名已加入 Cloudflare 且 Active）。

### 3.1 准备目录和登录

```bash
mkdir -p /opt/mindfulpenpal/cloudflared
docker run -it --rm -v /opt/mindfulpenpal/cloudflared:/etc/cloudflared \
  cloudflare/cloudflared tunnel login
```

终端会输出一个网址，在**你自己电脑的浏览器**打开并授权域名，完成后回服务器继续。

### 3.2 创建隧道

```bash
docker run --rm -v /opt/mindfulpenpal/cloudflared:/etc/cloudflared \
  cloudflare/cloudflared tunnel create mindfulpenpal-api
```

记下输出的 **Tunnel ID**（形如 `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`）。

### 3.3 写配置文件

```bash
sudoedit /opt/mindfulpenpal/cloudflared/config.yml
```

内容（把 `<TUNNEL_ID>` 换成上面记下的 ID）：

```yaml
tunnel: <TUNNEL_ID>
credentials-file: /etc/cloudflared/<TUNNEL_ID>.json
ingress:
  - hostname: api-ai.mindfulpenpal.com
    service: http://api:3101
  - service: http_status:404
```

### 3.4 绑定域名

先到 Cloudflare Dashboard → DNS，**删除 `api-ai` 的 A 记录**（第 1.1 步做过就跳过），然后：

```bash
docker run --rm -v /opt/mindfulpenpal/cloudflared:/etc/cloudflared \
  cloudflare/cloudflared tunnel route dns mindfulpenpal-api api-ai.mindfulpenpal.com
```

这会在 Cloudflare 自动创建一条 CNAME（`api-ai` → `<tunnel-id>.cfargotunnel.com`）。

### 3.5 启动隧道服务

```bash
cd /opt/mindfulpenpal
docker compose -f deploy/docker-compose.cloudflared.yml up -d
docker compose -f deploy/docker-compose.cloudflared.yml logs --tail=30 cloudflared
```

预期日志出现 `Registered tunnel connection`。

### 3.6 验证

在你电脑浏览器打开：

```text
https://api-ai.mindfulpenpal.com/v1/generation/workflows
```

预期返回 401 JSON（说明隧道已通、鉴权正常）。

## 4. Vercel 最终配置

1. Vercel → **my-toolbox-gallery** → Settings → Environment Variables：
   - **Production 和 Preview** 的 `GALLERY_SERVICE_BASE_URL` 统一改为
     `https://api-ai.mindfulpenpal.com`（如果第 2 步临时改成了 trycloudflare 地址，改回来）；
   - `GALLERY_INTERNAL_HMAC_SECRET` 保持与服务器一致；
2. 保存后自动重新部署，等 Deployments Success；
3. 刷新 `gallery.mindfulpenpal.com/create`，确认 `/api/generation/workflows` 返回 200。

## 5. 部署集成分支最新代码

集成分支 `codex/frontend-backend-integration` 已包含全部最新修复。上线方式：

0. **先确认 my-toolbox-gallery 的 Production Branch = main**（Settings → Git），
   否则线上会一直跑旧版本（`/api/generations` 返回 404）；
1. 打开 PR：https://github.com/shilei2024/my-toolbox/pull/new/codex/frontend-backend-integration
2. 让 Vercel 为 **my-toolbox** 和 **my-toolbox-gallery** 生成 Preview；
3. 在 Preview 的 Gallery 环境变量里配上 `GALLERY_SERVICE_BASE_URL`、
   `GALLERY_INTERNAL_HMAC_SECRET`、`MAVIS_AUTH_INTROSPECTION_URL`、
   `GALLERY_INTROSPECTION_SECRET`（与 Production 相同）；
4. Preview 验证通过后，合并 PR 到 main，生产自动部署新代码。

## 6. 兜底方案：海外小 VPS 转发

如果隧道也不通（出站到 Cloudflare 被限制），租一台香港/新加坡小 VPS（约 $5/月），
在上面装 Caddy 或 nginx，把 `https://api-ai.mindfulpenpal.com` 反向代理到
`http://<腾讯云服务器IP>:3101`（需要在腾讯云防火墙放行 3101 到该 VPS 的 IP，或用
Cloudflare Tunnel 的 API 端口）。之后 `GALLERY_SERVICE_BASE_URL` 指向 VPS 域名即可。

## 7. 验收清单（创作闭环）

1. `gallery.mindfulpenpal.com/api/me/session` 返回 `{"role":"admin","bridge":"ok"}`；
2. `/create` 能加载工作流（Network 里 `/api/generation/workflows` 为 200）；
3. 提交生成：任务创建 → 积分扣除 → Provider（jimeng）调用 → 图片上传 COS →
   最近任务列表显示 → 工作台内嵌预览展示；
4. 失败任务可重试（回填重试）；
5. mindfulpenpal.com 老账号登录正常、`/admin` 正常；
6. 服务器 `docker compose ps` 全部 Up，无崩溃循环。

## 8. 回退

- 停隧道：`docker compose -f deploy/docker-compose.cloudflared.yml down`；
- 恢复直连：Cloudflare DNS 把 `api-ai` 改回 A 记录 `101.43.122.182`（关闭代理）；
- `GALLERY_SERVICE_BASE_URL` 始终是 `https://api-ai.mindfulpenpal.com`，无需改动。
