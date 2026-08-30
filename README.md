# My Toolbox 在线工具箱

> 项目工程治理、架构、部署、API、运维和路线图统一收录在 [文档中心](docs/README.md)。所有功能实现前必须通过 [Golden Rule](docs/architecture/engineering-principles.md)。

My Toolbox 是一个基于 Flask 的轻量级在线工具箱，集成 PDF、图片、文本、数据转换和开发辅助工具。项目支持匿名试用、用户登录、按工具计量，以及可在线调整站点信息和免费限额的管理后台。

## 功能亮点

- 插件化工具：工具通过 Blueprint 和 `tools_config.yaml` 注册，便于独立扩展
- 文件处理：PDF 合并、拆分、旋转、压缩、加密、水印及图片格式转换
- 开发工具：JSON、SQL、Base64、URL、UUID、哈希、正则和时间戳转换
- 用户与配额：匿名用户和注册用户分别计量，支持用户级工具限额
- 管理后台：用户管理、工具启停、调用统计、日志筛选和系统设置
- 专有工具授权：FCST 预测合并和报销助手默认隐藏，仅向后台指定的用户开放
- 动态站点设置：网站名称、首页标语、注册用户限额、匿名用户限额保存后立即生效
- 中国时间：后台时间、日志日期筛选、每日配额和时间戳工具统一按中国标准时间（UTC+8）处理

## 技术栈

- Python 3.9+
- Flask 3、SQLAlchemy 2、Flask-Login、Flask-WTF、Flask-Limiter
- Bootstrap 5、Bootstrap Icons、Jinja2
- SQLite（默认）或 PostgreSQL
- Gunicorn、systemd、Nginx

## 快速开始

### 项目结构

```text
apps/gallery-web             # AI 画廊前端（Next.js BFF + Gallery + 管理控制台）
services/generation-service  # 生成服务（Provider 路由、队列、计分、COS 持久化）
app.py / templates/ / static # 主站（Flask 工具箱 + 统一后台）
docs/                        # 文档中心（docs/README.md 为唯一入口）
deploy/                      # 生产部署（compose、Caddy、迁移脚本）
```

最新能力：AI 生图/画廊、昵称、双积分账本、积分兑换码、模型配置中心等，见
[CHANGELOG.md](CHANGELOG.md) 与[平台路线图](docs/roadmap/ai-toolbox-platform-roadmap.md)。

### 1. 获取代码

```bash
git clone https://github.com/shilei2024/my-toolbox.git
cd my-toolbox
```

### 2. 创建虚拟环境并安装依赖

Linux / macOS：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell：

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

Windows PowerShell 可使用：

```powershell
Copy-Item .env.example .env
```

至少应修改：

```dotenv
SECRET_KEY=请替换为至少32位随机字符串
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=请替换为强密码
SESSION_COOKIE_SECURE=False
```

生产环境启用 HTTPS 后，将 `SESSION_COOKIE_SECURE` 改为 `True`。

### 4. 启动

```bash
python app.py
```

Windows 也可使用 `py -3 app.py`。按 `.env.example` 的默认配置，访问地址为 <http://127.0.0.1:8000>。

## 管理后台

使用 `.env` 中的管理员账号登录，然后访问 `/admin`。

后台支持：

- 仪表盘：注册用户、活跃用户和调用趋势
- 用户：启用或禁用账号，设置单个工具的用户级限额
- 专有工具权限：按用户开放或取消 FCST 预测合并、报销助手的访问权
- 工具：在线启用或停用工具
- 日志：按工具、状态和中国日期筛选调用记录
- 系统设置：修改网站名称、首页标语、两类免费限额及 AI 作图配置

“站点与限额”保存到数据库，并在每次请求时同步到当前服务进程，因此：

- 首页、导航、页面标题和描述会显示最新站点信息
- 注册用户与匿名用户的配额校验会立即使用最新限额
- Gunicorn 多 worker 部署不需要手动重启
- 服务重启后仍会恢复数据库中的设置

### 专有工具授权

`FCST 预测合并` 和 `报销助手` 配置为专有工具：

- 匿名用户无法查看或访问
- 未授权的普通用户不会在首页看到工具，直接访问页面或接口也会被拒绝
- 管理员自动拥有全部专有工具权限
- 管理员可在“后台 → 用户 → 专有工具权限”中按用户开放或取消权限
- 授权记录保存在 `user_tool_grants` 表中，服务重启后仍然有效

## 时间规则

