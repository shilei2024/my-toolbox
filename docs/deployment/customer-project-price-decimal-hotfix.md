# 客户项目单价小数输入补丁发布手册

## 目的与影响

本补丁修复客户项目中推广物料单价和竞品报价在部分浏览器、尤其移动端，无法输入小数的问题。页面不再依赖浏览器的 `number` 控件，而使用文本输入配合小数键盘，并将常见中文小数分隔符规范为 `.`；服务端仍以 `Decimal` 保存，最多允许 5 位有效小数。

这是纯应用与静态资源变更：不新增环境变量、不改 API、不执行数据库迁移，也不会修改既有价格数据。发布前仍须完成正常的生产备份和变更审批。

## 发布前检查

1. 在 GitHub PR 中确认客户项目回归测试和全部 CI 已通过，并记录待发布的合并提交 SHA。
2. 按现有生产流程确认 PostgreSQL 备份成功；本补丁不写迁移，但备份是任何生产变更的恢复前提。
3. 记录服务器当前应用 SHA 与 `APP_VERSION`。`APP_VERSION` 是静态资源缓存版本；若不更新，浏览器可能继续使用旧脚本。

```bash
cd /opt/mytoolbox
git rev-parse --short HEAD
grep '^APP_VERSION=' .env
```

## 发布步骤

在生产服务器执行以下命令。将 `<release-sha>` 替换为这次已合并提交的短 SHA，并把 `.env` 中的 `APP_VERSION` 改为唯一值，例如 `customer-price-decimal-<release-sha>`；不要在文档或终端输出任何密钥。

```bash
cd /opt/mytoolbox
git fetch origin
git switch main
git pull --ff-only origin main
git rev-parse --short HEAD
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
```

预期：`git rev-parse --short HEAD` 等于已合并提交（或包含该提交的更新提交），服务状态为 `active (running)`。本补丁无 migration，因此不要运行 `flask db upgrade` 来发布它。

完成后，在已登录的浏览器中强制刷新一次页面（桌面 Ctrl+F5；移动端关闭后重新打开页面），确保请求的 `customer-projects.js?v=` 使用新的 `APP_VERSION`。

## 验收

1. 以有价格编辑权限的业务或 PM 身份，新增物料并输入 USD `1.23456`，保存成功后仍显示该值。
2. 编辑同一物料，输入 CNY `8.136`，确认换算预览和保存结果正常。
3. 新增或编辑竞品报价，输入 `0.125` 并保存成功。
4. 输入第 6 位非零小数（如 `1.123456`）时，服务端应拒绝并提示“最多输入 5 位小数”。
5. 以 FAE 身份确认单价仍不可编辑；普通项目、跟进、导出功能正常。

## 常见问题与恢复

- 页面仍不能输入小数：先确认部署 SHA 与新 `APP_VERSION`，再清理该站点浏览器缓存并重新登录。不要通过直接修改数据库绕过问题。
- 服务未能启动：查看 `sudo journalctl -u mytoolbox -n 100 --no-pager`，恢复到发布前已记录的 Git SHA 和 `APP_VERSION` 后重启服务。
- 发现业务回归：先关闭 `CUSTOMER_PROJECTS_ENABLED`（如需立即止损），再回退应用代码与静态资源版本。本补丁没有迁移或数据回填，不需要、也不应执行数据库 downgrade。
