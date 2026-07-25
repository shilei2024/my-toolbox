"""
批量压缩包 PDF 提取 — 递归解压多层嵌套 zip，筛选出所有 PDF 文件。

Vercel 兼容：分析结果直接返回 base64 数据，不依赖跨请求文件系统。
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import zipfile
from pathlib import Path

from flask import Blueprint, jsonify, render_template, request

from auth.decorators import remaining_for
from extensions import csrf, limiter

log = logging.getLogger(__name__)

tool_bp = Blueprint("zip_extractor", __name__, template_folder="templates")


@tool_bp.route("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "zip_extractor",
            "name": "批量提取PDF发票",
            "icon": "bi-file-zip",
            "color": "#6f42c1",
        },
        remaining=remaining_for("zip_extractor"),
        body_template="tools/zip_extractor/_body.html",
    )


# ---------------------------------------------------------------------------
# 递归解压核心
# ---------------------------------------------------------------------------
def _extract_deep(zip_bytes: bytes, source_name: str, depth: int = 0) -> list[dict]:
    """
    递归解压 zip 字节流，最深 8 层。
    返回找到的所有 PDF 文件列表 [{filename, size, path_chain, data}].
    """
    if depth > 8:
        return []

    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                name = info.filename.rstrip("/")
                # 跳过目录、macOS 资源、隐藏文件
                if info.is_dir() or name.startswith("__MACOSX") or Path(name).name.startswith("."):
                    continue
                basename = Path(name).name

                if basename.lower().endswith(".pdf"):
                    try:
                        data = zf.read(info)
                        results.append({
                            "filename": basename,
                            "size": len(data),
                            "path_chain": [source_name, *info.filename.split("/")],
                            "data": data,
                        })
                    except Exception as e:
                        log.warning("read PDF failed %s: %s", info.filename, e)

                elif basename.lower().endswith(".zip"):
                    try:
                        inner_data = zf.read(info)
                        inner_source = f"{source_name} → {basename}"
                        results.extend(_extract_deep(inner_data, inner_source, depth + 1))
                    except Exception as e:
                        log.warning("read inner zip failed %s: %s", info.filename, e)

    except zipfile.BadZipFile:
        log.warning("BadZipFile from %s", source_name)
    except Exception as e:
        log.warning("extract exception %s: %s", source_name, e)

    return results


# ---------------------------------------------------------------------------
# API：上传并分析
# ---------------------------------------------------------------------------
@tool_bp.post("/analyze")
@csrf.exempt
@limiter.limit(lambda: "20/minute")
def analyze():
    """接收多个 zip 文件，递归解压找出所有 PDF。"""
    try:
        files = request.files.getlist("files")
        if not files or all(not (f and f.filename) for f in files):
            return jsonify(success=False, error="请选择至少一个 zip 文件"), 400

        all_pdfs = []

        for f in files:
            if not f.filename:
                continue
            if not f.filename.lower().endswith(".zip"):
                continue
            try:
                zip_bytes = f.read()
                if not zip_bytes:
                    continue
                log.info("analyze: %s (%d bytes)", f.filename, len(zip_bytes))
                pdfs = _extract_deep(zip_bytes, f.filename)
                all_pdfs.extend(pdfs)
            except Exception as e:
                log.warning("Failed to read %s: %s", f.filename, e)

        # 按内容哈希去重
        seen = set()
        unique = []
        for p in all_pdfs:
            data = p.pop("data")
            h = _quick_hash(data)
            if h in seen:
                continue
            seen.add(h)
            p["data_b64"] = base64.b64encode(data).decode("ascii")
            p["size_kb"] = round(len(data) / 1024, 1)
            unique.append(p)

        # 限制总返回 ~50MB
        total_b64 = sum(len(p["data_b64"]) for p in unique)
        if total_b64 > 50_000_000:
            return jsonify(
                success=False,
                error=f"PDF 总大小过大（{total_b64/1e6:.0f}MB），请分批上传",
            ), 413

        return jsonify(success=True, total=len(unique), files=unique)

    except Exception as e:
        log.exception("analyze fatal error")
        return jsonify(success=False, error=f"服务器错误：{type(e).__name__}: {str(e)[:200]}"), 500


def _quick_hash(data: bytes) -> str:
    """快速内容哈希（SHA256 前 16 位，用于去重）。"""
    return hashlib.sha256(data).hexdigest()[:16]
