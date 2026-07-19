"""Data converter — CSV ↔ JSON ↔ Excel (.xlsx) ↔ TSV."""
from __future__ import annotations

import csv
import io
import json
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

tool_bp = Blueprint("data_convert", __name__)


@tool_bp.get("/")
def index():
    return render_template(
        "tools_base.html",
        tool={"id": "data_convert", "name": "数据格式转换", "icon": "bi-arrow-left-right", "color": "#0dcaf0"},
        remaining=remaining_for("data_convert"),
        body_template="tools/data_convert/_body.html",
    )


@tool_bp.post("/process")
@limiter.limit(lambda: "20/minute")
@require_usage("data_convert")
def process():
    from_format = request.form.get("from", "")
    to_format = request.form.get("to", "")
    text = request.form.get("text", "")

    if not text.strip():
        return jsonify(error="请输入数据"), 400

    try:
        # Parse input to list of dicts
        if from_format == "json":
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
        elif from_format in ("csv", "tsv"):
            delim = "\t" if from_format == "tsv" else ","
            reader = csv.DictReader(io.StringIO(text), delimiter=delim)
            data = [dict(row) for row in reader]
        else:
            return jsonify(error=f"不支持的输入格式：{from_format}"), 400

        if not data:
            return jsonify(error="解析后数据为空"), 400

        # Convert to target format
        if to_format == "json":
            result = json.dumps(data, ensure_ascii=False, indent=2)
            commit_usage("data_convert", success=True)
            return jsonify(ok=True, result=result, mode="text")

        elif to_format in ("csv", "tsv"):
            delim = "\t" if to_format == "tsv" else ","
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=data[0].keys(), delimiter=delim)
            writer.writeheader()
            writer.writerows(data)
            commit_usage("data_convert", success=True)
            return jsonify(ok=True, result=buf.getvalue(), mode="text")

        elif to_format == "xlsx":
            from openpyxl import Workbook

            wb = Workbook()
            ws = wb.active
            headers = list(data[0].keys())
            ws.append(headers)
            for row in data:
                ws.append([row.get(h, "") for h in headers])

            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)

            filename = f"converted_{uuid.uuid4().hex[:8]}.xlsx"
            upload_dir: Path = current_app.config["UPLOAD_DIR"]
            upload_dir.mkdir(parents=True, exist_ok=True)
            target = upload_dir / filename
            target.write_bytes(buf.getvalue())

            commit_usage("data_convert", success=True)
            return jsonify(
                ok=True,
                url=f"/tools/data-convert/download/{filename}",
                filename=filename,
                size=target.stat().st_size,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                mode="file",
            )
        else:
            return jsonify(error=f"不支持的输出格式：{to_format}"), 400

    except json.JSONDecodeError as e:
        commit_usage("data_convert", success=False, message=str(e))
        return jsonify(error=f"JSON 解析失败：{e}"), 400
    except Exception as e:
        commit_usage("data_convert", success=False, message=str(e))
        return jsonify(error=f"转换失败：{e}"), 500


@tool_bp.get("/download/<filename>")
def download(filename: str):
    from utils.helpers import safe_download_path
    upload_dir: Path = current_app.config["UPLOAD_DIR"]
    target = safe_download_path(upload_dir, filename)
    if target is None or not target.exists():
        return jsonify(error="文件不存在"), 404
    return send_file(target, as_attachment=True)
