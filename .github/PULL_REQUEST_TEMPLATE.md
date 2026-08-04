## 变更目标

<!-- 说明真实目标、用户价值和不做什么。 -->

## 关联事项

<!-- Issue、ADR、事故或需求链接；没有则写“无”。 -->

## Golden Rule

- [ ] 已评估对线上 `mindfulpenpal.com` 的影响。
- [ ] 已说明是否可被未来 AI 模块复用。
- [ ] 已确认不存在满足要求且运维成本更低的方案。
- [ ] 部署和维护步骤适合零 DevOps 经验操作者。
- [ ] 方案符合长期平台架构。

## 变更范围

- 数据库/API/配置变化：
- 安全、隐私和权限影响：
- 性能和成本影响：
- 兼容性影响：

## 验证证据

- [ ] Python tests
- [ ] Generation Service typecheck/tests
- [ ] Gallery Web lint/tests/build
- [ ] PostgreSQL migrations/integration tests（如适用）
- [ ] Vercel Preview 已人工验证（前端变更）
- [ ] 安全与依赖检查通过

命令、输出摘要、截图或 Preview URL：

## 文档与发布

- [ ] 架构/API/部署/排障文档已更新，或本变更无需更新且已说明原因。
- [ ] 重要决策已新增 ADR。
- [ ] changelog 已更新。
- [ ] 环境变量清单已更新，但未提交任何真实密钥。
- [ ] 数据库迁移已 dry-run，并完成备份/恢复验证（如适用）。

## 回滚方案

<!-- 写明触发条件、负责人、应用/数据库/COS 回滚步骤和预计恢复时间。禁止只写“git revert”。 -->

## 发布风险

- 风险等级：低 / 中 / 高
- 建议发布窗口：
- 发布后重点监控：
