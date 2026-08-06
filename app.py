"""
Application factory.

Run locally:
    python app.py

Run in production:
    gunicorn -w 2 -b 127.0.0.1:8000 'app:create_app()'

Vercel (auto-detected via VERCEL env var):
    - Uses /tmp for writable directories (uploads, instance)
    - Uses in-memory SQLite (ephemeral — data resets per cold start)
    - Skips APScheduler (background threads not supported in Serverless)
    - Sets env vars via Vercel Dashboard (not .env file)
"""
from __future__ import annotations

import logging
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user

from admin import admin_bp
from auth.routes import auth_bp
from config import _auto_db_url, get_config
from extensions import csrf, db, limiter, login_manager
from models import Setting, User
from tools import list_enabled_tools, register_tools, sync_tool_registry
from utils.gallery_cors import apply_gallery_cors
from utils.helpers import china_now, get_client_ip, to_china_time, utc_today_str
from utils.settings import apply_runtime_settings

_ON_VERCEL = os.environ.get("VERCEL", "").strip() == "1"
_is_readonly_fs = False  # set True at runtime if mkdir fails (e.g. Vercel)


def _has_external_database() -> bool:
    """True when an external Postgres URL is configured for this process.

    Vercel Postgres is injected as POSTGRES_URL_NON_POOLING / POSTGRES_URL;
    standalone deployments (e.g. Tencent Cloud PostgreSQL) use DATABASE_URL.
    Without any of these the read-only Vercel filesystem falls back to an
    empty in-memory SQLite, which makes every stored account disappear.
    Prisma-pooler-only URLs (``prisma://`` or ``uselibpqcompat``) are not
    usable by psycopg2 and are treated as missing so boot never crashes on
    an unparseable DSN.
    """
    return _auto_db_url().startswith(("postgres://", "postgresql://"))


