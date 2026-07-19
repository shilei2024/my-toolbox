"""Markdown previewer — render Markdown to HTML in real time."""
from __future__ import annotations

import markdown as md_lib

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("markdown_preview", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "markdown_preview", "name": "Markdown 预览", "icon": "bi-markdown", "color": "#6f42c1"},
        remaining=remaining_for("markdown_preview"),
        body_template="tools/markdown_preview/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("markdown_preview")
def process():
    text = request.form.get("text", "")
    if not text.strip():
        return jsonify(error="请输入 Markdown 文本"), 400

    try:
        html = md_lib.markdown(
            text,
            extensions=["extra", "codehilite", "toc", "tables", "fenced_code"],
            extension_configs={"codehilite": {"css_class": "highlight"}},
        )
        commit_usage("markdown_preview", success=True)
        return jsonify(ok=True, html=html)
    except Exception as e:
        commit_usage("markdown_preview", success=False, message=str(e))
        return jsonify(error=f"渲染失败：{e}"), 500
