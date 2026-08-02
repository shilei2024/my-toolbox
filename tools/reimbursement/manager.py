"""Normalized reimbursement manager APIs and template-faithful XLS exports."""
from __future__ import annotations

import io
import json
import re
import base64
import html
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from flask import Blueprint, current_app, jsonify, request, send_file
from sqlalchemy import case, func, or_

from extensions import csrf, db
from models import (
    ReimbursementAttachment,
    ReimbursementAuxDetail,
    ReimbursementCategory,
    ReimbursementInvoice,
    ReimbursementOffice,
    ReimbursementPeriod,
    ReimbursementProductLine,
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
DEFAULT_OFFICES = ["深圳办", "厦门办", "杭州办", "上海办", "北京办", "合肥办", "西安办"]
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


def _normalize_vehicle_rows(
    rows: list[dict[str, Any]], *, legacy_km_from_end: bool = False
) -> list[dict[str, Any]]:
    """Apply the odometer chain while keeping kilometres as the entered value."""
    normalized: list[dict[str, Any]] = []
    previous_end: Decimal | None = None
    for index, source in enumerate(rows):
        value = dict(source)
        original_start = value.get("km_start")
        original_end = value.get("km_end")
        km = value.get("km_total")
        if (
            legacy_km_from_end
            and km in (None, "")
            and original_start not in (None, "")
            and original_end not in (None, "")
        ):
            km = float(_money(original_end) - _money(original_start))
        value["km_total"] = km if km not in (None, "") else ""

        start = _money(original_start) if index == 0 and original_start not in (None, "") else previous_end
        value["km_start"] = float(start) if start is not None else ""
        if start is not None and km not in (None, ""):
            previous_end = start + _money(km)
            value["km_end"] = float(previous_end)
        else:
            previous_end = None
            value["km_end"] = ""
        normalized.append(value)
    return normalized


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


def _product_line_dict(item: ReimbursementProductLine) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "code": item.code,
        "sort_order": item.sort_order,
    }


def _office_dict(item: ReimbursementOffice) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "sort_order": item.sort_order,
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
    product_line = ReimbursementProductLine.query.filter(
        ReimbursementProductLine.owner_type == invoice.owner_type,
        ReimbursementProductLine.owner_id == invoice.owner_id,
        or_(
            ReimbursementProductLine.name == invoice.product_line,
            ReimbursementProductLine.code == invoice.product_line_code,
        ),
    ).first()
    office = ReimbursementOffice.query.filter_by(
        owner_type=invoice.owner_type,
        owner_id=invoice.owner_id,
        name=invoice.office,
    ).first()
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
        "product_line_id": product_line.id if product_line else None,
        "office": invoice.office,
        "office_id": office.id if office else None,
        "customer_level": invoice.customer_level,
        "remarks": invoice.remarks,
        "upload_date": invoice.upload_date.isoformat() if invoice.upload_date else "",
        "linked_detail": _invoice_aux_data(invoice),
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


def _seed_offices(owner_type: str, owner_id: str) -> list[ReimbursementOffice]:
    rows = (
        ReimbursementOffice.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementOffice.sort_order, ReimbursementOffice.id)
        .all()
    )
    if rows:
        return rows
    for index, name in enumerate(DEFAULT_OFFICES):
        db.session.add(
            ReimbursementOffice(
                owner_type=owner_type,
                owner_id=owner_id,
                name=name,
                sort_order=(index + 1) * 10,
            )
        )
    db.session.commit()
    return (
        ReimbursementOffice.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementOffice.sort_order, ReimbursementOffice.id)
        .all()
    )


