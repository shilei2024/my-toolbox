"""Shared resource ceilings for CPU- and memory-intensive PDF tools."""
from __future__ import annotations

from collections.abc import Sized

from flask import current_app


class PdfResourceLimitError(ValueError):
    """Raised before a PDF workload exceeds the configured processing budget."""


def enforce_pdf_file_count(files: Sized) -> None:
    limit = _positive_limit("MAX_PDF_FILES", 10)
    if len(files) > limit:
        raise PdfResourceLimitError(f"PDF 文件数量不能超过 {limit} 个")


def enforce_pdf_page_count(page_count: int) -> None:
    limit = _positive_limit("MAX_PDF_PAGES", 200)
    if page_count > limit:
        raise PdfResourceLimitError(f"PDF 页数不能超过 {limit} 页")


def _positive_limit(key: str, fallback: int) -> int:
    value = current_app.config.get(key, fallback)
    return value if isinstance(value, int) and value > 0 else fallback
