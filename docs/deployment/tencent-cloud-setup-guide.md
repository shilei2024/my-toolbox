# 腾讯云资源准备指南（小白版）

> 本文是 `deploy/DEPLOY_GUIDE.md` 的“资源购买与配置”前置篇。每步都有：为什么做、控制台点哪里、填什么、预期看到什么、失败怎么办。
>
> **已有服务器、已有 COS，只是想搬迁原站数据库？** 直接看
> [已有服务器与 COS 的生产部署（数据库搬迁版）](tencent-existing-server-setup.md)；
> 本文用于从零购买和创建资源。
> **重要**：创建云资源会产生真实费用。开始前先看第 0 节确认信息和第 2 节费用估算；不确定时先选“按量计费”并设置预算提醒。

## 0. 开始前先确认（10 分钟）

打开腾讯云官网并登录（首次需要实名认证）：<https://cloud.tencent.com>

对照下表逐项填写，填完再继续：

| 需要确认的信息 | 建议默认值 | 你的选择 |
| --- | --- | --- |
| 地域 | 与你的用户最近：广州 / 上海 / 北京 | ______ |
| 服务器配置 | 2 核 4 GB（Ubuntu 22.04） | ______ |
| 域名 | `api-ai.<你的域名>` 指向服务器；`<gallery域名>` 指向 Vercel | ______ |
| 原网站数据库现状 | Vercel Postgres？腾讯云？还是 SQLite？**这决定第 8 节选哪个方案** | ______ |
| 付费方式 | 先按量计费，稳定后转包年 | ______ |

> 为什么先确认地域：CVM、COS、数据库最好都在同一地域（内网互通、延迟低、流量免费）；不同地域会走公网，既慢又产生流量费。

## 1. 实名认证

控制台右上角“账号信息”→ 实名认证（个人/企业均可）。未认证无法购买任何资源。

## 2. 费用估算（每月，人民币）

| 资源 | 推荐规格 | 预估月费 | 说明 |
| --- | --- | --- | --- |
| CVM | 2核4G、40GB SSD、3Mbps 按量带宽 | 约 100-200 元 | 按量可随时释放 |
| COS | 标准存储 + 少量外网下行 | 几元-几十元 | 图片量大后建议开 CDN |
| CDN（可选） | 按量流量 | 几元起 | 图片走 CDN 更快更省 |
| Redis | 内存版 1GB | 约 50-150 元 | 可先用 local-infra 容器省掉，生产再买 |
| PostgreSQL | 云数据库 PG 最小规格 | 约 200-400 元 | **方案 A 可复用现有 Vercel Postgres，不用买** |

> 省钱顺序：先只用 CVM + COS（+ 现有 Vercel Postgres），Redis 暂用 local-infra；稳定后再买腾讯云 Redis/CDN/托管 PG。

## 3. 创建云服务器 CVM

### 3.1 进入购买页

控制台搜索“云服务器 CVM”→ 立即购买。

### 3.2 按下面填

| 配置项 | 填什么 |
| --- | --- |
| 计费模式 | 按量计费（新手先用这个） |
| 地域/可用区 | 与第 0 节一致 |
| 实例 | 标准型 S5/S6，2核4GB |
| 镜像 | Ubuntu Server 22.04 LTS 64位 |
| 系统盘 | SSD 40GB |
| 带宽 | 按使用流量，3-5Mbps 上限 |
| 安全组 | 新建安全组（见 3.3） |
| 登录方式 | 推荐“密钥对”（可下载 `.pem` 文件）；不会用密钥就选密码并记住 |

### 3.3 安全组规则（最重要）

购买时或购买后：控制台 → 云服务器 → 安全组 → 修改规则。

入站规则（别人访问你服务器的方向）：

