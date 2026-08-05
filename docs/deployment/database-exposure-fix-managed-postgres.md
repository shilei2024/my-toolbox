# 关闭 5432 公网暴露：数据库迁移到托管 PostgreSQL（方案 C）

> 状态：待执行。本文是「主站保留 Vercel、数据库迁移到 Vercel/Neon 托管 PostgreSQL」的完整操作手册，
> 按顺序执行，任何一步失败都停下来贴出错误，不要跳过验证。

## 1. 为什么必须做

当前 PostgreSQL 运行在腾讯云服务器（101.43.122.182）上，监听 `0.0.0.0:5432`，Lighthouse
防火墙对全网开放 5432。任何互联网 IP 都可以尝试连接数据库；`mavis` 账号密码此前已经在对话和
终端历史中出现过，存在被爆破、拖库、勒索加密的真实风险。

本次迁移后：

- 主站 Flask 继续留在 Vercel，不搬服务器、不做 ICP 备案、不转移域名；
- 数据库换成 Vercel/Neon 托管 PostgreSQL，使用 TLS 连接，并拥有自动备份；
- AI 生成服务继续留在腾讯云服务器，只把数据库连接串改为托管库；
- 删除 5432 公网防火墙规则，本机 PostgreSQL 停止对外服务；
- COS 图片存储、Redis、Gallery（Vercel）全部保持不变。

### 迁移前后结构

迁移前：

```text
Vercel 主站 Flask ──公网 5432──> 腾讯云 PostgreSQL（暴露）
腾讯云 AI 服务（api/worker/dispatcher）──127.0.0.1──> 同一 PostgreSQL
```

迁移后：

```text
Vercel 主站 Flask ──TLS──> Neon 托管 PostgreSQL
腾讯云 AI 服务（api/worker/dispatcher）──TLS──> Neon 托管 PostgreSQL
```

## 2. 需要准备的东西

1. 直接使用 Vercel 自带的免费数据库：**Vercel Postgres**（由 Neon 提供，有免费 Hobby 档）。
   不需要另外注册 Neon 账号；只有想用 Neon 独立控制台的高级功能时才需要；
2. 服务器 SSH（你已经有了）；
3. 服务器上有 PostgreSQL 16 客户端（`pg_dump`/`psql` 16.14，已经确认有）。

费用说明：Vercel Postgres 免费档（Hobby）可以先完成迁移和验证；免费档闲置后可能休眠，
首次访问会慢几秒，并且存储和计算时长有限。正式长期运营再考虑升级付费档（以 Vercel 控制台
当前价格为准）。

## 3. 第 1 步：创建托管数据库

1. 打开 Vercel Dashboard → **Storage** → **Create Database** → 选 **Postgres**
   （这就是 Vercel Postgres，免费）；
2. 区域选 **Singapore**（如果没有就选离上海最近的区域）；
3. 创建后把数据库关联到 **my-toolbox** 项目：Vercel 会自动把 `POSTGRES_URL`、
   `POSTGRES_URL_NON_POOLING` 等变量注入 Production / Preview / Development 环境，
   主站 Flask 不需要手动配置；
4. 在数据库详情页复制 **Pooled connection** 连接串（带 `-pooler` 的那个），供第 4 步
   服务器 AI 服务使用。连接串形如：

   ```text
   postgresql://用户名:密码@ep-xxxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
   ```

> 重要：不要把连接串、密码、用户名发到聊天、工单或 GitHub。以下步骤全部在你自己电脑和
> 服务器终端里完成。

## 4. 第 2 步：备份并迁移数据（在服务器执行）

SSH 登录服务器后执行：

```bash
cd /opt/mindfulpenpal
git pull
```

> 如果仓库还没有这个迁移脚本，先让 Codex 把脚本推送上去，再执行 `git pull`。

把旧库地址从环境变量文件里取出来（不用手动敲密码），再填上新库地址：

```bash
export OLD_DB_URL="$(grep '^DATABASE_URL=' /etc/mindfulpenpal.production.env | cut -d= -f2- | sed 's#host.docker.internal#127.0.0.1#')"
export NEW_DB_URL='postgresql://<Neon用户名>:<Neon密码>@<ep-xxxx>-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require'
sh deploy/migrate-db-to-managed.sh
```

预期输出（数字可能不同，但结构一致）：

```text
[1/4] dumping current database -> /opt/mindfulpenpal/backups/...
[2/4] restoring into managed database ...
[3/4] verifying
 users
-------
     6
 public_tables
---------------
            16
 schema_name
-------------
 ai
[4/4] done.
```

验证要点：

- `users` 数量与现在一致（当前是 6）；
- `public_tables` 为 16；
- `ai` schema 存在；
- 全程没有 `ERROR`。

如果出现 ERROR，把完整错误贴出来，不要反复重试。已经失败过一次、确认目标库没有其他数据时，
可以带 `CLEAN_TARGET=1` 重跑：

```bash
CLEAN_TARGET=1 sh deploy/migrate-db-to-managed.sh
```

## 5. 第 3 步：切换 Vercel 主站到托管库

