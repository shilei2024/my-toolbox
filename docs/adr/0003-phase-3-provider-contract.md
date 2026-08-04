# ADR-0003：框架无关的 Provider Contract

状态：Accepted  
阶段：Phase 3

## Why

用框架无关的 TypeScript `ImageProvider` 统一 generate、cancel、status、health 和 cost，Provider Registry 与能力策略只依赖该契约，防止业务层依赖具体 SDK。

## Alternatives Considered

- 为每个 Provider 写独立业务流程：开发快，但重试、错误和计费无法统一。
- 直接在 NestJS Controller 中调用 SDK：文件少，但框架、HTTP 和 Provider 强耦合。
- 未知 Provider 自动降级到默认：表面可用，实际会造成不可解释的成本与隐私风险。

## Future Impact

ComfyUI 和未来 OpenAI/Gemini/即梦 Adapter 必须通过同一契约测试；fallback 使用排序候选，无需修改 Adapter。

## Performance

能力过滤为内存操作；Registry 查找为 O(1)，不会成为生成链路瓶颈。

## Cost

统一 cost estimate 为后续低成本路由和会员额度预留提供基础，Mock Provider 降低测试费用。

## Security

前端请求无 Provider 和密钥字段；未知错误被安全归一化，原始响应不返回客户端。

## Rollback Plan

Provider 核心尚未接管旧 Flask 入口。可移除 generation-service 部署并继续使用旧模块；契约代码和数据库不影响现有路径。

