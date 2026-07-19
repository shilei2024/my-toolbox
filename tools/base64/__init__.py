"""Base64 encoder / decoder — text, image files."""
from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file
from PIL import Image

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("base64", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "base64", "name": "Base64 编解码", "icon": "bi-file-binary", "color": "#0d6efd"},
        remaining=remaining_for("base64"),
        body_template="tools/base64/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "20/minute")
@require_usage("base64")
def process():
    action = request.form.get("action", "encode")
    try:
        if action == "encode":
            mode = request.form.get("mode", "text")
            if mode == "text":
                raw = request.form.get("text", "")
                if not raw:
                    return jsonify(error="请输入要编码的文本"), 400
                result = base64.b64encode(raw.encode("utf-8")).decode("ascii")
                commit_usage("base64", success=True)
                return jsonify(ok=True, result=result)
            elif mode == "file":
                f = request.files.get("file")
                if not f or not f.filename:
                    return jsonify(error="请选择文件"), 400
                raw = f.read()
                result = base64.b64encode(raw).decode("ascii")
                commit_usage("base64", success=True)
                return jsonify(ok=True, result=result)
            else:
                # image mode — generate data URI
                f = request.files.get("file")
                if not f or not f.filename:
                    return jsonify(error="请选择图片文件"), 400
                raw = f.read()
                ext = Path(f.filename).suffix.lstrip(".").lower()
                if ext == "jpg":
                    ext = "jpeg"
                b64 = base64.b64encode(raw).decode("ascii")
                result = f"data:image/{ext};base64,{b64}"
                commit_usage("base64", success=True)
                return jsonify(ok=True, result=result)
        else:
            # decode
            raw = request.form.get("text", "").strip()
            if not raw:
                return jsonify(error="请输入 Base64 字符串"), 400
            # Strip data URI prefix if present
            if "," in raw and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            raw = raw.strip()
            try:
                decoded = base64.b64decode(raw)
            except Exception:
                commit_usage("base64", success=False, message="Base64 解码失败")
                return jsonify(error="Base64 字符串无效，无法解码"), 400

            # Check if it's an image
            try:
                img = Image.open(io.BytesIO(decoded))
                filename = f"decoded_{uuid.uuid4().hex[:8]}.{img.format.lower() if img.format else 'png'}"
                upload_dir: Path = current_app.config["UPLOAD_DIR"]
                upload_dir.mkdir(parents=True, exist_ok=True)
                target = upload_dir / filename
                target.write_bytes(decoded)
                commit_usage("base64", success=True)
                return jsonify(
                    ok=True,
                    result=f"(图片: {img.size[0]}x{img.size[1]}, {img.format})",
                    url=f"/tools/base64/download/{filename}",
                    filename=filename,
                    size=len(decoded),
                    mime=f"image/{img.format.lower() if img.format else 'png'}",
                )
            except Exception:
                pass

            # Try text decode
            try:
                text = decoded.decode("utf-8")
                commit_usage("base64", success=True)
                return jsonify(ok=True, result=text)
            except UnicodeDecodeError:
                commit_usage("base64", success=False, message="无法解码为文本")
                return jsonify(error="解码结果不是文本也不是可识别的图片"), 400

    except Exception as e:
        commit_usage("base64", success=False, message=str(e))
        return jsonify(error=f"处理失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    from utils.helpers import safe_download_path
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