| 协议/端口 | 来源 | 用途 |
| --- | --- | --- |
| TCP:22 | 你的办公 IP（不知道就先 `你的IP`，可在[查询网站](https://myip.ipip.net)看） | SSH 管理 |
| TCP:80 | 0.0.0.0/0 | HTTP（Caddy 自动跳 HTTPS） |
| TCP:443 | 0.0.0.0/0 | HTTPS |

出站规则保持默认放行。

> 失败处理：SSH 连不上，先看 22 端口安全组是否放行、来源 IP 是否变化；80/443 打不开，检查这两条是否在。

## 4. SSH 登录服务器

Windows 10/11 自带 OpenSSH：

```powershell
ssh root@<服务器公网IP>
```

密码登录直接输密码；密钥登录用：

```powershell
ssh -i C:\Users\你的用户名\Downloads\mykey.pem root@<服务器公网IP>
```

预期：出现 `Welcome to Ubuntu` 提示符。连不上按 3.3 的“失败处理”排查，或在腾讯云控制台点“登录 → 标准登录（WebShell）”。

## 5. 创建最小权限密钥（CAM 子账号 + COS）

> 为什么不用主账号密钥：主账号密钥能管理你整个腾讯云账号，泄露等于账号失控。子账号密钥只允许操作指定的 COS 桶。

### 5.1 新建子用户

控制台 → 访问管理 CAM → 用户 → 用户列表 → 新建用户 → **自定义创建** → 选择“编程访问” → 不勾选“控制台访问”。

### 5.2 创建最小权限策略

控制台 → 访问管理 → 策略 → 新建自定义策略 → 按策略语法创建：

```json
{
  "version": "2.0",
  "statement": [
    {
      "effect": "allow",
      "action": [
        "cos:PutObject",
        "cos:GetObject",
        "cos:HeadObject",
        "cos:DeleteObject"
      ],
      "resource": [
        "qcs::cos:<你的地域>:uid/<你的账号ID>:<你的桶名>/*"
      ]
    }
  ]
}
```

把 `<你的地域>`、`<你的账号ID>`、`<你的桶名>` 替换成真实值（桶名在第 6 节创建后回填）。

### 5.3 给子用户绑定策略

子用户详情 → 关联策略 → 选择刚创建的策略。

### 5.4 生成并保存密钥

子用户 → API 密钥 → 新建密钥 → **立即下载 CSV**（只显示一次）。CSV 里有 `SecretId` 和 `SecretKey`，对应环境文件里的 `COS_SECRET_ID` / `COS_SECRET_KEY`。

> 失败处理：上传图片报 403，99% 是这里权限写错（地域/桶名/账号ID）或系统时间不准。不要为了省事换成主账号密钥。

## 6. 创建 COS 存储桶

### 6.1 建桶

控制台 → 对象存储 COS → 存储桶列表 → 创建存储桶：

| 配置项 | 填什么 |
| --- | --- |
| 名称 | 例如 `mindfulpenpal-images-<随机后缀>`（全球唯一） |
| 地域 | 与 CVM 同地域 |
| 访问权限 | **私有读写**（不要选公有读） |
| 版本控制 | 建议开启（防误删） |
| 服务端加密 | 建议开启 |

创建后记录：**存储桶名称**、**地域代码**（如 `ap-guangzhou`）。

### 6.2 选择图片访问方案（二选一）

程序上传的公开图片 URL 会返回给浏览器。桶是私有的，所以必须二选一，否则公开画廊图片打不开（403）。

#### 方案 A（推荐）：CDN + 回源鉴权

1. 控制台 → CDN → 域名管理 → 添加域名：`img.<你的域名>`
2. 源站类型选“对象存储 COS”，选刚建的桶，**开启“回源鉴权”**
3. 配置 CNAME（第 10 节 DNS 时一起加）
4. 环境文件填：
   - `COS_CDN_BASE_URL=https://img.<你的域名>`
   - `GALLERY_ASSET_HOSTS=img.<你的域名>`

#### 方案 B（省钱）：存储桶策略只放行图片目录

桶 → 权限管理 → 存储桶策略 → 添加：

```json
{
  "Statement": [
    {
      "Action": ["cos:GetObject"],
      "Effect": "Allow",
      "Principal": { "qcs": ["*"] },
      "Resource": ["qcs::cos:<地域>:uid/<账号ID>:<桶名>/images/*"]
    }
  ],
  "Version": "2.0"
}
```

环境文件填：

- `COS_CDN_BASE_URL=`（留空）
- `GALLERY_ASSET_HOSTS=<桶名>.cos.<地域>.myqcloud.com`

> 两种方案都只影响 `images/jobs/*`（公开图片），私密图片仍由服务端签名访问。不要选“公有读私有写”，那会让私密图片也能被猜到 URL 直接读取。

## 7. 数据库：先确认现状再选方案

AI 模块的 `ai` schema 直接外键引用原网站的 `public.users` 表，**必须和原网站共用同一个数据库**，不能新建一个独立库。

| 现状 | 推荐方案 |
| --- | --- |
| 原站已用 Vercel Postgres | **方案 A（推荐）**：继续用 Vercel Postgres，腾讯云 Generation 服务通过公网 TLS 连它；不买腾讯云 PG |
| 原站用 SQLite / 内存库 | **先迁移原站到 PostgreSQL**（建议 Vercel Postgres），迁移完成前不要上线 AI |
| 原站已用腾讯云 PG | 方案 B：把 `DATABASE_URL` 指向腾讯云 PG（需要公网访问白名单或与 CVM 同 VPC） |

### 方案 A：确认 Vercel Postgres 连接串

Vercel 项目 → Storage → 你的 Postgres → 获取 `POSTGRES_URL_NON_POOLING`（内含用户名密码，格式 `postgresql://...`）。把它填到服务器环境文件的 `DATABASE_URL`。

> 腾讯云服务器到 Vercel Postgres 走公网 TLS，这是当前架构下改动最小的做法；等流量大了再评估把原站整体迁到腾讯云。

### 方案 B：购买腾讯云 PostgreSQL

控制台 → 云数据库 PostgreSQL → 新建：地域与 CVM 一致、最小规格、VPC 与 CVM 相同（第 3 节创建时如果没有 VPC，用默认 VPC）。创建后：

- 在“安全组/白名单”放行 CVM 内网 IP；
- 创建数据库和用户，把 `users` 表结构交给 Flask 建表（原站首次连接时 `create_all` 会建）；
- `DATABASE_URL=postgresql://用户:密码@内网IP:5432/数据库名`。

> 如果原站在 Vercel，Vercel 无法访问腾讯云私有 VPC 数据库，因此方案 B 只适合“原站不在 Vercel 或已迁移”的情况。

## 8. Redis（可先用 local-infra 省掉）

### 8.1 临时省钱方案

在服务器上直接让 compose 的 `local-infra` profile 提供 Redis（见 `DEPLOY_GUIDE.md` 第 6 节）。**仅适合验收/小流量**。

### 8.2 生产方案：腾讯云 Redis

控制台 → 云数据库 Redis → 新建：内存版 1GB、同地域、**开启 SSL/TLS**。

连接串格式：

```text
rediss://:密码@Redis内网或公网地址:端口
```

`rediss://`（带 s）表示 TLS，预检脚本要求生产必须用 `rediss://`。腾讯云 Redis 如果只在内网，CVM 与 Redis 同 VPC 时直接填内网地址；跨网络才开公网访问并放行白名单。

## 9. 域名 DNS（DNSPod）

控制台 → 域名注册/DNSPod → 解析设置，添加三条记录：

| 主机记录 | 类型 | 值 |
| --- | --- | --- |
| `api-ai` | A | CVM 公网 IP |
| `img`（方案 A 才需要） | CNAME | CDN 分配的 CNAME 地址 |
| `<gallery子域名>` | A | CVM 公网 IP（Gallery 腾讯云自托管） |

预期：`nslookup api-ai.<你的域名>` 返回 CVM IP；`https://api-ai.<你的域名>` 能打开 Caddy 页面/`/health`。

> TLS 证书不用手动申请：Caddy 会自动签发。前提是 DNS 已生效、80/443 安全组放行。

Gallery 的构建、低停机 DNS 切换、验收和回滚以
[Gallery 国内访问修复：腾讯云自托管](gallery-tencent-self-hosting.md) 为准。Vercel 的
`cname.vercel-dns.com` 仅保留为回滚目标，不应与 Gallery 的 A 记录同时存在。

## 10. 把值填回环境文件

对照 `deploy/.env.production.example` 逐项填写，重点对应关系：

| 环境变量 | 来自哪里 |
| --- | --- |
| `COS_SECRET_ID` / `COS_SECRET_KEY` | 第 5.4 节 CAM 子用户 CSV |
| `COS_BUCKET` / `COS_REGION` | 第 6.1 节建桶信息 |
| `COS_CDN_BASE_URL` / `GALLERY_ASSET_HOSTS` | 第 6.2 节方案 A 或 B |
| `DATABASE_URL` | 第 7 节方案 A（Vercel Postgres）或方案 B（腾讯云 PG） |
| `REDIS_URL` | 第 8.2 节腾讯云 Redis（或 local-infra 的 `redis://redis:6379`） |
| `OPENAI_API_KEY` / `GEMINI_API_KEY` / `JIMENG_API_KEY` | 对应 AI 平台控制台 |

填完保存到服务器 `/etc/mindfulpenpal.production.env`（权限 600），然后回到 `DEPLOY_GUIDE.md` 从第 5 节继续。

## 11. 常见失败速查

| 现象 | 原因与处理 |
| --- | --- |
| 服务器 SSH 连不上 | 安全组 22 端口 / 来源 IP / 密钥权限（Windows 用 `ssh -i`） |
| COS 上传 403 | CAM 策略地域/桶名/账号ID 写错；系统时间不准 |
| 公开图片 403 | 第 6.2 节方案没做：CDN 回源鉴权未开，或桶策略没放行 `images/jobs/*` |
| 私密图片 403 | `GALLERY_ASSET_HOSTS` 漏填或填错 |
| 数据库连不上 | Vercel Postgres 用 `POSTGRES_URL_NON_POOLING`；腾讯云 PG 放行 CVM 内网 IP |
| Redis 连不上 | 确认 `rediss://`、密码、VPC/白名单 |
| Caddy 证书失败 | DNS 未生效或 80/443 未放行，等几分钟后重试 |
| 费用异常 | 控制台“费用中心”设置预算提醒；按量资源不用就释放/关机 |

## 12. 安全底线（不要做）

- 不要用主账号密钥配 COS/服务器；
- 不要把数据库、Redis、ComfyUI 端口开放到 `0.0.0.0/0`；
- 不要把填好密钥的 `.env` 提交 Git、发聊天或贴工单；
- 不要把桶设为“公有读写”。
