# 关闭 5432 公网暴露：数据库迁移到托管 PostgreSQL（方案 C）

> 状态：待执行。本文是「主站保留 Vercel、数据库迁移到 Vercel 上的 Prisma Postgres」的完整操作手册，
> 按顺序执行，任何一步失败都停下来贴出错误，不要跳过验证。

## 1. 为什么必须做

当前 PostgreSQL 运行在腾讯云服务器（101.43.122.182）上，监听 `0.0.0.0:5432`，Lighthouse
防火墙对全网开放 5432。任何互联网 IP 都可以尝试连接数据库；`mavis` 账号密码此前已经在对话和
终端历史中出现过，存在被爆破、拖库、勒索加密的真实风险。

本次迁移后：

- 主站 Flask 继续留在 Vercel，不搬服务器、不做 ICP 备案、不转移域名；
- 数据库换成 Vercel 上的 Prisma Postgres 托管数据库，使用 TLS 连接，并拥有自动备份；
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
Vercel 主站 Flask ──TLS──> Prisma Postgres（db.prisma.io）
腾讯云 AI 服务（api/worker/dispatcher）──TLS──> Prisma Postgres（db.prisma.io）
```

## 2. 需要准备的东西

1. 使用 Vercel 上的 **Prisma Postgres**（Vercel Marketplace 集成，有免费档）。
   连接串地址固定是 `db.prisma.io`，不需要另外注册独立账号；
2. 服务器 SSH（你已经有了）；
3. 服务器上有 PostgreSQL 16 客户端（`pg_dump`/`psql` 16.14，已经确认有）。

费用说明：Prisma Postgres 免费档可以先完成迁移和验证；免费档有存储和连接数限制，
正式长期运营再考虑升级付费档（以 Vercel 控制台当前价格为准）。

## 3. 第 1 步：创建托管数据库

1. 在 Vercel 上添加 **Prisma Postgres** 集成（Vercel Marketplace / 集成页面），
   创建数据库并关联到 **my-toolbox** 项目；
2. 创建向导里如果有区域选项，选离上海最近的区域；
3. Vercel 会自动把 `POSTGRES_URL`、`PRISMA_DATABASE_URL` 等变量注入 Production /
   Preview / Development 环境，主站 Flask 不需要手动配置；
4. 复制一条完整的连接串（`postgres://...`）。Prisma Postgres 的连接串地址固定是
   `db.prisma.io`，**没有** `-pooler` 这种写法，直接从项目环境变量里复制
   `POSTGRES_URL` 或 `PRISMA_DATABASE_URL` 的值即可。连接串形如：

   ```text
   postgres://用户名:密码@db.prisma.io:5432/postgres?sslmode=require
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

> 可选（推荐）：迁移期间如果不想让 AI 服务继续往旧库写数据，可以先暂停生成相关容器，
> 等第 4 步改好连接串后再启动：
>
> ```bash
> cd /opt/mindfulpenpal
> docker compose --env-file /etc/mindfulpenpal.production.env \
>   -f deploy/docker-compose.production.yml --profile production stop \
>   api dispatcher worker deletion-worker
> ```
>
> 注意：暂停后 Gallery 的生成入口会暂时不可用，几分钟内恢复正常。

把旧库地址从环境变量文件里取出来（不用手动敲密码），再填上新库地址：

```bash
export OLD_DB_URL="$(grep '^DATABASE_URL=' /etc/mindfulpenpal.production.env | cut -d= -f2- | sed 's|host.docker.internal|127.0.0.1|' | sed 's/[?&]uselibpqcompat=[^&]*//' | sed 's#\(://[^?]*\)&#\1?#')"
export NEW_DB_URL='postgres://<用户名>:<密码>@db.prisma.io:5432/postgres?sslmode=require'
psql "$NEW_DB_URL" -c "SELECT version();"
bash deploy/migrate-db-to-managed.sh
```

> 提示：`export` 的变量只在当前终端会话有效。如果中途重新登录过服务器，需要重新执行上面
> 两个 `export`。可以用下面的命令检查新库变量是否还在（只输出 OK，不会显示密码）：
>
> ```bash
> echo "$NEW_DB_URL" | grep -q db.prisma.io && echo "NEW_DB_URL OK"
> ```
>
> 推荐：把两个连接串保存到本机文件（只有 root 能读），以后重新登录只需 `source` 一次，
> 不用反复粘贴密码：
>
> ```bash
> sudoedit /opt/mindfulpenpal/.migrate-env
> ```
>
> 文件里写两行（占位符换成真实值，不要发到聊天）：
>
> ```text
> export OLD_DB_URL="postgresql://..."
> export NEW_DB_URL='postgres://...@db.prisma.io:5432/postgres?sslmode=require'
> ```
>
> 保存退出后：
>
> ```bash
> sudo chmod 600 /opt/mindfulpenpal/.migrate-env
> source /opt/mindfulpenpal/.migrate-env
> ```

先确认旧库地址确实指向本机（下面的命令会把密码隐藏，只显示主机名，可以放心执行）：

```bash
grep '^DATABASE_URL=' /etc/mindfulpenpal.production.env | sed -E 's#(postgres(ql)?://)[^@]*@#\1***@#'
```

预期显示 `host.docker.internal` 或 `127.0.0.1` 或 `localhost`。如果显示 `db.prisma.io`，
说明服务器 AI 服务还在连 Prisma 旧库，此时**不要**直接迁移，先停下来找 Codex 确认。

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

- `users` 数量与源库一致（迁移前本机是 6，如果迁移期间有新注册或自动创建的管理员，会多于 6）；
- `public_tables` 为 16；
- `ai` schema 存在；
- 全程没有 `ERROR`。

如果 restore 阶段没有报错，但验证阶段报 `SSL connection has been closed unexpectedly`，
说明数据已经恢复成功，只是公网连接抖动；**不要重跑迁移**，手动逐条验证即可：

```bash
psql "$NEW_DB_URL" -c "SELECT count(*) AS users FROM public.users;"
psql "$NEW_DB_URL" -c "SELECT count(*) AS public_tables FROM information_schema.tables WHERE table_schema='public';"
psql "$NEW_DB_URL" -c "SELECT schema_name FROM information_schema.schemata WHERE schema_name='ai';"
```

如果出现 ERROR，把完整错误贴出来，不要反复重试。已经失败过一次、确认目标库没有其他数据时，
可以带 `CLEAN_TARGET=1` 重跑：

```bash
CLEAN_TARGET=1 bash deploy/migrate-db-to-managed.sh
```

## 5. 第 3 步：切换 Vercel 主站到托管库

1. 打开 Vercel → 项目 **my-toolbox** → Settings → Environment Variables，环境选 **Production**；
2. 确认存在 Vercel 注入的 `POSTGRES_URL`（以及存在的 `POSTGRES_URL_NON_POOLING` /
   `PRISMA_DATABASE_URL`），值包含 `db.prisma.io`，指向刚创建的 Prisma Postgres；
3. 删除旧的 `DATABASE_URL`（它指向腾讯云旧库，避免回退）；
4. 如果保存后没有自动触发部署，就手动 Redeploy 一次；
5. 等 Deployments 显示 Success。

验证：

- 打开 https://mindfulpenpal.com，用老账号登录；
- 进入 `/admin`，用户列表应显示全部 6 个老账号；
- 如果老账号消失，说明第 3 步的旧变量没有删干净，或部署还没完成。

## 6. 第 4 步：切换腾讯云 AI 服务到托管库

在服务器执行：

```bash
sudoedit /etc/mindfulpenpal.production.env
```

只改 `DATABASE_URL` 这一行，改成和第 1 步复制的同一条连接串（`db.prisma.io` 那条）。
**其他行（Redis、COS、Provider 等）一律不动。**
保存退出（nano 是 Ctrl+O 回车，再 Ctrl+X）。

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
4. 托管库启用后，确认 Prisma Postgres 控制台里自动备份已开启（付费档默认有）；
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
| `pg_restore` 报 ERROR（例如 relation ... already exists） | 说明目标库已有表（可能是 Vercel 部署时 Flask 自动建的空表）。先用只读命令检查 `users` 数量和 `ai` schema，确认目标库没有独立数据后，用 `CLEAN_TARGET=1` 重跑 |
| `pg_restore` 长时间卡住不动 | 通常是主站（Vercel）仍连着新库，DROP 表在等锁，或免费档连接数满了在排队。按 Ctrl+C 停止（dump 已保存），再按第 10 节排查 |
| 免费档数据库休眠，首次访问慢 | 属正常现象；正式使用建议升级付费档 |
| Vercel 部署后老账号消失 | 检查 `POSTGRES_URL` 是否指向 `db.prisma.io` 新库、旧的 `DATABASE_URL` 是否已删除，确认部署 Success |
| worker 日志报数据库错误 | 确认服务器 env 的 `DATABASE_URL` 已改，并执行了 `--force-recreate` |
| 连接串里密码含特殊字符 | 从 Vercel 项目环境变量里复制完整值，不要手工改动 |

## 11. restore 卡住怎么办

1. 按 `Ctrl+C` 停止（dump 文件已保存，不会丢数据）；
2. 查看新库当前有哪些连接、是否在等锁：

   ```bash
   psql "$NEW_DB_URL" -c "SELECT pid, state, wait_event_type, wait_event, left(query,90) AS query FROM pg_stat_activity WHERE datname=current_database();"
   ```

   如果看到大量 `idle in transaction` / `active` 的连接（通常是 Vercel 主站），说明 DROP 表
   在等它们释放锁；
3. 终止其他连接后重试：

   ```bash
   psql "$NEW_DB_URL" -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid <> pg_backend_pid();"
   ```

   如果提示没有权限，就去 Prisma Postgres / Vercel 集成控制台找 Reset（清空数据库）功能；
4. 重新执行：

   ```bash
   CLEAN_TARGET=1 bash deploy/migrate-db-to-managed.sh
   ```

   如果第 2 步的查询本身也卡住，说明连接数已满，优先用控制台 Reset，而不是继续等待。

## 12. 从头重来：删除并重建托管库

如果目标库已经被反复失败的 restore 或主站自动写入弄脏，最干净的做法是删除重建：

1. 如果 Vercel 提供 **Pause Project**（Settings → General → Danger Zone），先暂停主站；
   如果没有该选项，就采用下面的顺序：**先创建新库并恢复数据，最后再关联项目**，期间不要
   访问 mindfulpenpal.com；
2. Vercel → Storage 或 Integrations → Prisma Postgres → **删除旧数据库**
   （旧连接串随之作废，之前泄露过的密码也一起失效）；
3. 重新创建 Prisma Postgres 数据库；创建向导如果允许"暂不关联项目"，就先不关联，
   等数据恢复完成后再关联到 my-toolbox；如果必须立即关联，关联后马上进入第 5 步；
4. 复制新的连接串（数据库详情页的 Connect/连接信息，或 `POSTGRES_URL` /
   `PRISMA_DATABASE_URL` 的值，地址是 `db.prisma.io`），不要发到聊天；
5. 在服务器重新设置 `NEW_DB_URL`，先确认新库是空的：

   ```bash
   psql "$NEW_DB_URL" -c "\dt public.*"
   ```

   预期输出 `Did not find any relations.`；
6. 新库为空时直接执行普通迁移（不需要 `CLEAN_TARGET=1`）；如果新库已经有表
   （说明主站已经连过并自动建表），就改用 `CLEAN_TARGET=1`：

   ```bash
   bash deploy/migrate-db-to-managed.sh
   ```

7. 验证 `[4/4] done.` 后，如果第 3 步没有关联项目，现在到 Vercel 把新库关联到
   **my-toolbox**（会注入环境变量并重新部署）；
8. 用老账号登录 mindfulpenpal.com 验证，然后继续后续收尾步骤。