def _seed_product_lines(owner_type: str, owner_id: str) -> list[ReimbursementProductLine]:
    rows = (
        ReimbursementProductLine.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementProductLine.sort_order, ReimbursementProductLine.code)
        .all()
    )
    if rows:
        return rows
    from . import PRODUCT_LINES

    for index, item in enumerate(PRODUCT_LINES):
        db.session.add(
            ReimbursementProductLine(
                owner_type=owner_type,
                owner_id=owner_id,
                name=item["name"],
                code=item["code"],
                office="",
                sort_order=(index + 1) * 10,
            )
        )
    db.session.commit()
    return (
        ReimbursementProductLine.query.filter_by(owner_type=owner_type, owner_id=owner_id)
        .order_by(ReimbursementProductLine.sort_order, ReimbursementProductLine.code)
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


def _owned_product_line(
    product_line_id: int | None, owner_type: str, owner_id: str
) -> ReimbursementProductLine | None:
    if not product_line_id:
        return None
    return ReimbursementProductLine.query.filter_by(
        id=product_line_id, owner_type=owner_type, owner_id=owner_id
    ).first()


def _owned_office(
    office_id: int | None, owner_type: str, owner_id: str
) -> ReimbursementOffice | None:
    if not office_id:
        return None
    return ReimbursementOffice.query.filter_by(
        id=office_id, owner_type=owner_type, owner_id=owner_id
    ).first()


def _replace_aux_product_line(owner_type: str, owner_id: str, old_name: str, new_name: str) -> None:
    rows = ReimbursementAuxDetail.query.filter_by(owner_type=owner_type, owner_id=owner_id).all()
    for row in rows:
        value = json.loads(row.data_json or "{}")
        if value.get("purpose") == old_name:
            value["purpose"] = new_name
        if value.get("product_line") == old_name:
            value["product_line"] = new_name
        if value.get("purpose") == new_name or value.get("product_line") == new_name:
            row.data_json = json.dumps(value, ensure_ascii=False)


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
    vehicle_rows = []
    for row in rows:
        value = json.loads(row.data_json or "{}")
        if row.kind == "vehicle":
            value["id"] = row.id
            vehicle_rows.append(value)
            continue
        value["id"] = row.id
        result.setdefault(row.kind, []).append(value)
    result["vehicle"] = _normalize_vehicle_rows(
        vehicle_rows, legacy_km_from_end=True
    )
    return result


def _invoice_aux_data(invoice: ReimbursementInvoice) -> dict[str, Any] | None:
    if not invoice.id:
        return None
    rows = ReimbursementAuxDetail.query.filter_by(
        owner_type=invoice.owner_type, owner_id=invoice.owner_id
    ).all()
    for row in rows:
        value = json.loads(row.data_json or "{}")
        if value.get("invoice_id") == invoice.id:
            value["kind"] = row.kind
            return value
    return None


def _linked_kind(category: ReimbursementCategory | None) -> str | None:
    if not category:
        return None
    if category.export_key == "entertainment":
        return "entertainment"
    if category.export_key in {"travel_transport", "travel_hotel"}:
        return "travel"
    return None


def _sync_invoice_aux(
    invoice: ReimbursementInvoice,
    category: ReimbursementCategory | None,
    linked_detail: dict[str, Any] | None,
) -> None:
    """Create or update the detail row generated from an entertainment/travel invoice."""
    desired_kind = _linked_kind(category)
    matched: list[tuple[ReimbursementAuxDetail, dict[str, Any]]] = []
    rows = ReimbursementAuxDetail.query.filter_by(
        owner_type=invoice.owner_type, owner_id=invoice.owner_id
    ).all()
    for row in rows:
        value = json.loads(row.data_json or "{}")
        if value.get("invoice_id") == invoice.id:
            matched.append((row, value))

    if not desired_kind:
        for row, _ in matched:
            db.session.delete(row)
        return

    detail = dict(linked_detail or {})
    if desired_kind == "entertainment":
        values = {
            "invoice_id": invoice.id,
            "auto_generated": True,
            "date": detail.get("date") or (invoice.invoice_date.isoformat() if invoice.invoice_date else ""),
            "category": detail.get("category") or "餐费",
            "place": detail.get("place") or invoice.vendor,
            "customer": detail.get("customer") or "",
            "participants": detail.get("participants") or "",
            "amount": float(_money(detail.get("amount") if detail.get("amount") not in (None, "") else invoice.total_amount)),
            "purpose": detail.get("purpose") or invoice.product_line,
            "approval": detail.get("approval") or "",
        }
    else:
        values = {
            "invoice_id": invoice.id,
            "auto_generated": True,
            "date": detail.get("date") or (invoice.invoice_date.isoformat() if invoice.invoice_date else ""),
            "location": detail.get("location") or "",
            "customer": detail.get("customer") or "",
            "expense_type": detail.get("expense_type") or (category.name if category else ""),
            "amount": float(_money(detail.get("amount") if detail.get("amount") not in (None, "") else invoice.total_amount)),
            "purpose": detail.get("purpose") or invoice.product_line,
        }

    if matched:
        target, _ = matched[0]
        target.period_id = invoice.period_id
        target.kind = desired_kind
        target.data_json = json.dumps(values, ensure_ascii=False)
        for duplicate, _ in matched[1:]:
            db.session.delete(duplicate)
        return

    max_order = (
        db.session.query(func.max(ReimbursementAuxDetail.sort_order))
        .filter_by(period_id=invoice.period_id, kind=desired_kind)
        .scalar()
    )
    db.session.add(
        ReimbursementAuxDetail(
            owner_type=invoice.owner_type,
            owner_id=invoice.owner_id,
            period_id=invoice.period_id,
            kind=desired_kind,
            sort_order=(max_order or 0) + 1,
            data_json=json.dumps(values, ensure_ascii=False),
        )
    )


def _remove_invoice_aux(invoice: ReimbursementInvoice) -> None:
    rows = ReimbursementAuxDetail.query.filter_by(
        owner_type=invoice.owner_type, owner_id=invoice.owner_id
    ).all()
    for row in rows:
        value = json.loads(row.data_json or "{}")
        if value.get("invoice_id") == invoice.id:
            db.session.delete(row)


def _assign_invoice_product_line(invoice: ReimbursementInvoice, data: dict[str, Any]) -> str | None:
    product_line_id = data.get("product_line_id")
    product_line = _owned_product_line(product_line_id, invoice.owner_type, invoice.owner_id)
    if product_line_id and not product_line:
        return "请选择有效的产品线"
    product_line_name = str(data.get("product_line") or "").strip()
    if not product_line and product_line_name:
        product_line = ReimbursementProductLine.query.filter_by(
            owner_type=invoice.owner_type,
            owner_id=invoice.owner_id,
            name=product_line_name,
        ).first()
        if not product_line:
            return "请选择产品线清单中的有效选项"
    invoice.product_line = product_line.name if product_line else ""
    invoice.product_line_code = product_line.code if product_line else ""
    return None


def _assign_invoice_office(invoice: ReimbursementInvoice, data: dict[str, Any]) -> str | None:
    office_id = data.get("office_id")
    office = _owned_office(office_id, invoice.owner_type, invoice.owner_id)
    if office_id and not office:
        return "请选择有效的办事处"
    office_name = str(data.get("office") or "").strip()
    if not office and office_name:
        office = ReimbursementOffice.query.filter_by(
            owner_type=invoice.owner_type,
            owner_id=invoice.owner_id,
            name=office_name,
        ).first()
        if not office:
            return "请选择办事处清单中的有效选项"
    if not office:
        return "请选择办事处"
    invoice.office = office.name
    return None


def _invoice_attachment_path(invoice: ReimbursementInvoice) -> Path | None:
    """Resolve the retained original upload, including legacy preview-only records."""
    if not invoice.file_url.startswith("/tools/reimbursement/preview/"):
        return None
    filename = invoice.file_url.rsplit("/", 1)[-1]
    if ".." in filename or "/" in filename or "\\" in filename:
        return None
    upload_dir = Path(current_app.config["UPLOAD_DIR"]) / "reimbursement"
    direct = upload_dir / filename
    stem = direct.stem
    file_id = re.sub(r"_(?:thumb|full)$", "", stem)
    original_ext = Path(invoice.file_name or "").suffix.lower()
    candidates = []
    if original_ext:
        candidates.append(upload_dir / f"{file_id}{original_ext}")
    candidates.extend(upload_dir / f"{file_id}{ext}" for ext in (".pdf", ".png", ".jpg", ".jpeg"))
    candidates.append(direct)
    existing = next((item for item in candidates if item.exists() and item.is_file()), None)
    if existing:
        return existing
    attachment = ReimbursementAttachment.query.filter(
        ReimbursementAttachment.stored_name.like(f"{file_id}.%")
    ).first()
    if not attachment:
        return None
    upload_dir.mkdir(parents=True, exist_ok=True)
    restored = upload_dir / attachment.stored_name
    restored.write_bytes(attachment.content)
    return restored


def _delete_invoice_attachment(invoice: ReimbursementInvoice) -> None:
    if not invoice.file_url.startswith("/tools/reimbursement/preview/"):
        return
    filename = invoice.file_url.rsplit("/", 1)[-1]
    file_id = re.sub(r"_(?:thumb|full)$", "", Path(filename).stem)
    ReimbursementAttachment.query.filter(
        ReimbursementAttachment.stored_name.like(f"{file_id}.%")
    ).delete(synchronize_session=False)


def _invoice_family_paths(invoice: ReimbursementInvoice) -> list[Path]:
    path = _invoice_attachment_path(invoice)
    if not path:
        return []
    file_id = re.sub(r"_(?:thumb|full)$", "", path.stem)
    upload_dir = path.parent
    return [
        item
        for item in upload_dir.glob(f"{file_id}.*")
        if item.is_file() and item.parent.resolve() == upload_dir.resolve()
    ] + [
        item
        for item in upload_dir.glob(f"{file_id}_*.png")
        if item.is_file() and item.parent.resolve() == upload_dir.resolve()
    ]


def _printable_invoice_pages(invoice: ReimbursementInvoice) -> list[str]:
    """Return each invoice page as an embeddable image data URL."""
    path = _invoice_attachment_path(invoice)
    if not path:
        return []
    if path.suffix.lower() == ".pdf":
        try:
            import fitz

            pages = []
            document = fitz.open(str(path))
            try:
                for page in document:
                    pixmap = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), colorspace=fitz.csRGB)
                    encoded = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
                    pages.append(f"data:image/png;base64,{encoded}")
            finally:
                document.close()
            return pages
        except Exception:
            return []
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(path.suffix.lower(), "image/png")
    return [f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"]


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

    # 派车单是封面“车辆费用”的明细来源。每条记录以
    # 公里数 + 过桥费 + 停车费计费，再按产品线汇总。
    vehicle_totals: dict[str, float] = {}
    for row in _aux_rows(period.id)["vehicle"]:
        product_line = str(row.get("product_line") or "").strip() or "未分类"
        amount = sum(
            float(_money(row.get(key)))
            for key in ("km_total", "toll_fee", "parking_fee")
        )
        vehicle_totals[product_line] = vehicle_totals.get(product_line, 0.0) + amount

    if vehicle_totals:
        product_lines = {
            item.name: item
            for item in _seed_product_lines(period.owner_type, period.owner_id)
        }
        for product_line, amount in vehicle_totals.items():
            group = next(
                (item for item in groups.values() if item["product_line"] == product_line),
                None,
            )
            if group is None:
                reference = product_lines.get(product_line)
                code = reference.code if reference else "-"
                group = groups.setdefault(
                    f"{code}|{product_line}",
                    {
                        "product_line": product_line,
                        "code": code,
                        "office": period.office,
                        "totals": {
                            export_key: 0.0
                            for _, export_key, _ in DEFAULT_CATEGORIES
                        },
                        "remarks": [],
                    },
                )
            # 同一产品线已有车辆类发票时，以派车单明细汇总为准，避免重复。
            existing = float(group["totals"].get("vehicle", 0) or 0)
            grand["vehicle"] -= existing
            group["totals"]["vehicle"] = round(amount, 2)
            grand["vehicle"] += round(amount, 2)

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
    from xlwt import Formula

    entertainment, travels = aux["entertainment"], aux["travel"]
    vehicles = _normalize_vehicle_rows(aux["vehicle"], legacy_km_from_end=True)
    if len(entertainment) > 9:
        raise ValueError("应酬费母版最多容纳 9 条明细")
    if len(vehicles) > 11:
        raise ValueError("派车单母版最多容纳 11 条明细")
    if len(travels) > 17:
        raise ValueError("出差明细母版需保留最后一行为合计，最多容纳 17 条明细")
    source, target = _template_copy(DETAIL_TEMPLATE)
    header = data["header"]

    _write_cell(source, target, 0, 1, 0, f"员工姓名：{header['employee_name']}")
    for row in range(3, 12):
        for col in range(8):
            _write_cell(source, target, 0, row, col, "")
    for offset, item in enumerate(entertainment):
        amount = float(item.get("amount") or 0)
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
    _write_cell(source, target, 0, 12, 0, "合计")
    _write_cell(source, target, 0, 12, 5, Formula("SUM(F4:F12)"))

    _write_cell(source, target, 1, 1, 0, f"员工姓名：{header['employee_name']}")
    _write_cell(source, target, 1, 1, 9, f" {header['period']}派车单")
    _write_cell(source, target, 1, 2, 9, "产品线")
    for row in range(4, 15):
        for col in range(10):
            _write_cell(source, target, 1, row, col, "")
    for offset, item in enumerate(vehicles):
        date_value = _date(item.get("date"))
        compact_date = int(date_value.strftime("%Y%m%d")) if date_value else ""
        excel_row = 5 + offset
        km_value = item.get("km_total")
        values = [
            compact_date,
            item.get("from_location", ""),
            item.get("to_location", ""),
            item.get("contact", ""),
            item.get("km_start", "") if offset == 0 else Formula(f'IF(F{excel_row - 1}="","",F{excel_row - 1})'),
            Formula(f'IF(OR(E{excel_row}="",G{excel_row}=""),"",E{excel_row}+G{excel_row})'),
            float(_money(km_value)) if km_value not in (None, "") else "",
            float(item.get("toll_fee") or 0),
            float(item.get("parking_fee") or 0),
            item.get("product_line") or item.get("remarks", ""),
        ]
        for col, value in enumerate(values):
            _write_cell(source, target, 1, 4 + offset, col, value)
    for col, formula in zip((6, 7, 8), ("SUM(G5:G15)", "SUM(H5:H15)", "SUM(I5:I15)")):
        _write_cell(source, target, 1, 15, col, Formula(formula))

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
    _write_cell(source, target, 2, 20, 0, "合计")
    _write_cell(source, target, 2, 20, 4, Formula("SUM(E4:E20)"))
    output = io.BytesIO()
    target.save(output)
    output.seek(0)
    return output


def register_routes(bp: Blueprint) -> None:
    @bp.get("/api/bootstrap")
    def bootstrap():
        owner_type, owner_id = _owner()
        _seed_categories(owner_type, owner_id)
        _seed_offices(owner_type, owner_id)
        _seed_product_lines(owner_type, owner_id)
        _migrate_legacy(owner_type, owner_id)
        periods = (
            ReimbursementPeriod.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementPeriod.start_year.desc(), ReimbursementPeriod.start_month.desc())
            .all()
        )
        active_period = next((item for item in periods if item.is_active), None)
        if not active_period and periods:
            active_period = periods[0]
            _set_active(active_period)
            db.session.commit()
        categories = (
            ReimbursementCategory.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementCategory.sort_order, ReimbursementCategory.id)
            .all()
        )
        product_lines = (
            ReimbursementProductLine.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementProductLine.sort_order, ReimbursementProductLine.code)
            .all()
        )
        offices = (
            ReimbursementOffice.query.filter_by(owner_type=owner_type, owner_id=owner_id)
            .order_by(ReimbursementOffice.sort_order, ReimbursementOffice.id)
            .all()
        )
        invoice_scope = ReimbursementInvoice.query.filter_by(
            owner_type=owner_type, owner_id=owner_id
        )
        if active_period:
            invoice_scope = invoice_scope.filter(
                ReimbursementInvoice.period_id == active_period.id
            )
        else:
            invoice_scope = invoice_scope.filter(ReimbursementInvoice.period_id == -1)
        invoices = invoice_scope.order_by(
            ReimbursementInvoice.created_at.desc()
        ).limit(5).all()
        total_count, total_amount, pending_count = (
            db.session.query(
                func.count(ReimbursementInvoice.id),
                func.coalesce(func.sum(ReimbursementInvoice.total_amount), 0),
                func.coalesce(func.sum(case((ReimbursementInvoice.status == "pending", 1), else_=0)), 0),
            )
            .filter(
                ReimbursementInvoice.owner_type == owner_type,
                ReimbursementInvoice.owner_id == owner_id,
                ReimbursementInvoice.period_id == (
                    active_period.id if active_period else -1
                ),
            )
            .one()
        )
        return jsonify(
            success=True,
            periods=[_period_dict(item) for item in periods],
            categories=[_category_dict(item) for item in categories],
            product_lines=[_product_line_dict(item) for item in product_lines],
            offices=[_office_dict(item) for item in offices],
            recent=[_invoice_dict(item) for item in invoices],
            stats={
                "invoice_count": int(total_count),
                "total_amount": float(total_amount or 0),
                "pending_count": int(pending_count or 0),
                "period_id": active_period.id if active_period else None,
                "period_name": active_period.name if active_period else "",
            },
        )

    @bp.post("/api/periods")
    @csrf.exempt
    def create_period():
        owner_type, owner_id = _owner()
        data = _payload()
        values, error = _validate_period(data)
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
        period = ReimbursementPeriod(
            owner_type=owner_type,
            owner_id=owner_id,
            employee_name=str(data.get("employee_name") or "").strip(),
            **values,
        )
        if data.get("is_active", True):
            _set_active(period)
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
            employee_name="",
            department="",
            office="深圳办",
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
        _set_active(period)
        db.session.add(period)
        db.session.commit()
        return jsonify(success=True, period=_period_dict(period)), 201

    @bp.post("/api/periods/<int:period_id>/activate")
    @csrf.exempt
    def activate_period(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return jsonify(error="周期不存在"), 404
        _set_active(period)
        db.session.commit()
        return jsonify(success=True, period=_period_dict(period))

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
        period_invoices = ReimbursementInvoice.query.filter_by(period_id=period.id).all()
        for invoice in period_invoices:
            for path in set(_invoice_family_paths(invoice)):
                path.unlink(missing_ok=True)
            _delete_invoice_attachment(invoice)
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

    @bp.get("/api/product-lines")
    def list_product_lines():
        owner_type, owner_id = _owner()
        rows = _seed_product_lines(owner_type, owner_id)
        return jsonify(product_lines=[_product_line_dict(item) for item in rows])

    @bp.post("/api/product-lines")
    @csrf.exempt
    def create_product_line():
        owner_type, owner_id = _owner()
        _seed_product_lines(owner_type, owner_id)
        data = _payload()
        name = str(data.get("name") or "").strip()
        code = str(data.get("code") or "").strip()
        if not name or not code:
            return jsonify(error="产品线名称和代码不能为空"), 400
        if ReimbursementProductLine.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, name=name
        ).first():
            return jsonify(error="产品线名称已存在"), 409
        if ReimbursementProductLine.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, code=code
        ).first():
            return jsonify(error="产品线代码已存在"), 409
        max_order = (
            db.session.query(func.max(ReimbursementProductLine.sort_order))
            .filter_by(owner_type=owner_type, owner_id=owner_id)
            .scalar()
        )
        item = ReimbursementProductLine(
            owner_type=owner_type,
            owner_id=owner_id,
            name=name,
            code=code,
            office="",
            sort_order=int(data.get("sort_order") or ((max_order or 0) + 10)),
        )
        db.session.add(item)
        db.session.commit()
        return jsonify(success=True, product_line=_product_line_dict(item)), 201

    @bp.put("/api/product-lines/<int:product_line_id>")
    @csrf.exempt
    def update_product_line(product_line_id: int):
        owner_type, owner_id = _owner()
        item = _owned_product_line(product_line_id, owner_type, owner_id)
        if not item:
            return jsonify(error="产品线不存在"), 404
        data = _payload()
        name = str(data.get("name") or "").strip()
        code = str(data.get("code") or "").strip()
        if not name or not code:
            return jsonify(error="产品线名称和代码不能为空"), 400
        duplicate_name = ReimbursementProductLine.query.filter(
            ReimbursementProductLine.owner_type == owner_type,
            ReimbursementProductLine.owner_id == owner_id,
            ReimbursementProductLine.name == name,
            ReimbursementProductLine.id != item.id,
        ).first()
        if duplicate_name:
            return jsonify(error="产品线名称已存在"), 409
        duplicate_code = ReimbursementProductLine.query.filter(
            ReimbursementProductLine.owner_type == owner_type,
            ReimbursementProductLine.owner_id == owner_id,
            ReimbursementProductLine.code == code,
            ReimbursementProductLine.id != item.id,
        ).first()
        if duplicate_code:
            return jsonify(error="产品线代码已存在"), 409
        old_name, old_code = item.name, item.code
        item.name = name
        item.code = code
        if "sort_order" in data:
            item.sort_order = int(data.get("sort_order") or 0)
        ReimbursementInvoice.query.filter(
            ReimbursementInvoice.owner_type == owner_type,
            ReimbursementInvoice.owner_id == owner_id,
            or_(
                ReimbursementInvoice.product_line == old_name,
                ReimbursementInvoice.product_line_code == old_code,
            ),
        ).update(
            {"product_line": item.name, "product_line_code": item.code},
            synchronize_session=False,
        )
        if old_name != item.name:
            _replace_aux_product_line(owner_type, owner_id, old_name, item.name)
        db.session.commit()
        return jsonify(success=True, product_line=_product_line_dict(item))

    @bp.delete("/api/product-lines/<int:product_line_id>")
    @csrf.exempt
    def remove_product_line(product_line_id: int):
        owner_type, owner_id = _owner()
        item = _owned_product_line(product_line_id, owner_type, owner_id)
        if not item:
            return jsonify(error="产品线不存在"), 404
        invoices = ReimbursementInvoice.query.filter(
            ReimbursementInvoice.owner_type == owner_type,
            ReimbursementInvoice.owner_id == owner_id,
            or_(
                ReimbursementInvoice.product_line == item.name,
                ReimbursementInvoice.product_line_code == item.code,
            ),
        )
        count = invoices.count()
        migrate_to = request.args.get("migrate_to", type=int)
        if count and not migrate_to:
            return jsonify(
                error="该产品线仍有关联发票，请选择迁移目标产品线",
                invoice_count=count,
                needs_migration=True,
            ), 409
        if migrate_to:
            target = _owned_product_line(migrate_to, owner_type, owner_id)
            if not target or target.id == item.id:
                return jsonify(error="迁移目标产品线无效"), 400
            invoices.update(
                {"product_line": target.name, "product_line_code": target.code},
                synchronize_session=False,
            )
            _replace_aux_product_line(owner_type, owner_id, item.name, target.name)
        db.session.delete(item)
        db.session.commit()
        return jsonify(success=True)

    @bp.get("/api/offices")
    def list_offices():
        owner_type, owner_id = _owner()
        rows = _seed_offices(owner_type, owner_id)
        return jsonify(offices=[_office_dict(item) for item in rows])

    @bp.post("/api/offices")
    @csrf.exempt
    def create_office():
        owner_type, owner_id = _owner()
        _seed_offices(owner_type, owner_id)
        data = _payload()
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify(error="办事处名称不能为空"), 400
        if ReimbursementOffice.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, name=name
        ).first():
            return jsonify(error="办事处名称已存在"), 409
        max_order = (
            db.session.query(func.max(ReimbursementOffice.sort_order))
            .filter_by(owner_type=owner_type, owner_id=owner_id)
            .scalar()
        )
        office = ReimbursementOffice(
            owner_type=owner_type,
            owner_id=owner_id,
            name=name,
            sort_order=int(data.get("sort_order") or ((max_order or 0) + 10)),
        )
        db.session.add(office)
        db.session.commit()
        return jsonify(success=True, office=_office_dict(office)), 201

    @bp.put("/api/offices/<int:office_id>")
    @csrf.exempt
    def update_office(office_id: int):
        owner_type, owner_id = _owner()
        office = _owned_office(office_id, owner_type, owner_id)
        if not office:
            return jsonify(error="办事处不存在"), 404
        data = _payload()
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify(error="办事处名称不能为空"), 400
        duplicate = ReimbursementOffice.query.filter(
            ReimbursementOffice.owner_type == owner_type,
            ReimbursementOffice.owner_id == owner_id,
            ReimbursementOffice.name == name,
            ReimbursementOffice.id != office.id,
        ).first()
        if duplicate:
            return jsonify(error="办事处名称已存在"), 409
        old_name = office.name
        office.name = name
        if "sort_order" in data:
            office.sort_order = int(data.get("sort_order") or 0)
        if old_name != name:
            ReimbursementInvoice.query.filter_by(
                owner_type=owner_type, owner_id=owner_id, office=old_name
            ).update({"office": name}, synchronize_session=False)
            ReimbursementPeriod.query.filter_by(
                owner_type=owner_type, owner_id=owner_id, office=old_name
            ).update({"office": name}, synchronize_session=False)
        db.session.commit()
        return jsonify(success=True, office=_office_dict(office))

    @bp.delete("/api/offices/<int:office_id>")
    @csrf.exempt
    def remove_office(office_id: int):
        owner_type, owner_id = _owner()
        office = _owned_office(office_id, owner_type, owner_id)
        if not office:
            return jsonify(error="办事处不存在"), 404
        invoices = ReimbursementInvoice.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, office=office.name
        )
        periods = ReimbursementPeriod.query.filter_by(
            owner_type=owner_type, owner_id=owner_id, office=office.name
        )
        invoice_count, period_count = invoices.count(), periods.count()
        migrate_to = request.args.get("migrate_to", type=int)
        if (invoice_count or period_count) and not migrate_to:
            return jsonify(
                error="该办事处仍有关联数据，请选择迁移目标办事处",
                invoice_count=invoice_count,
                period_count=period_count,
                needs_migration=True,
            ), 409
        if migrate_to:
            target = _owned_office(migrate_to, owner_type, owner_id)
            if not target or target.id == office.id:
                return jsonify(error="迁移目标办事处无效"), 400
            invoices.update({"office": target.name}, synchronize_session=False)
            periods.update({"office": target.name}, synchronize_session=False)
        db.session.delete(office)
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
        product_line_error = _assign_invoice_product_line(invoice, data)
        if product_line_error:
            return product_line_error
        office_error = _assign_invoice_office(invoice, data)
        if office_error:
            return office_error
        for key in ("vendor", "description", "file_url", "file_name", "customer_level", "remarks"):
            setattr(invoice, key, str(data.get(key) or "").strip())
        invoice.file_size = int(data.get("file_size") or 0)
        invoice.status = data.get("status") if data.get("status") in STATUS_LABELS else "pending"
        return None

    @bp.post("/api/invoices")
    @csrf.exempt
    def create_invoice():
        owner_type, owner_id = _owner()
        data = _payload()
        invoice = ReimbursementInvoice(owner_type=owner_type, owner_id=owner_id, period_id=0)
        error = save_invoice(invoice, data)
        if error:
            return jsonify(error=error), 400
        db.session.add(invoice)
        db.session.flush()
        category = _owned_category(invoice.category_id, owner_type, owner_id)
        _sync_invoice_aux(invoice, category, data.get("linked_detail"))
        db.session.commit()
        return jsonify(success=True, invoice=_invoice_dict(invoice)), 201

    @bp.put("/api/invoices/<int:invoice_id>")
    @csrf.exempt
    def update_invoice(invoice_id: int):
        owner_type, owner_id = _owner()
        invoice = ReimbursementInvoice.query.filter_by(id=invoice_id, owner_type=owner_type, owner_id=owner_id).first()
        if not invoice:
            return jsonify(error="发票不存在"), 404
        data = _payload()
        error = save_invoice(invoice, data)
        if error:
            return jsonify(error=error), 400
        category = _owned_category(invoice.category_id, owner_type, owner_id)
        _sync_invoice_aux(invoice, category, data.get("linked_detail"))
        db.session.commit()
        return jsonify(success=True, invoice=_invoice_dict(invoice))

    @bp.delete("/api/invoices/<int:invoice_id>")
    @csrf.exempt
    def remove_invoice(invoice_id: int):
        owner_type, owner_id = _owner()
        invoice = ReimbursementInvoice.query.filter_by(id=invoice_id, owner_type=owner_type, owner_id=owner_id).first()
        if not invoice:
            return jsonify(error="发票不存在"), 404
        for path in set(_invoice_family_paths(invoice)):
            path.unlink(missing_ok=True)
        _delete_invoice_attachment(invoice)
        _remove_invoice_aux(invoice)
        db.session.delete(invoice)
        db.session.commit()
        return jsonify(success=True)

    @bp.get("/api/periods/<int:period_id>/invoices/print")
    def print_period_invoices(period_id: int):
        owner_type, owner_id = _owner()
        period = _owned_period(period_id, owner_type, owner_id)
        if not period:
            return "报销周期不存在", 404
        invoices = (
            ReimbursementInvoice.query.filter_by(
                owner_type=owner_type,
                owner_id=owner_id,
                period_id=period.id,
            )
            .order_by(ReimbursementInvoice.invoice_date, ReimbursementInvoice.id)
            .all()
        )
        rendered_pages = []
        for index, invoice in enumerate(invoices, 1):
            pages = _printable_invoice_pages(invoice)
            if not pages:
                rendered_pages.append(
                    f'<section class="invoice-page missing"><h2>附件不可用</h2>'
                    f'<p>第 {index} 张：{html.escape(invoice.invoice_number or invoice.file_name or "未命名发票")}</p></section>'
                )
                continue
            for data_url in pages:
                rendered_pages.append(
                    '<section class="invoice-page">'
                    f'<img src="{data_url}" alt="发票原件"></section>'
                )
        body = "\n".join(rendered_pages) or (
            '<section class="invoice-page missing"><h2>当前周期没有可打印的发票</h2></section>'
        )
        period_name = html.escape(period.name)
        document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{period_name} 发票打印</title>
