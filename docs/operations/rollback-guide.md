# 回滚与紧急恢复指南

## 原则

回滚目标是恢复用户服务并保护数据，不是让 Git 看起来整洁。应用、数据库、COS、支付和积分必须分别评估；禁止使用 `git reset --hard`、删除账本或盲目执行 down migration 处理生产事故。

## 触发条件

- 登录、支付、积分或生成存在数据错误。
- 错误率、延迟或资源使用超过发布门槛。
- 安全/隐私数据泄露。
- migration、队列或 COS 出现不可恢复不一致。
- 核心 smoke 失败且无法在批准窗口内前向修复。

## Vercel 回滚

1. Vercel → Deployments，找到上一个已验证的 Production deployment。
2. 核对 Git SHA、环境和发布时间。
3. 执行 Promote/Rollback。
4. 验证 `mindfulpenpal.com` 首页、登录、Gallery、Billing 和管理权限。
5. 若事故来自环境变量，恢复变量后创建使用正确变量的新 deployment。

不要删除失败 deployment；保留日志用于复盘。

## Docker/后端回滚

部署前记录：

```bash
docker compose images --digests
docker compose ps
```

把 `RELEASE_IMAGE` 恢复为旧 digest，然后：

```bash
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f compose.yaml -f compose.production.yaml config --quiet
docker compose --env-file /etc/mindfulpenpal.production.env \
  -f compose.yaml -f compose.production.yaml up -d --no-build
docker compose -f compose.yaml -f compose.production.yaml ps
```

预期服务恢复 `healthy`。这些文件尚未实现时不要执行模板命令。

## 数据库回滚

优先使用 expand/contract migration 和应用兼容回滚：新列/表保留，旧应用忽略它们。只有在恢复库验证、Database Owner 批准并确认不会丢失新数据时才执行反向迁移。

严重数据损坏时：冻结写入、保留故障库、将备份恢复到新实例、验证账本/订单/任务后切换连接。不要覆盖唯一生产实例。

## COS 回滚

- 新对象错误：停止产生新对象，保留 object key 清单，再按审计流程清理。
- 覆盖/删除：从 COS 历史版本恢复指定 version ID。
- CDN：清理错误缓存并验证源站对象，不要把私有桶改成公有读作为临时修复。
- 凭据泄露：立即轮换 CAM/STS 权限并审计访问。

## 支付与积分

停止新 Checkout/购买入口，但继续接收并幂等保存 Provider Webhook。禁止删除订单、Webhook inbox 或积分 ledger；退款和余额修正使用可审计冲正记录。

## 紧急流程

```text
发现 → 指定 Incident Commander → 停止扩量/写入
→ 保存证据 → 选择前向修复或回滚
→ 验证核心链路 → 恢复流量 → 对账 → 复盘/ADR
```

每次事故记录版本、digest、deployment ID、备份 ID、事件 ID、时间线、决定、验证和后续任务，但不记录密钥或客户敏感数据。
