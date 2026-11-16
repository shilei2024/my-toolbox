# 09 用户迁移与上线记录

| 项目 | 结果 |
| --- | --- |
| 生产迁移执行 | 2026-11-16 操作员反馈 AUTH_RELEASE_OK，revision=c8d9e0f1a2b3 |
| 生产旧用户总量 | 备份恢复基线15；实时数量以生产为准 |
| 账号映射 | 恢复库15条、mismatches=0；生产发布器预检与历史摘要检查通过 |
| 生产异常用户数 | 发布器预检通过，不代替全部业务异常统计 |
| 合成演练 | 2 个虚构旧账号，ID 恒等映射；停用/冲突变体使用独立测试 |
| 密码/openid/旧Token/原件 | 恢复库迁移和应用 smoke历史摘要保持；生产发布器历史摘要通过；旧网站 Cookie 需重新登录 |
| PostgreSQL 合成迁移与并发 | 远端 PG16通过；真实备份恢复、迁移与应用验收通过 |
| 当前上线范围 | 网站核心代码已升级；真实邮件、下游撤销开关与新版小程序仍待验收/发布 |

## 操作员恢复库验收（2026-11-16）

操作员反馈：生产 ebb7fc0473be364004413ac022ab73637e787b69，main，服务 active，仅既有 Caddyfile 跟踪改动；已生成 PostgreSQL 备份并恢复至独立 auth_rehearsal_20261116。旧 revision f5a6b7c8d9e0，恢复数量 users=15、invoices=75、originals=91。

固定候选 a7aac0b4428b6afc41bdc6bd0e6826dd12eec9c5 的完整迁移返回 AUTH_REHEARSAL_OK，revision=c8d9e0f1a2b3；历史摘要保持，数量15/75/91，映射15，mismatches=0。随后用 cb724aa 的两个验收工具执行应用 smoke，所有 MOBILE_*、AUTH_APPLICATION_OK、AUTH_HISTORY_OK、AUTH_STAGING_OK 通过，生产继续 active。测试只对独立恢复库增加合成账号/业务；邮件和微信为模拟，不代表真实收件或微信平台验收。

以上为操作员反馈的隔离恢复验收证据。

## 生产核心升级（2026-11-16）

操作员确认：暂停客户提醒及本项目五个应用容器后，发布器最终备份、Git快进、事务迁移、历史摘要检查和健康检查成功；release_commit=a7aac0b4428b6afc41bdc6bd0e6826dd12eec9c5，revision=c8d9e0f1a2b3。主站和提醒定时器 active，正式域名 /healthz 返回 status=ok，五个应用容器已启动。API 当时 health starting，需随后确认 healthy。AUTH_MAIL_ADAPTER和新微信注册在发布前检查为关闭状态；真实收件、实际网站业务、下游和微信新版仍待继续验收，不将核心升级称为全部上线完成。

工具成功时输出版本、run_id、scanned、inserted、skipped、excluded_disabled、mappings_to_create、errors 等聚合值，并保存运行摘要与逐账号恒等映射。失败返回聚合错误、不输出身份值。后续获得恢复库后用实际结果更新本报告，不用合成数据数量代替真实用户统计。
