# 客户项目 Phase 3 生命周期发布与回滚

## 目的与边界

本阶段增加重新激活、衍生项目和生命周期汇总，不新增表、列、依赖、环境变量、定时任务或外部服务。生产站点继续受 `CUSTOMER_PROJECTS_ENABLED` 与 `CUSTOMER_PROJECTS_PILOT_EMAILS` 保护。发布不等于启用；真实 PostgreSQL staging、备份恢复和权限验收未完成前不得扩大生产范围。

## 发布前检查

1. 确认当前分支不是 `main`，工作区变更已评审，数据库已完成可恢复备份。
2. 在同版本 PostgreSQL staging 执行 `flask db current`；预期仍为 `b3c4d5e6f7a8 (head)`，本阶段不运行新 migration。
3. 保持生产总开关关闭或只配置内部试点邮箱；确认统一后台只有预期经理角色。

## 验证命令

```powershell
.\.venv\Scripts\python.exe -m compileall customer_projects
.\.venv\Scripts\python.exe -m pytest tests\test_customer_projects_phase1.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

预期全部退出码为 0，无失败或错误。随后在 staging 手工验证：经理把失败项目恢复到进行中阶段，原失败事件和复盘仍可见；以同一幂等键重试不新增事件；衍生后编号不同、来源可点击、物料/竞品按选择复制且活动不复制；Sales 只能看到授权项目报表，经理可看组织范围；报表文字明确“当前状态，不是转化率”。

## 发布步骤

先部署不可变应用版本并重启 Flask/Gunicorn 进程，检查健康页和错误日志；仅对内部试点开放，在一个工作日内观察 4xx/5xx、409、查询耗时和审计记录。审批通过后再按既有变更流程扩大试点。不得直接向生产 `main` 推送未评审代码。

## 常见失败与恢复

- `PROJECT_VERSION_CONFLICT`：项目被并发更新，刷新详情后重新提交，不人工改库。
- `REACTIVATION_NOT_ALLOWED`：来源不是暂停/终态，使用普通阶段变更。
- 衍生结果缺少竞品：必须同时选择复制物料和竞品；软删除资产不会复制。
- 报表数量与预期不同：核对当前状态、用户数据范围和 `updated_at` UTC 日期筛选，不把历史阶段事件混入当前快照。

## 回滚

先关闭客户项目总开关或收窄试点邮箱，再回退到上一应用版本并重启。没有数据库 downgrade；保留已生成的来源关系、阶段事件、项目和审计。确认旧版本健康、主站其他模块正常后结束回滚。业务上误建的衍生项目通过带原因软删除处理，不物理删除。
