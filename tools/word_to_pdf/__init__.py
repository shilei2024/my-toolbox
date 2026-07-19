"""Word (.docx) to PDF converter using python-docx + reportlab."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("word_to_pdf", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "word_to_pdf", "name": "Word 转 PDF", "icon": "bi-file-earmark-pdf", "color": "#0d6efd"},
        remaining=remaining_for("word_to_pdf"),
        body_template="tools/word_to_pdf/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("word_to_pdf")
def process():
    file = request.files.get("file")
    if not file or not file.filename:
        commit_usage("word_to_pdf", success=False, message="未选择文件")
        return jsonify(error="请选择 .docx 文件"), 400

    ext = Path(file.filename).suffix.lower()
    if ext != ".docx":
        return jsonify(error="仅支持 .docx 格式（不支持 .doc）"), 400

    try:
        from docx import Document
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import cm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import os

        # Try to find a CJK font
        cjk_font = "Helvetica"
        for font_name in ["msyh", "simsun", "simhei", "SimHei", "Microsoft YaHei"]:
            for font_dir in ["C:/Windows/Fonts", "/usr/share/fonts", "/System/Library/Fonts"]:
                path = os.path.join(font_dir, f"{font_name}.ttf")
                if os.path.exists(path):
                    try:
                        pdfmetrics.registerFont(TTFont("CJK", path))
                        cjk_font = "CJK"
                        break
                    except Exception:
                        pass
            if cjk_font != "Helvetica":
                break

        doc = Document(file.stream)
        buf = io.BytesIO()
        pdf = SimpleDocTemplate(buf, pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm)
        styles = getSampleStyleSheet()
        body_style = ParagraphStyle("Body", parent=styles["Normal"], fontName=cjk_font, fontSize=11, leading=16)
        heading_style = ParagraphStyle("Heading", parent=styles["Heading1"], fontName=cjk_font, fontSize=16, leading=22)

        story = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                story.append(Spacer(1, 6))
                continue
            if para.style.name.startswith("Heading"):
                story.append(Paragraph(text, heading_style))
            else:
                story.append(Paragraph(text, body_style))
            story.append(Spacer(1, 4))

        pdf.build(story)
        buf.seek(0)

        filename = f"converted_{uuid.uuid4().hex[:8]}.pdf"
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / filename
        target.write_bytes(buf.getvalue())

        commit_usage("word_to_pdf", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/word-to-pdf/download/{filename}",
            filename=filename,
            size=target.stat().st_size,
            mime="application/pdf",
        )
    except Exception as e:
        commit_usage("word_to_pdf", success=False, message=str(e))
        return jsonify(error=f"转换失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    from utils.helpers import safe_download_path
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
