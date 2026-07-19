"""SQL formatter / beautifier."""
from __future__ import annotations

import sqlparse

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("sql_formatter", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "sql_formatter", "name": "SQL 格式化", "icon": "bi-database", "color": "#0d6efd"},
        remaining=remaining_for("sql_formatter"),
        body_template="tools/sql_formatter/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("sql_formatter")
def process():
    sql = request.form.get("sql", "").strip()
    action = request.form.get("action", "format")
    if not sql:
        return jsonify(error="请输入 SQL 语句"), 400

    try:
        if action == "format":
            result = sqlparse.format(
                sql,
                reindent=True,
                keyword_case="upper",
                identifier_case="lower",
                strip_comments=False,
            )
        elif action == "compress":
            result = sqlparse.format(sql, strip_whitespace=True, strip_comments=True)
        else:
            result = sqlparse.format(sql, reindent=True)

        # Also validate by parsing
        parsed = sqlparse.parse(sql)
        stmt_count = len(parsed)

        commit_usage("sql_formatter", success=True)
        return jsonify(ok=True, result=result, statements=stmt_count)
    except Exception as e:
        commit_usage("sql_formatter", success=False, message=str(e))
        return jsonify(error=f"处理失败：{e}"), 500
