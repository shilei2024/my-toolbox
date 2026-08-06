"""
Application configuration.

Loaded from environment variables via python-dotenv. Anything that varies
between dev / prod / different hosts should live here, not in code.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _strip_prisma_pool_params(url: str) -> str:
    """Remove Prisma-pooler-only query parameters libpq/psycopg2 rejects.

    Vercel Prisma Postgres pooled URLs carry ``uselibpqcompat=true`` (and
    sometimes ``pgbouncer=true``) for Prisma clients; psycopg2 fails the DSN
    with ``invalid URI query parameter`` before any network connection.
    """
    if "?" not in url:
        return url
    base, _, query = url.partition("?")
    kept = [
        part
        for part in query.split("&")
        if part and part.split("=", 1)[0].lower() not in {"uselibpqcompat", "pgbouncer"}
    ]
    return base if not kept else f"{base}?{'&'.join(kept)}"


def _auto_db_url() -> str:
    """Auto-detect external database (Vercel Postgres) or default to SQLite.

    Priority:
      1. POSTGRES_URL_NON_POOLING  — Vercel Postgres direct (best for SQLAlchemy)
      2. POSTGRES_URL              — Vercel Postgres pooled (fallback)
      3. DATABASE_URL              — explicit override by user (for non-Vercel envs)
      4. sqlite:///app.db          — local default

    Prisma-pooler-only values are rejected: ``prisma://`` URLs have no
    SQLAlchemy dialect and pooled URLs may carry ``uselibpqcompat`` /
    ``pgbouncer`` query parameters that psycopg2 refuses to parse.
    """
    for candidate in (
        os.environ.get("POSTGRES_URL_NON_POOLING", ""),
        os.environ.get("POSTGRES_URL", ""),
        os.environ.get("DATABASE_URL", ""),
    ):
        if not candidate:
            continue
        # SQLAlchemy 2.x requires postgresql:// not postgres://
        normalized = _strip_prisma_pool_params(
            candidate.replace("postgres://", "postgresql://")
        )
        if normalized.startswith(("postgres://", "postgresql://")):
            return normalized
    return "sqlite:///app.db"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def engine_options_for(database_url: str) -> dict:
    """SQLAlchemy engine options for a detected database URL.

    PostgreSQL gets a short connect timeout so a dead or paused database
    fails fast at cold start instead of hanging the whole Vercel function.
    """
    options = {"pool_pre_ping": True}
    if database_url.startswith(("postgres://", "postgresql://")):
        options["connect_args"] = {"connect_timeout": 5}
    return options


class Config:
    # --- Flask ---
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SESSION_COOKIE_NAME = "mytoolbox_session"
    SESSION_COOKIE_DOMAIN: str | None = os.environ.get("SESSION_COOKIE_DOMAIN") or None
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Cookies must be secure in production (HTTPS). Override via env if serving plain HTTP locally.
    SESSION_COOKIE_SECURE: bool = _bool(os.environ.get("SESSION_COOKIE_SECURE"), default=False)
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # --- Database ---
    # Detects Vercel Postgres (POSTGRES_URL_*) automatically.
    # Default is relative to Flask's instance/ directory.
    SQLALCHEMY_DATABASE_URI: str = _auto_db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: dict = engine_options_for(_auto_db_url())

    # --- Bootstrap admin ---
    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")

    # --- App-wide limits ---
    DAILY_FREE_LIMIT: int = int(os.environ.get("DAILY_FREE_LIMIT", "10"))
    ANON_FREE_LIMIT: int = int(os.environ.get("ANON_FREE_LIMIT", "3"))
    MAX_UPLOAD_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "25"))
    MAX_CONTENT_LENGTH: int = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    TEMP_FILE_TTL_MINUTES: int = int(os.environ.get("TEMP_FILE_TTL_MINUTES", "30"))

    # --- Rate limit ---
    RATELIMIT_DEFAULT: str = os.environ.get("RATELIMIT_DEFAULT", "120/minute")
    RATELIMIT_TOOL: str = os.environ.get("RATELIMIT_TOOL", "20/minute")
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Misc ---
    APP_BASE_URL: str = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    APP_VERSION: str = os.environ.get("APP_VERSION", "0.4.3")
    DISPLAY_TIMEZONE: str = os.environ.get("DISPLAY_TIMEZONE", "Asia/Shanghai")
    SITE_NAME: str = os.environ.get("SITE_NAME", "Mavis 在线工具箱")
    SITE_TAGLINE: str = os.environ.get(
        "SITE_TAGLINE", "把常用的小工具放在一个干净的网页里，随时用，随时走。"
    )

    # --- Gallery BFF bridge ---
    # Shared only between Flask and the Next.js server. Never expose to browsers.
    GALLERY_INTROSPECTION_SECRET: str = os.environ.get("GALLERY_INTROSPECTION_SECRET", "")
    # Optional public HTTPS entry to the independently deployed Gallery Web.
    # Keeping this environment-specific avoids committing Preview/Production URLs.
    AI_IMAGE_EXTERNAL_URL: str = os.environ.get("AI_IMAGE_EXTERNAL_URL", "").strip()

    # --- Gallery admin bridge (Flask admin -> Generation Service) ---
    # Same contract the Next.js BFF uses: a public HTTPS API origin plus the
    # shared HMAC secret that signs the internal admin viewer context.
    GALLERY_SERVICE_BASE_URL: str = os.environ.get("GALLERY_SERVICE_BASE_URL", "").strip()
    GALLERY_INTERNAL_HMAC_SECRET: str = os.environ.get("GALLERY_INTERNAL_HMAC_SECRET", "")

    # --- Paths ---
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    INSTANCE_DIR: Path = BASE_DIR / "instance"
    TOOLS_CONFIG_PATH: Path = BASE_DIR / "tools_config.yaml"

    # --- CSRF / uploads ---
    WTF_CSRF_TIME_LIMIT = 60 * 60 * 8  # 8h
    ALLOWED_PDF_EXT = {"pdf"}
    ALLOWED_IMAGE_EXT = {"png", "jpg", "jpeg", "webp", "gif"}


class DevConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProdConfig(Config):
    DEBUG = False


def get_config() -> type[Config]:
    env = os.environ.get("FLASK_ENV", "production").lower()
    return DevConfig if env in {"development", "dev"} else ProdConfig
