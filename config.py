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


def _auto_db_url() -> str:
    """Auto-detect external database (Vercel Postgres) or default to SQLite.

    Priority:
      1. DATABASE_URL   — explicit override by the user
      2. POSTGRES_URL_NON_POOLING  — Vercel Postgres (recommended for SQLAlchemy)
      3. POSTGRES_URL   — Vercel Postgres fallback (includes pgbouncer)
      4. sqlite:///app.db  — local default
    """
    explicit = os.environ.get("DATABASE_URL")
    if explicit:
        return explicit
    vercel = os.environ.get("POSTGRES_URL_NON_POOLING") or os.environ.get("POSTGRES_URL")
    if vercel:
        return vercel
    return "sqlite:///app.db"


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # --- Flask ---
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SESSION_COOKIE_NAME = "mytoolbox_session"
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
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Bootstrap admin ---
    ADMIN_EMAIL: str = os.environ.get("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD: str = os.environ.get("ADMIN_PASSWORD", "ChangeMe123!")

    # --- App-wide limits ---
    DAILY_FREE_LIMIT: int = int(os.environ.get("DAILY_FREE_LIMIT", "10"))
    ANON_FREE_LIMIT: int = int(os.environ.get("ANON_FREE_LIMIT", "3"))
    MAX_UPLOAD_MB: int = int(os.environ.get("MAX_UPLOAD_MB", "25"))
    MAX_CONTENT_LENGTH: int = int(os.environ.get("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    TEMP_FILE_TTL_MINUTES: int = int(os.environ.get("TEMP_FILE_TTL_MINUTES", "30"))

    # --- AI provider ---
    # Default to "pollinations" — a free, no-API-key image generation service.
    # Admin can switch to openai/siliconflow/mock from the settings page.
    AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "pollinations")
    AI_API_KEY: str = os.environ.get("AI_API_KEY", "")
    AI_BASE_URL: str = os.environ.get("AI_BASE_URL", "https://image.pollinations.ai")
    AI_MODEL: str = os.environ.get("AI_MODEL", "")

    # --- Rate limit ---
    RATELIMIT_DEFAULT: str = os.environ.get("RATELIMIT_DEFAULT", "120/minute")
    RATELIMIT_TOOL: str = os.environ.get("RATELIMIT_TOOL", "20/minute")
    RATELIMIT_STORAGE_URI: str = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

    # --- Misc ---
    APP_BASE_URL: str = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    DISPLAY_TIMEZONE: str = os.environ.get("DISPLAY_TIMEZONE", "Asia/Shanghai")
    SITE_NAME: str = os.environ.get("SITE_NAME", "Mavis 在线工具箱")
    SITE_TAGLINE: str = os.environ.get(
        "SITE_TAGLINE", "把常用的小工具放在一个干净的网页里，随时用，随时走。"
    )

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
