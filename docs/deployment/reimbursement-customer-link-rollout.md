# 报销客户关联与曜石主题更新发布手册

## 2026-09-06 发票录入补丁

本补丁移除上传/编辑发票弹窗中的“报销状态”，在关联客户旁增加统一客户资料的快捷录入入口，让汇总导出的应酬费客户列只显示简称，并修复火车票触发百度增值税模板 `282103` 后不再继续通用 OCR 的问题。它复用现有客户服务、组织权限、审计与 OCR 配置，不新增数据库迁移、环境变量、业务依赖或常驻进程，适合按本页现有应用更新流程发布。为恢复 CI 安全门禁，Generation Service 的锁文件同时升级了现有间接依赖；仅部署 Flask 主站时无需额外操作，部署 Generation Service 时须按其标准镜像流程重新执行 `npm ci` 并构建镜像。

发布后额外验收：打开上传发票弹窗确认没有状态字段；使用有客户录入权限的账号新增“客户名称、简称、等级”并确认保存后自动选中；导出应酬费明细，确认客户列只有简称且不含 `A/AA/AAA/0-1` 后缀；上传一张票面完整、清晰的火车票，确认可回填票号、日期、票价和“火车票”摘要，若所有服务均失败只显示中文操作提示而不显示供应商错误码。编辑一张历史非待报销发票时，确认其原状态未被重置。

本补丁仅修改应用代码。回滚时恢复发布前 Git SHA 并重启服务即可，不执行数据库 downgrade；客户快捷录入期间新建的客户属于有效业务数据，应用回滚不会也不应删除这些记录。

## 影响与门禁

本次更新影响主站公共主题、报销助手和客户列表，并新增迁移 `d3e4f5a6b7c8`。迁移只为 `reimbursement_invoices` 增加可空客户外键和索引，同时转换旧客户等级：客户主数据 `D→0-1、C→A、B→AA、A→AAA`，报销旧等级 `level 1/2/3→A/AA/AAA`。项目等级 A/B/C/D 不变。

发布前必须确认 PR CI 全绿、主分支已合并、数据库备份可恢复，且记录当前 Git SHA。以下命令适用于现有腾讯云 `/opt/mytoolbox` + systemd `mytoolbox` 部署，不要把真实数据库口令粘贴到终端历史、工单或聊天中。

## 腾讯云更新命令

```bash
cd /opt/mytoolbox
git status --short
git rev-parse --short HEAD

mkdir -p /opt/mytoolbox/backups
set -a
. /opt/mytoolbox/.env
set +a
pg_dump --format=custom --file="/opt/mytoolbox/backups/before-reimbursement-customer-$(date +%Y%m%d-%H%M%S).dump" "$DATABASE_URL"

git fetch origin
git switch main
git pull --ff-only origin main
.venv/bin/pip install --requirement requirements.txt

export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
.venv/bin/flask db current
.venv/bin/flask db heads
.venv/bin/flask db upgrade
.venv/bin/flask db current

sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

预期结果：升级前 `flask db current` 为 `c2d3e4f5a6b7`，`heads` 和升级后 `current` 均为 `d3e4f5a6b7c8`；systemd 显示 `active (running)`；健康检查返回成功。若 `git status --short` 有输出，先停止发布并确认服务器上的改动来源。

## 业务验收

1. 使用曜石专业主题依次打开首页、登录/注册、报销助手、客户列表和项目详情；表单、下拉、只读输入、表格、弹窗、警告及分页文字均可读。
2. 客户列表只提供 `0-1/A/AA/AAA`，有简称时列表优先显示简称并保留全称说明。
3. 登录组织成员打开报销助手，关联客户下拉只出现同组织有效客户并显示简称；选择客户后等级自动带入且在报销页面不可单独修改。
4. 新建招待费或出差发票，关联明细和汇总中显示客户简称；在客户项目模块修改简称或等级后刷新报销页面，显示同步变化。
5. 匿名报销不显示组织客户，但仍可使用 `0-1/A/AA/AAA`；历史未关联记录继续可查看和导出。

## 常见失败与恢复

- `pg_dump` 失败：不要拉代码或迁移；检查数据库连接与备份目录权限。
- `flask db upgrade` 失败：不要重启服务，保留完整错误和备份文件，修复后重试。
- 服务重启后失败：执行 `journalctl -u mytoolbox -n 200 --no-pager`，日志不得复制真实口令、Cookie 或客户数据到公开渠道。
- 健康检查成功但客户为空：确认用户是有效组织成员、客户项目功能已初始化，并检查客户未软删除。

## 回滚

记录发布前 SHA 为 `<PREVIOUS_SHA>` 后，应用可按以下方式回滚；新增列对上一版本兼容，生产事故中不要执行数据库 downgrade：

```bash
cd /opt/mytoolbox
git switch --detach <PREVIOUS_SHA>
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

故障解除后通过正常 PR 修复并重新部署 `main`，不要在服务器上直接修改源码。只有数据库数据损坏且应用回滚不足时，才在停写窗口内使用本次发布前 `.dump` 恢复。
