"""
PDF to Word tool.

Converts a PDF to an editable .docx using pdf2docx (which parses the PDF
layout into paragraphs / tables / images). The conversion writes to a
temp file, which we then stage into UPLOAD_DIR and return as JSON for
the result card. No-JS fallback streams the file directly.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from pypdf import PdfReader

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_to_word", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "pdf_to_word",
            "name": "PDF 转 Word",
            "icon": "bi-file-earmark-word",
            "color": "#0d6efd",
        },
        remaining=remaining_for("pdf_to_word"),
        body_template="tools/pdf_to_word/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_to_word")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    file = request.files.get("pdf")
    if file is None or not file.filename:
        return _fail("请选择一个 PDF 文件。", is_ajax)
    if not is_allowed_ext(file.filename, {"pdf"}):
        return _fail("只能上传 PDF 文件。", is_ajax)

    # Quick sanity check: can we open it?
    try:
        # Save uploaded PDF to a temp file because pdf2docx wants a path.
        tmp_pdf = None
        tmp_docx = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(file.read())
                tmp_pdf = tmp.name

            # Count pages + check encryption for the stats.
            reader = PdfReader(tmp_pdf)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:  # noqa: BLE001
                    return _fail("PDF 已加密，请先解除密码再上传。", is_ajax)
            total_pages = len(reader.pages)
            if total_pages == 0:
                return _fail("PDF 没有页面。", is_ajax)

            # Convert with pdf2docx.
            from pdf2docx import Converter  # noqa: PLC0415  (import on demand)

            tmp_docx = tempfile.mktemp(suffix=".docx")
            cv = Converter(tmp_pdf)
            try:
                cv.convert(tmp_docx, start=0, end=None)
            finally:
                cv.close()

            if not os.path.exists(tmp_docx) or os.path.getsize(tmp_docx) == 0:
                return _fail("转换失败：生成的 Word 文件为空。", is_ajax)

            with open(tmp_docx, "rb") as f:
                data = f.read()
        finally:
            for p in (tmp_pdf, tmp_docx):
                if p and os.path.exists(p):
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("pdf_to_word: conversion failed: %s", exc)
        return _fail(f"转换失败：{exc}", is_ajax)

    commit_usage("pdf_to_word", success=True)
    download_name = safe_filename("converted.docx")

    if is_ajax:
        try:
            filename = _stage_to_uploads(download_name, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf_to_word: failed to stage output: %s", exc)
            return jsonify(error="保存结果失败，请稍后再试。"), 500
        return jsonify(
            ok=True,
            url=url_for("pdf_to_word.download", filename=filename),
            filename=filename,
            size=len(data),
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            total_pages=total_pages,
        )

    return send_file(
        __import__("io").BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=download_name,
    )


@tool_bp.get("/download/<path:filename>")
def download(filename: str):
    if not is_allowed_ext(filename, {"docx"}):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"],
        filename,
        as_attachment=True,
        download_name=filename,
    )


def _fail(message: str, is_ajax: bool = False):
    commit_usage("pdf_to_word", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("pdf_to_word.index"))


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
