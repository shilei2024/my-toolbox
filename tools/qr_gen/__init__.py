"""QR code generator."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

import qrcode
from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("qr_gen", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "qr_gen", "name": "二维码生成", "icon": "bi-qr-code", "color": "#198754"},
        remaining=remaining_for("qr_gen"),
        body_template="tools/qr_gen/_body.html",
        # _body.html 用 <form data-async="1" data-preview="image">，依赖 result.js
        # 拦截提交走 AJAX；不加载它的话点击按钮会整页 POST 到 /process 显示裸 JSON
        # → 页面丢失。
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("qr_gen")
def process():
    text = request.form.get("text", "").strip()
    if not text:
        commit_usage("qr_gen", success=False, message="输入为空")
        return jsonify(error="请输入要生成二维码的内容"), 400
    if len(text) > 2000:
        return jsonify(error="内容过长（最多 2000 字符）"), 400

    try:
        size = int(request.form.get("size", 10))
        size = max(1, min(40, size))
        border = int(request.form.get("border", 2))
        fg = request.form.get("fg", "#000000")
        bg = request.form.get("bg", "#ffffff")

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=size,
            border=border,
        )
        qr.add_data(text)
        qr.make(fit=True)
        img = qr.make_image(fill_color=fg, back_color=bg)

        filename = f"qr_{uuid.uuid4().hex[:8]}.png"
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / filename
        img.save(target)

        commit_usage("qr_gen", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/qr-gen/download/{filename}",
            filename=filename,
            size=target.stat().st_size,
            mime="image/png",
        )
    except Exception as e:
        commit_usage("qr_gen", success=False, message=str(e))
        return jsonify(error=f"生成失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    from utils.helpers import safe_download_path
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
