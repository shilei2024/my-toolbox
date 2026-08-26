"""Secure recursive ZIP extraction shared by the invoice workspace."""
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

MB = 1024 * 1024
DEFAULT_SINGLE_ZIP_MB = 20
DEFAULT_BATCH_ZIP_MB = 20
DEFAULT_RESPONSE_B64_MB = 48
MAX_DEPTH = 8                                 # 递归层数上限
# Limits apply before decompression. The upload limit alone cannot protect a
# worker from a highly-compressible ZIP expanding into gigabytes of memory.
MAX_ENTRY_UNCOMPRESSED_BYTES = 32 * MB
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 64 * MB
MAX_COMPRESSION_RATIO = 100


def invoice_zip_limits() -> dict[str, int]:
    """Return limits aligned with the current Flask deployment.

    The main site now runs on Tencent Cloud, so the former 3/4 MB Vercel
    gateway limits are obsolete.  Keep a 1 MB multipart safety margin below
    Flask's application-wide request cap and retain independent extraction and
    response limits to protect worker/browser memory.
    """
    app_request_bytes = int(current_app.config.get("MAX_CONTENT_LENGTH") or 25 * MB)
    request_budget = max(MB, app_request_bytes - MB)
    single_bytes = min(
        int(current_app.config.get("INVOICE_ZIP_MAX_MB", DEFAULT_SINGLE_ZIP_MB)) * MB,
        request_budget,
    )
    batch_bytes = min(
        int(current_app.config.get("INVOICE_ZIP_BATCH_MB", DEFAULT_BATCH_ZIP_MB)) * MB,
        request_budget,
    )
    response_bytes = int(
        current_app.config.get("INVOICE_ZIP_RESPONSE_MB", DEFAULT_RESPONSE_B64_MB)
    ) * MB
    return {
        "single_bytes": max(MB, single_bytes),
        "batch_bytes": max(MB, batch_bytes),
        "response_bytes": max(MB, response_bytes),
        "single_mb": max(1, single_bytes // MB),
        "batch_mb": max(1, batch_bytes // MB),
    }


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
    return analyze_uploaded_archives("zip_extractor")


def analyze_uploaded_archives(usage_tool_id: str):
    """接收本批 zip 文件，递归解压找出 PDF，按大小上限截断返回。

    Limits follow ``invoice_zip_limits()`` and the Flask request cap.
    """
    try:
        files = request.files.getlist("files")
        if not files or all(not (f and f.filename) for f in files):
            return jsonify(success=False, error="请选择至少一个 zip 文件"), 400

        limits = invoice_zip_limits()
        max_single_file_bytes = limits["single_bytes"]
        max_request_zip_bytes = limits["batch_bytes"]
        max_response_b64_bytes = limits["response_bytes"]

        # Keep multipart overhead below Flask's application-wide request cap.
        cl = request.content_length or 0
        if cl > max_request_zip_bytes + MB:
            return jsonify(
                success=False,
                error=f"本批上传体积过大（{cl/MB:.1f}MB），请保持单批不超过 {limits['batch_mb']}MB",
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
                if size > max_single_file_bytes:
                    skipped_oversize.append(
                        f"{f.filename}（{size/MB:.1f}MB，单包上限 {limits['single_mb']}MB）"
                    )
                    continue
                # 累加本批总大小，提前拦
                if received_bytes + size > max_request_zip_bytes:
                    skipped_oversize.append(
                        f"{f.filename}（{size/MB:.1f}MB，超出本批 {limits['batch_mb']}MB 上限）"
                    )
                    continue
                zip_bytes = f.read()
                received_bytes += len(zip_bytes)
                log.info("analyze: %s (%d bytes)", f.filename, len(zip_bytes))
                pdfs = _extract_deep(zip_bytes, f.filename)
                all_pdfs.extend(pdfs)
            except Exception as e:
                log.warning("Failed to read %s: %s", f.filename, e)

        if not all_pdfs and skipped_oversize:
            return jsonify(
                success=False,
                error=(
                    f"压缩包超过上传上限，请将单包控制在 {limits['single_mb']}MB、"
                    f"单批控制在 {limits['batch_mb']}MB 以内"
                ),
                skipped_oversize=skipped_oversize,
            ), 413

        if not all_pdfs:
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
            p["content_hash"] = h
            p["data_b64"] = base64.b64encode(data).decode("ascii")
            p["size_kb"] = round(len(data) / 1024, 1)
            unique.append(p)

        # ---- 响应体大小门禁：按 base64 累计截断 ----
        kept: list[dict] = []
        truncated: list[dict] = []
        acc = 0
        for p in unique:
            sz = len(p["data_b64"])
            if acc + sz > max_response_b64_bytes:
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
                f"{max_response_b64_bytes//MB}MB 上限）。"
                f"建议：① 改用更小的压缩包分批；② 减少单包内文件数。"
            )
        commit_usage(usage_tool_id, success=True)
        return jsonify(body)

    except Exception:
        log.exception("analyze fatal error")
        return jsonify(success=False, error="发票压缩包处理失败，请稍后重试"), 500


def _quick_hash(data: bytes) -> str:
    """快速内容哈希（SHA256 前 16 位，用于去重）。"""
    return hashlib.sha256(data).hexdigest()[:16]
