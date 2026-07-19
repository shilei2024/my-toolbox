"""Image to PDF — convert one or more images into a single PDF."""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from PIL import Image

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

tool_bp = Blueprint("image_to_pdf", __name__)

_ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "image_to_pdf", "name": "图片转 PDF", "icon": "bi-file-earmark-pdf", "color": "#dc3545"},
        remaining=remaining_for("image_to_pdf"),
        body_template="tools/image_to_pdf/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("image_to_pdf")
def process():
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        commit_usage("image_to_pdf", success=False, message="未选择文件")
        return jsonify(error="请至少选择一张图片"), 400

    images = []
    for f in files:
        ext = Path(f.filename).suffix.lstrip(".").lower()
        if ext not in _ALLOWED_EXTS:
            commit_usage("image_to_pdf", success=False, message=f"不支持的格式: {ext}")
            return jsonify(error=f"不支持 .{ext}，请上传 PNG/JPG/WEBP 等"), 400
        try:
            img = Image.open(f.stream)
            if img.mode in ("RGBA", "P"):
                img = img.convert("RGB")
            images.append(img)
        except Exception as e:
            commit_usage("image_to_pdf", success=False, message=str(e))
            return jsonify(error=f"读取图片失败：{e}"), 400

    if not images:
        commit_usage("image_to_pdf", success=False, message="没有有效图片")
        return jsonify(error="没有有效的图片文件"), 400

    try:
        first = images[0].convert("RGB")
        rest = [img.convert("RGB") for img in images[1:]]
        buf = io.BytesIO()
        first.save(buf, format="PDF", save_all=True, append_images=rest)
        buf.seek(0)

        filename = f"images_{uuid.uuid4().hex[:8]}.pdf"
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / filename
        target.write_bytes(buf.getvalue())

        commit_usage("image_to_pdf", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/image-to-pdf/download/{filename}",
            filename=filename,
            size=target.stat().st_size,
            mime="application/pdf",
        )
    except Exception as e:
        commit_usage("image_to_pdf", success=False, message=str(e))
        return jsonify(error=f"生成 PDF 失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    safe = safe_filename(filename)
    if not safe:
        return jsonify(error="文件名不合法"), 400
    return send_file(upload_dir / safe, as_attachment=True)
