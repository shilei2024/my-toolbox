"""Regex tester — test patterns against text, show matches and groups."""
from __future__ import annotations

import re

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("regex_tester", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "regex_tester", "name": "正则测试器", "icon": "bi-code-square", "color": "#6f42c1"},
        remaining=remaining_for("regex_tester"),
        body_template="tools/regex_tester/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("regex_tester")
def process():
    pattern = request.form.get("pattern", "")
    text = request.form.get("text", "")
    flags_str = request.form.get("flags", "")

    if not pattern:
        return jsonify(error="请输入正则表达式"), 400
    if not text:
        return jsonify(error="请输入测试文本"), 400

    flags = 0
    if "i" in flags_str:
        flags |= re.IGNORECASE
    if "m" in flags_str:
        flags |= re.MULTILINE
    if "s" in flags_str:
        flags |= re.DOTALL

    try:
        compiled = re.compile(pattern, flags)
        matches = list(compiled.finditer(text))
        results = []
        for m in matches:
            results.append({
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "groups": list(m.groups()),
            })
        commit_usage("regex_tester", success=True)
        return jsonify(
            ok=True,
            count=len(results),
            matches=results[:200],
            highlighted=_highlight(text, matches[:200]),
        )
    except re.error as e:
        commit_usage("regex_tester", success=False, message=str(e))
        return jsonify(error=f"正则表达式错误：{e}"), 400


def _highlight(text: str, matches: list) -> str:
    if not matches:
        return text
    parts = []
    last = 0
    for m in matches:
        parts.append(text[last:m.start()])
        parts.append(f"【{text[m.start():m.end()]}】")
        last = m.end()
    parts.append(text[last:])
    return "".join(parts)
