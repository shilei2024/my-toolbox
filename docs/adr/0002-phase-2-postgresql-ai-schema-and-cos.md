# ADR-0002：PostgreSQL AI Schema 与腾讯云 COS

状态：Accepted  
阶段：Phase 2

## Why

使用 PostgreSQL `ai` schema 保存任务、尝试、图片、社区、审核和审计事实；腾讯云 COS 保存永久二进制。数据库与对象存储职责清晰，且符合当前腾讯云基础设施。

## Alternatives Considered

- SQLite：本地简单，但不适合多实例并发、JSONB 和可靠 outbox。
- 把图片存 PostgreSQL：事务方便，但备份、带宽和容量成本高。
- Cloudflare R2 作为默认：出网优势明显，但用户确认腾讯云 COS 更符合部署区域。
- Redis 作为任务事实来源：吞吐高，但持久性和审计不足。

## Future Impact

Phase 5 BullMQ 必须通过 outbox 与 PostgreSQL 协作；Storage Adapter 可增加 R2、OSS、S3、MinIO 而不修改图片业务表。

## Performance

Gallery 使用部分索引和聚合计数；COS/CDN 直接分发图片，避免应用代理大文件。

## Cost

同区域 CVM、COS 和 CDN 降低跨云流量；对象生命周期和缩略图策略可继续压缩存储成本。

## Security

数据库只保存 `secret_ref`，COS 凭据不落库；私有图片必须使用授权或短时签名 URL。

## Rollback Plan

Migration 在事务中执行。失败自动回滚；上线后若需撤回，停止新服务、切回旧入口，并保留 `ai` schema 供审计，不直接删除数据。

