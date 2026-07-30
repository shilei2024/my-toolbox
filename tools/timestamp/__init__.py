"""Timestamp converter — Unix ↔ datetime bidirectional. 100% Python stdlib."""
from __future__ import annotations

from datetime import datetime, timezone

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter
from utils.helpers import CHINA_TIMEZONE

tool_bp = Blueprint("timestamp", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "timestamp", "name": "时间戳转换", "icon": "bi-clock", "color": "#20c997"},
        remaining=remaining_for("timestamp"),
        body_template="tools/timestamp/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "30/minute")
@require_usage("timestamp")
def process():
    direction = request.form.get("direction", "ts2dt")
    raw = request.form.get("value", "").strip()
    if not raw:
        commit_usage("timestamp", success=False, message="输入为空")
        return jsonify(error="请输入时间戳或日期时间"), 400

    try:
        if direction == "ts2dt":
            ts = float(raw)
            if raw.find(".") == -1 and abs(ts) >= 100_000_000_000_000:
                ts = ts / 1_000_000.0  # microseconds
            elif raw.find(".") == -1 and abs(ts) >= 100_000_000_000:
                ts = ts / 1000.0  # milliseconds
            dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
            dt_china = dt_utc.astimezone(CHINA_TIMEZONE)
            current_ts = int(datetime.now(timezone.utc).timestamp())
            commit_usage("timestamp", success=True)
            return jsonify(
                ok=True,
                result={
                    "china": dt_china.strftime("%Y-%m-%d %H:%M:%S UTC+08:00"),
                    "utc": dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "iso": dt_china.isoformat(),
                    "seconds": int(ts),
                    "milliseconds": int(ts * 1000),
                    "current_ts": current_ts,
                },
            )
        else:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                # A date entered without an offset is interpreted as China time.
                dt = dt.replace(tzinfo=CHINA_TIMEZONE)
            ts = int(dt.timestamp())
            dt_china = dt.astimezone(CHINA_TIMEZONE)
            dt_utc = dt.astimezone(timezone.utc)
            commit_usage("timestamp", success=True)
            return jsonify(
                ok=True,
                result={
                    "china": dt_china.strftime("%Y-%m-%d %H:%M:%S UTC+08:00"),
                    "utc": dt_utc.strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "iso": dt_china.isoformat(),
                    "seconds": ts,
                    "milliseconds": ts * 1000,
                    "current_ts": int(datetime.now(timezone.utc).timestamp()),
                },
            )
    except (ValueError, OSError) as e:
        commit_usage("timestamp", success=False, message=str(e))
        return jsonify(error=f"转换失败：{e}"), 400
