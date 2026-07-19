"""
PDF rotate tool.

Rotates pages of a PDF by 90 / 180 / 270 degrees, either every page or a
subset specified by a page range like `1-3,5`. Uses pypdf's page.rotate().
Output is staged in UPLOAD_DIR and returned as JSON for the result card.
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
from pypdf import PdfReader, PdfWriter, Transformation

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, parse_page_ranges, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_rotate", __name__)

# Valid rotation angles (clockwise, degrees).
_VALID_ANGLES = {90, 180, 270}


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "pdf_rotate",
            "name": "PDF 旋转",
            "icon": "bi-arrow-clockwise",
            "color": "#20c997",
        },
        remaining=remaining_for("pdf_rotate"),
        body_template="tools/pdf_rotate/_body.html",
        tool_js_list=["js/result.js", "js/tools.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_rotate")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    file = request.files.get("pdf")
    if file is None or not file.filename:
        return _fail("请选择一个 PDF 文件。", is_ajax)
    if not is_allowed_ext(file.filename, {"pdf"}):
        return _fail("只能上传 PDF 文件。", is_ajax)

    try:
        angle = int(request.form.get("angle", "90"))
    except ValueError:
        return _fail("旋转角度无效。", is_ajax)
    if angle not in _VALID_ANGLES:
        return _fail(f"旋转角度必须是 {sorted(_VALID_ANGLES)} 之一。", is_ajax)

    # "all" = rotate every page; otherwise parse a page range.
    scope = request.form.get("scope", "all")
    ranges_raw = (request.form.get("ranges") or "").strip()
    if scope not in {"all", "custom"}:
        scope = "all"

    try:
        reader = PdfReader(file.stream)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"PDF 解析失败：{exc}", is_ajax)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return _fail("PDF 已加密，无法旋转。", is_ajax)

    total_pages = len(reader.pages)
    if total_pages == 0:
        return _fail("PDF 没有页面。", is_ajax)

    # Resolve the set of 1-indexed page numbers to rotate.
    if scope == "all":
        target_pages = set(range(1, total_pages + 1))
    else:
        try:
            target_pages = set(parse_page_ranges(ranges_raw, total_pages))
        except ValueError as exc:
            return _fail(str(exc), is_ajax)
    if not target_pages:
        return _fail("指定的页码范围没有任何有效页面。", is_ajax)

    writer = PdfWriter()
    rotated_count = 0
    for idx in range(1, total_pages + 1):
        page = reader.pages[idx - 1]
        if idx in target_pages:
            # pypdf's rotate() rotates clockwise and mutates the page in place.
            page.rotate(angle)
            rotated_count += 1
        writer.add_page(page)

    out = io.BytesIO()
    try:
        writer.write(out)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"生成 PDF 失败：{exc}", is_ajax)
    out.seek(0)
    data = out.getvalue()

    commit_usage("pdf_rotate", success=True)
    download_name = safe_filename("rotated.pdf")

    if is_ajax:
        try:
            filename = _stage_to_uploads(download_name, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf_rotate: failed to stage output: %s", exc)
            return jsonify(error="保存结果失败，请稍后再试。"), 500
        return jsonify(
            ok=True,
            url=url_for("pdf_rotate.download", filename=filename),
            filename=filename,
            size=len(data),
            mime="application/pdf",
            total_pages=total_pages,
            rotated_pages=rotated_count,
            angle=angle,
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


def _fail(message: str, is_ajax: bool = False):
    commit_usage("pdf_rotate", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("pdf_rotate.index"))


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
