# MindfulPenPal 文档中心

本目录是项目文档的唯一入口。新文档不得再建立平行的 `docs` 树或放在业务代码目录中；业务 README 只保留快速启动说明，并链接到这里的权威文档。

所有功能在实现前必须通过[永久工程原则与 Golden Rule](architecture/engineering-principles.md)；自动化开发者同时受仓库根目录 [`AGENTS.md`](../AGENTS.md) 约束。

开发、评审和发布从[贡献指南](../CONTRIBUTING.md)与[Git 策略总览](operations/git-strategy.md)开始。当前生产发布检查见[生产发布清单](operations/release-checklist.md)。

## 文档导航

| 目录 | 内容 | 主要读者 |
| --- | --- | --- |
| [architecture](architecture/README.md) | 系统边界、模块设计、数据模型和架构图 | 架构师、开发者 |
| [product](product/README.md) | 产品需求、范围、角色、业务规则和验收标准 | 产品、业务、设计、开发与测试 |
| [deployment](deployment/README.md) | 从准备环境到发布、验证和回滚的小白教程 | 首次部署人员 |
| [operations](operations/README.md) | 日常巡检、真实部署验证、备份恢复和事件响应 | 运维人员 |
| [api](api/README.md) | 对外 BFF、内部服务 API 及鉴权边界 | 前后端开发者 |
| [adr](adr/README.md) | 不可变的架构决策记录 | 全体成员 |
| [roadmap](roadmap/README.md) | 平台原则、里程碑、依赖和上线顺序 | 产品、技术负责人 |
| [troubleshooting](troubleshooting/README.md) | 常见故障的定位、恢复和升级路径 | 开发、运维、客服 |
| [changelog](changelog/README.md) | Phase 1–10 与后续里程碑的交付和验证记录 | 全体成员 |

## 文档去重说明（2026-08-08 整理）

- **新手部署**：唯一入口是 [deploy/DEPLOY_GUIDE.md](../deploy/DEPLOY_GUIDE.md)；
  规范部署索引见 [deployment/README.md](deployment/README.md)，两者互为补充而非重复。
- **本地开发**：见 [local-development-bridge.md](deployment/local-development-bridge.md)。
- **变更记录**：根目录 [CHANGELOG.md](../CHANGELOG.md) 为最新权威变更日志；
  [changelog/](changelog/README.md) 保留历史阶段档案，不再追加新条目。
- **平台升级方案**：8 项需求与 Phase 1–3 进度见
  [platform-upgrade-plan.md](development/platform-upgrade-plan.md)。

## 文档治理规则

1. 架构事实写入 `architecture/`，重要取舍同时新增 ADR。
2. 部署文档必须包含目的、前置条件、命令、预期输出、验证、常见失败和回滚。
3. 运维文档只描述已经存在的生产能力；尚未实现的能力必须标记为阻断项。
4. API 文档以服务端路由和契约测试为事实来源，变更 API 时必须同步更新。
5. 每个 Phase 完成时同时更新架构/部署/API、ADR 和对应 changelog。
6. Markdown 使用 UTF-8；内部链接使用相对路径；密钥、Token、真实账号和客户数据不得进入文档。
7. 删除或移动文档前先全仓检索引用，并在同一变更中修复链接。

## 当前平台边界

MindfulPenPal 是可扩展的 AI Toolbox Platform，图片生成只是第一个业务模块。认证、积分、支付、Provider Registry、存储、队列、任务历史、日志、监控和配置应作为可复用平台能力建设，模块业务不得与具体 AI、支付或存储供应商紧耦合。
