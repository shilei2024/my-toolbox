"""admin blueprint package."""
from __future__ import annotations

from flask import Blueprint

admin_bp = Blueprint(
    "admin",
    __name__,
    url_prefix="/admin",
    template_folder="../templates",
)

# import routes so the views register on the blueprint
from . import routes  # noqa: E402,F401
