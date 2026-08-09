# 小白部署教程

部署人员应先阅读 [生产部署验证 Runbook](../operations/production-deployment-verification.md)，确认 Go/No-Go 阻断项已经关闭，再按 Phase 文档执行。

## 平台部署标准

- [Vercel 前端部署](vercel-deployment.md)
- [Gallery 部署：仅 Vercel（腾讯云自托管已撤销）](gallery-tencent-self-hosting.md)
- [腾讯云 CVM 后端部署](tencent-backend-deployment.md)
- [腾讯云资源准备指南（小白版）](tencent-cloud-setup-guide.md)
- [环境变量与密钥管理](environment-variables.md)
- [部署准备检查清单](../operations/deployment-checklist.md)
- [回滚指南](../operations/rollback-guide.md)
- [AI 增强版生产部署指南（非程序员版）](../../deploy/DEPLOY_GUIDE.md)
- [上线验收清单](ai-merge-acceptance.md)
- [关闭 5432 公网暴露：数据库迁移到托管 PostgreSQL](database-exposure-fix-managed-postgres.md)

## 配置与部署文档

| Phase | 配置 | 部署与回滚 |
| --- | --- | --- |
| 4 | [ComfyUI/COS 配置](phase-4-configuration.md) | [Phase 4 部署](phase-4-deployment.md) |
| 5 | [Redis/BullMQ 配置](phase-5-configuration.md) | [Phase 5 部署](phase-5-deployment.md) |
| 6 | [Gallery 配置](phase-6-configuration.md) | [Phase 6 部署](phase-6-deployment.md) |
| 7 | — | [SEO 部署](phase-7-deployment.md) |
| 8 | — | [管理后台部署](phase-8-deployment.md) |
| 9 | [多 Provider 配置](phase-9-configuration.md) | [Phase 9 部署](phase-9-deployment.md) |
| 10 | [支付、积分、会员配置与部署](phase-10-configuration-and-deployment.md) | 同左 |

## 部署前必须准备

- 软件、域名、DNS、服务器、COS、环境变量清单
- 防火墙、TLS、Docker/进程管理、PostgreSQL、Redis 清单
- 数据备份、恢复演练和应用回滚方案
- staging 与 production 隔离资源
- 不包含真实密钥的发布证据包

任何教程缺少“为什么、命令、预期输出、验证、常见失败、恢复、回滚”之一，都视为未完成文档。

M1 AI 生图上线测试见 [Vercel Preview 与 Generation Staging 验证](m1-vercel-preview-validation.md) 和 [Generation Staging 服务器部署](m1-staging-server-deployment.md)。

M1 生产服务器、托管 PostgreSQL/Redis、腾讯 COS 与 Vercel 的人工密钥清单见 [M1 AI 功能生产配置（人工填写版）](m1-production-configuration.md)。该文档只准备配置，不绕过生产 Go/No-Go 门禁。

AI 模块并入生产主线的合并流程与审批门见 [AI 模块并入生产主线 · 合并 Runbook](../operations/ai-merge-runbook.md)。
