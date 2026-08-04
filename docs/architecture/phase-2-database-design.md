# AI Image Community — Phase 2 数据库设计

状态：**实现完成，待阶段确认**  
数据库：PostgreSQL 15+  
默认对象存储：**腾讯云 COS**

## 1. 交付范围

本阶段完成 AI 图片社区的规范化数据库设计、首个 PostgreSQL migration、索引/约束策略以及 ER 图。不实现 Provider 调用、API、BullMQ 消费者或页面。

- Migration：[0001_initial.sql](../../services/generation-service/database/migrations/0001_initial.sql)
- ER 图：[phase-2-er-diagram.svg](diagrams/phase-2-er-diagram.svg)

## 2. Schema 边界

AI 业务表统一位于独立的 `ai` schema。首期复用现有 Flask 的 `public.users`，通过外键保持数据完整性；Generation Service 不直接修改用户表。

- `public.users`：身份事实来源，由现有 Flask/Auth 管理。
- `ai.*`：Generation Service 独占写入的业务域。
- Redis/BullMQ：Phase 5 引入，只保存可恢复的队列状态。
- 腾讯云 COS：保存图片二进制；数据库只保存 bucket、region、object key、校验值和可选 CDN URL。

未来拆分独立数据库时，可先通过 outbox/CDC 同步用户身份，再移除跨 schema 外键，不影响图片与任务主键。

## 3. 领域分组

### Provider 与工作流

| 表 | 职责 |
| --- | --- |
| `ai.providers` | Provider 注册、适配器类型、健康状态、优先级、能力与成本配置；只保存 `secret_ref`，不保存 API key 明文 |
| `ai.workflows` | 面向用户的稳定工作流，例如 Portrait、Anime、Product |
| `ai.workflow_versions` | 不可变的输入/输出契约版本，同一工作流只能有一个 active version |
| `ai.workflow_provider_bindings` | 将工作流版本映射到 ComfyUI workflow JSON 引用或第三方模型，并保存超时、重试和成本策略 |

工作流不直接绑定 Provider。新增 Provider 只增加 binding，不修改公开 workflow ID。

### 生成任务

| 表 | 职责 |
| --- | --- |
| `ai.generation_jobs` | 生成请求与公开状态机，是任务事实来源 |
| `ai.generation_attempts` | 每次 Provider 尝试的独立记录，支持 retry、fallback、成本和错误审计 |
| `ai.outbox_events` | 数据库事务提交后可靠投递到 BullMQ，避免“任务已写库但消息丢失” |

`generation_jobs.status` 严格限制为 `pending/running/completed/failed/cancelled`。`Redis` 中的 job 即使丢失，也能依据数据库和 outbox 恢复。

### 图片与 COS 资产

| 表 | 职责 |
| --- | --- |
| `ai.images` | Gallery 内容实体，保存永久生成快照、隐私、审核状态、SEO slug 与聚合计数 |
| `ai.image_assets` | 原图、预览图和缩略图对应的 COS 对象；对象键全局唯一 |
| `ai.tags` / `ai.image_tags` | 标签及图片多对多关系 |

`images` 会保存 Provider、模型、工作流名、Prompt 和生成参数快照。这是有意的历史快照，不依赖后台日后修改 Provider 或 Workflow 名称。COS 默认值为 `tencent_cos`；业务层通过 Storage Adapter 生成 URL，不拼接 COS 域名。

### 社区互动

| 表 | 职责 |
| --- | --- |
| `ai.likes` | 用户点赞；复合主键保证同一用户不能重复点赞 |
| `ai.favorites` | 用户收藏；复合主键保证同一用户不能重复收藏 |
| `ai.comments` | 评论和单层/多层回复，支持软删除及独立审核 |
| `ai.download_logs` | 下载事件，用 hash 记录必要的反滥用信息，不保存原始 IP |

`images` 中的互动计数是高频读取的缓存字段，事实仍以关系表和下载日志为准；事务内更新，必要时可离线重算。

### 审核、设置和审计

| 表 | 职责 |
| --- | --- |
| `ai.moderation_events` | Prompt、图片和人工审核的每次决策 |
| `ai.audit_logs` | 管理员、用户、Worker、Service 的业务操作审计 |
| `ai.system_settings` | AI 域动态设置；敏感配置只保存 `secret_ref` |

## 4. 隐私与删除设计

