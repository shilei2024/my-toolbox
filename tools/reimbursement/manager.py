"""Normalized reimbursement manager APIs and template-faithful XLS exports."""
from __future__ import annotations

import io
import json
import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy import case, func, or_

from extensions import csrf, db
from models import (
    ReimbursementAuxDetail,
    ReimbursementCategory,
    ReimbursementInvoice,
    ReimbursementPeriod,
    ReimbursementRecord,
)


DEFAULT_CATEGORIES = [
    ("招待费", "entertainment", "#f97316"),
    ("出差交通费", "travel_transport", "#2563eb"),
    ("出差住宿费", "travel_hotel", "#7c3aed"),
    ("市内交通费", "local_transport", "#0891b2"),
    ("车辆费用", "vehicle", "#0f766e"),
    ("通讯费", "communication", "#4f46e5"),
    ("办公费", "office_supplies", "#64748b"),
    ("快递费", "delivery", "#a16207"),
    ("福利", "welfare", "#db2777"),
]
STATUS_LABELS = {"pending": "待报销", "approved": "已通过", "rejected": "已驳回"}
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
COVER_TEMPLATE = TEMPLATE_DIR / "报销封面及费用分类表_母版.xls"
DETAIL_TEMPLATE = TEMPLATE_DIR / "应酬费、出差明细、派车单_母版.xls"


def _owner() -> tuple[str, str]:
    from auth.decorators import ensure_anon_id
    from flask_login import current_user

    if current_user.is_authenticated:
        return "user", str(current_user.id)
    client_id = (request.headers.get("X-RB-Anon-Id") or "").strip()
    return "anon", client_id or ensure_anon_id()


def _payload() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def _date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _money(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _month_index(year: int, month: int) -> int:
    return year * 12 + month - 1


def _period_parts(name: str) -> tuple[int, int, int, int]:
    """Infer rolling two-month dates from common Chinese period names."""
    now = datetime.now()
    m = re.search(r"(?:(\d{4})年)?\s*(\d{1,2})\s*[-~至]\s*(?:(\d{4})年)?\s*(\d{1,2})月?", name)
    if not m:
        m = re.search(r"(?:(\d{4})年)?\s*(\d{1,2})月", name)
        sm = int(m.group(2)) if m else now.month
        sy = int(m.group(1)) if m and m.group(1) else now.year
        em = sm % 12 + 1
        return sy, sm, sy + (1 if sm == 12 else 0), em
    sy = int(m.group(1) or now.year)
    sm = int(m.group(2))
    em = int(m.group(4))
    ey = int(m.group(3) or (sy + 1 if em < sm else sy))
    return sy, sm, ey, em


def _period_name(sy: int, sm: int, ey: int, em: int) -> str:
    return f"{sy}年{sm}-{em}月" if sy == ey else f"{sy}年{sm}月-{ey}年{em}月"


def _category_dict(cat: ReimbursementCategory) -> dict[str, Any]:
    return {
        "id": cat.id,
        "name": cat.name,
        "export_key": cat.export_key,
        "color": cat.color,
        "description": cat.description,
        "sort_order": cat.sort_order,
    }


def _period_dict(period: ReimbursementPeriod, with_stats: bool = True) -> dict[str, Any]:
    result = {
        "id": period.id,
        "name": period.name,
        "start_year": period.start_year,
        "start_month": period.start_month,
        "end_year": period.end_year,
        "end_month": period.end_month,
        "is_active": period.is_active,
        "employee_name": period.employee_name,
        "department": period.department,
        "office": period.office,
        "reimbursement_date": period.reimbursement_date.isoformat() if period.reimbursement_date else "",
    }
    if with_stats:
        count, total = (
            db.session.query(func.count(ReimbursementInvoice.id), func.coalesce(func.sum(ReimbursementInvoice.total_amount), 0))
            .filter(ReimbursementInvoice.period_id == period.id)
            .one()
        )
        result.update(invoice_count=int(count), total_amount=float(total or 0))
    return result


def _invoice_dict(invoice: ReimbursementInvoice, category: ReimbursementCategory | None = None) -> dict[str, Any]:
    if category is None and invoice.category_id:
        category = db.session.get(ReimbursementCategory, invoice.category_id)
    return {
        "id": invoice.id,
        "period_id": invoice.period_id,
        "category_id": invoice.category_id,
        "category": _category_dict(category) if category else None,
        "invoice_number": invoice.invoice_number,
        "invoice_date": invoice.invoice_date.isoformat() if invoice.invoice_date else "",
        "amount": float(invoice.amount or 0),
        "tax_amount": float(invoice.tax_amount or 0),
        "total_amount": float(invoice.total_amount or 0),
        "vendor": invoice.vendor,
        "description": invoice.description,
        "file_url": invoice.file_url,
        "file_name": invoice.file_name,
        "file_size": invoice.file_size,
        "status": invoice.status,
        "status_label": STATUS_LABELS.get(invoice.status, invoice.status),
        "product_line": invoice.product_line,
        "product_line_code": invoice.product_line_code,
        "office": invoice.office,
        "customer_level": invoice.customer_level,
        "remarks": invoice.remarks,
        "upload_date": invoice.upload_date.isoformat() if invoice.upload_date else "",
    }


def _seed_categories(owner_type: str, owner_id: str) -> list[ReimbursementCategory]:
    categories = (
        ReimbursementCategory.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementCategory.sort_order, ReimbursementCategory.id)
        .all()
    )
    if categories:
        return categories
    for index, (name, key, color) in enumerate(DEFAULT_CATEGORIES):
        db.session.add(
            ReimbursementCategory(
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                export_key=key,
                color=color,
                sort_order=(index + 1) * 10,
            )
        )
    db.session.commit()
    return (
        ReimbursementCategory.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementCategory.sort_order)
        .all()
    )


