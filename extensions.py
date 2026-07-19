"""
Shared extension singletons.

Kept in a separate module so blueprints / models can import them without
triggering circular imports through the app factory.
"""
from __future__ import annotations

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base)
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["120 per minute"])

login_manager.login_view = "auth.login"
login_manager.login_message = "请先登录后再使用此功能。"
login_manager.login_message_category = "warning"
