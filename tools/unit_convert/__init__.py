"""Unit converter — length, weight, temperature, storage, time."""
from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("unit_convert", __name__)

# Conversion factors to base unit
_UNITS = {
    "length": {
        "base": "m",
        "units": {"mm": 0.001, "cm": 0.01, "m": 1, "km": 1000, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344},
    },
    "weight": {
        "base": "kg",
        "units": {"mg": 0.000001, "g": 0.001, "kg": 1, "t": 1000, "oz": 0.0283495, "lb": 0.453592},
    },
    "storage": {
        "base": "B",
        "units": {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3, "TB": 1024**4, "PB": 1024**5},
    },
    "time": {
        "base": "s",
        "units": {"ms": 0.001, "s": 1, "min": 60, "h": 3600, "d": 86400, "w": 604800, "y": 31536000},
    },
}


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "unit_convert", "name": "单位换算", "icon": "bi-rulers", "color": "#20c997"},
        remaining=remaining_for("unit_convert"),
        body_template="tools/unit_convert/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "60/minute")
@require_usage("unit_convert")
def process():
    category = request.form.get("category", "length")
    value_str = request.form.get("value", "0")
    from_unit = request.form.get("from_unit", "")
    to_unit = request.form.get("to_unit", "")

    try:
        value = float(value_str)
    except ValueError:
        return jsonify(error="请输入有效的数字"), 400

    if category == "temperature":
        # Special handling: C / F / K
        try:
            if from_unit == "C" and to_unit == "F":
                result = value * 9 / 5 + 32
            elif from_unit == "C" and to_unit == "K":
                result = value + 273.15
            elif from_unit == "F" and to_unit == "C":
                result = (value - 32) * 5 / 9
            elif from_unit == "F" and to_unit == "K":
                result = (value - 32) * 5 / 9 + 273.15
            elif from_unit == "K" and to_unit == "C":
                result = value - 273.15
            elif from_unit == "K" and to_unit == "F":
                result = (value - 273.15) * 9 / 5 + 32
            elif from_unit == to_unit:
                result = value
            else:
                return jsonify(error="不支持的温度单位"), 400
            commit_usage("unit_convert", success=True)
            return jsonify(ok=True, result=round(result, 6))
        except Exception as e:
            return jsonify(error=str(e)), 400

    if category not in _UNITS:
        return jsonify(error=f"不支持的类别：{category}"), 400

    units = _UNITS[category]["units"]
    if from_unit not in units or to_unit not in units:
        return jsonify(error="单位不合法"), 400

    # Convert to base then to target
    base_value = value * units[from_unit]
    result = base_value / units[to_unit]

    commit_usage("unit_convert", success=True)
    return jsonify(ok=True, result=round(result, 8))
