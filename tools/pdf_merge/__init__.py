"""
PDF merge tool.

Accepts 2+ PDFs, lets the user order them client-side, then concatenates
them on the server. On AJAX requests, the merged file is staged in
UPLOAD_DIR and the result is returned as JSON so the page can show a
preview / filename / download button. On plain form submits, the file
is streamed back directly (no-JS fallback).
"""
from __future__ import annotations

import io
import logging
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
from pypdf import PdfReader, PdfWriter
from werkzeug.datastructures import FileStorage

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_merge", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "pdf_merge",
            "name": "PDF 合并",
            "icon": "bi-files",
            "color": "#0d6efd",
        },
        remaining=remaining_for("pdf_merge"),
        body_template="tools/pdf_merge/_body.html",
        tool_js_list=["js/result.js", "js/pdf_merge.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_merge")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    files: list[FileStorage] = request.files.getlist("pdfs")
    order_raw = request.form.get("order", "").strip()
    order = [int(x) for x in order_raw.split(",") if x.strip().isdigit()] if order_raw else []

    # reorder according to client-provided order
    if order and len(order) == len(files):
        try:
            files = [files[i] for i in order]
        except IndexError:
            pass

    if len(files) < 2:
        return _fail("至少上传 2 个 PDF 文件。", is_ajax)

    for f in files:
        if not f.filename or not is_allowed_ext(f.filename, {"pdf"}):
            return _fail("只能上传 PDF 文件。", is_ajax)
        if not _magic_ok(f.stream, mime=b"%PDF"):
            return _fail(f"文件 {f.filename} 不是有效的 PDF。", is_ajax)

    writer = PdfWriter()
    for f in files:
        try:
            reader = PdfReader(f.stream)
            if reader.is_encrypted:
                try:
                    reader.decrypt("")
                except Exception:  # noqa: BLE001
                    return _fail(f"文件 {f.filename} 已加密，无法合并。", is_ajax)
            for page in reader.pages:
                writer.add_page(page)
        except Exception as exc:  # noqa: BLE001
            logger.warning("pdf_merge: %s", exc)
            return _fail(f"文件 {f.filename} 解析失败：{exc}", is_ajax)

    out = io.BytesIO()
    try:
        writer.write(out)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"合并失败：{exc}", is_ajax)
    out.seek(0)
    data = out.getvalue()

    commit_usage("pdf_merge", success=True)
    download_name = safe_filename("merged.pdf")

    if is_ajax:
        try:
            filename = _stage_to_uploads(download_name, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf_merge: failed to stage output: %s", exc)
            return jsonify(error="保存结果失败，请稍后再试。"), 500
        return jsonify(
            ok=True,
            url=url_for("pdf_merge.download", filename=filename),
            filename=filename,
            size=len(data),
            mime="application/pdf",
        )

    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=download_name,
    )


@tool_bp.get("/download/<path:filename>")
def download(filename: str):
    if not is_allowed_ext(filename, {"pdf"}):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"],
        filename,
        as_attachment=True,
        download_name=filename,
    )


# ----- helpers -----
def _fail(message: str, is_ajax: bool = False):
    commit_usage("pdf_merge", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("pdf_merge.index"))


def _magic_ok(stream, mime: bytes, length: int = 8) -> bool:
    head = stream.read(length)
    stream.seek(0)
    return head.startswith(mime)


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    """Save bytes into UPLOAD_DIR under a uuid-prefixed name. Returns the
    stored filename (which the cleanup job will sweep after TTL)."""
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Suggested name is already uuid-prefixed by safe_filename; just persist it.
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
