# 产品线 79 更名与发票 OCR 提速发布手册

## 2026-10-24 发布（0.9.45）

本次发布包含两件事：产品线 79 由“物料分组”更名为“先楫”，以及发票上传/OCR 链路的重复工作清理。
前者只改动名称文本，后者只删除无用请求、缓存与日志路径上的多余工作，都不改变识别口径、接口契约、
页面结构或数据库结构。

适合按现有 `/opt/mytoolbox` + systemd `mytoolbox` 流程发布：**无数据库迁移、无新增环境变量、
无新增依赖、无新增常驻进程**。

## 影响与门禁

- 影响模块：仅报销助手（`tools/reimbursement`）与发票上传弹窗模板。
- 产品线更名会一次性纠正该用户名下的目录行、发票 `product_line` 文本与应酬/派车/出差明细 `purpose`，
  命中条件基于旧名称，重复执行不再触发。不纠正会让导出封面按名称匹配不到产品线而落到“未匹配”。
- OCR 仍按“百度增值税票 → 百度通用票 → 腾讯云 → 本地 PaddleOCR”顺序降级，超时值不变。
- CI 中 Python tests、PostgreSQL integration、Vercel 通过；`Generation Service` 与 `Gallery Web`
  两个 Node 任务因上游新披露的 `fast-uri` 等漏洞失败（`npm audit` 修复需 breaking change），
  与本次改动无关，主分支基线同样失败，另行处理。

发布前记录当前 Git SHA 与 `flask db current` 输出；数据库备份按平台标准始终保留。

## 腾讯云更新命令

```bash
cd /opt/mytoolbox
git status --short
# 若有输出先停止：服务器上不应存在未提交改动
git rev-parse --short HEAD

git fetch origin
git switch main
git pull --ff-only origin main
git log --oneline -1

# 本次没有新增 Python 依赖，习惯性执行也安全
.venv/bin/pip install --requirement requirements.txt

export FLASK_APP='app:create_app'
export AUTO_CREATE_SCHEMA=false
.venv/bin/flask db current
.venv/bin/flask db heads
# 两者应一致；本次无新迁移，无需 upgrade

sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

预期：`git log -1` 显示合并提交 `Merge pull request #97`；`db current` 与 `db heads` 相同；
systemd 为 `active (running)`；健康检查返回成功。

## 业务验收

1. 打开报销助手，产品线下拉第 79 项显示“先楫”，编号仍为 `79`。
2. 打开或导出涉及该产品线的历史报销，封面汇总里该分组带编号 `79`，不再出现在“未匹配”。
3. 上传一张增值税专票，确认发票号码、日期、销售方、金额、税额、价税合计自动回填。
4. 上传一张火车票（触发通用 OCR 降级）与一张扫描版 PDF 发票，确认仍能回填且提示语为中文。
5. 连续上传 3–5 张发票，确认不再出现 429（限流已从 10 次/分钟调整为 30 次/分钟），
   且浏览器网络面板中 `/tools/reimbursement/ocr` 请求体只有 `file_id`，不含 `image_base64`。

## 性能观察

- 单张票据的浏览器上行从“原件 + 整图 base64”降为一次 `file_id` 请求，弱网（4G/远程办公）改善最明显。
- 服务端在首批请求后不再重复换取百度 token；同进程后续识别省去一次 HTTPS 往返。
- 命中增值税模板时不再编码未使用的增强变体，本机基准由约 0.53 s 降至 0。
- 可用 `journalctl -u mytoolbox -n 200 --no-pager | grep -i "Baidu token"` 确认 token 告警未持续出现。

## 常见失败与恢复

- `git pull` 冲突：说明服务器上有本地改动，停止发布，先确认来源再处理，不要在服务器上编辑源码。
- 服务起不来：`journalctl -u mytoolbox -n 200 --no-pager` 查看；日志不得复制口令、Cookie 或客户数据到公开渠道。
- 产品线仍显示“物料分组”：确认该账号已打开过报销助手（目录纠正发生在读取目录时），
  或检查该账号是否已存在名为“先楫”的目录行（存在时脚本会跳过以避免唯一约束冲突）。
- OCR 变慢：确认 `BAIDU_OCR_API_KEY` / `BAIDU_OCR_SECRET_KEY` 仍有效；配额耗尽会额外触发腾讯云与本地兜底。

## 回滚

```bash
cd /opt/mytoolbox
git switch --detach <PREVIOUS_SHA>
sudo systemctl restart mytoolbox
sudo systemctl status mytoolbox --no-pager
curl --fail --silent --show-error https://mindfulpenpal.com/healthz
```

注意：更名纠正已经写入数据库，回滚代码只会让新播种目录重新使用旧名称，不会把已纠正的历史文本改回
“物料分组”。如需完全恢复旧名称语义，须在确认后单独执行一次反向 SQL，并在变更记录中登记。
