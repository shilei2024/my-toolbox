# AI 并入主项目 · 上线验收清单

状态：**合并后、切生产流量前逐项验收**。全部通过并留档后才能把 release 分支合并进 `main` 并允许 Vercel/服务器切流量。

## 验收环境

- 生产数据库、Redis、COS 已隔离并完成备份；
- 至少一个真实 AI Provider 已配置且管理员已启用；
- Gallery Web 与 Flask 处于同一受控父域，登录 Cookie 已在 staging 验证；
- 记录：Git SHA、镜像 digest、Vercel deployment ID、操作者、时间。

## 验收项

| # | 验收项 | 通过标准 | 验证方法 |
| --- | --- | --- | --- |
| 1 | `mindfulpenpal.com` 正常打开 | 首页 200，无 500/504，控制台无报错 | 浏览器 + `curl -I` |
| 2 | 用户登录正常 | 注册/登录/登出均可用，管理员可进 `/admin` | 真实账号走一遍 |
| 3 | AI 入口正常 | 首页出现“AI 作图”卡片且跳转到 Gallery `/create` | 点击卡片 |
| 4 | AI 生成任务创建 | `/create` 提交后返回 202，任务进入 pending/running | 浏览器 Network + 后台任务列表 |
| 5 | 积分扣除 | 新用户首次汇总到账赠送积分；创建时预占、成功后结算 | 账单页流水 |
| 6 | AI Provider 调用成功 | Worker 日志出现 `generation.completed`，无 Provider 错误 | `docker compose logs worker` |
| 7 | 图片上传 COS | COS Bucket 出现 `images/jobs/...` 对象，asset 记录一致 | COS 控制台 + 数据库 `ai.image_assets` |
| 8 | Gallery 展示 | 公开作品（或本人作品）能打开，图片可下载/点赞/收藏 | 浏览器访问详情页 |
| 9 | Vercel build 成功 | 两个 Vercel 项目生产构建均为 Success，路由清单完整 | Vercel Deployments |
| 10 | 服务器服务稳定 | 运行 24h：api healthy，dispatcher/worker 无异常重启，日志无密钥泄露 | `docker compose ps` + 日志 |

## 记录要求

每项记录：通过/失败、操作者、时间、证据（截图/日志片段/命令输出）。失败项未修复前，生产发布为 **No-Go**。

## 验收后开关

1. 确认全部通过后，把 `PRODUCTION_RELEASE_APPROVED=true` 写入服务器环境文件并重启后端。
2. 在 Vercel 原站项目设置 `AI_IMAGE_EXTERNAL_URL` 与 `SESSION_COOKIE_DOMAIN`，触发一次生产部署。
3. 复测第 1-3 项与登录；异常时按回滚指南恢复，不要继续扩大流量。