def _migrate_legacy(owner_type: str, owner_id: str) -> None:
    """One-time best-effort migration from the former period JSON store."""
    if ReimbursementPeriod.query.filter_by(owner_type=owner_type, owner_id=owner_id).first():
        return
    records = ReimbursementRecord.query.filter_by(owner_type=owner_type, owner_id=owner_id).all()
    if not records:
        return
    categories = {c.export_key: c for c in _seed_categories(owner_type, owner_id)}
    for index, record in enumerate(records):
        data = json.loads(record.data_json or "{}")
        header = data.get("header") or {}
        sy, sm, ey, em = _period_parts(record.period)
        period = ReimbursementPeriod(
            owner_type=owner_type,
            owner_id=owner_id,
            name=record.period,
            start_year=sy,
            start_month=sm,
            end_year=ey,
            end_month=em,
            is_active=index == 0,
            employee_name=header.get("employee_name", ""),
            department=header.get("department", ""),
            office=header.get("office", "深圳办"),
            reimbursement_date=_date(header.get("date")),
        )
        db.session.add(period)
        db.session.flush()
        for old in data.get("invoices") or []:
            values = old.get("data") or {}
            key = old.get("expense_type") or ""
            total = _money(values.get("total_amount"))
            tax = _money(values.get("tax_amount"))
            amount = _money(values.get("amount_excluding_tax")) or total - tax
            db.session.add(
                ReimbursementInvoice(
                    owner_type=owner_type,
                    owner_id=owner_id,
                    period_id=period.id,
                    category_id=categories.get(key).id if categories.get(key) else None,
                    invoice_number=values.get("invoice_number", ""),
                    invoice_date=_date(values.get("invoice_date")),
                    amount=amount,
                    tax_amount=tax,
                    total_amount=total,
                    vendor=values.get("seller_name", ""),
                    description=values.get("description", ""),
                    file_url=old.get("full_url") or old.get("preview_url") or "",
                    file_name=old.get("original_name") or old.get("filename") or "",
                    product_line=old.get("product_line", ""),
                    product_line_code=old.get("product_line_code", ""),
                    office=old.get("office", ""),
                    customer_level=old.get("customer_level", ""),
                    remarks=old.get("remarks", ""),
                )
            )
        for kind, key in (("entertainment", "entertainment"), ("vehicle", "vehicles"), ("travel", "travels")):
            for position, row in enumerate(data.get(key) or []):
                db.session.add(
                    ReimbursementAuxDetail(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        period_id=period.id,
                        kind=kind,
                        sort_order=position,
                        data_json=json.dumps(row, ensure_ascii=False),
                    )
                )
    db.session.commit()


def _owned_period(period_id: int, owner_type: str, owner_id: str) -> ReimbursementPeriod | None:
    return ReimbursementPeriod.query.filter_by(
        id=period_id, owner_type=owner_type, owner_id=owner_id
    ).first()