- 数据库时间字段继续使用 UTC 保存，便于迁移和跨地区部署
- 后台用户时间、登录时间和调用日志转换为中国标准时间展示
- 后台日志的起止日期按中国自然日换算成 UTC 查询区间
- 每日配额以中国日期为边界，在北京时间零点进入新一天
- 时间戳工具默认输出中国标准时间，同时保留 UTC 和 ISO 8601 结果
- 日期转时间戳时，无时区输入按中国标准时间解释；带偏移量输入按自身时区解释

## 常用配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `dev-only-change-me` | Flask 会话签名密钥，生产环境必须修改 |
| `DATABASE_URL` | `sqlite:///app.db` | SQLAlchemy 数据库地址 |
| `ADMIN_EMAIL` | `admin@example.com` | 首次启动时创建的管理员邮箱 |
| `ADMIN_PASSWORD` | `ChangeMe123!` | 首次启动时创建的管理员密码 |
| `SITE_NAME` | `Mavis 在线工具箱` | 网站名称的初始值 |
| `SITE_TAGLINE` | 内置文案 | 首页标语的初始值 |
| `DAILY_FREE_LIMIT` | `10` | 注册用户每个工具每日免费次数 |
| `ANON_FREE_LIMIT` | `3` | 匿名用户每个工具免费次数 |
| `MAX_UPLOAD_MB` | `25` | 单文件最大上传体积 |
| `TEMP_FILE_TTL_MINUTES` | `30` | 临时文件保留时间 |
| `RATELIMIT_DEFAULT` | `120/minute` | 全局 IP 限速 |
| `RATELIMIT_TOOL` | `20/minute` | 工具处理接口限速 |
| `RATELIMIT_STORAGE_URI` | `memory://` | 限速存储；多实例建议使用 Redis |
| `DISPLAY_TIMEZONE` | `Asia/Shanghai` | 显示时区配置 |
| `SESSION_COOKIE_SECURE` | `False` | HTTPS 生产环境设为 `True` |

环境变量是初始默认值。管理员在后台保存“站点与限额”后，数据库值优先。

图像生成服务的 Provider、模型和密钥配置已迁移至 `services/generation-service/.env.example`；主站不再读取 `AI_PROVIDER`、`AI_API_KEY`、`AI_BASE_URL` 或 `AI_MODEL`。

## 测试

项目包含覆盖应用启动、工具路由、鉴权、后台操作、动态设置和配额的回归脚本：

```bash
python tests/run_tests.py
```

Windows：

```powershell
py -3 tests\run_tests.py
```

测试使用内存数据库和临时目录，不会修改本地业务数据。生成的 HTML 与 JSON 报告已被 Git 忽略。

## 添加新工具

1. 创建 `tools/<tool_id>/__init__.py`，导出名为 `tool_bp` 的 Blueprint。
2. 创建 `templates/tools/<tool_id>/_body.html`。
3. 在 `tools_config.yaml` 中添加工具配置。
4. 重启应用，使 Blueprint 完成注册。

最小处理接口示例：

```python
from flask import Blueprint, current_app, jsonify

from auth.decorators import commit_usage, require_usage
from extensions import limiter

tool_bp = Blueprint("my_tool", __name__)


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("my_tool")
def process():
    commit_usage("my_tool", success=True)
    return jsonify(ok=True, result="done")
```

工具成功后调用 `commit_usage(..., success=True)` 扣减次数并记录日志；失败时传入 `success=False`，只记录日志而不扣减次数。

## 生产部署

仓库提供：

- `deploy/mytoolbox.service`：systemd 服务
- `deploy/nginx.conf`：Nginx 反向代理示例
- `deploy/backup.sh`：数据库备份脚本
- `deploy/mytoolbox-logrotate`：日志轮转配置

典型部署流程：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

sudo cp deploy/mytoolbox.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mytoolbox

sudo cp deploy/nginx.conf /etc/nginx/sites-available/mytoolbox
sudo ln -s /etc/nginx/sites-available/mytoolbox /etc/nginx/sites-enabled/mytoolbox
sudo nginx -t
sudo systemctl reload nginx
```

上线前请检查 systemd 文件中的项目路径、运行用户和环境文件路径，并在 Nginx 配置中替换域名及证书路径。

## 常用命令

```bash
# 确保管理员存在
flask --app app create-admin

# 列出已注册工具
flask --app app list-tools

# 查看服务日志
journalctl -u mytoolbox -n 200 --no-pager
```

## License

MIT
