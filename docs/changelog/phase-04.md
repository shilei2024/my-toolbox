# Phase 4 变更记录

## 交付

- 接入 ComfyUI Adapter、workflow 版本和结果轮询。
- 生成结果持久化到腾讯云 COS，ComfyUI 输出仅作临时文件。
- 输出配置、部署、生成时序图和 ADR-0004。

## 验证

本地契约和集成测试通过。

## 已知限制

不包含 BullMQ、Gallery、支付和多 Provider fallback。
