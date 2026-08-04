# 生产发布检查清单

## 变更与审批

- [ ] Release/Hotfix PR 目标为 `main`，没有直接 push。
- [ ] Golden Rule 五项结论已填写。
- [ ] 独立 Reviewer 已批准，所有会话已解决。
- [ ] SemVer、release notes、ADR 和 changelog 已确认。
- [ ] 发布负责人、操作者、数据库负责人和回滚负责人明确。

## 自动化与 Preview

- [ ] Python tests 成功。
- [ ] Generation Service typecheck/tests/audit 成功。
- [ ] Gallery Web lint/tests/build/audit 成功。
- [ ] PostgreSQL migration 0001–最新版本与集成测试成功。
- [ ] Vercel Preview 已完成桌面、移动、登录、权限和核心业务验收。
- [ ] Preview/CI 未使用 production 写凭据。

## 数据与基础设施

- [ ] 环境变量名称、作用域和 secret store 已双人核对。
- [ ] 数据库 migration 已在生产备份恢复库 dry-run。
- [ ] 发布前数据库备份成功，且已记录可恢复 ID。
- [ ] COS 版本/生命周期和待变更 object key 已确认。
- [ ] Redis/BullMQ 容量、失败队列和 Worker 状态正常。
- [ ] staging 使用的镜像 digest 与计划 production digest 完全一致。

## 发布与回滚

- [ ] 发布窗口和用户影响已确认。
- [ ] 当前 Vercel deployment ID、后端镜像 digest 已记录。
- [ ] 回滚命令、旧 digest、数据库/COS 恢复步骤已演练。
- [ ] 监控 Dashboard 和告警接收人在线。
- [ ] 支付/积分/生成对账查询已准备。

任一必选项未完成：No-Go，不得通过口头承诺跳过。
