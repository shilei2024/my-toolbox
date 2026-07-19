"""JSON formatter / validator — beautify, compress, or validate JSON."""
from __future__ import annotations

import json

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("json_formatter", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "json_formatter", "name": "JSON 格式化", "icon": "bi-braces", "color": "#6f42c1"},
        remaining=remaining_for("json_formatter"),
        body_template="tools/json_formatter/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("json_formatter")
def process():
    raw = request.form.get("text", "").strip()
    action = request.form.get("action", "format")
    if not raw:
        commit_usage("json_formatter", success=False, message="输入为空")
        return jsonify(error="请输入 JSON 文本"), 400

    try:
        parsed = json.loads(raw)
        if action == "format":
            result = json.dumps(parsed, ensure_ascii=False, indent=2)
        elif action == "compress":
            result = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        else:
            result = json.dumps(parsed, ensure_ascii=False, indent=2)
        commit_usage("json_formatter", success=True)
        return jsonify(ok=True, result=result)
    except json.JSONDecodeError as e:
        commit_usage("json_formatter", success=False, message=str(e))
        return jsonify(error=f"JSON 格式错误：{e}"), 400
