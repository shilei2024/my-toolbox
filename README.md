# My Toolbox — 在线小工具箱

一个轻量的个人在线工具箱：PDF 合并 / 拆分、AI 作图、图片压缩。  
支持匿名试用 + 注册账号两级用户体系，配套后台管理面板，工具以插件形式加载。

> 仓库根目录的 `app.py` 既是入口也是工厂；`gunicorn app:app` 直接可用。

---

## 1. 功能一览

| 工具 | 路径 | 说明 |
| --- | --- | --- |
| PDF 合并 | `/tools/pdf-merge` | 拖拽排序后合并多份 PDF |
| PDF 拆分 | `/tools/pdf-split` | 输入 `1-3,5,7-9` 提取页面 |
| AI 作图 | `/tools/ai-image` | OpenAI / SiliconFlow / Mock provider |
| 图片压缩 | `/tools/image-compress` | 本地 Pillow 压缩，可调质量 |

后台：`/admin`（仅管理员）

- 仪表盘：注册用户、今日活跃、各工具调用统计、近 14 天调用量
- 用户管理：启用 / 禁用、调整单个工具的自定义上限
- 工具管理：在线启停
- 日志：调用记录，按工具 / 状态 / 时间筛选
- 设置：网站名、标语、每日免费次数

---

## 2. 技术栈

- **后端**：Python 3.9+ / Flask 3 / SQLAlchemy 2
- **前端**：Bootstrap 5 + Bootstrap Icons（CDN），Jinja2 模板
- **数据库**：SQLite（开发 / 小规模），切换到 PostgreSQL 只需改 `DATABASE_URL`
- **进程管理**：Gunicorn + systemd
- **反向代理**：Nginx
- **HTTPS**：Let's Encrypt
- **依赖**：[`requirements.txt`](./requirements.txt)

---

## 3. 本地开发

```bash
git clone <your-fork-url> my-toolbox
cd my-toolbox
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env：改 SECRET_KEY、ADMIN_PASSWORD 等

# 启动（开发模式，自动建表 + 启用 debug）
FLASK_ENV=development python app.py
# → http://localhost:5000
```

### 常用命令

```bash
# 创建管理员（首次启动时已自动建，重复执行是幂等的）
flask --app app create-admin

# 列出已注册工具
flask --app app list-tools
```

---

## 4. 环境变量

| 变量 | 必填 | 说明 | 示例 |
| --- | :-: | --- | --- |
| `FLASK_ENV` |  | `production`（默认）/ `development` | `production` |
| `SECRET_KEY` | ✅ | Flask 会话签名密钥，至少 32 字符随机串 | `xxxxxxxx...` |
| `APP_BASE_URL` |  | 用于 OG meta / 邮件拼接 | `https://toolbox.example.com` |
| `DATABASE_URL` |  | 默认 `sqlite:///instance/app.db` | `postgresql://...` |
| `ADMIN_EMAIL` | ✅ | 首次启动时自动创建的超级管理员邮箱 | `you@example.com` |
| `ADMIN_PASSWORD` | ✅ | 上述管理员的初始密码（首次启动后请立即改） | `ChangeMe123!` |
| `AI_PROVIDER` |  | `openai` / `siliconflow` / `mock` | `openai` |
| `AI_API_KEY` |  | 第三方图像 API key | `sk-...` |
| `AI_BASE_URL` |  | 兼容 OpenAI 的服务地址 | `https://api.openai.com/v1` |
| `AI_MODEL` |  | 模型名 | `gpt-image-1` |
| `DAILY_FREE_LIMIT` |  | 注册用户每个工具每日次数 | `10` |
| `ANON_FREE_LIMIT` |  | 匿名用户每个工具总次数 | `3` |
| `MAX_UPLOAD_MB` |  | 单文件最大 MB | `25` |
| `TEMP_FILE_TTL_MINUTES` |  | 临时文件多久后清理 | `30` |
| `RATELIMIT_DEFAULT` |  | 全局 IP 限速 | `120/minute` |
| `RATELIMIT_TOOL` |  | 工具处理接口限速 | `20/minute` |
| `RATELIMIT_STORAGE_URI` |  | 限速存储后端，集群请用 `redis://...` | `memory://` |
| `HOST` |  | gunicorn 监听地址 | `127.0.0.1` |
| `PORT` |  | gunicorn 端口 | `8000` |
| `DISPLAY_TIMEZONE` |  | 前端显示时区 | `Asia/Shanghai` |
| `SESSION_COOKIE_SECURE` |  | 生产 `True`，本地 HTTP 开发 `False` | `True` |

---

## 5. 生产部署（Ubuntu 22.04, 4GB）

> 假设项目部署在 `/opt/mytoolbox`，由 `www-data` 用户运行，域名 `toolbox.example.com`。

### 5.1 准备

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip nginx sqlite3 certbot python3-certbot-nginx

sudo useradd -r -s /usr/sbin/nologin www-data || true
sudo mkdir -p /opt/mytoolbox
sudo chown -R "$USER":"$USER" /opt/mytoolbox   # 部署时用你自己的用户
cd /opt/mytoolbox
```

把代码同步到 `/opt/mytoolbox`：

```bash
# git clone / scp / rsync 任选其一
```

### 5.2 虚拟环境 + 依赖

```bash
cd /opt/mytoolbox
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5.3 写 `.env`

```bash
cp .env.example .env
sudo chown www-data:www-data .env
sudo chmod 640 .env
$EDITOR .env
# 必须改：SECRET_KEY、ADMIN_EMAIL、ADMIN_PASSWORD
# 生产建议：SESSION_COOKIE_SECURE=True
```

### 5.4 systemd 服务

