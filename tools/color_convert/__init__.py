"""Color converter — HEX ↔ RGB ↔ HSL."""
from __future__ import annotations

import colorsys

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("color_convert", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "color_convert", "name": "颜色转换", "icon": "bi-palette", "color": "#e83e8c"},
        remaining=remaining_for("color_convert"),
        body_template="tools/color_convert/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "60/minute")
@require_usage("color_convert")
def process():
    raw = request.form.get("color", "").strip()
    if not raw:
        return jsonify(error="请输入颜色值"), 400

    raw = raw.lstrip("#").strip()
    try:
        if len(raw) == 6:
            r = int(raw[0:2], 16)
            g = int(raw[2:4], 16)
            b = int(raw[4:6], 16)
        elif len(raw) == 3:
            r = int(raw[0] * 2, 16)
            g = int(raw[1] * 2, 16)
            b = int(raw[2] * 2, 16)
        elif raw.startswith("rgb"):
            nums = raw.replace("rgb(", "").replace(")", "").split(",")
            r, g, b = int(nums[0]), int(nums[1]), int(nums[2])
        elif raw.startswith("hsl"):
            nums = raw.replace("hsl(", "").replace(")", "").split(",")
            h = float(nums[0]) / 360.0
            s = float(nums[1].strip().rstrip("%")) / 100.0
            l = float(nums[2].strip().rstrip("%")) / 100.0
            r, g, b = colorsys.hls_to_rgb(h, l, s)
            r, g, b = int(r * 255), int(g * 255), int(b * 255)
        else:
            return jsonify(error="无法识别的颜色格式，支持 #HEX / rgb() / hsl()"), 400

        h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
        commit_usage("color_convert", success=True)
        return jsonify(
            ok=True,
            hex=f"#{r:02x}{g:02x}{b:02x}",
            rgb=f"rgb({r}, {g}, {b})",
            hsl=f"hsl({int(h * 360)}, {int(s * 100)}%, {int(l * 100)}%)",
            preview=f"#{r:02x}{g:02x}{b:02x}",
        )
    except (ValueError, IndexError) as e:
        commit_usage("color_convert", success=False, message=str(e))
        return jsonify(error=f"解析失败：{e}"), 400
