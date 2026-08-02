# ADR-0001：独立 Generation Service 边界

状态：Accepted  
阶段：Phase 1

## Why

保留现有 Flask 站点，将生成路由、重试、Provider 选择、计费和审计集中到独立 NestJS Generation Service，使前端和原站不依赖供应商协议。

## Alternatives Considered

- 继续在 Flask 工具路由中增加 Provider：部署简单，但任务、文件和供应商逻辑继续耦合。
- 立即重写整站为 Next.js/NestJS：目标统一，但迁移成本和上线风险过高。
- 每个 Provider 独立微服务：隔离强，但早期运维成本不合理。

## Future Impact

后续 ComfyUI、队列、Gallery 和支付都通过 Generation Service 演进；Flask/Next.js 只消费统一 API。

## Performance

增加一次内网调用，但 API 可无状态横向扩展，耗时生成从 Web 请求进程隔离。

## Cost

初期多一个 CPU 服务进程；换来 GPU 按需启停和集中成本路由，整体成本更可控。

## Security

Provider 密钥和内网端点不进入浏览器；服务间必须使用短时签名身份并保留审计。

## Rollback Plan

在新链路上线前保留旧 Flask AI 作图入口。发生问题时由反向代理/功能开关切回旧入口，数据库新表保持只读待排查。

