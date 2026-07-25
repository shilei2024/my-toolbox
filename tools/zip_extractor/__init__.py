"""
批量压缩包 PDF 提取 — 递归解压多层嵌套 zip，筛选出所有 PDF 文件。

支持：zip 嵌套 zip、不同目录层级、多种压缩格式。
"""
from __future__ import annotations

import io
import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, send_file

tool_bp = Blueprint("zip_extractor", __name__, template_folder="templates")


@tool_bp.route("/")
def index():
    return render_template("tools_base.html", body_template="tools/zip_extractor/_body.html")


# ---------------------------------------------------------------------------
# 递归解压核心
# ---------------------------------------------------------------------------
def _extract_deep(zip_bytes: bytes, source_name: str, depth: int = 0) -> list[dict]:
    """
    递归解压 zip 字节流，最深 8 层。
    返回找到的所有 PDF 文件列表 [{filename, size, path_chain}].
    """
    if depth > 8:
        return []

    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                name = info.filename.rstrip("/")
                # 跳过目录和隐藏文件
                if info.is_dir() or name.startswith("__MACOSX") or name.startswith("."):
                    continue
                basename = Path(name).name

                # PDF 文件 → 直接收集
                if basename.lower().endswith(".pdf"):
                    data = zf.read(info)
                    results.append({
                        "filename": basename,
                        "size": len(data),
                        "path_chain": [source_name, *info.filename.split("/")],
                        "data": data,
                    })

                # 嵌套 zip → 递归解压
                elif basename.lower().endswith(".zip"):
                    try:
                        inner_data = zf.read(info)
                        inner_chain = f"{source_name} → {basename}"
                        sub = _extract_deep(inner_data, inner_chain, depth + 1)
                        results.extend(sub)
                    except Exception:
                        pass

    except zipfile.BadZipFile:
        pass
    except Exception:
        pass

    return results


# ---------------------------------------------------------------------------
# API：上传并分析
# ---------------------------------------------------------------------------
@tool_bp.post("/analyze")
def analyze():
    """接收多个 zip 文件，递归解压找出所有 PDF。"""
    files = request.files.getlist("files")
    if not files or all(not f.filename for f in files):
        return jsonify(error="请选择至少一个 zip 文件"), 400

    # 工作目录
    work_dir = Path(current_app.config["UPLOAD_DIR"]) / "zip_extractor" / uuid.uuid4().hex[:10]
    work_dir.mkdir(parents=True, exist_ok=True)

    all_pdfs = []
    saved_pdfs = []

    try:
        for f in files:
            if not f.filename:
                continue
            zip_bytes = f.read()
            name = f.filename
            pdfs = _extract_deep(zip_bytes, name)
            for p in pdfs:
                # 用 PDF 内容哈希去重
                data = p["data"]
                pdf_hash = _quick_hash(data)
                # 生成唯一文件名（保留原名，重名加序号）
                p["hash"] = pdf_hash
                all_pdfs.append(p)

        # 去重（按内容哈希）
        seen = set()
        unique = []
        for p in all_pdfs:
            if p["hash"] not in seen:
                seen.add(p["hash"])
                unique.append(p)
            # 重名处理
            del p["data"], p["hash"]
        all_pdfs = unique

        # 保存到磁盘备用下载
        for idx, p in enumerate(all_pdfs):
            data = p.pop("data")
            saved_name = _safe_filename(p["filename"])
            saved_path = work_dir / f"{idx:03d}_{saved_name}"
            saved_path.write_bytes(data)
            p["download_id"] = saved_path.name
            p["size_kb"] = round(p["size"] / 1024, 1)

        return jsonify(
            success=True,
            total=len(all_pdfs),
            files=all_pdfs,
            work_id=work_dir.name,
        )
    except Exception as e:
        return jsonify(error=str(e)), 500


def _quick_hash(data: bytes) -> str:
    """快速内容哈希（SHA256 前 16 位，用于去重）。"""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def _safe_filename(name: str) -> str:
    """过滤非法文件名字符。"""
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    return name[:200]


@tool_bp.get("/download/<work_id>/<filename>")
def download_single(work_id, filename):
    """下载单个 PDF。"""
    # 安全检查
    if ".." in filename or "/" in filename or "\\" in filename:
        return jsonify(error="非法文件名"), 400

    work_dir = Path(current_app.config["UPLOAD_DIR"]) / "zip_extractor" / work_id
    filepath = work_dir / filename
    if not filepath.exists():
        return jsonify(error="文件不存在"), 404

    return send_file(str(filepath), mimetype="application/pdf", as_attachment=True, download_name=filename.split("_", 1)[-1])


@tool_bp.post("/download-all")
def download_all():
    """批量下载所有 PDF 为一个 zip。支持 JSON {work_id} 或 form work_id=xxx。"""
    data = request.get_json(silent=True) or {}
    work_id = (data.get("work_id") or request.form.get("work_id") or "").strip()
    if not work_id:
        return jsonify(error="缺少 work_id"), 400

    work_dir = Path(current_app.config["UPLOAD_DIR"]) / "zip_extractor" / work_id
    if not work_dir.exists():
        return jsonify(error="会话已过期，请重新上传"), 404

    import tempfile
    zip_path = work_dir / "_all_pdfs.zip"
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(work_dir.glob("*.pdf")):
            zf.write(str(f), f.name.split("_", 1)[-1])

    return send_file(str(zip_path), mimetype="application/zip", as_attachment=True, download_name="提取的发票文件.zip")
