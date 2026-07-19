"""URL encoder / decoder."""
from __future__ import annotations

from urllib.parse import quote, unquote

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("url_codec", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "url_codec", "name": "URL 编解码", "icon": "bi-link-45deg", "color": "#fd7e14"},
        remaining=remaining_for("url_codec"),
        body_template="tools/url_codec/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "20/minute")
@require_usage("url_codec")
def process():
    action = request.form.get("action", "encode")
    raw = request.form.get("text", "").strip()
    if not raw:
        commit_usage("url_codec", success=False, message="输入为空")
        return jsonify(error="请输入文本"), 400

    try:
        if action == "encode":
            result = quote(raw, safe="")
        else:
            result = unquote(raw)
        commit_usage("url_codec", success=True)
        return jsonify(ok=True, result=result)
    except Exception as e:
        commit_usage("url_codec", success=False, message=str(e))
        return jsonify(error=f"处理失败：{e}"), 400
