# 客户项目提醒验证手册

首次生产验证必须先走 dry-run，确认扫描、发件箱和投递记录闭环后，才允许开启真实 SMTP。

## Dry-run 验证

在主站运行环境执行：

```bash
cd /opt/mytoolbox
source .venv/bin/activate
set -a
. /opt/mytoolbox/.env
set +a
export FLASK_APP='app:create_app'
export CUSTOMER_PROJECT_REMINDERS_ENABLED=true
export CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false
export NOTIFICATION_ADAPTER=dry-run

flask customer-projects scan-reminders --now 2026-08-28T02:00:00Z
flask customer-projects dispatch-notifications --now 2026-08-28T02:00:00Z --limit 100
```

`--now` 允许使用固定 UTC 时间验证，不必等待真实到期时间。项目的下次跟进时间、停滞天数和组织提醒策略必须使测试项目在该时间点已经到期。

## 数据库核对

```sql
SELECT event_type, status, scheduled_for, sent_at, last_error_code
FROM notification_outbox
WHERE module_code = 'customer_projects'
ORDER BY created_at DESC
LIMIT 20;

SELECT status, provider_message_id, attempts, last_error_code
FROM notification_deliveries
ORDER BY created_at DESC
LIMIT 20;
```

通过标准：

- 扫描命令报告 `created>0`；
- 发件箱状态为 `sent`；
- 投递记录的 `provider_message_id` 以 `dry-run:` 开头；
- 重复执行扫描不会产生相同幂等键的新记录；
- 停用成员不会出现在投递收件人中；
- 项目产生有效跟进后，尚未发送的旧提醒变为 `cancelled`。

## 真实邮件验证

仅在 dry-run 通过后，在测试收件箱配置：

```dotenv
NOTIFICATION_ADAPTER=smtp
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=true
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_FROM=<verified-sender>
```

只使用少量试点邮箱，执行同样的扫描和 dispatch 命令，确认邮件、投递状态、重试和失败日志后，再扩大范围。生产回滚时先关闭提醒扫描和真实发信，保留发件箱与投递记录，不执行数据库 downgrade。
