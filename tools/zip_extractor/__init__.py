"""
批量压缩包 PDF 提取 — 递归解压多层嵌套 zip，筛选出所有 PDF 文件。

Vercel 兼容：单次请求/响应体严格控制在 3MB 以内（Vercel Serverless
Function 上限 4.5MB，留出 multipart boundary 与 base64 膨胀空间）。
超出时返回 413 + 明确提示，前端会自动拆分分批。
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import zipfile
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from auth.decorators import commit_usage, remaining_for, require_usage
from extensions import limiter

log = logging.getLogger(__name__)

tool_bp = Blueprint("zip_extractor", __name__, template_folder="templates")

# ---------------------------------------------------------------------------
# Vercel-friendly 上限
# ---------------------------------------------------------------------------
# Vercel Serverless Function 单次请求/响应上限 4.5MB。multipart 边界、filename、
# base64 膨胀（×1.33）都要扣掉，单批 zip 净数据 ≤ 3MB、返回 PDF base64 ≤ 3MB
# 比较稳。超出后端会显式 413，前端据此自动分批。
MAX_REQUEST_ZIP_BYTES = 3 * 1024 * 1024       # 3 MB（本批 zip 总大小上限）
MAX_RESPONSE_B64_BYTES = 3 * 1024 * 1024      # 3 MB（返回 PDF base64 总大小上限）
MAX_SINGLE_FILE_BYTES = 4 * 1024 * 1024       # 4 MB（单 zip 上限，超出直接拒收）
MAX_DEPTH = 8                                 # 递归层数上限
# Limits apply before decompression. The upload limit alone cannot protect a
# worker from a highly-compressible ZIP expanding into gigabytes of memory.
MAX_ENTRY_UNCOMPRESSED_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100


class _ExtractionBudget:
    def __init__(self, limit: int = MAX_ARCHIVE_UNCOMPRESSED_BYTES) -> None:
        self.remaining = limit

    def reserve(self, size: int) -> bool:
        if size < 0 or size > self.remaining:
            return False
        self.remaining -= size
        return True


def _safe_to_extract(info: zipfile.ZipInfo, budget: _ExtractionBudget) -> bool:
    """Reject dangerous ZIP members without materialising their payload."""
    if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
        log.warning("ZIP member exceeds uncompressed limit: %s (%d bytes)", info.filename, info.file_size)
        return False
    if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
        log.warning("ZIP member exceeds compression-ratio limit: %s", info.filename)
        return False
    if not budget.reserve(info.file_size):
        log.warning("ZIP archive exceeds cumulative extraction limit at: %s", info.filename)
        return False
    return True


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
def _extract_deep(
    zip_bytes: bytes,
    source_name: str,
    depth: int = 0,
    budget: _ExtractionBudget | None = None,
) -> list[dict]:
    """
    递归解压 zip 字节流，最深 8 层。
    返回找到的所有 PDF 文件列表 [{filename, size, path_chain, data}].
    """
    if depth > MAX_DEPTH:
        return []
    budget = budget or _ExtractionBudget()

    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for info in zf.infolist():
                name = info.filename.rstrip("/")
                # 跳过目录、macOS 资源、隐藏文件
                if info.is_dir() or name.startswith("__MACOSX") or Path(name).name.startswith("."):
                    continue
                basename = Path(name).name

                if not _safe_to_extract(info, budget):
                    continue

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
                        results.extend(_extract_deep(inner_data, inner_source, depth + 1, budget))
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
@limiter.limit(lambda: "20/minute")
@require_usage("zip_extractor")
def analyze():
    """接收本批 zip 文件，递归解压找出 PDF，按大小上限截断返回。

    入参：本批 zip 总大小 ≤ MAX_REQUEST_ZIP_BYTES。
    出参：本批 PDF base64 总大小 ≤ MAX_RESPONSE_B64_BYTES；超出则返回部分 + truncated=true。
    """
    try:
        files = request.files.getlist("files")
        if not files or all(not (f and f.filename) for f in files):
            return jsonify(success=False, error="请选择至少一个 zip 文件"), 400

        # ---- 单批请求体大小门禁：避免到 Vercel 网关层才被 413 砍掉 ----
        # 用 Content-Length 提前拦截，不必真把全部流读完。
        cl = request.content_length or 0
        if cl > MAX_REQUEST_ZIP_BYTES * 2:  # multipart 边界等约 1 倍开销
            return jsonify(
                success=False,
                error=f"本批上传体积过大（{cl/1024/1024:.1f}MB），前端应已自动分批；"
                      f"若仍失败请刷新页面或单批 ≤ {MAX_REQUEST_ZIP_BYTES//(1024*1024)}MB",
            ), 413

        all_pdfs: list[dict] = []
        received_bytes = 0
        skipped_oversize: list[str] = []

        for f in files:
            if not f.filename:
                continue
            if not f.filename.lower().endswith(".zip"):
                continue
            try:
                # 先看 stream 长度，提前拦掉超大单文件
                f.stream.seek(0, io.SEEK_END)
                size = f.stream.tell()
                f.stream.seek(0)
                if size == 0:
                    continue
                if size > MAX_SINGLE_FILE_BYTES:
                    skipped_oversize.append(f"{f.filename}（{size/1024/1024:.1f}MB）")
                    continue
                # 累加本批总大小，提前拦
                if received_bytes + size > MAX_REQUEST_ZIP_BYTES:
                    skipped_oversize.append(
                        f"{f.filename}（{size/1024/1024:.1f}MB，超出本批 {MAX_REQUEST_ZIP_BYTES//(1024*1024)}MB 上限）"
                    )
                    continue
                zip_bytes = f.read()
                received_bytes += len(zip_bytes)
                log.info("analyze: %s (%d bytes)", f.filename, len(zip_bytes))
                pdfs = _extract_deep(zip_bytes, f.filename)
                all_pdfs.extend(pdfs)
            except Exception as e:
                log.warning("Failed to read %s: %s", f.filename, e)

        if not all_pdfs and not skipped_oversize:
            return jsonify(success=False, error="本批没有可解压的 zip 或未提取到 PDF"), 400

        # 按内容哈希去重
        seen: set[str] = set()
        unique: list[dict] = []
        for p in all_pdfs:
            data = p.pop("data")
            h = _quick_hash(data)
            if h in seen:
                continue
            seen.add(h)
            p["data_b64"] = base64.b64encode(data).decode("ascii")
            p["size_kb"] = round(len(data) / 1024, 1)
            unique.append(p)

        # ---- 响应体大小门禁：按 base64 累计截断 ----
        kept: list[dict] = []
        truncated: list[dict] = []  # 没塞下的，附带 client 可继续请求的提示
        acc = 0
        for p in unique:
            sz = len(p["data_b64"])
            if acc + sz > MAX_RESPONSE_B64_BYTES:
                truncated.append(p)
                continue
            acc += sz
            kept.append(p)

        body: dict = {
            "success": True,
            "total": len(kept),
            "files": kept,
            "skipped_oversize": skipped_oversize,
        }
        if truncated:
            body["truncated"] = True
            body["truncated_count"] = len(truncated)
            body["truncated_msg"] = (
                f"本批还剩 {len(truncated)} 个 PDF 未返回（响应体超 "
                f"{MAX_RESPONSE_B64_BYTES//(1024*1024)}MB 上限）。"
                f"建议：① 改用更小的压缩包分批；② 减少单包内文件数。"
            )
        commit_usage("zip_extractor", success=True)
        return jsonify(body)

    except Exception as e:
        log.exception("analyze fatal error")
        return jsonify(success=False, error=f"服务器错误：{type(e).__name__}: {str(e)[:200]}"), 500


def _quick_hash(data: bytes) -> str:
    """快速内容哈希（SHA256 前 16 位，用于去重）。"""
    return hashlib.sha256(data).hexdigest()[:16]
