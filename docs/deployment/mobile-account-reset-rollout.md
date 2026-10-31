# 忘记密码（管理员一次性码）与客户按账号归属发布

生产起点 e22cfefab2cfaba62cda04218b2cc1f07bcb13db（0.11.1 手机新建周期版），f5a6b7c8d9e0、mobile enabled。业务候选 db2d55d1611da5b23434570daeb9b1ae4063b1b4 已合入 develop；发布脚本的 CANDIDATE 固定为发布 PR 的基线 905a1c102d6cf289be9d6a6f582e921d5de16254（develop 业务代码与 main 0.11.1 工件合并后的提交），使候选到目标的差异只剩文档与本轮运维脚本。

## 前置

本轮脚本固定 SOURCE=e22cfef，因此**必须先把 0.11.1 部署上线**（见 [手机端新建报销周期发布](mobile-period-create-rollout.md)）。若服务器仍是 0.11.0（29edd8b），脚本会在预检阶段以 unexpected-production-sha 拒绝，不会动服务。

## 边界

无迁移、无新依赖、无新环境变量（可选 PASSWORD_RESET_MODE / PASSWORD_RESET_TTL_MINUTES，默认 admin/60）；无 Caddy 变更。客户端无改动，0.11.1 可继续使用。

## 发布

```bash
(
set -euo pipefail
umask 077
cd /opt/mytoolbox
git fetch origin main
release=APPROVED_MAIN_SHA
test "$(git rev-parse origin/main)" = "$release"
runner=$(mktemp -d /root/mytoolbox-account-release-XXXXXX)
for helper in mobile_account_release.py mobile_entry_release.py invoice_release.py invoice_backup.py; do
  git show "${release}:scripts/ops/${helper}" > "$runner/$helper"
done
/opt/mytoolbox/.venv/bin/python "$runner/mobile_account_release.py" "$release"
)
```

成功标记 MOBILE_ACCOUNT_DEPLOY_OK。随后只读核对：

- `/forgot` 返回 200 且带 no-store；登录页出现「忘记密码？」。
- 管理后台「用户」页出现「生成重置码」，点击后页内显示一次性码（刷新即消失）。
- 用审核账号在小程序核对页看客户列表：只有本人创建/负责的客户；网站旧发票仍显示原客户名与等级。
- 用一次性码重置一个测试账号：成功后旧码立即失效，小程序旧 password 会话 401。

## 回滚

代码退回 e22cfef，客户端不变；重置码只是签名串，回退后自然失效；客户与发票数据未改动，无需回库。

## 0.12.1 热修：生成重置码 500

0.12.0 部署后发现管理后台「生成重置码」返回 500：`issue_password_reset` 传入的 `page` 与 `_render_users` 内部传给 `render_template` 的 `page` 重复，触发 TypeError。修复只改 `admin/routes.py` 的渲染入口，重置码格式、有效期、客户隔离逻辑均未变；新增 `tests/test_admin_users_render.py` 复现该调用。

源码 dc98efc，报告 SHA 为 release PR 合并后的 main；用本轮专用 `mobile_reset_fix_release.py`，连同 `mobile_entry_release.py`、`invoice_release.py`、`invoice_backup.py` 从同一 main SHA 提取到 root 新建 0700 目录。

```bash
(
set -euo pipefail
umask 077
cd /opt/mytoolbox
git fetch origin main
release=APPROVED_MAIN_SHA
test "$(git rev-parse origin/main)" = "$release"
runner=$(mktemp -d /root/mytoolbox-reset-fix-release-XXXXXX)
for helper in mobile_reset_fix_release.py mobile_entry_release.py invoice_release.py invoice_backup.py; do
  git show "${release}:scripts/ops/${helper}" > "$runner/$helper"
done
/opt/mytoolbox/.venv/bin/python "$runner/mobile_reset_fix_release.py" "$release"
)
```

成功标记 MOBILE_RESET_FIX_DEPLOY_OK；随后在后台点一次「生成重置码」，应直接显示一次性码而不是 500。回滚退回 dc98efc，数据不受影响。