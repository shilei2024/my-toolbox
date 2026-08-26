"""Unified invoice extraction, preview, printing and export workspace."""
from __future__ import annotations

from flask import Blueprint, render_template

from auth.decorators import remaining_for, require_usage
from extensions import limiter
from tools.zip_extractor import analyze_uploaded_archives, invoice_zip_limits

tool_bp = Blueprint("invoice_printer", __name__, template_folder="templates")


@tool_bp.route("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "invoice_printer",
            "name": "发票提取与批量打印",
            "icon": "bi-printer",
            "color": "#198754",
        },
        remaining=remaining_for("invoice_printer"),
        body_template="tools/invoice_printer/_body.html",
        invoice_limits=invoice_zip_limits(),
    )


@tool_bp.post("/analyze")
@limiter.limit(lambda: "20/minute")
@require_usage("invoice_printer")
def analyze():
    """Securely extract PDFs from ZIP files into the browser-side queue."""
    return analyze_uploaded_archives("invoice_printer")
