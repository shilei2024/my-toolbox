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
import traceback
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
from config import get_config
from extensions import csrf, db, limiter, login_manager
from models import Setting, User
from tools import list_enabled_tools, register_tools, sync_tool_registry
from utils.helpers import get_client_ip, utc_today_str

_ON_VERCEL = os.environ.get("VERCEL", "").strip() == "1"
_is_readonly_fs = False  # set True at runtime if mkdir fails (e.g. Vercel)


def create_app() -> Flask:
    global _is_readonly_fs
    _log = lambda msg: print(f"[my-toolbox] {msg}", file=sys.stderr, flush=True)

    _log(f"Bootstrap start (VERCEL={_ON_VERCEL}, py={sys.version.split()[0]})")

    try:
        _log("Step 1/8: Flask(__name__)...")
        app = Flask(__name__)
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
        # Only switch to in-memory SQLite if no external DB env var is set.
        # Vercel Postgres URLs use "postgres://" (not "postgresql://"), so we
        # detect via env var presence rather than URL substring matching.
        _has_external_db = bool(
            os.environ.get("POSTGRES_URL_NON_POOLING")
            or os.environ.get("POSTGRES_URL")
        )
        if not _has_external_db:
            app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
            _log("  DB: in-memory SQLite (no Vercel Postgres detected)")
        else:
            _log("  DB: Vercel Postgres (external, persistent)")
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
        _log("  FATAL")
        traceback.print_exc(file=sys.stderr)
        raise

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
    with app.app_context():
        db.create_all()

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
    tz_name = app.config.get("DISPLAY_TIMEZONE", "Asia/Shanghai")

    @app.context_processor
    def inject_globals():  # noqa: ANN202
        from auth.decorators import remaining_for
        from datetime import datetime

        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")

        def _remaining_for(tool_id: str) -> int:
            return remaining_for(tool_id)

        def _now() -> datetime:
            return datetime.now(tz)

        return {
            "site_name": app.config["SITE_NAME"],
            "site_tagline": app.config["SITE_TAGLINE"],
            "current_user": current_user,
            "is_admin": current_user.is_authenticated and getattr(current_user, "is_admin", False),
            "tz": tz,
            "remaining_for": _remaining_for,
            "now": _now,
        }


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
