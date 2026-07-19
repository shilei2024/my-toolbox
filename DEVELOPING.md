# 开发与扩展指南

本文档面向"想加新工具"或"想改逻辑"的开发者。先把 `README.md` 看完，那是面向运维/部署的。

## 1. 目录约定

```
my-toolbox/
├── app.py                # 应用工厂
├── config.py             # 全部环境变量 / 配置类
├── extensions.py         # SQLAlchemy / LoginManager / CSRF / Limiter 单例
├── models.py             # User / Tool / AnonUsage / UserUsage / UsageLog / Setting
├── auth/                 # 注册 / 登录 / 装饰器
├── admin/                # 后台所有页面
├── tools/                # 工具插件（每个子目录 = 一个工具）
│   └── <tool_id>/
│       ├── __init__.py   # 必含 `tool_bp = Blueprint(...)`
│       └── (可选) 其它文件
├── templates/            # Jinja2 模板
│   ├── base.html
│   ├── tools_base.html   # 工具页通用壳
│   ├── tools/<tool_id>/_body.html
│   └── admin/
├── static/               # CSS / JS / favicon
├── utils/                # cleanup / helpers
├── deploy/               # systemd / nginx / logrotate / backup
└── requirements.txt
```

## 2. 写一个新工具（最小例子）

假设你要做一个 JSON 格式化工具。

### 2.1 创建包

`tools/json_format/__init__.py`：

```python
"""JSON 格式化工具。"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, url_for
from flask import flash

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import safe_filename

tool_bp = Blueprint("json_format", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "json_format", "name": "JSON 格式化",
              "icon": "bi-braces", "color": "#0dcaf0"},
        remaining=remaining_for("json_format"),
        body_template="tools/json_format/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("json_format")
def process():
    raw = (request.form.get("json") or "").strip()
    if not raw:
        return _fail("请输入 JSON。")
    try:
        import json
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _fail(f"JSON 解析失败: {exc}")
    pretty = json.dumps(parsed, ensure_ascii=False, indent=2)
    commit_usage("json_format", success=True)
    return jsonify(ok=True, result=pretty)


def _fail(msg):
    commit_usage("json_format", success=False, message=msg)
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(error=msg), 400
    flash(msg, "danger")
    return redirect(url_for("json_format.index"))
```

要点：
- Blueprint **必须** 叫 `tool_bp`，否则 `tools/__init__.py` 找不到；
- `index` 渲染 `tools_base.html`，并把工具卡片的数据传进去；
- 业务接口挂 `@require_usage("json_format")` 自动检查次数；
- 处理成功调 `commit_usage("json_format", success=True)` 落库；
- 失败传 `success=False` 不会扣次数，但会写审计日志。

### 2.2 写页面

`templates/tools/json_format/_body.html`：

```html
<form id="jsonForm" action="{{ url_for('json_format.process') }}" method="post">
  <input type="hidden" name="csrf_token" value="{{ csrf_token() }}"/>
  <div class="mb-3">
    <label class="form-label">原始 JSON</label>
    <textarea name="json" class="form-control" rows="10" required></textarea>
  </div>
  <button class="btn btn-primary btn-lg">格式化</button>
</form>
<pre id="result" class="mt-3 p-3 bg-light border rounded d-none"></pre>

{% block scripts_extra %}
<script>
  document.getElementById('jsonForm').addEventListener('submit', async e => {
    e.preventDefault();
    const r = await fetch(e.target.action, { method: 'POST', body: new FormData(e.target) });
    const data = await r.json();
    const out = document.getElementById('result');
    if (data.ok) { out.textContent = data.result; out.classList.remove('d-none'); }
    else { alert(data.error); }
  });
</script>
{% endblock %}
```

### 2.3 注册

`tools_config.yaml` 加一行：

```yaml
- id: json_format
  name: JSON 格式化
  description: 美化 / 校验 JSON
  icon: bi-braces
  color: "#0dcaf0"
  route: /tools/json-format
  blueprint_module: tools.json_format
  order: 50
```

### 2.4 重启 + 测试

```bash
sudo systemctl restart mytoolbox
flask --app app list-tools   # 应该能看到 json_format
```

浏览器打开 `/tools/json-format/` 即可。

## 3. 次数与计费

### 3.1 数据表

- `anon_usage`（匿名）：`(anon_id, tool_id, day) -> count`，每个工具每天上限独立计算；
- `user_usage`（注册）：`(user_id, tool_id, day) -> count`。

### 3.2 装饰器

`auth/decorators.py` 提供：

```python
@require_usage("pdf_merge")    # 进入视图前检查
def process(): ...              # 不通过会 flash + 重定向 或返回 429 JSON

commit_usage("pdf_merge",      # 业务完成后调用
             success=True,      # True = 扣次数; False = 仅写日志
             message="...")     # 可选，写入 usage_logs.message
```

### 3.3 用户自定义上限

管理员可以在 `/admin/users` 给某个用户对某个工具单独设置 `custom_limit`：

```json
{ "pdf_merge": 50, "ai_image": 0 }
```

写入 `users.custom_limits`（JSON 文本）。`User.limit_for()` 读取。

## 4. 后台添加新页面

`admin/routes.py` 加新 view + 在 `templates/admin/` 加模板。模板继承 `admin/_base.html` 即可自动得到左侧导航。

如果要做新的"管理对象"（比如评论审核、文件管理），按下面三步走：

1. `models.py` 加表
2. `admin/routes.py` 加 view（别忘 `@admin_required`）
3. `templates/admin/<name>.html`

## 5. 切换到 PostgreSQL

只要 `DATABASE_URL` 改成 `postgresql://user:pass@host/db`，其它代码**完全不需要改**。

```bash
# 1. 装驱动
pip install psycopg2-binary
# 2. 导出旧数据
sqlite3 instance/app.db .dump > backup.sql
# 3. 导入
psql -d mydb -f backup.sql
# 4. 改 .env 并重启
```

## 6. 接 Sentry / 其它监控

```python
# app.py 顶部
import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration

sentry_sdk.init(dsn=os.environ.get("SENTRY_DSN"), integrations=[FlaskIntegration()])
```

放在 `create_app()` 之前即可。

## 7. 单元测试样例

```python
# tests/test_pdf_merge.py
import io
from app import create_app

def test_pdf_merge_anonymous_limit():
    app = create_app({"TESTING": True, "RATELIMIT_TOOL": "1000/minute"})
    client = app.test_client()
    # 上传 2 个 PDF，跑 4 次（>3 触发限制）
    for i in range(4):
        r = client.post("/tools/pdf-merge/process", data={
            "csrf_token": _get_csrf(client),
            "pdfs": [io.BytesIO(b"%PDF-..."), io.BytesIO(b"%PDF-...")],
        }, content_type="multipart/form-data")
        assert r.status_code in (200, 429)
```

## 8. 风格 / Lint

```bash
ruff check .
black .
```

建议在 `requirements-dev.txt` 里加 `ruff`、`black`。
