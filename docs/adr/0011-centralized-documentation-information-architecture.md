# ADR-0011：统一文档信息架构

状态：Accepted

## Why

原文档按 AI Image Platform 和 Phase 混排，架构、配置、部署、ADR 与图表位于同一层级，随着 AI Toolbox 增加视频、OCR、PDF 等模块后会难以发现、复用和维护。项目需要一个稳定的 `/docs` 门户，并按文档职责而非当前业务模块统一分类。

决定采用 `architecture`、`deployment`、`operations`、`api`、`adr`、`roadmap`、`troubleshooting` 和 `changelog` 八类目录。`docs/README.md` 是唯一总入口，每个分类维护自己的索引。

## Alternatives Considered

- 继续按 Phase 平铺：迁移成本最低，但不同职责混杂，长期扩展困难。
- 按业务模块分目录：便于单模块开发，但共享认证、积分、支付和队列文档会重复。
- 引入独立文档站生成器：搜索和导航更强，但当前增加构建、部署和维护成本，暂不采用。

## Future Impact

新模块必须复用同一文档分类，不再创建 `docs/ai-video-platform` 等平行树。API 变更、架构决策和阶段发布需要在同一变更中同步文档。未来可在不改变源目录的前提下接入 MkDocs、Docusaurus 或其他发布器。

## Performance

不影响应用运行性能。分类和稳定链接可减少文档检索与评审时间；若未来生成文档站，构建成本仅发生在 CI。

## Cost

当前没有新增云资源成本，主要成本是一次性迁移和持续维护。集中管理可以降低重复文档和错误部署造成的返工成本。

## Security

统一规则明确禁止文档保存密钥、Token、Cookie、真实客户数据和完整敏感 Prompt。运维和排障文档只记录引用 ID；密钥通过 Secret Manager 或部署环境注入。

## Rollback Plan

若新结构影响现有工具，可在保留新目录内容的同时恢复兼容索引或重定向文件。完整回滚可按版本控制恢复旧路径并同步修复引用；不允许只移动文件而留下失效链接。
