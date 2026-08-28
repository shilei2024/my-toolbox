# ADR 0034：物料机会四类分类（Design In / Design Win / Evaluation / Lost）与 Lost 竞品口径

日期：2026-08-28 · 状态：已接受 · 覆盖：ADR 0032

## Why

业务把原三类标签（设计中物料、已匹配料号机会、竞品替代机会）统一为行业术语：Design In、Design Win、Evaluation、Lost，并新增 Design Win 类型以区分"已定点"物料。Lost 表示该物料位置被竞品占据，只有竞品信息可记录；其市场容量（TAM）仍需计入，因此按竞品报价估算。四类状态可在项目推进中互转，Lost 重新赢回时必须补充推广物料信息，避免出现无品牌/型号的"空"推广物料。

## Alternatives Considered

1. **重命名数据库枚举代码**（`matched_opportunity` → `evaluation` 等）：需要数据迁移与全量代码替换，风险高且无业务收益。
2. **为 Lost 单独建表**：与现有物料版本锁、审计、竞品关联冲突，重复度高。
3. **采用方案**：保留稳定代码，仅新增 `design_win` 枚举值并更新约束；展示层统一新标签；Lost 口径在服务层集中处理。

## Decision

- `opportunity_type` 稳定值：`design_in`（Design In）、`design_win`（Design Win，新增）、`matched_opportunity`（Evaluation）、`competitive_opportunity`（Lost）。迁移 `c2d3e4f5a6b7` 仅替换检查约束。
- TAM = 四类合计，其中 Lost 按"项目年用量 × 单机数量 × 竞品最高报价"估算；SAM = Design In + Design Win + Evaluation；SOM = Design In + Design Win。
- Lost 物料创建/转入时推广品牌、型号非必填（前端隐藏单价输入并提示）；`promoted_brand` 以空字符串满足非空约束。
- Lost 转出为其他三类时，服务端强制要求推广品牌 + 推广型号（或型号待确认），返回 422 字段级错误。
- 新增竞品时即可填写 `quoted_price`（最多 5 位小数），支撑 Lost 的 TAM 估算。

## Future Impact

若未来需要区分"在用竞品"报价而非最高报价，可在 `material_competitors.incumbent_status` 上扩展取价策略；口径调整只需修改 `competitor_reference_price`。

## Performance

市场口径在详情页实时派生，物料/竞品查询已有索引；新增竞品报价取最大值为 O(n) 内存操作，n 为单物料竞品数（个位数），可忽略。

## Cost

无新增基础设施；迁移只改约束，秒级完成。

## Security

沿用现有 RBAC、乐观锁、CSRF 与审计；Lost 转出校验在服务端强制执行，不依赖前端。

## Rollback Plan

迁移 `c2d3e4f5a6b7` 的 downgrade 先把 `design_win` 数据归入 `design_in` 再恢复旧约束；应用层回退到上一版本即可，Lost 口径变化不影响存量数据结构。