1. 打开 Vercel → 项目 **my-toolbox** → Settings → Environment Variables，环境选 **Production**；
2. 确认存在 Vercel 自动注入的 `POSTGRES_URL` / `POSTGRES_URL_NON_POOLING`，
   值指向刚创建的 Vercel Postgres；
3. 删除旧的 `DATABASE_URL`（它指向腾讯云旧库，避免回退）；
4. 确认 `PRISMA_DATABASE_URL` 不存在；
5. 如果保存后没有自动触发部署，就手动 Redeploy 一次；
6. 等 Deployments 显示 Success。

验证：

- 打开 https://mindfulpenpal.com，用老账号登录；
- 进入 `/admin`，用户列表应显示全部 6 个老账号；
- 如果老账号消失，说明第 3 步的旧变量没有删干净，或部署还没完成。

## 6. 第 4 步：切换腾讯云 AI 服务到托管库

在服务器执行：

```bash
sudoedit /etc/mindfulpenpal.production.env
```

只改 `DATABASE_URL` 这一行，改成和第 1 步相同的 Pooled 连接串。**其他行（Redis、COS、
Provider 等）一律不动。** 保存退出（nano 是 Ctrl+O 回车，再 Ctrl+X）。

然后重启 AI 相关容器：

```bash
cd /opt/mindfulpenpal
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml --profile production up -d \
  --force-recreate api dispatcher worker deletion-worker
```

验证：

```bash
curl -s https://api-ai.mindfulpenpal.com/health
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml ps
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f deploy/docker-compose.production.yml logs --tail=50 worker
```

预期：`health` 返回 ok；所有容器 Up；worker 日志出现 `queue.generation_worker_started`，
且不再有 `redis_connection_error` / 数据库连接错误。

最后做一次全链路验收：

1. 打开 https://gallery.mindfulpenpal.com/create；
2. 登录（管理员共享登录已修好）；
3. 提交一个生成任务，确认：任务创建 → 积分扣除 → Provider 调用 → 图片上传 COS →
   Gallery 展示。

## 7. 第 5 步：收口，删除 5432 公网暴露

先确认没有容器还在映射 5432：

```bash
sudo ss -tlnp | grep ':5432' || echo "no listener"
sudo docker ps --format '{{.Names}} {{.Ports}}' | grep 5432 || echo "no container mapping"
```

如果还有 Docker 容器映射 5432（例如旧的 `mavis-postgres`），先停掉它：

```bash
sudo docker stop mavis-postgres
```

然后到腾讯云控制台删除防火墙规则：

1. 打开腾讯云 Lighthouse 控制台 → 实例（101.43.122.182）；
2. 点 **防火墙**；
3. 找到 **5432** 那条规则（来源 `0.0.0.0/0`）；
4. 删除它。

再停用服务器本机的 PostgreSQL（数据文件保留，随时可以重新启用）：

```bash
sudo systemctl disable --now postgresql
```

最终验证：

```bash
sudo ss -tlnp | grep ':5432' || echo "5432 closed"
```

预期输出 `5432 closed`。然后在你自己的电脑上执行：

```text
telnet 101.43.122.182 5432
```

预期：连接失败/超时。Lighthouse 安全告警会在下一个检测周期消失。

## 8. 第 6 步：安全收尾

1. 旧数据库（db.prisma.io）如果还在，登录对应平台删除项目或轮换密码；
2. 本机 PostgreSQL 已停用，`mavis` 账号不再对外；
3. 第 2 步的 dump 文件保留至少 30 天（文件在 `/opt/mindfulpenpal/backups/`）；
4. 托管库启用后，确认 Neon/Vercel 控制台里自动备份已开启（付费档默认有）；
5. 以后不要把任何数据库连接串、密码发到聊天或工单。

## 9. 回滚方案

如果迁移后发现严重问题，可以整体回滚（主站和 AI 服务不会同时断）：

1. **主站回滚**：Vercel 把 `DATABASE_URL` 改回腾讯云连接串，保存后自动重新部署；
2. **AI 服务回滚**：服务器上把 `/etc/mindfulpenpal.production.env` 的 `DATABASE_URL`
   改回原来的本机地址，重启 compose 容器；
3. **数据回滚**：如果需要，用第 2 步的 dump 恢复到本机 PostgreSQL；
4. 回滚期间如需临时开放 5432，记得用完后立刻再删除规则。

## 10. 常见失败

| 现象 | 处理 |
| --- | --- |
| `pg_restore` 报 ERROR | 贴出完整错误；确认目标库为空后可用 `CLEAN_TARGET=1` 重跑 |
| 免费档数据库休眠，首次访问慢 | 属正常现象；正式使用建议升级付费档 |
| Vercel 部署后老账号消失 | 检查 `POSTGRES_URL_*`、`PRISMA_DATABASE_URL` 是否已删除，确认部署 Success |
| worker 日志报数据库错误 | 确认服务器 env 的 `DATABASE_URL` 已改，并执行了 `--force-recreate` |
| 连接串里密码含特殊字符 | 在 Neon 控制台复制 Pooled 连接串，不要手工改动 |
