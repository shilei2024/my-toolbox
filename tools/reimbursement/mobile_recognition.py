"""Owned OCR suggestions and explicit, optimistic invoice confirmation."""

import hashlib
import json
from datetime import date
from flask import request
from sqlalchemy import text, cast, func
from extensions import db
from models import (
    ReimbursementInvoice,
    ReimbursementPeriod,
    ReimbursementAuxDetail,
    User,
)
from auth.tool_access import can_access_private_tool
from auth.decorators import remaining_for, commit_usage
from auth import mobile_service as service
from .models import ReimbursementAudit
from .retention import money

FIELDS = {
    "customer_id",
    "customer_level",
    "linked_detail",
    "amount_confirmed",
    "period_id",
    "office_id",
    "category_id",
    "product_line_id",
    "invoice_number",
    "invoice_date",
    "vendor",
    "description",
    "amount",
    "tax_amount",
    "total_amount",
    "document_kind",
    "inclusion_policy",
    "occurrence_month",
    "settlement_month",
    "print_selected",
    "remarks",
}


def owned(invoice_id):
    from flask_login import current_user

    row = (
        ReimbursementInvoice.query.filter_by(
            id=invoice_id, owner_type="user", owner_id=str(current_user.id)
        )
        .populate_existing()
        .first()
    )
    if not row:
        raise service.MobileError("票据不存在", 404)
    return row


def state(row):
    from .manager import _invoice_dict

    data = _invoice_dict(row)
    token = hashlib.sha256(
        json.dumps(data, sort_keys=True, default=str, ensure_ascii=False).encode()
    ).hexdigest()
    # Attachment access remains through the scoped mobile download endpoint.
    data.pop("file_url", None)
    return data, token


def reauthorize():
    if not service.authenticate(request.headers.get("Authorization", "")[7:]):
        raise service.MobileError("登录已失效，请重新登录", 401)
    if not can_access_private_tool("reimbursement"):
        raise service.MobileError("报销助手使用权限已撤销", 403)


def draft_fields(result):
    result = result or {}
    data = {}
    for target, source, limit in [
        ("invoice_number", "invoice_number", 64),
        ("vendor", "seller_name", 255),
        ("description", "description", 500),
    ]:
        data[target] = str(result.get(source) or "")[:limit].strip()
    for target, source in [
        ("amount", "amount_excluding_tax"),
        ("tax_amount", "tax_amount"),
        ("total_amount", "total_amount"),
    ]:
        try:
            data[target] = str(
                money(
                    str(result.get(source) or "")
                    .replace(",", "")
                    .replace("￥", "")
                    .replace("¥", "")
                    .strip()
                )
            )
        except ValueError:
            data[target] = ""
    try:
        data["invoice_date"] = date.fromisoformat(
            str(result.get("invoice_date") or "")
        ).isoformat()
    except ValueError:
        data["invoice_date"] = ""
    return data


def recognize(invoice_id, retry=False):
    from flask_login import current_user
    from tools.reimbursement import _owned_attachment_for_name, recognize_original

    row = owned(invoice_id)
    data, snapshot = state(row)
    attachment = _owned_attachment_for_name(row.file_url.rsplit("/", 1)[-1])
    if not attachment:
        raise service.MobileError("原件不可用，请重新上传", 404)
    source = hashlib.sha256(attachment.content).hexdigest()
    if db.engine.dialect.name == "postgresql":
        if not db.session.execute(
            text("SELECT pg_try_advisory_xact_lock(694803, :id)"), {"id": row.id}
        ).scalar():
            raise service.MobileError("此票正在识别，请稍后打开核对", 409)
    query = ReimbursementAudit.query.filter_by(
        owner_type="user", owner_id=row.owner_id, action="invoice.ocr"
    )
    if db.engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import JSONB

        value = cast(ReimbursementAudit.data_json, JSONB)
        query = query.filter(
            value["invoice_id"].astext == str(row.id), value["source"].astext == source
        )
    else:
        query = query.filter(
            func.json_extract(ReimbursementAudit.data_json, "$.invoice_id") == row.id,
            func.json_extract(ReimbursementAudit.data_json, "$.source") == source,
        )
    entries = query.order_by(ReimbursementAudit.id.desc()).all()
    for entry in entries:
        cached = json.loads(entry.data_json)
        if cached.get("invoice_id") == row.id and cached.get("source") == source:
            if cached.get("success") or not retry:
                return {
                    "success": cached["success"],
                    "draft": cached["draft"],
                    "snapshot": snapshot,
                    "cached": True,
                }
            break
    if remaining_for("reimbursement") <= 0:
        raise service.MobileError("今日可用次数已用完", 429)
    file_url = row.file_url
    raw = attachment.content
    uid = current_user.id
    result, provider = recognize_original(raw)
    User.query.filter_by(id=uid).with_for_update().one()
    db.session.expire_all()
    reauthorize()
    row = owned(invoice_id)
    if row.file_url != file_url:
        raise service.MobileError("原件已变更，请刷新后识别", 409)
    if remaining_for("reimbursement") <= 0:
        raise service.MobileError("今日可用次数已用完", 429)
    draft = draft_fields(result)
    success = bool(result)
    db.session.add(
        ReimbursementAudit(
            owner_type="user",
            owner_id=str(uid),
            period_id=row.period_id,
            action="invoice.ocr",
            data_json=json.dumps(
                {
                    "invoice_id": row.id,
                    "source": source,
                    "success": success,
                    "draft": draft,
                    "provider": provider,
                },
                ensure_ascii=False,
            ),
        )
    )
    if success:
        commit_usage("reimbursement", commit=False)
    db.session.commit()
    return {"success": success, "draft": draft, "snapshot": snapshot, "cached": False}


