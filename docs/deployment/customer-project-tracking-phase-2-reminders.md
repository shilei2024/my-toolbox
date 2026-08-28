# 客户项目 Phase 2 提醒闭环部署与回滚

## 状态与安全边界

本阶段提供组织提醒策略、到期/逾期/停滞扫描、共享通知发件箱、逐收件人投递、dry-run/SMTP 适配器、重试、死信、心跳和统一后台通知日志。生产默认不扫描、不真实发信；Web 进程不运行提醒线程，外部 cron/systemd timer 只触发幂等 Flask CLI。

Golden Rule 结论：提醒会影响生产客户邮箱，因此使用数据库策略、全局扫描开关和真实发送开关三重门禁；共享发件箱可被未来模块复用；PostgreSQL + 外部 cron 比新增 Redis/常驻服务成本更低；命令、期望输出和回滚均可由初学者执行；架构保持主站模块化单体、统一后台和 PostgreSQL 事实源。

## 迁移

先备份并在同版本 PostgreSQL staging 演练：

```powershell
$env:FLASK_APP = "app:create_app"
flask db current
flask db upgrade
flask db current
```

升级前应为 `f1a2b3c4d5e6`，完整升级后应为 `b3c4d5e6f7a8`。`a2b3c4d5e6f7` 只新增组织策略、发件箱、投递和心跳；`b3c4d5e6f7a8` 只新增项目提醒覆盖表，不修改或回填既有客户项目。

## 首次 dry-run

保持以下配置并重启应用：

```dotenv
CUSTOMER_PROJECT_REMINDERS_ENABLED=false
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false
NOTIFICATION_ADAPTER=dry-run
```

在 staging 统一后台保存组织提醒策略并启用；如需例外，在项目详情设置项目启停、PM/FAE 继承覆盖和成员邮件偏好，然后手工执行：

```powershell
flask customer-projects scan-reminders --force
flask customer-projects dispatch-notifications --limit 100
```

预期输出含 `created=N`、`sent=N`、`failed=0`。统一后台“通知运行状态”应显示扫描/发送心跳，发件箱状态为 `sent`，provider 标识使用 `dry-run:`；不会连接邮件服务器。重复扫描 10 次不应增加相同提醒。

## 外部调度

dry-run 验收通过后设置 `CUSTOMER_PROJECT_REMINDERS_ENABLED=true`，由服务器 cron 或 systemd timer 每 10 分钟依次执行扫描和发送命令。不要把命令放进 Flask/Gunicorn worker，也不要启动 APScheduler 业务线程。每次命令必须记录退出码和时间，但不得记录邮件正文、完整收件地址或 SMTP 异常原文。

## SMTP 小流量启用

先完成发件域 SPF、DKIM、DMARC 和测试收件域验证，再配置：

```dotenv
NOTIFICATION_ADAPTER=smtp
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=true
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=service-account
SMTP_PASSWORD=从密钥管理注入
SMTP_FROM=projects@example.com
SMTP_TIMEOUT_SECONDS=10
```

真实凭据不得写入仓库、日志或工单。先把组织策略每日上限设为小值，仅保留测试项目和测试收件人，观察至少一个完整提醒周期后再审批扩大范围。

## 成功检查

- 停用用户和非有效组织成员不会产生投递记录。
- 项目停用覆盖不会生成意图；成员关闭邮件后不进入新投递，覆盖变化会取消未发送旧意图。
- 同一项目、提醒类型、周期和策略版本只有一个发件箱记录。
- 有效跟进、跟进时间变化、暂停、终态或软删除会取消未发送旧提醒。
- 发送失败只保存安全错误码并按退避时间重试；达到上限进入 `dead`，项目写入不回滚。
- 发送进程异常退出后，超过 5 分钟的领取状态可被下一轮回收。
- 组织每日上限生效，心跳显示 `DAILY_LIMIT_REACHED` 时停止扩大发送范围。

## 回滚

先设置 `CUSTOMER_PROJECT_REMINDERS_ENABLED=false` 停止新意图，再设置 `CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false`、`NOTIFICATION_ADAPTER=dry-run` 并停止外部 timer。保留发件箱、投递和心跳记录用于审计，不删除失败任务，不执行生产 downgrade。若需应用回退，旧应用会忽略新增表；仅在备份恢复演练和单独审批后才允许清理表。

## 常见故障

- `SMTP_NOT_CONFIGURED`：缺少主机或发件地址；保持真实发送关闭后修正配置。
- `SMTP_DELIVERY_FAILED`：检查网络、TLS、账号权限和服务商状态；日志不得打印凭据或原始响应。
- `STALE_CLAIM_RECOVERED`：上次发送进程中断，下一轮已回收；核对该时段进程和数据库健康。
- 待发最老时长超过两个扫描周期：停止扩大试点，检查外部 timer、数据库锁和 SMTP；不要手工改成 `sent`。
