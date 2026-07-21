"""PDF 压缩 — 减小 PDF 文件大小，可调压缩等级，预览前后体积变化。"""
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
tool_bp = Blueprint("pdf_compress", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "pdf_compress", "name": "PDF 压缩", "icon": "bi-file-earmark-zip", "color": "#0d6efd"},
        remaining=remaining_for("pdf_compress"),
        body_template="tools/pdf_compress/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_compress")
def process():
    file = request.files.get("pdf")
    if file is None or not file.filename:
        commit_usage("pdf_compress", success=False, message="未选择文件")
        return jsonify(error="请选择一个 PDF 文件"), 400
    if not is_allowed_ext(file.filename, {"pdf"}):
        return jsonify(error="只能上传 PDF 文件"), 400

    try:
        level = request.form.get("level", "medium")
    except Exception:
        level = "medium"

    # 读取原始大小
    raw_bytes = file.read()
    original_size = len(raw_bytes)

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except Exception as exc:
        commit_usage("pdf_compress", success=False, message=str(exc))
        return jsonify(error=f"PDF 解析失败：{exc}"), 400

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            return jsonify(error="PDF 已加密，请先解除密码再压缩。"), 400

    try:
        writer = PdfWriter()
        for page in reader.pages:
            writer.add_page(page)

        # 压缩内容流
        for page in writer.pages:
            page.compress_content_streams()

        # 激进模式：去元数据 + 去重复对象
        if level == "aggressive":
            # remove metadata
            writer.add_metadata({})
            reader_info = reader.metadata
            if reader_info:
                try:
                    writer.add_metadata(reader_info)
                except Exception:
                    pass

        # 输出
        out = io.BytesIO()
        writer.write(out)
        out.seek(0)
        compressed_data = out.getvalue()
        compressed_size = len(compressed_data)

        saved = original_size - compressed_size
        saved_pct = round(saved / original_size * 100, 1) if original_size > 0 else 0

        filename = safe_filename("compressed.pdf")
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / filename).write_bytes(compressed_data)

        commit_usage("pdf_compress", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/pdf-compress/download/{filename}",
            filename=filename,
            size=compressed_size,
            original_size=original_size,
            saved=saved,
            saved_pct=saved_pct,
            mime="application/pdf",
        )
    except Exception as exc:
        logger.exception("pdf_compress failed: %s", exc)
        commit_usage("pdf_compress", success=False, message=str(exc))
        return jsonify(error=f"压缩失败：{exc}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
