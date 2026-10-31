# 高铁票金额补齐发布

起点：操作者已确认生产1c1f192fa0dc748d7ae02584487abe0f2d5fd5c4 / f5a6b7c8d9e0，服务active。服务器命令由操作者执行。无迁移、依赖、环境、Caddy、Redis/COS/生成链改动；仍需确认当前SHA及健康、磁盘、已有监控，保护生产本地Caddy与.env、上传、备份。详见[需求与风险](../product/mobile-ticket-amount-fix.md)。

## 恢复库验收

在已验证的固定PG16隔离恢复库运行候选；不是生产库。先核实隔离库归属与f5、候选SHA、无.env；沿用[工作台恢复库步骤](mobile-reimbursement-entry-rollout.md)，将候选替换为本hotfix精确提交。脚本拒绝root、非固定库名/非socket或错误版本。所有验证只对新建合成账号写入，历史用户、发票和原件BLOB指纹保持不变。候选如变化，重做。

预期既有五项MOBILE_*成功标记，加MOBILE_TICKET_AMOUNTS_OK，后者检查仅票价补齐、OCR缓存、旧客户端空白确认、真实不相等拒绝、网站金额、隔离与会话。未取得这些回执前，不执行生产发布。

## 发布与验证

独立评审与全部CI、恢复库通过后才合入main；由协作者提供本hotfix精确main SHA及固定起点的mobile_ticket_release.py。工具复用mobile_entry_release.execute的备份/历史/可读性/启动流程，传入独立固定source=1c1f192、业务候选94f79f4与专用门禁，原入口默认保护保持不变。不能运行旧mobile_entry_release.py（其起点8cd9d31已过时）。新工具停止主站、最终备份、保持相同f5和历史行指纹、Git快进（子进程umask022）、检查服务用户可读、启动并检查本机/公网health200及无凭据手机401。全程不输出密钥/连接串，私有备份/日志受0700/0600保护。失败只反馈阶段与私有日志路径，不粘贴内容。

后端通过后用仍未更新的客户端重新打开原高铁票，点击重新识别会复用旧缓存；检查金额和税额提示，按原票核对后确认保存。网站汇总/Excel金额必须一致，错误金额仍拦截且登录态保留。随后编译上传新版，真机检查“按票价补齐金额”及提示。不需要重复上传原票。开发版本上传不等于微信审核通过或正式发布。

## 回滚

保留已创建票据、同一f5和原件。不要downgrade、reset --hard或用旧库覆盖新录入。停服务后确保.env/Caddy摘要未变、无其他tracked修改，只用Git切到上版1c1f192的detached代码；Git子进程权限022；核实服务用户代码可读、启动、health/401，后续正式修复重新发布。若数据库指纹或配置异常，保持停写，核对私有备份与日志后制定恢复方案。仅在确认新写入影响后人工处理数据库，绝不自动恢复。

## 已完成的本机验证与待办

业务候选94f79f48d19c6724cc4baa99372ea0ed567fdd88：独立只读Reviewer批准，另行16项相关API/原生/恢复库逻辑测试通过。本机真实PG18临时集群33项成功并停止；PG16 CI随后已通过。原生WXML/WXSS实际编译、JS语法、diff空白检查通过。后续发布工具13项顺序/备份失败重启旧版/新健康失败保持停写测试通过。PR116七项CI及操作者隔离PG16恢复库六标记已全部通过；业务与工件已获独立批准。主线CI随后全部通过，操作者已反馈MOBILE_TICKET_DEPLOY_OK：c74de7e/f5、active/HTTPS/mobile enabled；高铁票真机复核及微信正式发布仍待。

生产执行时从批准main精确SHA提取mobile_ticket_release.py、mobile_entry_release.py、invoice_release.py、invoice_backup.py四文件到root新建0700目录；用生产venv执行mobile_ticket_release.py SHA。成功应为MOBILE_TICKET_DEPLOY_OK、相同f5、active及HTTPS/mobile enabled。旧入口保持旧保护，不要直接运行它。