def _owned_category(category_id: int | None, owner_type: str, owner_id: str) -> ReimbursementCategory | None:
    if not category_id:
        return None
    return ReimbursementCategory.query.filter_by(
        id=category_id, owner_type=owner_type, owner_id=owner_id
    ).first()


def _validate_period(data: dict[str, Any], current_id: int | None = None) -> tuple[dict[str, Any] | None, str | None]:
    try:
        sy, sm = int(data["start_year"]), int(data["start_month"])
        ey, em = int(data["end_year"]), int(data["end_month"])
    except (KeyError, TypeError, ValueError):
        return None, "请输入完整的起止年月"
    if not (1 <= sm <= 12 and 1 <= em <= 12):
        return None, "月份必须在 1 到 12 之间"
    if _month_index(ey, em) < _month_index(sy, sm):
        return None, "结束月份不能早于开始月份"
    if _month_index(ey, em) - _month_index(sy, sm) != 1:
        return None, "报销周期必须连续覆盖两个月"
    name = str(data.get("name") or _period_name(sy, sm, ey, em)).strip()
    if not name:
        return None, "周期名称不能为空"
    return {"name": name, "start_year": sy, "start_month": sm, "end_year": ey, "end_month": em}, None


def _set_active(period: ReimbursementPeriod) -> None:
    ReimbursementPeriod.query.filter_by(
        owner_type=period.owner_type, owner_id=period.owner_id
    ).update({"is_active": False})
    period.is_active = True


def _summary(period: ReimbursementPeriod) -> dict[str, Any]:
    categories = _seed_categories(period.owner_type, period.owner_id)
    invoices = ReimbursementInvoice.query.filter_by(period_id=period.id).all()
    by_category = []
    for category in categories:
        rows = [item for item in invoices if item.category_id == category.id]
        by_category.append(
            {
                **_category_dict(category),
                "invoice_count": len(rows),
                "amount": round(sum(float(item.amount or 0) for item in rows), 2),
                "tax_amount": round(sum(float(item.tax_amount or 0) for item in rows), 2),
                "total_amount": round(sum(float(item.total_amount or 0) for item in rows), 2),
            }
        )
    by_status = []
    for status, label in STATUS_LABELS.items():
        rows = [item for item in invoices if item.status == status]
        by_status.append(
            {
                "status": status,
                "label": label,
                "invoice_count": len(rows),
                "total_amount": round(sum(float(item.total_amount or 0) for item in rows), 2),
            }
        )
    return {
        "period": _period_dict(period),
        "by_category": by_category,
        "by_status": by_status,
        "invoice_count": len(invoices),
        "amount": round(sum(float(item.amount or 0) for item in invoices), 2),
        "tax_amount": round(sum(float(item.tax_amount or 0) for item in invoices), 2),
        "total_amount": round(sum(float(item.total_amount or 0) for item in invoices), 2),
    }


def _aux_rows(period_id: int) -> dict[str, list[dict[str, Any]]]:
    result = {"entertainment": [], "vehicle": [], "travel": []}
    rows = (
        ReimbursementAuxDetail.query.filter_by(period_id=period_id)
        .order_by(ReimbursementAuxDetail.kind, ReimbursementAuxDetail.sort_order)
        .all()
    )
    for row in rows:
        value = json.loads(row.data_json or "{}")
        value["id"] = row.id
        result.setdefault(row.kind, []).append(value)
    return result


def _number_to_chinese(amount: float) -> str:
    from . import _number_to_chinese as converter

    return converter(amount)