```bash
sudo cp deploy/mytoolbox.service /etc/systemd/system/mytoolbox.service
sudo systemctl daemon-reload
sudo systemctl enable --now mytoolbox
sudo systemctl status mytoolbox
```

服务文件使用 `gunicorn -w 2 -k gthread --threads 4 -b 127.0.0.1:8000`。  
4GB 内存下 `-w 2 --threads 4` 是稳妥的起点；如果内存吃紧可降到 `-w 1 --threads 4` 或加 `--max-requests 1000 --max-requests-jitter 200` 防止内存泄漏。

### 5.5 Nginx + HTTPS

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/mytoolbox
sudo ln -s /etc/nginx/sites-available/mytoolbox /etc/nginx/sites-enabled/mytoolbox
# 修改文件里的 server_name 和 ssl_certificate 路径占位
sudo nginx -t
sudo certbot --nginx -d toolbox.example.com
sudo systemctl reload nginx
```

### 5.6 日志轮转（可选但推荐）

```bash
sudo cp deploy/mytoolbox-logrotate /etc/logrotate.d/mytoolbox
# 创建一个 logs 目录
sudo mkdir -p /opt/mytoolbox/logs
sudo chown www-data:www-data /opt/mytoolbox/logs
```

Gunicorn 写 systemd journalctl 看；如果想把访问日志落盘，把 `deploy/mytoolbox.service` 里的 `--access-logfile -` 改成 `--access-logfile /opt/mytoolbox/logs/access.log`，重启服务即可。

### 5.7 数据库备份

```bash
sudo install -m 0755 deploy/backup.sh /usr/local/bin/mytoolbox-backup
# 每天凌晨 3 点跑
sudo crontab -e
0 3 * * * /usr/local/bin/mytoolbox-backup
```

---

## 6. 添加一个新工具

每个工具都是一个独立的 Python 包，扩展无需改动核心代码。

### 步骤

1. **创建包** `tools/<id>/__init__.py`，暴露一个名为 `tool_bp` 的 Blueprint：

   ```python
   from flask import Blueprint
   from auth.decorators import require_usage, remaining_for
   from extensions import limiter

   tool_bp = Blueprint("my_tool", __name__)

   @tool_bp.get("/")
   def index():
       return render_template("tools_base.html",
                              tool={"id": "my_tool", "name": "我的工具", "icon": "bi-tools", "color": "#6610f2"},
                              remaining=remaining_for("my_tool"),
                              body_template="tools/my_tool/_body.html")

   @tool_bp.post("/process")
   @limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
   @require_usage("my_tool")
   def process():
       # ... 业务逻辑 ...
       from auth.decorators import commit_usage
       commit_usage("my_tool", success=True)
       return ...
   ```

2. **写页面** `templates/tools/my_tool/_body.html`（参考现有工具的 _body 文件）。

3. **注册到配置** `tools_config.yaml`：

   ```yaml
   - id: my_tool
     name: 我的工具
     description: 简介
     icon: bi-tools
     color: '#6610f2'
     route: /tools/my-tool
     blueprint_module: tools.my_tool
     order: 50
   ```

4. **重启应用**：`sudo systemctl restart mytoolbox`。`sync_tool_registry` 会把新工具写进 `tools` 表，首页和管理后台立即可见。

### 次数与日志

- 在视图函数上挂 `@require_usage("my_tool")` 装饰器即可启用匿名 / 注册用户次数检查；
- 处理成功时调用 `commit_usage("my_tool", success=True)` 落库 + 写审计日志；
- 失败时传 `success=False, message=...` —— 这样不会扣次数，但留下排查线索。

---

## 7. AI 提供商切换

`tools/ai_image/__init__.py` 中通过 `AI_PROVIDER` 选择后端：

| Provider | `AI_PROVIDER` | 备注 |
| --- | --- | --- |
| OpenAI (官方) | `openai` | 默认 base = `https://api.openai.com/v1` |
| 硅基流动 | `siliconflow` | 把 `AI_BASE_URL` 改成 `https://api.siliconflow.cn/v1` |
| Mock（占位） | `mock` | 不消耗额度，返回 1×1 透明 PNG，便于 UI 联调 |

要新增 provider：在 `tools/ai_image/__init__.py` 继承 `ImageProvider` 并在 `_PROVIDERS` 中注册一行。

---

## 8. 故障排查

| 现象 | 排查 |
| --- | --- |
| 502 Bad Gateway | `journalctl -u mytoolbox -n 200` 看 gunicorn 错误；多数是 `.env` 漏了变量或权限问题 |
| 上传 413 | 检查 `client_max_body_size` 是否 ≥ `MAX_UPLOAD_MB`；同时 `MAX_CONTENT_LENGTH` 已经从环境变量算出 |
| 登录后立刻掉线 | `.env` 里 `SESSION_COOKIE_SECURE=True` 但还没上 HTTPS → 暂时关掉或上证书 |
| `sqlite3.OperationalError: database is locked` | 调低 gunicorn worker 数（`--workers 1`）或换 PostgreSQL |
| AI 一直 mock | `AI_PROVIDER=mock` 是默认值；显式设为 `openai` 并配置 `AI_API_KEY` |

---

## 9. 升级 / 数据迁移

- 字段加列：直接改 `models.py`，首次启动会自动建表，**新增列** 用 `db.session.execute(text('ALTER TABLE ...'))` 在 `_migrate()` 里手动补；下一次启动日志会有提示。
- 切到 PostgreSQL：导出 SQLite → `sqlite3 instance/app.db .dump | psql ...`；改 `DATABASE_URL` 重启。

---

## 10. License

MIT（你可以随便用、改、商用）。