def create_app() -> Flask:
    global _is_readonly_fs
    _log = lambda msg: print(f"[my-toolbox] {msg}", file=sys.stderr, flush=True)

    _log(f"Bootstrap start (VERCEL={_ON_VERCEL}, py={sys.version.split()[0]})")

    try:
        _log("Step 1/8: Flask(__name__)...")
        app = Flask(__name__)
        # Accept both `/tools/x` and `/tools/x/` without a 308 redirect.
        # Vercel's serverless layer sometimes drops/mishandles the trailing-slash
        # redirect, which made tool pages unreachable when clicked from the homepage
        # (homepage links use `tool.route` without a trailing slash).
        app.url_map.strict_slashes = False
        _log(f"  ok, instance_path={app.instance_path}")
    except Exception:
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

    try:
        _log("Step 2/8: config.from_object...")
        app.config.from_object(get_config())
        _log("  ok")
    except Exception:
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

    # --- Writable directories: try project path first, fall back to /tmp ---
    try:
        _log("Step 3/8: ensure folders...")
        Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(app.config["INSTANCE_DIR"]).mkdir(parents=True, exist_ok=True)
        _log("  ok (project dirs)")
    except OSError:
        _log("  project dirs read-only, falling back to /tmp …")
        _tmp = Path(tempfile.gettempdir()) / "mytoolbox"
        app.config["UPLOAD_DIR"] = _tmp / "uploads"
        app.config["INSTANCE_DIR"] = _tmp / "instance"
        _is_readonly_fs = True
        _has_external_db = _has_external_database()
        if not _has_external_db:
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
            _log("  DB: in-memory SQLite (no external Postgres detected)")
        else:
            _log("  DB: external Postgres (persistent)")
        # These MUST succeed — /tmp is always writable
        Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
        Path(app.config["INSTANCE_DIR"]).mkdir(parents=True, exist_ok=True)
        _log("  ok (/tmp fallback, DB=in-memory)")


    try:
        _log("Step 4/8: _setup_logging...")
        _setup_logging(app)
        _log("  ok")
    except Exception:
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

    try:
        _log("Step 5/8: _init_extensions (db, login, csrf, limiter)...")
        _init_extensions(app)
        _log("  ok")
    except Exception:
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

    try:
        _log("Step 6/8: blueprints + error handlers + context + cli...")
        _register_blueprints(app)
        _register_error_handlers(app)
        _register_context(app)
        apply_gallery_cors(app)
        _register_cli(app)
        _log("  ok")
    except Exception:
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

    try:
        _log("Step 7/8: seed_admin + sync_tools + register_tools...")
        _seed_admin(app)
        sync_tool_registry(app)
        register_tools(app)
        _log("  ok")
    except Exception:
        _log("  WARN: boot DB/tool init failed; continuing so the function can serve requests")
        traceback.print_exc(file=sys.stderr)
        app.config["_BOOT_DB_FAILED"] = True

    # background cleanup (skipped on read-only filesystem — no threads in Serverless)
    if not _is_readonly_fs:
        from utils.cleanup import schedule_cleanup
        scheduler = schedule_cleanup(app)
        scheduler.start()
    else:
        _log("Step 8/8: APScheduler skipped (read-only fs)")
        _log(f"Bootstrap COMPLETE — {len(list(app.url_map.iter_rules()))} routes")

    @app.get("/healthz")
    def healthz():
        return jsonify(status="ok", time=utc_today_str())

    @app.get("/diag")
    def diag():
        """Deployment diagnostics — reveals why tool pages may not load.

        Public (no auth) so it can be checked on Vercel without logging in.
        Reports Python version, how many tools registered vs failed to import,
        and the exact import error for each failed tool.
        """
        import platform
        diag = app.config.get("TOOL_DIAG", {})
        tool_routes = sorted(
            {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/tools/")}
        )
        return jsonify(
            python_version=platform.python_version(),
            sys_version=sys.version.split()[0],
            on_vercel=_ON_VERCEL,
            readonly_fs=_is_readonly_fs,
            db_uri_head=str(app.config["SQLALCHEMY_DATABASE_URI"])[:60],
            yaml_tool_count=diag.get("yaml_count"),
            registered_count=len(diag.get("registered", [])),
            failed_count=len(diag.get("failed", {})),
            failed=diag.get("failed", {}),
            tool_route_count=len(tool_routes),
            tool_routes=tool_routes,
        )

    @app.get("/api/exchange-rate")
    def exchange_rate():
        """Return exchange rate for any pair, defaults to USD→CNY.

        Query params:
            from  — base currency (default USD)
            to    — target currency (default CNY)

        Uses open.er-api.com (free, no key).  All rates are USD-based;
        cross pairs are calculated from the cached USD rates object.
        Cached 10 minutes; stale-while-revalidate on upstream failure.
        """
        from_cur = (request.args.get("from", "") or "USD").upper().strip()
        to_cur = (request.args.get("to", "") or "CNY").upper().strip()
        # valid currency codes are 3 letters
        if len(from_cur) != 3 or len(to_cur) != 3:
            return jsonify(error="Invalid currency code"), 400

        def _calc(rates: dict, frm: str, to: str):
            if frm == to:
                return 1.0
            if frm not in rates or to not in rates:
                return None
            return round(rates[to] / rates[frm], 6)

        cache = getattr(app, "_fx_cache", None)
        if cache is None:
            cache = {"rates": {}, "updated": None, "ts": 0}
            app._fx_cache = cache

        now = time.time()
        # cache hit
        if cache["rates"] and (now - cache["ts"]) < 600:
            rate = _calc(cache["rates"], from_cur, to_cur)
            if rate is not None:
                return jsonify(rate=rate, from_cur=from_cur, to_cur=to_cur,
                               updated=cache["updated"], cached=True)

        import requests  # noqa: PLC0415

        try:
            # open.er-api.com gives full rates vs USD with 6 decimal precision
            resp = requests.get("https://open.er-api.com/v6/latest/USD", timeout=5)
            if resp.status_code >= 400:
                raise RuntimeError(f"HTTP {resp.status_code}")
            data = resp.json()
            if data.get("result") != "success":
                raise RuntimeError("API returned non-success")
            cache["rates"] = data["rates"]  # {"USD":1, "CNY":6.7653, ...}
            cache["updated"] = data.get("time_last_update_utc", "")
            cache["ts"] = now
            rate = _calc(cache["rates"], from_cur, to_cur)
            if rate is None:
                return jsonify(error=f"不支持币种 {from_cur}/{to_cur}"), 400
            return jsonify(rate=rate, from_cur=from_cur, to_cur=to_cur,
                           updated=cache["updated"], cached=False)
        except Exception as exc:  # noqa: BLE001
            app.logger.warning("exchange-rate fetch failed: %s", exc)
            if cache["rates"]:
                rate = _calc(cache["rates"], from_cur, to_cur)
                if rate is not None:
                    return jsonify(rate=rate, from_cur=from_cur, to_cur=to_cur,
                                   updated=cache["updated"], cached=True, stale=True)
            return jsonify(error="汇率获取失败，请稍后再试"), 502

    @app.get("/")
    def home():
        # Group tools by category for the homepage. CATEGORY_META drives the
        # section title / icon / color; categories not listed here fall back
        # to a generic "其他工具" bucket so new tools always have a home.
        CATEGORY_META = {
            "pdf": {"title": "PDF 文件操作", "icon": "bi-file-earmark-pdf", "color": "#dc3545", "order": 1},
            "image": {"title": "图片功能", "icon": "bi-image", "color": "#fd7e14", "order": 2},
            "business": {"title": "业务工具", "icon": "bi-briefcase", "color": "#0d6efd", "order": 3},
            "developer": {"title": "开发工具", "icon": "bi-code-slash", "color": "#6f42c1", "order": 4},
            "text": {"title": "文本工具", "icon": "bi-file-text", "color": "#20c997", "order": 5},
            "other": {"title": "其他工具", "icon": "bi-grid", "color": "#6c757d", "order": 99},
        }
        tools = list_enabled_tools()
        # bucket by category
        groups: dict[str, list] = {}
        for t in tools:
            groups.setdefault(t.category or "other", []).append(t)
        # sort categories by their meta order; unknown categories go last (alpha)
        def _cat_sort_key(cat: str) -> tuple[int, str]:
            meta = CATEGORY_META.get(cat)
            return (meta["order"] if meta else 100, cat)
        categories = sorted(groups.keys(), key=_cat_sort_key)
        return render_template(
            "index.html",
            tools=tools,
            groups=groups,
            categories=categories,
            category_meta=CATEGORY_META,
        )

    @app.get("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.get("/terms")
    def terms():
        return render_template("terms.html")

    return app


# -----------------------------------------------------------------------------
# internals
# -----------------------------------------------------------------------------
def _setup_logging(app: Flask) -> None:
    level = logging.DEBUG if app.config.get("DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _ensure_tool_external_url_column(app: Flask) -> None:
    """Lightweight migration: `db.create_all()` never alters existing tables,
    so add the `tools.external_url` column on databases created before the
    AI 作图 external-entry change (SQLite only; idempotent)."""
    from sqlalchemy import inspect as sa_inspect, text  # noqa: PLC0415

    try:
        insp = sa_inspect(db.engine)
        if "tools" not in insp.get_table_names():
            return
        columns = {col["name"] for col in insp.get_columns("tools")}
        if "external_url" in columns:
            return
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE tools ADD COLUMN external_url VARCHAR(255) NOT NULL DEFAULT ''"))
        app.logger.info("Migrated tools table: added external_url column")
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("tools.external_url migration skipped: %s", exc)


def _init_extensions(app: Flask) -> None:
    # Resolve SQLite path to the app's instance_path if user didn't override.
    # Skip for in-memory DB (used on Vercel / read-only FS), absolute paths,
    # and when VERCEL env var is detected.
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if (
        uri.startswith("sqlite:///")
        and not uri.startswith("sqlite:////")
        and not _ON_VERCEL
        and not _is_readonly_fs
        and ":memory:" not in uri
    ):
        # relative path -> anchor on instance_path
        rel = uri[len("sqlite:///"):]
        target = Path(app.instance_path) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{target.as_posix()}"

    db.init_app(app)
    try:
        with app.app_context():
            db.create_all()
            _ensure_tool_external_url_column(app)
            apply_runtime_settings(app)
    except Exception:
        app.logger.warning(
            "Database unavailable at boot; continuing without schema/runtime settings",
            exc_info=True,
        )
        app.config["_BOOT_DB_FAILED"] = True

    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):  # noqa: ANN001
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    csrf.init_app(app)
    limiter.init_app(app)

    # ensure an anon_id is set on every request
    @app.before_request
    def _ensure_anon_id():  # noqa: ANN202
        from auth.decorators import ensure_anon_id

        # Keep all workers in sync with settings saved from the admin panel.
        apply_runtime_settings(app)
        g.anon_id = ensure_anon_id()


def _register_blueprints(app: Flask) -> None:
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(400)
    def bad_request(err):
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error="请求格式不正确"), 400
        return render_template("errors/400.html"), 400

    @app.errorhandler(403)
    def forbidden(err):
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error="没有权限"), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(err):
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error="页面不存在"), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(err):
        msg = f"文件太大，单文件最大 {app.config['MAX_UPLOAD_MB']} MB"
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error=msg), 413
        return make_response(render_template("errors/413.html", limit_mb=app.config["MAX_UPLOAD_MB"]), 413)

    @app.errorhandler(429)
    def too_many(err):
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error="请求过于频繁，请稍后再试"), 429
        return render_template("errors/429.html"), 429

    @app.errorhandler(500)
    def server_error(err):
        app.logger.exception("Unhandled error: %s", err)
        if request.accept_mimetypes.best == "application/json" or request.is_json:
            return jsonify(error="服务器内部错误"), 500
        return render_template("errors/500.html"), 500


