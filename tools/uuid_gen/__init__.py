"""UUID generator — generate UUIDs in bulk, one-click copy."""
from __future__ import annotations

import uuid

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("uuid_gen", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "uuid_gen", "name": "UUID 生成器", "icon": "bi-fingerprint", "color": "#6610f2"},
        remaining=remaining_for("uuid_gen"),
        body_template="tools/uuid_gen/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("uuid_gen")
def process():
    try:
        count = min(500, max(1, int(request.form.get("count", 1))))
        version = request.form.get("version", "4")
        uppercase = request.form.get("uppercase") == "1"

        uuids = []
        for _ in range(count):
            if version == "1":
                u = str(uuid.uuid1())
            else:
                u = str(uuid.uuid4())
            if uppercase:
                u = u.upper()
            uuids.append(u)

        commit_usage("uuid_gen", success=True)
        return jsonify(ok=True, uuids=uuids, count=len(uuids))
    except (ValueError, TypeError) as e:
        commit_usage("uuid_gen", success=False, message=str(e))
        return jsonify(error=f"生成失败：{e}"), 400