def _cover_payload(period: ReimbursementPeriod) -> dict[str, Any]:
    invoices = ReimbursementInvoice.query.filter_by(period_id=period.id).all()
    categories = {c.id: c for c in _seed_categories(period.owner_type, period.owner_id)}
    groups: dict[str, dict[str, Any]] = {}
    grand = {key: 0.0 for _, key, _ in DEFAULT_CATEGORIES}
    levels: dict[str, dict[str, float]] = {}
    for invoice in invoices:
        key = f"{invoice.product_line_code}|{invoice.product_line}"
        group = groups.setdefault(
            key,
            {
                "product_line": invoice.product_line or "未分类",
                "code": invoice.product_line_code or "-",
                "office": invoice.office or period.office,
                "totals": {export_key: 0.0 for _, export_key, _ in DEFAULT_CATEGORIES},
                "remarks": [],
            },
        )
        category = categories.get(invoice.category_id)
        export_key = category.export_key if category else "other"
        total = float(invoice.total_amount or 0)
        if export_key in group["totals"]:
            group["totals"][export_key] += total
            grand[export_key] += total
        if invoice.remarks and invoice.remarks not in group["remarks"]:
            group["remarks"].append(invoice.remarks)
        level = invoice.customer_level or "未分类"
        values = levels.setdefault(level, {"entertainment": 0.0, "travel": 0.0, "other": 0.0, "total": 0.0})
        if export_key == "entertainment":
            values["entertainment"] += total
        elif export_key in {"travel_transport", "travel_hotel"}:
            values["travel"] += total
        else:
            values["other"] += total
        values["total"] += total
    total_all = round(sum(grand.values()), 2)
    return {
        "header": {
            "employee_name": period.employee_name,
            "department": period.department,
            "office": period.office,
            "date": period.reimbursement_date.isoformat() if period.reimbursement_date else "",
            "period": period.name,
        },
        "groups": sorted(groups.values(), key=lambda item: item["code"]),
        "grand_totals": grand,
        "level_groups": [{"level": key, **value} for key, value in levels.items()],
        "total_all": total_all,
        "total_cn": _number_to_chinese(total_all),
    }


def _template_copy(template: Path):
    import xlrd
    from xlutils.copy import copy

    source = xlrd.open_workbook(str(template), formatting_info=True)
    target = copy(source)
    for index, source_sheet in enumerate(source.sheets()):
        target_sheet = target.get_sheet(index)
        target_sheet.set_vert_page_breaks(list(source_sheet.vertical_page_breaks))
        target_sheet.set_horz_page_breaks(list(source_sheet.horizontal_page_breaks))
    return source, target


def _write_cell(source, target, sheet_index: int, row: int, col: int, value: Any) -> None:
    """Overwrite a copied cell while reusing the exact source XF style."""
    sheet = target.get_sheet(sheet_index)
    target_row = sheet.row(row)
    old_cell = target_row._Row__cells.get(col)
    old_xf = old_cell.xf_idx if old_cell is not None else 0
    sheet.write(row, col, value)
    target_row._Row__cells[col].xf_idx = old_xf


def _excel_date(value: str) -> date | str:
    return _date(value) or ""


def _build_cover_xls(data: dict[str, Any]) -> io.BytesIO:
    groups = data["groups"]
    if len(groups) > 12:
        raise ValueError("封面母版最多容纳 12 条产品线汇总，请拆分报销周期后导出")
    source, target = _template_copy(COVER_TEMPLATE)
    header, total = data["header"], data["total_all"]
    # Sheet 1 remains the original product-line reference sheet.
    cover_index, category_index = 1, 2
    _write_cell(source, target, cover_index, 3, 2, header["employee_name"])
    _write_cell(source, target, cover_index, 3, 7, header["department"])
    _write_cell(source, target, cover_index, 3, 12, _excel_date(header["date"]))
    export_keys = [key for _, key, _ in DEFAULT_CATEGORIES]
    for row in range(6, 18):
        for col in range(15):
            _write_cell(source, target, cover_index, row, col, "")
    for offset, group in enumerate(groups):
        row = 6 + offset
        values = [
            offset + 1,
            group["product_line"],
            group["code"],
            group["office"],
            header["period"],
            *[round(group["totals"].get(key, 0), 2) or "" for key in export_keys],
            "；".join(group["remarks"]),
        ]
        for col, value in enumerate(values):
            _write_cell(source, target, cover_index, row, col, value)
    for col, key in enumerate(export_keys, 5):
        _write_cell(source, target, cover_index, 18, col, round(data["grand_totals"].get(key, 0), 2))
    _write_cell(source, target, cover_index, 20, 7, total)
    _write_cell(source, target, cover_index, 21, 7, data["total_cn"])
    _write_cell(source, target, cover_index, 23, 2, header["employee_name"])
    _write_cell(source, target, cover_index, 24, 2, _excel_date(header["date"]))

    level_map = {item["level"]: item for item in data["level_groups"]}
    for offset, level in enumerate(("0-1", "level 1", "level 2", "level 3")):
        row = 2 + offset
        item = level_map.get(level, {})
        for col, value in {
            0: offset + 1,
            1: level,
            2: round(item.get("entertainment", 0), 2),
            3: round(item.get("travel", 0), 2),
            5: round(item.get("other", 0), 2),
            6: round(item.get("total", 0), 2),
            7: "",
        }.items():
            _write_cell(source, target, category_index, row, col, value)
    _write_cell(source, target, category_index, 7, 4, total)
    _write_cell(source, target, category_index, 8, 4, data["total_cn"])
    _write_cell(source, target, category_index, 10, 2, header["employee_name"])
    _write_cell(source, target, category_index, 11, 2, _excel_date(header["date"]))
    output = io.BytesIO()
    target.save(output)
    output.seek(0)
    return output