def _register_context(app: Flask) -> None:
    @app.template_filter("china_time")
    def china_time_filter(value, fmt: str = "%Y-%m-%d %H:%M:%S"):  # noqa: ANN001
        local = to_china_time(value)
        return local.strftime(fmt) if local else "—"

    @app.context_processor
    def inject_globals():  # noqa: ANN202
        from auth.decorators import remaining_for

        def _remaining_for(tool_id: str) -> int:
            return remaining_for(tool_id)

        return {
            "site_name": app.config["SITE_NAME"],
            "site_tagline": app.config["SITE_TAGLINE"],
            "current_user": current_user,
            "is_admin": current_user.is_authenticated and getattr(current_user, "is_admin", False),
            "remaining_for": _remaining_for,
            "now": china_now,
        }

    @app.after_request
    def _no_store_private_pages(response):
        """Never cache authenticated or admin pages (stale CSRF tokens break forms)."""
        if current_user.is_authenticated or (request.endpoint or "").startswith("admin."):
            response.headers["Cache-Control"] = "private, no-store, max-age=0"
            response.headers["Vary"] = "Cookie"
        return response


def _register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    def create_admin():  # noqa: ANN202
        """Create the bootstrap admin from env vars if missing."""
        with app.app_context():
            _seed_admin(app, force=False)
            print("admin check done")

    @app.cli.command("list-tools")
    def list_tools_cmd():  # noqa: ANN202
        with app.app_context():
            for t in list_enabled_tools():
                print(f"- {t.id:15s} {t.name:20s} {t.route} (enabled={t.enabled})")

    @app.cli.command("check-gallery-integration")
    def check_gallery_integration_cmd():  # noqa: ANN202
        """Validate bridge settings without printing any secret values."""
        from utils.integration_check import gallery_integration_checks

        checks = gallery_integration_checks(app)
        for check in checks:
            print(f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.message}")
        if not all(check.ok for check in checks):
            raise SystemExit(1)


def _seed_admin(app: Flask, force: bool = False) -> None:
    """Idempotently create the bootstrap admin."""
    with app.app_context():
        email = app.config["ADMIN_EMAIL"]
        password = app.config["ADMIN_PASSWORD"]
        existing = db.session.query(User).filter_by(email=email).one_or_none()
        if existing is not None:
            if force and not existing.is_admin:
                existing.is_admin = True
                db.session.commit()
            return
        if not email or not password:
            app.logger.warning("ADMIN_EMAIL / ADMIN_PASSWORD not set, skipping bootstrap admin")
            return
        admin = User(email=email, is_admin=True, is_active_user=True)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Bootstrap admin created: %s", email)


# Allow `gunicorn app:app`
app = create_app()


if __name__ == "__main__":
    import os
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_ENV", "production") in {"development", "dev"}
    app.run(host=host, port=port, debug=debug, use_reloader=False)
