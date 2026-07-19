"""
PDF watermark tool.

Accepts a single PDF + a watermark text + optional font size / color /
opacity / rotation. Uses reportlab to draw transparent text directly onto
a PDF page (no image background → the original page content stays fully
visible), then merges that watermark page onto every page of the source
PDF using pypdf.

Output is staged in UPLOAD_DIR and returned as JSON so the page can show
a preview / filename + download button.
"""
from __future__ import annotations

import io
import logging
import math
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
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("pdf_watermark", __name__)

# Cache for registered reportlab fonts (registering the same name twice raises).
_FONT_REGISTERED: set[str] = set()

# Candidate CJK + Latin fonts, tried in order. The first that loads wins.
_FONT_CANDIDATES = [
    ("msyh",   "C:/Windows/Fonts/msyh.ttc"),     # Microsoft YaHei (Windows, CJK)
    ("simhei", "C:/Windows/Fonts/simhei.ttf"),    # SimHei (Windows, CJK)
    ("simsun", "C:/Windows/Fonts/simsun.ttc"),    # SimSun (Windows, CJK)
    ("arial",  "C:/Windows/Fonts/arial.ttf"),      # Arial (Windows, Latin)
    ("noto",   "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    ("wqy",    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
]
# Built-in fallback name (Helvetica — Latin only, always available in reportlab).
_FALLBACK_FONT = "Helvetica"


def _resolve_font() -> str:
    """Register and return a usable reportlab font name (CJK-capable when possible)."""
    for name, path in _FONT_CANDIDATES:
        if name in _FONT_REGISTERED:
            return name
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            _FONT_REGISTERED.add(name)
            logger.debug("pdf_watermark: using font %s (%s)", name, path)
            return name
        except Exception:  # noqa: BLE001
            continue
    return _FALLBACK_FONT  # Helvetica, always available — Latin only


def _hex_to_rgb(text: str, default=(0.53, 0.53, 0.53)):
    """Parse '#RRGGBB' → (r, g, b) floats 0–1. Falls back to default."""
    text = (text or "").strip().lstrip("#")
    if len(text) == 6:
        try:
            r = int(text[0:2], 16) / 255
            g = int(text[2:4], 16) / 255
            b = int(text[4:6], 16) / 255
            return (r, g, b)
        except ValueError:
            return default
    return default


# ---------------------------------------------------------------------------
# Watermark page rendering (reportlab → transparent text on a PDF page)
# ---------------------------------------------------------------------------
def render_watermark_page(
    text: str,
    page_width: float,
    page_height: float,
    font_size: int = 60,
    color_hex: str = "#888888",
    opacity: int = 80,
    rotation_deg: float = 45,
) -> bytes:
    """Draw watermark text on a transparent PDF page matching ``page_width``
    × ``page_height``. Returns the PDF bytes.

    The page has NO background fill, so when pypdf merges it the original
    page content stays fully visible — only the text is overlaid.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width, page_height))

    font_name = _resolve_font()
    r, g, b = _hex_to_rgb(color_hex)
    alpha = max(0.0, min(1.0, opacity / 255.0))

    c.saveState()
    c.setFillColor(Color(r, g, b, alpha=alpha))
    c.setFont(font_name, font_size)

    # Move to page center, rotate, draw centered text.
    c.translate(page_width / 2, page_height / 2)
    c.rotate(rotation_deg)
    c.drawCentredString(0, -font_size / 4, text)
    c.restoreState()

    c.showPage()
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "pdf_watermark",
            "name": "PDF 加水印",
            "icon": "bi-stamp",
            "color": "#6610f2",
        },
        remaining=remaining_for("pdf_watermark"),
        body_template="tools/pdf_watermark/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("pdf_watermark")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    file = request.files.get("pdf")
    text = (request.form.get("text") or "").strip()
    if file is None or not file.filename:
        return _fail("请选择一个 PDF 文件。", is_ajax)
    if not is_allowed_ext(file.filename, {"pdf"}):
        return _fail("只能上传 PDF 文件。", is_ajax)
    if not text:
        return _fail("水印文字不能为空。", is_ajax)
    if len(text) > 100:
        return _fail("水印文字太长（最多 100 字）。", is_ajax)

    try:
        font_size = int(request.form.get("font_size", "60"))
    except ValueError:
        font_size = 60
    font_size = max(12, min(font_size, 200))

    color_hex = (request.form.get("color") or "#888888").strip() or "#888888"

    try:
        opacity = int(request.form.get("opacity", "80"))
    except ValueError:
        opacity = 80
    opacity = max(10, min(opacity, 255))

    try:
        rotation = float(request.form.get("rotation", "45"))
    except ValueError:
        rotation = 45.0
    rotation = max(-180, min(rotation, 180))

    try:
        reader = PdfReader(file.stream)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"PDF 解析失败：{exc}", is_ajax)
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:  # noqa: BLE001
            return _fail("PDF 已加密，无法加水印。", is_ajax)
    total_pages = len(reader.pages)
    if total_pages == 0:
        return _fail("PDF 没有页面。", is_ajax)

    writer = PdfWriter()
    for page in reader.pages:
        page_w = float(page.mediabox.width)
        page_h = float(page.mediabox.height)

        # Render a transparent watermark page sized to match THIS page,
        # so the watermark is centered & scaled correctly regardless of
        # page size / orientation within the document.
        wm_pdf_bytes = render_watermark_page(
            text=text,
            page_width=page_w,
            page_height=page_h,
            font_size=font_size,
            color_hex=color_hex,
            opacity=opacity,
            rotation_deg=rotation,
        )
        wm_reader = PdfReader(io.BytesIO(wm_pdf_bytes))
        wm_page = wm_reader.pages[0]

        # Merge watermark on top of the original page. Because the watermark
        # page has no background fill, only the text is overlaid — the original
        # content stays fully visible.
        page.merge_page(wm_page, over=True, expand=False)
        writer.add_page(page)

    out = io.BytesIO()
    try:
        writer.write(out)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"生成 PDF 失败：{exc}", is_ajax)
    out.seek(0)
    data = out.getvalue()

    commit_usage("pdf_watermark", success=True)
    download_name = safe_filename("watermarked.pdf")

    if is_ajax:
        try:
            filename = _stage_to_uploads(download_name, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf_watermark: failed to stage output: %s", exc)
            return jsonify(error="保存结果失败，请稍后再试。"), 500
        return jsonify(
            ok=True,
            url=url_for("pdf_watermark.download", filename=filename),
            filename=filename,
            size=len(data),
            mime="application/pdf",
            page_count=total_pages,
            watermark_text=text,
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
    commit_usage("pdf_watermark", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("pdf_watermark.index"))


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
