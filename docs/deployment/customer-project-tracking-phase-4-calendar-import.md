# 客户项目 Phase 4 工作日历与受控导入发布手册

## 生产影响与前置条件

本阶段会改变提醒排期并允许经理批量创建项目。发布前必须备份 PostgreSQL，在同版本 staging 演练迁移与恢复；功能开关保持关闭或仅限内部试点。无需 Redis、对象存储、SMTP 新配置或常驻任务。

## 迁移

```powershell
$env:FLASK_APP = "app:create_app"
flask db current
flask db upgrade
flask db current
```

升级前预期为 `b3c4d5e6f7a8`；升级后为 `d5e6f7a8b9c0 (head)`。`c4d5e6f7a8b9` 只新增组织日期覆盖表，`d5e6f7a8b9c0` 只新增导入批次和逐行记录表，不回填或修改既有项目。

## 自动验证

```powershell
.\.venv\Scripts\python.exe -m compileall customer_projects shared admin
.\.venv\Scripts\python.exe -m pytest tests\test_customer_project_reminders.py tests\test_customer_project_imports.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

预期退出码为 0。迁移演练需验证 `b3 → c4 → d5`，并在临时副本验证 `d5 → c4 → b3` 后重新升级；生产回滚仍不执行 downgrade。

## Staging 人工验收

1. 在统一后台把一个周四设为休息日、相邻周六设为工作日；运行 reminder dry-run，确认提前/逾期日期移动且到期日本身不被改写。
2. 修改日历后确认旧 `pending/failed` 提醒变为 `cancelled`，下一次扫描使用新策略版本且不重复。
3. 下载模板，准备一行有效和一行错误数据；上传后确认没有客户/项目写入，页面展示字段映射结果和逐行错误。
4. 确认导入后只创建有效行；重复点击确认不重复创建。修改一个导入项目后执行撤销，未修改项目进入回收站，已修改项目保留并标记不可撤销。
5. 使用 Sales/FAE/只读账号访问导入入口应返回 403 或隐藏入口；跨组织批次不可枚举。

## 常见失败

- “模板缺少必填列”：重新下载模板，不直接改服务端映射。
- “Excel 压缩比异常/解压后超过 25MB”：拆分为小于 1000 行的可信工作簿，不放宽生产边界。
- 行显示负责人无效：先在统一后台启用成员并赋予业务/经理角色。
- `not_revertible`：项目导入后已有修改，按真实业务记录人工处理，不改数据库版本。
- 日历变更后没有新提醒：确认扫描开关、组织策略和项目覆盖启用，再运行 dry-run；旧意图被取消属于预期。

## 回滚

先停止提醒扫描与真实发送，关闭 `CUSTOMER_PROJECTS_ENABLED`，再回退应用并重启。保留四张新增表、导入对象、软删除记录和审计，不执行生产 downgrade。若错误导入尚未被修改，使用批次撤销；否则逐项目评审后走正常软删除。确认旧版本健康和主站其他工具正常后结束回滚。
