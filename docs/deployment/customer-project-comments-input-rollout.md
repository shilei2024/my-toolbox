# 客户项目协作留言与输入精度发布手册

## 影响与门禁

本次影响客户项目详情、物料/竞品输入和时间线，并新增评论与提及两张表。迁移只加表，不修改项目、物料、价格、活动或提醒数据。生产先保持客户项目功能开关现状，在 PostgreSQL staging 验证后发布。

## `/opt/mytoolbox` 更新与迁移

先创建 PostgreSQL 备份并记录当前 Git SHA，然后执行：

```bash
cd /opt/mytoolbox
git fetch origin
git switch main
git pull --ff-only origin main
.venv/bin/pip install -r requirements.txt
set -a
. /opt/mytoolbox/.env
set +a
export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
.venv/bin/flask db current
.venv/bin/flask db heads
.venv/bin/flask db upgrade
.venv/bin/flask db current
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
```

升级前预期为 `a8b9c0d1e2f3`，升级后和 `heads` 都应为 `b9c0d1e2f3a4`。迁移失败时不要重启新应用。

## 验收

1. 新建和编辑物料时，单机数量只接受整数并显示 PCS；小数返回校验错误。
2. 物料单价和竞品报价最多 5 位小数；`1.23000` 显示为 `1.23`，第 6 位非零时拒绝。
3. 点击项目名打开基础信息弹窗，保存仍能处理版本冲突。
4. 有写权限成员可发表 4000 字以内留言，并选择最多 10 名同组织有效成员。
5. 留言进入时间线，但不修改项目版本、下一步和跟进时间；跨组织提及被拒绝。
6. 在 375px 与桌面宽度验证项目弹窗、留言表单和时间线，无横向滚动或控制台错误。

## 回滚

先关闭 `CUSTOMER_PROJECTS_ENABLED`，恢复上一稳定 Git SHA/应用版本并重启 `mytoolbox`。保留 `project_comments` 与 `project_comment_mentions`，旧应用不会读取它们；生产事故处理中不要执行 `flask db downgrade`。