def _build_detail_xls(data: dict[str, Any], aux: dict[str, list[dict[str, Any]]]) -> io.BytesIO:
    entertainment, vehicles, travels = aux["entertainment"], aux["vehicle"], aux["travel"]
    if len(entertainment) > 9:
        raise ValueError("应酬费母版最多容纳 9 条明细")
    if len(vehicles) > 11:
        raise ValueError("派车单母版最多容纳 11 条明细")
    if len(travels) > 18:
        raise ValueError("出差明细母版最多容纳 18 条明细")
    source, target = _template_copy(DETAIL_TEMPLATE)
    header = data["header"]

    _write_cell(source, target, 0, 1, 0, f"员工姓名：{header['employee_name']}")
    for row in range(3, 12):
        for col in range(8):
            _write_cell(source, target, 0, row, col, "")
    ent_total = 0.0
    for offset, item in enumerate(entertainment):
        amount = float(item.get("amount") or 0)
        ent_total += amount
        values = [
            _excel_date(item.get("date", "")),
            item.get("category", ""),
            item.get("place", ""),
            item.get("customer", ""),
            item.get("participants", ""),
            amount,
            item.get("purpose", ""),
            item.get("approval", ""),
        ]
        for col, value in enumerate(values):
            _write_cell(source, target, 0, 3 + offset, col, value)
    _write_cell(source, target, 0, 12, 5, round(ent_total, 2))

    _write_cell(source, target, 1, 1, 0, f"员工姓名：{header['employee_name']}")
    _write_cell(source, target, 1, 1, 9, f" {header['period']}派车单")
    for row in range(4, 15):
        for col in range(10):
            _write_cell(source, target, 1, row, col, "")
    totals = [0.0, 0.0, 0.0]
    for offset, item in enumerate(vehicles):
        km = float(item.get("km_total") or 0)
        toll = float(item.get("toll_fee") or 0)
        parking = float(item.get("parking_fee") or 0)
        totals = [totals[0] + km, totals[1] + toll, totals[2] + parking]
        date_value = _date(item.get("date"))
        compact_date = int(date_value.strftime("%Y%m%d")) if date_value else ""
        values = [
            compact_date,
            item.get("from_location", ""),
            item.get("to_location", ""),
            item.get("contact", ""),
            item.get("km_start", ""),
            item.get("km_end", ""),
            km,
            toll,
            parking,
            item.get("remarks", ""),
        ]
        for col, value in enumerate(values):
            _write_cell(source, target, 1, 4 + offset, col, value)
    for col, value in zip((6, 7, 8), totals):
        _write_cell(source, target, 1, 15, col, round(value, 2))

    _write_cell(source, target, 2, 1, 0, f"员工姓名：{header['employee_name']}")
    for row in range(3, 21):
        for col in range(6):
            _write_cell(source, target, 2, row, col, "")
    for offset, item in enumerate(travels):
        values = [
            _excel_date(item.get("date", "")),
            item.get("location", ""),
            item.get("customer", ""),
            item.get("expense_type", ""),
            float(item.get("amount") or 0),
            item.get("purpose", ""),
        ]
        for col, value in enumerate(values):
            _write_cell(source, target, 2, 3 + offset, col, value)
    output = io.BytesIO()
    target.save(output)
    output.seek(0)
    return output


