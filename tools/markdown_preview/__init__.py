"""Markdown previewer — render Markdown to HTML in real time."""
from __future__ import annotations

import bleach
import markdown as md_lib

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("markdown_preview", __name__)

# Only safe inline/block HTML is allowed through. Python-Markdown preserves
# raw HTML by default (e.g. <script>, <img onerror>), so the rendered HTML
# must be sanitized before it reaches the browser via innerHTML.
_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "code", "del", "em", "h1", "h2", "h3",
    "h4", "h5", "h6", "hr", "i", "img", "kbd", "li", "ol", "p", "pre", "s",
    "span", "strong", "sub", "sup", "table", "tbody", "td", "th", "thead", "tr",
    "ul", "caption", "col", "colgroup", "dl", "dt", "dd",
}
_ALLOWED_ATTRS = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"align", "colspan", "rowspan"},
    "th": {"align", "colspan", "rowspan"},
    "table": {"align"},
    "*": {"class", "id"},
}
_ALLOWED_PROTOCOLS = {"http", "https", "mailto", "tel"}


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
        # Sanitize: strip scripts, event handlers, javascript: URLs and any
        # other active content before the frontend injects it with innerHTML.
        # Inline style attributes are stripped entirely (no style allowlist).
        html = bleach.clean(
            html,
            tags=_ALLOWED_TAGS,
            attributes=_ALLOWED_ATTRS,
            protocols=_ALLOWED_PROTOCOLS,
            strip=True,
        )
        commit_usage("markdown_preview", success=True)
        return jsonify(ok=True, html=html)
    except Exception as e:
        commit_usage("markdown_preview", success=False, message=str(e))
        return jsonify(error=f"渲染失败：{e}"), 500