def confirm(invoice_id, payload):
    from flask_login import current_user
    from .manager import save_invoice, _invoice_dict, _sync_invoice_aux, _owned_category

    if not isinstance(payload, dict) or set(payload) - FIELDS - {
        "snapshot",
        "confirmed",
    }:
        raise service.MobileError("确认参数无效")
    if payload.get("confirmed") is not True:
        raise service.MobileError("请核对票面及归属后明确确认")
    User.query.filter_by(id=current_user.id).with_for_update().one()
    db.session.expire_all()
    reauthorize()
    row = owned(invoice_id)
    ReimbursementPeriod.query.filter_by(id=row.period_id).with_for_update().one()
    db.session.refresh(row)
    before = _invoice_dict(row)
    _, snapshot = state(row)
    if payload.get("snapshot") != snapshot:
        raise service.MobileError("票据已在其他页面修改，请刷新核对", 409)
    if row.document_kind == "toll_statement" and any(
        json.loads(r.data_json).get("toll_statement_id") == row.id
        for r in ReimbursementAuxDetail.query.filter_by(
            period_id=row.period_id, kind="vehicle"
        ).all()
    ):
        raise service.MobileError("账单已分摊，请先在网站撤销分摊", 409)
    retained_customer = (row.customer_id, row.customer_level)
    values = {
        **before,
        **{k: v for k, v in payload.items() if k in FIELDS},
        "amount_confirmed": payload.get("amount_confirmed", True),
    }
    try:
        for key in ("period_id", "office_id", "category_id", "product_line_id"):
            value = values.get(key)
            if value in (None, "") and key in {"category_id", "product_line_id"}:
                values[key] = None
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (str, int))
                or not str(value).isdigit()
                or int(value) <= 0
            ):
                raise ValueError("请选择有效的周期、办事处、类别及产品线")
            values[key] = int(value)
        if "product_line_id" in payload:
            values["product_line"] = ""
        if "office_id" in payload:
            values["office"] = ""
        for key, limit in [
            ("invoice_number", 64),
            ("vendor", 255),
            ("description", 500),
            ("remarks", 4000),
        ]:
            if not isinstance(values.get(key), str) or len(values[key]) > limit:
                raise ValueError("文本字段长度或格式无效")
        if values.get("invoice_date"):
            date.fromisoformat(str(values["invoice_date"]))
        amounts = [
            money(values.get(k) or 0) for k in ("amount", "tax_amount", "total_amount")
        ]
        if amounts[0] + amounts[1] != amounts[2]:
            raise ValueError("未税金额加税额必须等于价税合计")
        if values["inclusion_policy"] == "expense" and (
            not values.get("category_id") or not values.get("product_line_id")
        ):
            raise ValueError("计入费用前请选择费用类别及产品线")
        error = save_invoice(row, values)
        if error:
            raise ValueError(error)
        if "customer_id" not in payload and "customer_level" not in payload:
            row.customer_id, row.customer_level = retained_customer
    except (ValueError, TypeError) as exc:
        raise service.MobileError(
            str(exc)
            if isinstance(exc, ValueError)
            and not str(exc).startswith(("Invalid isoformat", "invalid literal"))
            else "请填写有效日期及金额"
        ) from None
    linked = dict(before.get("linked_detail") or {})
    category = _owned_category(row.category_id, row.owner_type, row.owner_id)
    explicit_linked = "linked_detail" in payload
    if explicit_linked:
        incoming = payload["linked_detail"]
        allowed = {
            "date",
            "category",
            "place",
            "participants",
            "amount",
            "purpose",
            "approval",
            "location",
            "expense_type",
            "customer",
            "customer_id",
        }
        if incoming is not None and (
            not isinstance(incoming, dict) or set(incoming) - allowed
        ):
            raise service.MobileError("关联明细字段无效")
        linked = dict(incoming or {})
        for key, value in linked.items():
            if key in {"customer", "customer_id"}:
                continue
            if (
                not isinstance(value, (str, int, float))
                or isinstance(value, bool)
                or len(str(value)) > 4000
            ):
                raise service.MobileError("关联明细格式或长度无效")
            if key == "date" and value:
                try:
                    date.fromisoformat(str(value))
                except ValueError:
                    raise service.MobileError("关联明细日期无效") from None
            if key == "amount" and value not in (None, ""):
                try:
                    money(value)
                except ValueError:
                    raise service.MobileError("关联明细金额无效") from None
        from .manager import _owned_customer

        customer = _owned_customer(row.customer_id)
        linked["customer_id"] = customer.id if customer else None
        linked["customer"] = customer.short_name or customer.name if customer else ""
    if linked and not explicit_linked:
        amount_changed = money(before["total_amount"]) != money(row.total_amount)
        date_changed = before["invoice_date"] != (
            row.invoice_date.isoformat() if row.invoice_date else ""
        )
        if amount_changed:
            if money(linked.get("amount") or 0) != money(before["total_amount"]):
                raise service.MobileError(
                    "关联明细金额曾单独调整，请到网站核对后修改", 409
                )
            linked["amount"] = float(row.total_amount)
        if date_changed:
            if linked.get("date", "") != before["invoice_date"]:
                raise service.MobileError(
                    "关联明细日期曾单独调整，请到网站核对后修改", 409
                )
            linked["date"] = row.invoice_date.isoformat() if row.invoice_date else ""
        if linked.get("place") == before["vendor"]:
            linked["place"] = row.vendor
        if linked.get("purpose") == before["product_line"]:
            linked["purpose"] = row.product_line
        if category and linked.get("expense_type") == (
            before.get("category") or {}
        ).get("name"):
            linked["expense_type"] = category.name
    _sync_invoice_aux(row, category, linked)
    from .manager import _owned_customer

    if (
        retained_customer[0]
        and "customer_id" not in payload
        and "customer_level" not in payload
        and _owned_customer(retained_customer[0]) is None
        and before.get("linked_detail")
    ):
        # A retired/out-of-scope customer cannot be selected in the new form.
        # Editing unrelated fields must still preserve its historical export.
        historical = before["linked_detail"]
        for detail in ReimbursementAuxDetail.query.filter_by(
            owner_type=row.owner_type, owner_id=row.owner_id, period_id=row.period_id
        ).all():
            value = json.loads(detail.data_json)
            if value.get("invoice_id") == row.id:
                for key in ("customer_id", "customer", "customer_level"):
                    if key in historical:
                        value[key] = historical[key]
                detail.data_json = json.dumps(value, ensure_ascii=False)
    if linked and not explicit_linked:
        # Shared desktop defaults fill empty dates/amounts. Preserve explicitly
        # adjusted detail values on mobile when that invoice field is unchanged.
        for detail in ReimbursementAuxDetail.query.filter_by(
            owner_type=row.owner_type, owner_id=row.owner_id, period_id=row.period_id
        ).all():
            value = json.loads(detail.data_json)
            if value.get("invoice_id") == row.id:
                if not amount_changed and "amount" in linked:
                    value["amount"] = linked["amount"]
                if not date_changed and "date" in linked:
                    value["date"] = linked["date"]
                detail.data_json = json.dumps(value, ensure_ascii=False)
    db.session.add(
        ReimbursementAudit(
            owner_type="user",
            owner_id=row.owner_id,
            period_id=row.period_id,
            action="invoice.confirm",
            data_json=json.dumps(
                {"invoice_id": row.id, "before": before, "after": _invoice_dict(row)},
                ensure_ascii=False,
            ),
        )
    )
    db.session.commit()
    data, token = state(row)
    return {"invoice": data, "snapshot": token}
