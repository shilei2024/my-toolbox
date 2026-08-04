# Phase 3 变更记录

## 交付

- 新增框架无关 `ImageProvider` 契约、Registry、错误模型和 Mock Provider。
- 业务层不依赖 ComfyUI、OpenAI、Gemini 或其他 SDK 类型。
- 输出 ADR-0003。

## 验证

Provider 契约与 Mock 测试通过。

## 已知限制

只定义抽象层，不包含真实生产 Provider。
