# 手机端新建报销周期发布

生产起点29edd8b882138f0b62bde3a27a6d1bcc5f0024a2（0.11.0 网站密码登录版），f5a6b7c8d9e0、mobile enabled。本轮新增手机端创建周期的接口与首页入口，业务候选b281d485fc0861b5eecf3d344800483cdbb6b5c6已合入develop，并与 main 的 0.11.0 发布记录同步为be4e89d044a77fe0ce13e4dc0657762c12e39fdc。

## 边界

无新迁移、依赖、环境变量或 Caddy 变更；周期仍按 owner=user 隔离，网站与手机共用 ReimbursementPeriod 与同一套校验（_validate_period）。恢复库沿用既有标记；本轮新增能力的证据为 API/PG 用例与发布后真机实测，不新增 smoke 标记。

## 发布

固定 SHA 为发布 PR 合并后的 main；用本轮专用 mobile_period_release.py，连同 mobile_entry_release.py、invoice_release.py、invoice_backup.py 从同一 main SHA 提取到 root 新建 0700 目录，复用互斥锁、停写最终备份、配置摘要、f5/历史指纹、022 Git 检出与服务用户可读检查。

```bash
(
set -euo pipefail
umask 077
cd /opt/mytoolbox
git fetch origin main
release=APPROVED_MAIN_SHA
test "$(git rev-parse origin/main)" = "$release"
runner=$(mktemp -d /root/mytoolbox-period-release-XXXXXX)
for helper in mobile_period_release.py mobile_entry_release.py invoice_release.py invoice_backup.py; do
  git show "${release}:scripts/ops/${helper}" > "$runner/$helper"
done
/opt/mytoolbox/.venv/bin/python "$runner/mobile_period_release.py" "$release"
)
```

成功标记 MOBILE_PERIOD_DEPLOY_OK。随后在体验版用审核账号打开首页 →“＋ 新建报销周期”→ 选择起始月 → 创建并切换；确认工作台出现新周期、网站同账号也显示该周期，重复创建返回“相同起止月份的周期已存在”。

## 客户端

后端成功后编译上传 0.11.1，保持合法域名/TLS 校验。旧 0.11.0 客户端仍可用，只是没有新建入口。

## 回滚

代码退回 29edd8b、客户端回 0.11.0，f5 与新周期/票据保留；旧代码不认识新路由但不影响既有数据。不覆盖数据库。
