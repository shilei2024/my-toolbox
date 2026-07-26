"""
批量发票打印 — 客户端驱动的打印/预览/导出工具。

与 Vercel 兼容：全部逻辑在浏览器端完成（FileReader + JSZip + Blob），
后端只负责渲染 HTML 页面，不涉及文件上传/存储/处理。
"""
from __future__ import annotations

from flask import Blueprint, render_template

from auth.decorators import remaining_for

tool_bp = Blueprint("invoice_printer", __name__, template_folder="templates")


@tool_bp.route("/")
def index():
    return render_template(
        "tools_base.html",
        tool={
            "id": "invoice_printer",
            "name": "批量发票打印",
            "icon": "bi-printer",
            "color": "#198754",
        },
        remaining=remaining_for("invoice_printer"),
        body_template="tools/invoice_printer/_body.html",
    )
