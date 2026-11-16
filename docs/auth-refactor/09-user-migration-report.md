# 09 用户迁移报告（发布候选，尚无真实迁移）

| 项目 | 结果 |
| --- | --- |
| 生产迁移执行 | 未执行 |
| 生产旧用户总量 | 未知，尚无恢复库核验 |
| 生产已迁移用户数 | 0（未执行，不代表没有用户） |
| 生产异常用户数 | 未知，不得报告为零异常 |
| 合成演练 | 2 个虚构旧账号，ID 恒等映射；停用/冲突变体使用独立测试 |
| 密码/openid/旧Token/原件 | 合成前后快照保持，非生产证明 |
| PostgreSQL 合成迁移与并发 | 2026-11-15 远端 PG16 的认证3组检查通过；真实生产恢复仍未执行 |
| 是否可生产发布 | 否 |

## 操作员恢复库验收（2026-11-16）

操作员反馈：生产 ebb7fc0473be364004413ac022ab73637e787b69，main，服务 active，仅既有 Caddyfile 跟踪改动；已生成 PostgreSQL 备份并恢复至独立 auth_rehearsal_20261116。旧 revision f5a6b7c8d9e0，恢复数量 users=15、invoices=75、originals=91。

固定候选 a7aac0b4428b6afc41bdc6bd0e6826dd12eec9c5 的完整迁移返回 AUTH_REHEARSAL_OK，revision=c8d9e0f1a2b3；历史摘要保持，数量15/75/91，映射15，mismatches=0。随后用 cb724aa 的两个验收工具执行应用 smoke，所有 MOBILE_*、AUTH_APPLICATION_OK、AUTH_HISTORY_OK、AUTH_STAGING_OK 通过，生产继续 active。测试只对独立恢复库增加合成账号/业务；邮件和微信为模拟，不代表真实收件或微信平台验收。

生产迁移仍未执行，以上为操作员反馈的隔离恢复验收证据。下一步确认生产其他写者和功能开关，先升级核心网站，再按顺序验收/启用邮件、下游和小程序。

工具成功时输出版本、run_id、scanned、inserted、skipped、excluded_disabled、mappings_to_create、errors 等聚合值，并保存运行摘要与逐账号恒等映射。失败返回聚合错误、不输出身份值。后续获得恢复库后用实际结果更新本报告，不用合成数据数量代替真实用户统计。
