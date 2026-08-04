# 常见问题

| 现象 | 首先检查 | 恢复动作 |
| --- | --- | --- |
| Gallery 返回 401 | HMAC secret、时间偏差、Viewer Context | 同步时间并确认 Flask/Next/Generation 使用同一组环境配置 |
| 写操作返回 403 | 登录态、角色、`Origin` | 使用同源请求；不得关闭 Origin 校验绕过问题 |
| Sitemap 失败 | Gallery 内网连接、HMAC、COS/CDN allowlist | 修正内网地址和 hostname allowlist 后重新构建 |
| BullMQ 任务不消费 | Worker、Redis、queue name/prefix | 恢复 Worker；禁止通过 `FLUSHDB` 清队列 |
| 任务重复执行 | Job ID、幂等状态、数据库锁 | 以 PostgreSQL 状态为准，禁止重复结算积分 |
| ComfyUI 超时 | GPU 负载、workflow、内网 8188 | 降低并发；只对可重试错误重试 |
| COS 上传失败 | Region、Bucket、CAM、系统时间 | 修正最小权限或时间；上传成功前不得标记任务完成 |
| Stripe 签名失败 | 原始 body、endpoint secret、环境模式 | 确认 Test/Live secret 未混用，不要先解析 body |
| 支付成功但无积分 | Webhook inbox、订单状态、ledger reference | 重放幂等事件；不得直接改余额 |
| 余额与账本不一致 | ledger 汇总、重复 reference、历史人工写入 | 停止付费扩量，生成冲正记录并审计，禁止删除账本 |
| 删除后对象仍存在 | deletion job、COS 权限、重试次数 | 恢复删除 Worker；数据库继续保留软删除状态 |

处理故障时保留 request ID、job ID、Stripe event ID、COS object key 和发布时间。日志、截图和工单中不得包含 API Key、Cookie、Authorization、完整 Prompt 或用户隐私数据。
