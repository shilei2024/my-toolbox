"""PDF 解锁/加密 — 移除打开密码 / 添加密码保护。"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from pypdf import PdfReader, PdfWriter

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_download_path, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_protect", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "pdf_protect", "name": "PDF 解锁/加密", "icon": "bi-shield-lock", "color": "#6610f2"},
        remaining=remaining_for("pdf_protect"),
        body_template="tools/pdf_protect/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_protect")
def process():
    file = request.files.get("pdf")
    if file is None or not file.filename:
        commit_usage("pdf_protect", success=False, message="未选择文件")
        return jsonify(error="请选择一个 PDF 文件"), 400
    if not is_allowed_ext(file.filename, {"pdf"}):
        return jsonify(error="只能上传 PDF 文件"), 400

    mode = request.form.get("mode", "encrypt")
    password = (request.form.get("password") or "").strip()

    raw_bytes = file.read()

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except Exception as exc:
        commit_usage("pdf_protect", success=False, message=str(exc))
        return jsonify(error=f"PDF 解析失败：{exc}"), 400

    try:
        if mode == "encrypt":
            # 加密模式
            if not password:
                return jsonify(error="请输入密码"), 400
            if len(password) < 1 or len(password) > 128:
                return jsonify(error="密码长度应在 1-128 位之间"), 400

            writer = PdfWriter(clone_from=reader)
            writer.encrypt(password)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            data = out.getvalue()
            action_name = "加密"

        else:
            # 解密模式
            if not reader.is_encrypted:
                return jsonify(error="该 PDF 未加密，无需解锁"), 400

            if not password and reader.is_encrypted:
                # 尝试空密码
                try:
                    reader.decrypt("")
                except Exception:
                    return jsonify(error="PDF 已加密，请输入密码解锁"), 400

            if password:
                try:
                    result = reader.decrypt(password)
                    if result == 0:  # pypdf returns 0 on wrong password
                        return jsonify(error="密码错误，请重试"), 400
                except Exception as exc:
                    return jsonify(error=f"密码错误：{exc}"), 400

            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)
            out = io.BytesIO()
            writer.write(out)
            out.seek(0)
            data = out.getvalue()
            action_name = "解锁"

        filename = safe_filename(f"{action_name}d.pdf")
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / filename).write_bytes(data)

        commit_usage("pdf_protect", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/pdf-protect/download/{filename}",
            filename=filename,
            size=len(data),
            mime="application/pdf",
            action=action_name,
        )
    except Exception as exc:
        logger.exception("pdf_protect failed: %s", exc)
        commit_usage("pdf_protect", success=False, message=str(exc))
        return jsonify(error=f"处理失败：{exc}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
