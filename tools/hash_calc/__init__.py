"""Hash calculator — MD5 / SHA1 / SHA256 / SHA512 for text or file."""
from __future__ import annotations

import hashlib

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("hash_calc", __name__)

_ALGOS = {
    "md5": hashlib.md5,
    "sha1": hashlib.sha1,
    "sha256": hashlib.sha256,
    "sha512": hashlib.sha512,
}


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "hash_calc", "name": "哈希计算", "icon": "bi-hash", "color": "#fd7e14"},
        remaining=remaining_for("hash_calc"),
        body_template="tools/hash_calc/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "20/minute")
@require_usage("hash_calc")
def process():
    algo = request.form.get("algo", "sha256").lower()
    if algo not in _ALGOS:
        return jsonify(error=f"不支持的算法：{algo}"), 400

    file = request.files.get("file")
    text = request.form.get("text", "")

    try:
        h = _ALGOS[algo]()
        if file and file.filename:
            while True:
                chunk = file.stream.read(8192)
                if not chunk:
                    break
                h.update(chunk)
            source = f"文件: {file.filename}"
        elif text:
            h.update(text.encode("utf-8"))
            source = f"文本 ({len(text)} 字符)"
        else:
            return jsonify(error="请输入文本或上传文件"), 400

        result = h.hexdigest()
        commit_usage("hash_calc", success=True)
        return jsonify(ok=True, result=result, algo=algo.upper(), source=source)
    except Exception as e:
        commit_usage("hash_calc", success=False, message=str(e))
        return jsonify(error=f"计算失败：{e}"), 500
