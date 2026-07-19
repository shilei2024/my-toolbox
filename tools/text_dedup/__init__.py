"""Text deduplication — remove duplicate lines, sort, count."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("text_dedup", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "text_dedup", "name": "文本去重", "icon": "bi-funnel", "color": "#198754"},
        remaining=remaining_for("text_dedup"),
        body_template="tools/text_dedup/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("text_dedup")
def process():
    text = request.form.get("text", "")
    if not text.strip():
        return jsonify(error="请输入文本"), 400

    trim = request.form.get("trim") == "1"
    ignore_case = request.form.get("ignore_case") == "1"
    sort_output = request.form.get("sort") == "1"
    keep_empty = request.form.get("keep_empty") == "1"

    lines = text.split("\n")
    original_count = len(lines)

    seen = set()
    result = []
    for line in lines:
        key = line
        if trim:
            key = line.strip()
        if ignore_case:
            key = key.lower()
        if not keep_empty and key == "":
            continue
        if key not in seen:
            seen.add(key)
            result.append(line)

    if sort_output:
        result.sort()

    commit_usage("text_dedup", success=True)
    return jsonify(
        ok=True,
        result="\n".join(result),
        original_count=original_count,
        unique_count=len(result),
        removed=original_count - len(result),
    )
