"""Image format converter — PNG ↔ JPG ↔ WEBP ↔ GIF ↔ BMP."""
from __future__ import annotations

import io
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from PIL import Image

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_download_path, safe_filename

tool_bp = Blueprint("image_convert", __name__)

_FORMATS = {
    "png": "PNG",
    "jpg": "JPEG",
    "jpeg": "JPEG",
    "webp": "WEBP",
    "gif": "GIF",
    "bmp": "BMP",
}

_ALLOWED_EXTS = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "image_convert", "name": "图片格式转换", "icon": "bi-arrow-left-right", "color": "#e83e8c"},
        remaining=remaining_for("image_convert"),
        body_template="tools/image_convert/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("image_convert")
def process():
    file = request.files.get("file")
    if not file or not file.filename:
        commit_usage("image_convert", success=False, message="未选择文件")
        return jsonify(error="请选择一个图片文件"), 400

    ext = Path(file.filename).suffix.lstrip(".").lower()
    if ext not in _ALLOWED_EXTS:
        commit_usage("image_convert", success=False, message=f"不支持的格式: {ext}")
        return jsonify(error=f"不支持的格式 .{ext}，支持：PNG / JPG / WEBP / GIF / BMP"), 400

    target_fmt = request.form.get("format", "").lower()
    if target_fmt not in _FORMATS:
        commit_usage("image_convert", success=False, message="未指定目标格式")
        return jsonify(error="请选择目标格式"), 400

    try:
        img = Image.open(file.stream)
        # Convert to RGB for JPEG (no alpha)
        if target_fmt in ("jpg", "jpeg") and img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        elif target_fmt == "bmp" and img.mode == "RGBA":
            img = img.convert("RGB")

        out_buf = io.BytesIO()
        save_fmt = _FORMATS[target_fmt]
        if target_fmt in ("jpg", "jpeg"):
            quality = min(100, max(1, int(request.form.get("quality", 85))))
            img.save(out_buf, format=save_fmt, quality=quality)
        else:
            img.save(out_buf, format=save_fmt)
        out_buf.seek(0)

        original_name = Path(file.filename).stem
        new_name = safe_filename(f"{original_name}.{target_fmt}")
        upload_dir: Path = current_app.config["UPLOAD_DIR"]
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / new_name
        target.write_bytes(out_buf.getvalue())

        commit_usage("image_convert", success=True)
        return jsonify(
            ok=True,
            url=f"/tools/image-convert/download/{new_name}",
            filename=new_name,
            size=target.stat().st_size,
            mime=f"image/{target_fmt}",
        )
    except Exception as e:
        commit_usage("image_convert", success=False, message=str(e))
        return jsonify(error=f"转换失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    if not is_allowed_ext(filename, _ALLOWED_EXTS):
        return jsonify(error="文件名不合法"), 400
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
