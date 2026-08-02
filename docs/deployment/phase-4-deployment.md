# Phase 4 部署手册

目标环境：Next.js/Vercel 前端、腾讯云 CVM（Ubuntu、Docker Compose）上的 Generation Service、腾讯云 COS，以及独立的 ComfyUI GPU 执行端。

> 4 CPU / 4 GB RAM 的 CVM 适合作为 API/协调节点，不适合本地运行主流扩散模型。ComfyUI 应放在有 GPU 和足够显存的独立实例，或使用受保护的 GPU 服务地址。

## 网络拓扑

- Vercel 前端只调用公开业务 API，不获得 Provider code、ComfyUI 地址或 COS 凭证。
- Generation Service 到 ComfyUI 使用腾讯云 VPC/专线或 HTTPS 鉴权网关。
- Generation Service 仅需访问 COS API；COS bucket 默认私有，通过 CDN 签名或受控公开策略提供最终图片。
- ComfyUI 的 8188 端口不得直接暴露公网；安全组只允许 Generation Service 来源。

## 发布目录

```text
/opt/ai-image-platform/
├── compose.yaml
├── .env                 # 600 权限，不进入镜像/仓库
└── workflows/           # 只读、版本化 API workflow JSON
```

运行时容器挂载：

- `/opt/ai-image-platform/workflows:/app/workflows:ro`
- 命名 volume 或受限目录到 `/app/tmp/comfyui`

## Compose 要点

```yaml
services:
  generation-service:
    image: your-registry/generation-service:${RELEASE_TAG}
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./workflows:/app/workflows:ro
      - comfy-temp:/app/tmp/comfyui
    networks: [backend]
    read_only: true
    tmpfs:
      - /tmp:size=64m,mode=1770

volumes:
  comfy-temp:

networks:
  backend:
```

镜像启动入口应先运行配置校验，再启动 API/worker。容器使用非 root 用户，并设置 CPU、内存、日志轮转和健康检查。Phase 5 引入 BullMQ 后，再把同一镜像拆成 API 与 worker 两个进程角色。

## 工作流发布

1. 在与生产节点版本一致的 ComfyUI 中导出 API 格式 JSON。
2. 把动态字段替换为受支持的 `{{placeholder}}`，保存为新版本，例如 `portrait-v2.json`。
3. 在预发布环境运行 loader 与真实 ComfyUI smoke test。
4. 先发布 workflow 文件，再启用对应 database binding；旧 binding 和旧文件继续保留。
5. 禁止就地覆盖已用于历史 generation 的版本文件。

## COS 权限

服务身份只授予目标 bucket/prefix 的上传与补偿删除权限，不授予 bucket 管理权限。优先使用短期凭证并轮换长期密钥；开启服务端加密、访问日志、生命周期策略和费用告警。若 Gallery 需要公开访问，优先通过 CDN/签名 URL，不直接公开整个 bucket。

## 上线验证

```powershell
cd services/generation-service
npm.cmd run typecheck
npm.cmd test
```

生产 smoke test 应使用专用测试 workflow 和 bucket prefix，验证：提交、轮询、下载、COS URL 可读、临时文件消失、取消、超时、安全日志无 prompt/密钥/路径。

## 监控与告警

- generation 成功率和 p50/p95/p99 总耗时
- ComfyUI 429/5xx、网络错误、重试次数、队列等待时间
- COS 上传成功率、上传耗时、补偿删除失败数
- 临时 volume 使用率与遗留文件数
- Provider health、错误分类和单 workflow/model 失败率

## 回滚

禁用新 binding 或将流量切回 Mock/上一可用 Provider；回滚 Generation Service 镜像与 workflow 清单。数据库记录和已上传 COS 图片不删除。若新 workflow 有问题，只停用新版本，历史版本文件继续保留用于复现。

