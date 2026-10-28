# 部署准备检查清单

本清单面向首次部署人员。勾选前必须实际执行验证，不能只确认“应该已经配置”。

## 域名与 Vercel

- [ ] `mindfulpenpal.com` 当前 DNS 记录已导出。
- [ ] Vercel Production Branch 是 `main`。
- [ ] 非 main 分支只生成 Preview。
- [ ] TLS 证书有效，Preview 不被搜索引擎索引。

验证：

```bash
nslookup mindfulpenpal.com
curl -I https://mindfulpenpal.com
```

预期：DNS 指向批准的平台，HTTPS 返回正常状态且证书无警告。

## CVM、Docker 与防火墙

- [ ] Ubuntu 和安全更新状态已确认。
- [ ] Docker/Compose 版本符合部署文档。
- [ ] 磁盘、内存和 inode 有足够余量。
- [ ] 公网只开放 80/443 和受控管理入口。
- [ ] PostgreSQL、Redis、ComfyUI 仅私网访问。

```bash
docker --version
docker compose version
df -h
free -h
sudo ss -lntp
```

## 数据库、Redis、COS

- [ ] staging/production PostgreSQL 独立。
- [ ] migration ledger、备份、恢复演练完成。
- [ ] Redis 使用独立实例/namespace，有容量和持久化告警。
- [ ] COS 使用私有桶、最小 CAM 权限、加密、版本和生命周期。
- [ ] CDN/签名 URL hostname 与应用 allowlist 一致。

## 环境变量与密钥

- [ ] `.env`、Vercel Preview/Production、CVM env 相互隔离。
- [ ] Vercel 原站（my-toolbox）Production 已配置 `GALLERY_SERVICE_BASE_URL` 与
  `GALLERY_INTERNAL_HMAC_SECRET`（与 my-toolbox-gallery 完全一致），`/admin/gallery`
  能读取待审核队列与 Provider/Workflow 数据。
- [ ] 没有密钥使用 `NEXT_PUBLIC_`。
- [ ] GitHub CI 不读取部署密钥。
- [ ] production Environment 有人工审批和分支限制。
- [ ] 密钥轮换和泄露响应负责人明确。

## 应用与监控

- [ ] 所有 CI required checks 成功。
- [ ] healthcheck、smoke、日志、错误率、延迟、队列、数据库、Redis、COS 监控就绪。
- [ ] 支付 Test Mode、重复/乱序 Webhook、积分对账通过。
- [ ] Provider/COS/Redis/Worker 故障演练通过。
- [ ] 发布和回滚清单已由不同人员复核。

失败恢复：保留当前生产 deployment，不合并 `main`、不更新后端 digest；修复 staging 后从检查清单第一项重新验证。
