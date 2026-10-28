# 管理日志中国标准时间校准发布手册

## 目的和影响

本版本修复调用日志写入时间可能受 PostgreSQL 会话时区影响的问题。数据库继续保存 UTC，管理页面按 `Asia/Shanghai` 显示并明确标注 `UTC+8`。无数据库迁移、无新环境变量、无新增服务费用。

## 发布前检查

1. 确认代码在已通过 CI 的主分支提交上。
2. 确认 `/opt/mytoolbox` 没有未提交修改；`git status --short` 有输出时停止发布。
3. 记录当前提交，供回滚使用。

```bash
cd /opt/mytoolbox
git status --short
git rev-parse HEAD
```

## 腾讯云更新命令

```bash
cd /opt/mytoolbox
git fetch origin
git switch main
git pull --ff-only origin main
.venv/bin/pip install --requirement requirements.txt
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

预期：服务状态为 `active (running)`，健康检查返回成功。此次不运行 `flask db upgrade`，因为没有数据库迁移。

## 验收

1. 登录管理后台，执行一次不会包含敏感数据的测试工具调用。
2. 打开“调用日志”，确认表头为“中国标准时间，UTC+8”。
3. 新日志显示时间应与中国标准时间一致，允许请求和刷新造成数秒差异。
4. 日期筛选应继续按中国自然日包含该记录。
5. `sudo journalctl -u mytoolbox -n 20 --no-pager` 中的应用日志时间应带 `+0800`。

不要求修改 PostgreSQL 的全局或连接会话时区；应用会在写入无时区字段前把时间规范化为 UTC。不要根据单条旧日志自动修改历史数据，历史连接来源可能不同，需要单独取证。

## 常见失败

- 服务无法启动：检查 `sudo journalctl -u mytoolbox -n 100 --no-pager`，重点确认 PostgreSQL 驱动是否仍为项目要求的 `psycopg2`。
- 日志仍受服务器时区影响：确认服务已重启且运行的是最新提交，不要直接修改数据库全局时区作为替代。
- 新日志仍偏移：记录页面时间、腾讯云主机 `date -Is` 和数据库 `now()`，停止继续改历史数据并回滚应用。

## 回滚

本版本不修改数据库，可直接回滚应用：

```bash
cd /opt/mytoolbox
git switch --detach <PREVIOUS_SHA>
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

恢复后从 `main` 重新部署修复版本；不要让服务器长期停留在 detached HEAD。
