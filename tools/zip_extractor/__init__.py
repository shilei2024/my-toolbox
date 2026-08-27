"""Secure recursive ZIP extraction shared by the invoice workspace."""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import zipfile
from pathlib import PurePosixPath

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
ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


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


def _member_within_limits(info: zipfile.ZipInfo) -> bool:
    """Reject a dangerous member before reading even its signature."""
    if info.file_size > MAX_ENTRY_UNCOMPRESSED_BYTES:
        log.warning("ZIP member exceeds uncompressed limit: %s (%d bytes)", info.filename, info.file_size)
        return False
    if info.file_size and (info.compress_size == 0 or info.file_size / info.compress_size > MAX_COMPRESSION_RATIO):
        log.warning("ZIP member exceeds compression-ratio limit: %s", info.filename)
        return False
    return True


def _safe_to_extract(info: zipfile.ZipInfo, budget: _ExtractionBudget) -> bool:
    """Reject dangerous ZIP members without materialising their payload."""
    if not _member_within_limits(info):
        return False
    if not budget.reserve(info.file_size):
        log.warning("ZIP archive exceeds cumulative extraction limit at: %s", info.filename)
        return False
    return True


def _member_signature(zf: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    """Read only enough bytes to identify extensionless PDF/ZIP members."""
    try:
        with zf.open(info, "r") as member:
            return member.read(5)
    except Exception as exc:
        log.warning("read ZIP member signature failed %s: %s", info.filename, exc)
        return b""


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
    diagnostics: dict | None = None,
) -> list[dict]:
    """
    递归解压 zip 字节流，最深 8 层。
    返回找到的所有 PDF 文件列表 [{filename, size, path_chain, data}].
    """
    if depth > MAX_DEPTH:
        if diagnostics is not None:
            diagnostics.setdefault("issues", []).append(f"嵌套层数超过 {MAX_DEPTH} 层")
        return []
    budget = budget or _ExtractionBudget()
    diagnostics = diagnostics if diagnostics is not None else {"issues": [], "nested_archives": 0}

    results = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            diagnostics["archives_opened"] = diagnostics.get("archives_opened", 0) + 1
            for info in zf.infolist():
                name = info.filename.rstrip("/\\")
                normalized_name = name.replace("\\", "/")
                # 跳过目录、macOS 资源、隐藏文件
                if info.is_dir() or normalized_name.startswith("__MACOSX"):
                    continue
                basename = PurePosixPath(normalized_name).name
                if basename.startswith("."):
                    continue

                lower_name = basename.lower()
                member_kind = "pdf" if lower_name.endswith(".pdf") else (
                    "zip" if lower_name.endswith((".zip", ".zipx")) else ""
                )

                # 部分发票平台生成的内层压缩包或 PDF 没有可靠扩展名，
                # 读取最少量文件头识别真实格式，避免递归链路静默中断。
                if not member_kind:
                    if not _member_within_limits(info):
                        continue
                    signature = _member_signature(zf, info)
                    if signature.startswith(b"%PDF-"):
                        member_kind = "pdf"
                    elif signature[:4] in ZIP_SIGNATURES:
                        member_kind = "zip"
                    else:
                        continue

                if not _safe_to_extract(info, budget):
                    continue

                if member_kind == "pdf":
                    try:
                        data = zf.read(info)
                        results.append({
                            "filename": basename if lower_name.endswith(".pdf") else f"{basename}.pdf",
                            "size": len(data),
                            "path_chain": [source_name, *normalized_name.split("/")],
                            "data": data,
                        })
                    except Exception as e:
                        reason = "PDF 所在压缩包已加密" if "password" in str(e).lower() else "PDF 读取失败"
                        diagnostics.setdefault("issues", []).append(f"{basename}：{reason}")
                        log.warning("read PDF failed %s: %s", info.filename, e)

                elif member_kind == "zip":
                    try:
                        diagnostics["nested_archives"] = diagnostics.get("nested_archives", 0) + 1
                        inner_data = zf.read(info)
                        inner_source = f"{source_name} → {basename}"
                        results.extend(
                            _extract_deep(
                                inner_data,
                                inner_source,
                                depth + 1,
                                budget,
                                diagnostics,
                            )
                        )
                    except Exception as e:
                        reason = "内层压缩包已加密" if "password" in str(e).lower() else "内层压缩包读取失败"
                        diagnostics.setdefault("issues", []).append(f"{basename}：{reason}")
                        log.warning("read inner zip failed %s: %s", info.filename, e)

    except zipfile.BadZipFile:
        diagnostics.setdefault("issues", []).append(f"{source_name}：不是有效 ZIP 或文件已损坏")
        log.warning("BadZipFile from %s", source_name)
    except Exception as e:
        diagnostics.setdefault("issues", []).append(f"{source_name}：解压异常")
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
        archive_results: list[dict] = []

        for f in files:
            if not f.filename:
                continue
            if not f.filename.lower().endswith(".zip"):
                continue
            archive_result = {"name": f.filename, "pdf_count": 0}
            archive_results.append(archive_result)
            try:
                # 先看 stream 长度，提前拦掉超大单文件
                f.stream.seek(0, io.SEEK_END)
                size = f.stream.tell()
                f.stream.seek(0)
                if size == 0:
                    archive_result["skipped"] = True
                    continue
                if size > max_single_file_bytes:
                    archive_result["skipped"] = True
                    skipped_oversize.append(
                        f"{f.filename}（{size/MB:.1f}MB，单包上限 {limits['single_mb']}MB）"
                    )
                    continue
                # 累加本批总大小，提前拦
                if received_bytes + size > max_request_zip_bytes:
                    archive_result["skipped"] = True
                    skipped_oversize.append(
                        f"{f.filename}（{size/MB:.1f}MB，超出本批 {limits['batch_mb']}MB 上限）"
                    )
                    continue
                zip_bytes = f.read()
                received_bytes += len(zip_bytes)
                log.info("analyze: %s (%d bytes)", f.filename, len(zip_bytes))
                diagnostics = {"issues": [], "nested_archives": 0, "archives_opened": 0}
                pdfs = _extract_deep(zip_bytes, f.filename, diagnostics=diagnostics)
                archive_result["pdf_count"] = len(pdfs)
                archive_result["nested_archives"] = diagnostics["nested_archives"]
                if diagnostics["issues"]:
                    archive_result["issues"] = diagnostics["issues"][:5]
                all_pdfs.extend(pdfs)
            except Exception as e:
                archive_result["error"] = True
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
            return jsonify(
                success=False,
                error="本批压缩包未提取到 PDF，请查看每个文件的具体原因",
                archive_results=archive_results,
            ), 400

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
            "archive_results": archive_results,
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
