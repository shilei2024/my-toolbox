# 客户项目市场工作台与真实邮件提醒腾讯云发布

## 目的与生产影响

本次发布增加授权范围内的 TAM/SAM/SOM 汇总与品牌/类别下钻、客户优先项目入口，并把已有提醒扫描/发件箱/SMTP 投递接入腾讯云 systemd timer。无数据库迁移、无新增依赖；真实邮件会触达用户，必须先 dry-run、再测试邮件、最后小流量启用。

Golden Rule 结论：变更会影响生产页面和邮件；市场汇总、通知发件箱均可复用；实时派生和系统 timer 是当前最低成本方案；命令与验证适合初学者；保持模块化单体、统一后台和 PostgreSQL 事实源。

## 前置检查

- PR 已合并且 GitHub CI 全部通过，已记录发布前 `git rev-parse HEAD`。
- 数据库已有可恢复备份；服务器 `/opt/mytoolbox` 是生产仓库，服务名为 `mytoolbox`。
- 发件域已配置 SPF、DKIM、DMARC；SMTP 账号只允许发信，不使用个人密码。
- 腾讯云安全组和主机防火墙不需要新增入站端口，只需允许到 SMTP 服务商端口的出站连接。

## 1. 更新应用（先保持真实发送关闭）

```bash
cd /opt/mytoolbox
git fetch origin --prune
git checkout main
git pull --ff-only origin main
source .venv/bin/activate
pip install -r requirements.txt
flask db current
flask db upgrade
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
```

预期：`git pull` 快进到已合并提交，迁移保持最新，`mytoolbox` 显示 `active (running)`。虽然本次无迁移，仍执行 `db upgrade` 保证服务器没有遗漏早期迁移。

先在 `/opt/mytoolbox/.env` 保持：

```dotenv
CUSTOMER_PROJECT_REMINDERS_ENABLED=true
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false
NOTIFICATION_ADAPTER=dry-run
APP_BASE_URL=https://你的生产域名
```

## 2. 安装并演练调度器

```bash
sudo install -o root -g root -m 644 deploy/customer-project-reminders.service /etc/systemd/system/customer-project-reminders.service
sudo install -o root -g root -m 644 deploy/customer-project-reminders.timer /etc/systemd/system/customer-project-reminders.timer
sudo systemctl daemon-reload
sudo -u www-data /opt/mytoolbox/.venv/bin/flask --app app:create_app customer-projects notifications-check
sudo systemctl start customer-project-reminders.service
sudo systemctl status customer-project-reminders.service --no-pager
sudo journalctl -u customer-project-reminders.service -n 50 --no-pager
```

预期：自检显示 `adapter=dry-run ready=true`；执行输出含 `scanned=N created=N limited=0` 和 `claimed=N sent=N failed=0`。dry-run 会更新可审计状态，但不会连接 SMTP。

## 3. 配置并验证真实 SMTP

使用 `sudoedit /opt/mytoolbox/.env` 写入真实值，不把凭据粘贴到终端历史、Git 或工单：

```dotenv
CUSTOMER_PROJECT_REMINDERS_ENABLED=true
CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=true
NOTIFICATION_ADAPTER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USERNAME=service-account@example.com
SMTP_PASSWORD=由密钥管理生成的专用密码
SMTP_FROM=客户项目提醒 <service-account@example.com>
SMTP_TIMEOUT_SECONDS=10
APP_BASE_URL=https://你的生产域名
```

```bash
cd /opt/mytoolbox
sudo -u www-data /opt/mytoolbox/.venv/bin/flask --app app:create_app customer-projects notifications-check --require-live
sudo -u www-data /opt/mytoolbox/.venv/bin/flask --app app:create_app customer-projects send-test-email --recipient 你的测试邮箱
```

预期：自检显示 `adapter=smtp ready=true`，测试命令显示 `test email accepted by SMTP server`，测试邮箱收到不含客户数据的邮件。SMTP 接受不等于最终送达，仍需检查收件箱和服务商投递日志。

## 4. 小流量启用与验收

先在统一后台把组织每日上限设小，并只保留测试项目/收件人，然后：

```bash
sudo systemctl enable --now customer-project-reminders.timer
systemctl list-timers customer-project-reminders.timer --no-pager
sudo journalctl -u customer-project-reminders.service -f
```

完成一次周期后退出日志跟随（`Ctrl+C`），验证：工作台金额与项目明细合计一致；品牌、类别页只包含当前账号可见项目；客户列表进入客户后才能看到“新建项目”；邮件时间为组织时区，链接使用生产 HTTPS 域名；统一后台发送心跳为正常且没有 `dead`。

## 常见失败与恢复

- `CUSTOMER_PROJECT_REMINDERS_ENABLED=false`：编辑环境文件启用扫描，再重跑自检。
- `SMTP_FROM is invalid` 或凭据不完整：修正配置；不要在日志中打印密码。
- `SMTP_DELIVERY_FAILED`：确认出站网络、端口、TLS、账号权限和服务商限流；发件箱会退避重试。
- service 超时：先禁用 timer，检查数据库/SMTP 延迟和积压量，不要并行启动第二个发送器。

## 回滚

```bash
sudo systemctl disable --now customer-project-reminders.timer
sudoedit /opt/mytoolbox/.env
# 设置 CUSTOMER_PROJECT_REMINDERS_ENABLED=false
# 设置 CUSTOMER_PROJECT_NOTIFICATIONS_ENABLED=false
# 设置 NOTIFICATION_ADAPTER=dry-run
cd /opt/mytoolbox
git checkout <发布前已记录的提交>
sudo systemctl restart mytoolbox
```

保留发件箱、投递和心跳记录用于审计，不删除失败任务，不执行数据库 downgrade。恢复后检查站点健康页与原有客户项目详情；需要重启自动提醒时，先重新执行 live 自检和测试邮件。