def register_routes(bp: Blueprint) -> None:
    @bp.get("/api/bootstrap")
    def bootstrap():
        owner_type, owner_id = _owner()
        _seed_categories(owner_type, owner_id)
        _migrate_legacy(owner_type, owner_id)
        periods = (
            ReimbursementPeriod.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementPeriod.start_year.desc(), ReimbursementPeriod.start_month.desc())
            .all()
        )
        categories = (
            ReimbursementCategory.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementCategory.sort_order, ReimbursementCategory.id)
            .all()
        )
        invoices = (
            ReimbursementInvoice.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementInvoice.created_at.desc())
            .limit(5)
            .all()
        )
        total_count, total_amount, pending_count = (
            db.session.query(
                func.count(ReimbursementInvoice.id),
                func.coalesce(func.sum(ReimbursementInvoice.total_amount), 0),
                func.coalesce(func.sum(case((ReimbursementInvoice.status == "pending", 1), else_=0)), 0),
            )
            .filter(ReimbursementInvoice.owner_type == owner_type, ReimbursementInvoice.owner_id == owner_id)
            .one()
        )
        return jsonify(
            success=True,
            periods=[_period_dict(item) for item in periods],
            categories=[_category_dict(item) for item in categories],
            recent=[_invoice_dict(item) for item in invoices],
            stats={
                "invoice_count": int(total_count),
                "total_amount": float(total_amount or 0),
                "pending_count": int(pending_count or 0),
            },
        )

    @bp.post("/api/periods")
    @csrf.exempt
    def create_period():
        owner_type, owner_id = _owner()
        values, error = _validate_period(_payload())
        if error:
            return jsonify(error=error), 400
        duplicate = ReimbursementPeriod.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, name=values["name"]
        ).first()
        if duplicate:
            return jsonify(error="同名周期已存在"), 409
        exact = ReimbursementPeriod.query.filter_by(
            owner_type=owner_type,
            owner_id=owner_id,
            start_year=values["start_year"],
            start_month=values["start_month"],
            end_year=values["end_year"],
            end_month=values["end_month"],
        ).first()
        if exact:
            return jsonify(error="相同起止月份的周期已存在"), 409
        period = ReimbursementPeriod(owner_type=owner_type, owner_id=owner_id, **values)
        if not ReimbursementPeriod.query.filter_by(owner_type=owner_type, owner_id=owner_id).first():
            period.is_active = True
        db.session.add(period)
        db.session.commit()
        return jsonify(success=True, period=_period_dict(period)), 201

    @bp.post("/api/periods/next")
    @csrf.exempt
    def create_next_period():
        owner_type, owner_id = _owner()
        latest = (
            ReimbursementPeriod.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementPeriod.end_year.desc(), ReimbursementPeriod.end_month.desc())
            .first()
        )
        if latest:
            sy, sm = latest.end_year, latest.end_month
        else:
            today = date.today()
            sy, sm = today.year, today.month
        em = sm % 12 + 1
        ey = sy + (1 if sm == 12 else 0)
        period = ReimbursementPeriod(
            owner_type=owner_type,
            owner_id=owner_id,
            name=_period_name(sy, sm, ey, em),
            start_year=sy,
            start_month=sm,
            end_year=ey,
            end_month=em,
            is_active=not bool(latest),
        )
        duplicate = ReimbursementPeriod.query.filter_by(
            owner_type=owner_type,
            owner_id=owner_id,
            start_year=sy,
            start_month=sm,
            end_year=ey,
            end_month=em,
        ).first()
        if duplicate:
            return jsonify(error="下一周期已存在", period=_period_dict(duplicate)), 409
        db.session.add(period)
        db.session.commit()
        return jsonify(success=True, period=_period_dict(period)), 201

    @bp.put("/api/periods/<int:period_id>")
    @csrf.exempt
    def update_period(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        data = _payload()
        if {"start_year", "start_month", "end_year", "end_month"} <= data.keys():
            values, error = _validate_period(data, period_id)
            if error:
                return jsonify(error=error), 400
            for key, value in values.items():
                setattr(period, key, value)
        for key in ("employee_name", "department", "office"):
            if key in data:
                setattr(period, key, str(data[key] or "").strip())
        if "reimbursement_date" in data:
            period.reimbursement_date = _date(data["reimbursement_date"])
        if data.get("is_active"):
            _set_active(period)
        db.session.commit()
        return jsonify(success=True, period=_period_dict(period))

    @bp.delete("/api/periods/<int:period_id>")
    @csrf.exempt
    def remove_period(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        invoice_count = ReimbursementInvoice.query.filter_by(period_id=period.id).count()
        if invoice_count and request.args.get("force") != "1":
            return jsonify(error="该周期已有发票，请二次确认", invoice_count=invoice_count, needs_confirmation=True), 409
        ReimbursementAuxDetail.query.filter_by(period_id=period.id).delete()
        ReimbursementInvoice.query.filter_by(period_id=period.id).delete()
        db.session.delete(period)
        db.session.commit()
        return jsonify(success=True)

    @bp.get("/api/categories")
    def list_categories():
        owner_type, owner_id = _owner()
        return jsonify(categories=[_category_dict(item) for item in _seed_categories(owner_type, owner_id)])

    @bp.post("/api/categories")
    @csrf.exempt
    def create_category():
        owner_type, owner_id = _owner()
        data = _payload()
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify(error="类别名称不能为空"), 400
        if ReimbursementCategory.query.filter_by(owner_type=owner_type, owner_id=owner_id, name=name).first():
            return jsonify(error="类别名称已存在"), 409
        category = ReimbursementCategory(
            owner_type=owner_type,
            owner_id=owner_id,
            name=name,
            export_key=str(data.get("export_key") or "other"),
            color=str(data.get("color") or "#64748b"),
            description=str(data.get("description") or ""),
            sort_order=int(data.get("sort_order") or 100),
        )
        db.session.add(category)
        db.session.commit()
        return jsonify(success=True, category=_category_dict(category)), 201

    @bp.put("/api/categories/<int:category_id>")
    @csrf.exempt
    def update_category(category_id: int):
        owner_type, owner_id = _owner()
        category = _owned_category(category_id, owner_type, owner_id)
        if not category:
            return jsonify(error="类别不存在"), 404
        data = _payload()
        for key in ("name", "export_key", "color", "description"):
            if key in data:
                setattr(category, key, str(data[key] or "").strip())
        if "sort_order" in data:
            category.sort_order = int(data["sort_order"])
        db.session.commit()
        return jsonify(success=True, category=_category_dict(category))

    @bp.delete("/api/categories/<int:category_id>")
    @csrf.exempt
    def remove_category(category_id: int):
        owner_type, owner_id = _owner()
        category = _owned_category(category_id, owner_type, owner_id)
        if not category:
            return jsonify(error="类别不存在"), 404
        invoices = ReimbursementInvoice.query.filter_by(category_id=category.id)
        count = invoices.count()
        migrate_to = request.args.get("migrate_to", type=int)
        if count and not migrate_to:
            return jsonify(error="该类别仍有关联发票，请先选择迁移目标类别", invoice_count=count, needs_migration=True), 409
        if migrate_to:
            target = _owned_category(migrate_to, owner_type, owner_id)
            if not target or target.id == category.id:
                return jsonify(error="迁移目标类别无效"), 400
            invoices.update({"category_id": target.id})
        db.session.delete(category)
        db.session.commit()
        return jsonify(success=True)

    @bp.get("/api/invoices")
    def list_invoices():
        owner_type, owner_id = _owner()
        query = ReimbursementInvoice.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        period_id = request.args.get("period_id", type=int)
        category_id = request.args.get("category_id", type=int)
        status = (request.args.get("status") or "").strip()
        search = (request.args.get("q") or "").strip()
        if period_id:
            query = query.filter(ReimbursementInvoice.period_id == period_id)
        if category_id:
            query = query.filter(ReimbursementInvoice.category_id == category_id)
        if status in STATUS_LABELS:
            query = query.filter(ReimbursementInvoice.status == status)
        if search:
            term = f"%{search}%"
            query = query.filter(or_(ReimbursementInvoice.invoice_number.ilike(term), ReimbursementInvoice.vendor.ilike(term)))
        page = max(request.args.get("page", 1, type=int), 1)
        per_page = min(max(request.args.get("per_page", 20, type=int), 1), 100)
        total = query.count()
        rows = query.order_by(ReimbursementInvoice.invoice_date.desc(), ReimbursementInvoice.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
        return jsonify(
            invoices=[_invoice_dict(item) for item in rows],
            pagination={"page": page, "per_page": per_page, "total": total, "pages": max(1, (total + per_page - 1) // per_page)},
        )

    def save_invoice(invoice: ReimbursementInvoice, data: dict[str, Any]) -> str | None:
        period = _owned_period(int(data.get("period_id") or 0), invoice.owner_type, invoice.owner_id)
        if not period:
            return "请选择有效的报销周期"
        category = _owned_category(data.get("category_id"), invoice.owner_type, invoice.owner_id)
        if data.get("category_id") and not category:
            return "请选择有效的费用类别"
        invoice.period_id = period.id
        invoice.category_id = category.id if category else None
        invoice.invoice_number = str(data.get("invoice_number") or "").strip()
        invoice.invoice_date = _date(data.get("invoice_date"))
        invoice.amount = _money(data.get("amount"))
        invoice.tax_amount = _money(data.get("tax_amount"))
        invoice.total_amount = _money(data.get("total_amount"))
        if invoice.total_amount == 0:
            invoice.total_amount = invoice.amount + invoice.tax_amount
        for key in ("vendor", "description", "file_url", "file_name", "product_line", "product_line_code", "office", "customer_level", "remarks"):
            setattr(invoice, key, str(data.get(key) or "").strip())
        invoice.file_size = int(data.get("file_size") or 0)
        invoice.status = data.get("status") if data.get("status") in STATUS_LABELS else "pending"
        return None

    @bp.post("/api/invoices")
    @csrf.exempt
    def create_invoice():
        owner_type, owner_id = _owner()
        invoice = ReimbursementInvoice(owner_type=owner_type, owner_id=owner_id, period_id=0)
        error = save_invoice(invoice, _payload())
        if error:
            return jsonify(error=error), 400
        db.session.add(invoice)
        db.session.commit()
        return jsonify(success=True, invoice=_invoice_dict(invoice)), 201

    @bp.put("/api/invoices/<int:invoice_id>")
    @csrf.exempt
    def update_invoice(invoice_id: int):
        owner_type, owner_id = _owner()
        invoice = ReimbursementInvoice.query.filter_by(id=invoice_id, owner_type=owner_type, owner_id=owner_id).first()
        if not invoice:
            return jsonify(error="发票不存在"), 404
        error = save_invoice(invoice, _payload())
        if error:
            return jsonify(error=error), 400
        db.session.commit()
        return jsonify(success=True, invoice=_invoice_dict(invoice))

    @bp.delete("/api/invoices/<int:invoice_id>")
    @csrf.exempt
    def remove_invoice(invoice_id: int):
        owner_type, owner_id = _owner()
        invoice = ReimbursementInvoice.query.filter_by(id=invoice_id, owner_type=owner_type, owner_id=owner_id).first()
        if not invoice:
            return jsonify(error="发票不存在"), 404
        if invoice.file_url.startswith("/tools/reimbursement/preview/"):
            filename = invoice.file_url.rsplit("/", 1)[-1]
            path = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement" / filename
            if path.exists():
                path.unlink()
        db.session.delete(invoice)
        db.session.commit()
        return jsonify(success=True)

    @bp.get("/api/summary/<int:period_id>")
    def period_summary(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        return jsonify(success=True, summary=_summary(period), aux=_aux_rows(period.id))

    @bp.put("/api/aux/<int:period_id>")
    @csrf.exempt
    def save_aux(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        data = _payload()
        ReimbursementAuxDetail.query.filter_by(period_id=period.id).delete()
        for kind in ("entertainment", "vehicle", "travel"):
            for index, row in enumerate(data.get(kind) or []):
                db.session.add(
                    ReimbursementAuxDetail(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        period_id=period.id,
                        kind=kind,
                        sort_order=index,
                        data_json=json.dumps(row, ensure_ascii=False),
                    )
                )
        db.session.commit()
        return jsonify(success=True, aux=_aux_rows(period.id))

    @bp.get("/api/export/<kind>/<int:period_id>")
    def export_xls(kind: str, period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        try:
            data = _cover_payload(period)
            if kind == "cover":
                output = _build_cover_xls(data)
                filename = f"报销封面及费用分类表 {period.office}-{period.name}.xls"
            elif kind == "details":
                output = _build_detail_xls(data, _aux_rows(period.id))
                filename = f"应酬费、出差明细、派车单{period.name}--{period.office}.xls"
            else:
                return jsonify(error="导出类型不存在"), 404
            return send_file(
                output,
                mimetype="application/vnd.ms-excel",
                as_attachment=True,
                download_name=filename,
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 422
        except Exception as exc:
            current_app.logger.exception("template XLS export failed")
            return jsonify(error=f"导出失败：{exc}"), 500