<style>
@page{{size:A5 landscape;margin:6mm}}*{{box-sizing:border-box}}body{{margin:0;font-family:"Microsoft YaHei",sans-serif;color:#17231f;background:#eef3f1}}
.invoice-page{{width:210mm;min-height:148mm;margin:12px auto;background:#fff;padding:6mm;display:flex;flex-direction:column;break-after:page;page-break-after:always;overflow:hidden}}
.invoice-page:last-child{{break-after:auto;page-break-after:auto}}img{{display:block;max-width:100%;max-height:136mm;margin:auto;object-fit:contain;min-height:0}}.missing{{align-items:center;justify-content:center;text-align:center}}
@media print{{html,body{{width:198mm}}body{{background:#fff}}.invoice-page{{margin:0;padding:0;width:198mm;height:136mm;min-height:136mm}}img{{max-width:198mm;max-height:136mm}}}}
</style></head><body>{body}<script>window.addEventListener('load',()=>setTimeout(()=>window.print(),350));</script></body></html>"""
        return document, 200, {"Content-Type": "text/html; charset=utf-8"}

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
            incoming_rows = [dict(row) for row in (data.get(kind) or [])]
            if kind == "vehicle":
                incoming_rows = _normalize_vehicle_rows(incoming_rows)
            for index, row in enumerate(incoming_rows):
                value = dict(row)
                value.pop("id", None)
                db.session.add(
                    ReimbursementAuxDetail(
                        owner_type=owner_type,
                        owner_id=owner_id,
                        period_id=period.id,
                        kind=kind,
                        sort_order=index,
                        data_json=json.dumps(value, ensure_ascii=False),
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