- 图片公开性：`visibility = public/private`。
- Prompt 公开性：`prompt_visibility = public/hidden`，与图片公开性互相独立。
- 公开 Gallery 查询必须同时满足：`public + approved + deleted_at IS NULL`。
- 隐藏 Prompt 由 API 字段级过滤，只有 owner/admin 可读取。
- 用户删除图片使用 `deleted_at` 软删除，立即从 Gallery 隐藏；后台异步删除 COS 对象后保留最小审计记录。
- 用户账号删除时，图片、评论和历史任务可匿名化为 `user_id = NULL`；点赞、收藏按 `CASCADE` 清除。
- `download_logs` 只记录散列后的 IP/User-Agent，用于限速和反滥用。

## 5. 关键约束与索引

- `(user_id, idempotency_key)` 部分唯一索引防止重复生成与重复扣费。
- `(job_id, attempt_no)` 唯一，保证重试序号稳定。
- `(workflow_id, version)` 唯一，且每个 workflow 只有一个 active version。
- `(workflow_version_id, provider_id)` 唯一，避免重复 Provider binding。
- `(image_id, user_id)` 是 like/favorite 复合主键。
- `(storage_provider, bucket, object_key)` 唯一，避免同一 COS 对象被重复登记。
- Gallery 部分索引只覆盖公开、审核通过且未删除图片。
- Outbox 部分索引只覆盖未发布事件。
- 用户历史、任务状态、Provider 尝试、评论、下载、审核和审计均有面向主要查询的组合索引。

## 6. 为什么保留 JSONB

规范化核心关系之外，以下内容使用受约束的 JSONB：

- Provider 能力和非敏感配置。
- 工作流输入/输出 JSON Schema 与默认值。
- 不同 Provider 的参数映射。
- 生成请求的扩展参数。
- 脱敏后的请求/响应快照和审核详情。

这些字段跨 Provider 差异大且会持续演进。所有 JSONB 字段都有对象/数组类型约束；需要频繁筛选或参与一致性约束的数据仍使用普通列。

## 7. Migration 策略

- `0001_initial.sql` 是 Generation Service 的基线 migration，使用事务执行。
- 首次 migration 创建 `ai` schema、枚举、表、索引与 `updated_at` trigger。
- Migration 只能前进执行；生产环境修改采用新的编号文件，不直接改已执行 migration。
- 部署顺序：备份 → migration dry-run → 执行 migration → 启动新版本 API/Worker → 健康检查。
- `CREATE EXTENSION pgcrypto` 在受限托管 PostgreSQL 上可能需要管理员预先启用；若平台禁止扩展，应用层生成 UUID，移除数据库默认值即可。

## 8. 数据生命周期

| 数据 | 建议保留 |
| --- | --- |
| 公开图片及 COS 原图 | 永久，除非用户删除、审核下架或版权投诉 |
| 私有图片 | 用户可配置；默认永久，后续可提供自动清理策略 |
| Generation Job | 长期保留核心字段，错误详情按策略脱敏/归档 |
| Provider response snapshot | 脱敏后短期保留，例如 30–90 天 |
| Audit log | 至少 180 天，支付上线后按财务要求延长 |
| Download log | 明细 90 天，之后只保留聚合统计 |
| Outbox event | 发布成功后定期归档/删除，例如 7–30 天 |

## 9. Phase 2 验收标准

- [x] 覆盖 users、providers、workflows、generation_jobs、images、image_tags、likes、favorites、comments、download_logs、system_settings。
- [x] 增加 attempts、assets、moderation、audit 和 outbox，满足 Phase 1 的可靠性要求。
- [x] Provider 与 Workflow 是多对多版本化映射，不存在单 Provider 紧耦合。
- [x] 腾讯云 COS 是默认存储，但数据库结构支持替换 Storage Adapter。
- [x] Prompt 隐私、图片隐私、审核状态和软删除可独立表达。
- [x] 唯一约束、检查约束、外键、删除行为和主要查询索引已定义。
- [x] Migration 与 Schema 契约测试通过。
- [x] ER 图已完成 SVG/PNG 渲染和视觉检查。

### 验证记录

- Schema 契约测试：10/10 通过。
- 现有报销模块回归测试：13/13 通过。
- PostgreSQL 18 临时实例：完整 migration 成功提交，共创建 18 张 `ai` 表。
- `image_assets.storage_provider` 数据库默认值实测为 `tencent_cos`。
- 临时 PostgreSQL 实例已停止并清理，未连接或修改业务数据库。

## 10. Phase 3 输入边界

Phase 3 只实现 Provider 抽象层和 Mock Provider，不接 ComfyUI、不接 BullMQ、不实现 Gallery 页面。Provider 契约将以本阶段的 `providers`、`workflow_provider_bindings`、`generation_attempts` 和错误分类为数据基础。
