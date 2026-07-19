"""
Image compression tool.

Lossless-ish: keeps EXIF when possible, lets the user pick a quality
for JPEG/WebP, and downscales large images by an optional max-edge
slider. On AJAX requests the output is staged in UPLOAD_DIR and the
result is returned as JSON so the page can show a preview + filename +
download button; on plain form submits the file is streamed back directly.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path

from flask import (
    Blueprint,
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
from PIL import Image

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import is_allowed_ext, safe_filename

logger = logging.getLogger(__name__)
tool_bp = Blueprint("image_compress", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "image_compress",
            "name": "图片压缩",
            "icon": "bi-image",
            "color": "#fd7e14",
        },
        remaining=remaining_for("image_compress"),
        body_template="tools/image_compress/_body.html",
        tool_js_list=["js/result.js"],
    )


@tool_bp.post("/process")
@limiter.limit(lambda: current_app.config["RATELIMIT_TOOL"])
@require_usage("image_compress")
def process():
    is_ajax = request.accept_mimetypes.best == "application/json" or request.is_json

    file = request.files.get("image")
    if file is None or not file.filename:
        return _fail("请选择一张图片。", is_ajax)
    if not is_allowed_ext(file.filename, current_app.config["ALLOWED_IMAGE_EXT"]):
        return _fail("仅支持 PNG / JPG / WebP / GIF。", is_ajax)

    # Capture original size before we touch the stream
    file.stream.seek(0, io.SEEK_END)
    original_size = file.stream.tell()
    file.stream.seek(0)

    try:
        quality = int(request.form.get("quality", "75"))
    except ValueError:
        quality = 75
    quality = max(1, min(quality, 100))

    try:
        max_edge_raw = request.form.get("max_edge", "").strip()
        max_edge = int(max_edge_raw) if max_edge_raw else None
        if max_edge is not None:
            max_edge = max(64, min(max_edge, 8000))
    except ValueError:
        max_edge = None

    try:
        img = Image.open(file.stream)
        img.load()
    except Exception as exc:  # noqa: BLE001
        return _fail(f"图片解析失败：{exc}", is_ajax)

    if max_edge is not None and max(img.size) > max_edge:
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)

    fmt = (img.format or "PNG").upper()
    out = io.BytesIO()
    save_kwargs: dict = {}

    if fmt in {"JPEG", "JPG"}:
        if img.mode in {"RGBA", "P"}:
            img = img.convert("RGB")
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True
        out_ext = "jpg"
    elif fmt == "WEBP":
        save_kwargs["quality"] = quality
        save_kwargs["method"] = 6
        out_ext = "webp"
    elif fmt == "PNG":
        save_kwargs["optimize"] = True
        out_ext = "png"
    elif fmt == "GIF":
        out_ext = "gif"
    else:
        out_ext = fmt.lower()

    try:
        img.save(out, format=fmt, **save_kwargs)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"压缩失败：{exc}", is_ajax)
    out.seek(0)
    data = out.getvalue()

    commit_usage("image_compress", success=True)
    download_name = safe_filename(f"compressed.{out_ext}")

    if is_ajax:
        try:
            filename = _stage_to_uploads(download_name, data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("image_compress: failed to stage output: %s", exc)
            return jsonify(error="保存结果失败，请稍后再试。"), 500
        # format might have changed (RGBA→RGB JPEG); report what we actually saved
        saved_w, saved_h = img.size
        return jsonify(
            ok=True,
            url=url_for("image_compress.download", filename=filename),
            filename=filename,
            size=len(data),
            mime=f"image/{out_ext}",
            original_size=original_size,
            original_filename=file.filename,
            width=saved_w,
            height=saved_h,
        )

    return send_file(
        io.BytesIO(data),
        mimetype=f"image/{out_ext}",
        as_attachment=True,
        download_name=download_name,
    )


@tool_bp.get("/download/<path:filename>")
def download(filename: str):
    from flask import abort

    if not is_allowed_ext(filename, current_app.config["ALLOWED_IMAGE_EXT"]):
        abort(404)
    return send_from_directory(
        current_app.config["UPLOAD_DIR"],
        filename,
        as_attachment=True,
        download_name=filename,
    )


def _fail(message: str, is_ajax: bool = False):
    commit_usage("image_compress", success=False, message=message)
    if is_ajax:
        return jsonify(error=message), 400
    flash(message, "danger")
    return redirect(url_for("image_compress.index"))


def _stage_to_uploads(suggested_name: str, data: bytes) -> str:
    """Save bytes into UPLOAD_DIR under a uuid-prefixed name."""
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / suggested_name
    target.write_bytes(data)
    return suggested_name
