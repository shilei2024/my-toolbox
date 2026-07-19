"""
PDF split tool.

Accepts a single PDF + a page range spec like `1-3,5,7-9`, extracts those
pages into a new PDF. Ranges can be split into multiple output files using
`;` — e.g. `1-3; 5; 7-9` produces three separate PDFs. On AJAX requests
the output is staged in UPLOAD_DIR and returned as JSON so the page can
show a filename + download button (or a file list when multiple outputs);
on plain form submits the (first / merged) file is streamed back directly.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any

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

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, parse_page_ranges, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_split", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "pdf_split",
            "name": "PDF 拆分",
            "icon": "bi-scissors",
            "color": "#198754",
        },
        remaining=remaining_for("pdf_split"),
        body_template="tools/pdf_split/_body.html",
        tool_js_list=["js/result.js", "js/tools.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_split")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    file = request.files.get("pdf")
    ranges = request.form.get("ranges", "").strip()

    if file is None or not file.filename:
        return _fail("请选择一个 PDF 文件。", is_ajax)
    if not is_allowed_ext(file.filename, {"pdf"}):
        return _fail("只能上传 PDF 文件。", is_ajax)

    try:
        reader = PdfReader(file.stream)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"PDF 解析失败：{exc}", is_ajax)

    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return _fail("PDF 已加密，无法拆分。", is_ajax)

    total_pages = len(reader.pages)

    # Split on `;` to allow multiple output files. Whitespace around `;` is ignored.
    specs = [s.strip() for s in ranges.split(";") if s.strip()]
    if not specs:
        return _fail("页码范围不能为空。", is_ajax)

    outputs: list[dict[str, Any]] = []
    for idx, spec in enumerate(specs):
        try:
            page_numbers = parse_page_ranges(spec, total_pages)
        except ValueError as exc:
            return _fail(str(exc), is_ajax)
        writer = PdfWriter()
        for n in page_numbers:
            writer.add_page(reader.pages[n - 1])
        buf = io.BytesIO()
        try:
            writer.write(buf)
        except Exception as exc:  # noqa: BLE001
            return _fail(f"生成 PDF 失败：{exc}", is_ajax)
        outputs.append({
            "spec": spec,
            "label": f"第 {idx + 1} 段：{spec}",
            "page_count": len(page_numbers),
            "data": buf.getvalue(),
        })

    commit_usage("pdf_split", success=True)

    # Single-file mode (the common case): one output, backward-compatible payload.
    if len(outputs) == 1:
        out = outputs[0]
        download_name = safe_filename("split.pdf")
        if is_ajax:
            try:
                filename = _stage_to_uploads(download_name, out["data"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("pdf_split: failed to stage output: %s", exc)
                return jsonify(error="保存结果失败，请稍后再试。"), 500
            return jsonify(
                ok=True,
                url=url_for("pdf_split.download", filename=filename),
                filename=filename,
                size=len(out["data"]),
                mime="application/pdf",
            )
        return send_file(
            io.BytesIO(out["data"]),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=download_name,
        )

    # Multi-file mode: stage every output, return a `files` list.
    if is_ajax:
        files_meta = []
        for out in outputs:
            suggested = safe_filename(f"split_{out['spec'].replace('-', '_to_').replace(',', '_')}.pdf")
            try:
                filename = _stage_to_uploads(suggested, out["data"])
            except Exception as exc:  # noqa: BLE001
                logger.exception("pdf_split: failed to stage output: %s", exc)
                return jsonify(error="保存结果失败，请稍后再试。"), 500
            files_meta.append({
                "label": out["label"],
                "url": url_for("pdf_split.download", filename=filename),
                "filename": filename,
                "size": len(out["data"]),
                "page_count": out["page_count"],
            })
        # also expose the first file as the top-level url/filename so the
        # generic result card still has something to show.
        first = files_meta[0]
        return jsonify(
            ok=True,
            url=first["url"],
            filename=first["filename"],
            size=sum(f["size"] for f in files_meta),
            mime="application/pdf",
            files=files_meta,
        )

    # No-JS fallback: just send the first one.
    out = outputs[0]
    return send_file(
        io.BytesIO(out["data"]),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=safe_filename("split.pdf"),
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
    commit_usage("pdf_split", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("pdf_split.index"))


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    """Save bytes into UPLOAD_DIR under a uuid-prefixed name."""
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
