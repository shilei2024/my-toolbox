"""Mobile vehicle rows share website snapshots, odometer rules and summaries."""

import json
from datetime import date
from flask_login import current_user
from extensions import db
from models import (
    ReimbursementPeriod,
    ReimbursementAuxDetail,
    ReimbursementInvoice,
    ReimbursementProductLine,
    User,
)
from auth import mobile_service as service
from .mobile_recognition import reauthorize
from .retention import money
from .manager import _aux_state, _normalize_vehicle_rows, _sort_rows_by_date, _summary
from .models import ReimbursementAudit

EDITABLE = {
    "date",
    "from_location",
    "to_location",
    "contact",
    "km_start",
    "km_total",
    "toll_fee",
    "parking_fee",
    "product_line",
}


def period_owned(period_id):
    row = ReimbursementPeriod.query.filter_by(
        id=period_id, owner_type="user", owner_id=str(current_user.id)
    ).first()
    if not row:
        raise service.MobileError("周期不存在", 404)
    return row


def dispatch_state(period):
    state = _aux_state(period.id)
    rows = [
        {
            **{k: v for k, v in row.items() if k in EDITABLE | {"id", "km_end"}},
            "allocated": bool(row.get("toll_statement_id")),
        }
        for row in state["aux"]["vehicle"]
    ]
    return {
        "rows": rows,
        "snapshot": state["aux_snapshot"],
        "period_name": period.name,
        "totals": {
            key: str(sum((money(r.get(key) or 0) for r in rows), money(0)))
            for key in ("km_total", "toll_fee", "parking_fee")
        },
    }


def save_dispatch(period_id, payload):
    if (
        not isinstance(payload, dict)
        or set(payload) - {"rows", "snapshot"}
        or not isinstance(payload.get("rows"), list)
        or len(payload["rows"]) > 1000
    ):
        raise service.MobileError("派车记录格式无效，每次最多1000行")
    User.query.filter_by(id=current_user.id).with_for_update().one()
    period = period_owned(period_id)
    ReimbursementPeriod.query.filter_by(id=period.id).with_for_update().one()
    db.session.expire_all()
    reauthorize()
    state = _aux_state(period.id)
    if payload.get("snapshot") != state["aux_snapshot"]:
        raise service.MobileError("明细已在其他页面修改，请刷新核对", 409)
    current = {
        r.id: r
        for r in ReimbursementAuxDetail.query.filter_by(
            period_id=period.id, kind="vehicle"
        ).all()
    }
    old = {r["id"]: r for r in state["aux"]["vehicle"]}
    known = {
        r.name
        for r in ReimbursementProductLine.query.filter_by(
            owner_type="user", owner_id=str(current_user.id)
        ).all()
    }
    prepared = []
    seen = set()
    for incoming in payload["rows"]:
        if not isinstance(incoming, dict) or set(incoming) - EDITABLE - {
            "id",
            "km_end",
            "allocated",
        }:
            raise service.MobileError("派车字段无效")
        id = incoming.get("id")
        if id is not None:
            if (
                isinstance(id, bool)
                or not isinstance(id, int)
                or id not in current
                or id in seen
            ):
                raise service.MobileError("派车行不存在或重复")
            seen.add(id)
        values = dict(old[id]) if id is not None else {}
        values.update({k: v for k, v in incoming.items() if k in EDITABLE})
        values["id"] = id
        try:
            date.fromisoformat(str(values.get("date") or ""))
            for key in ("from_location", "to_location", "contact", "product_line"):
                value = values.get(key, "")
                if not isinstance(value, str) or len(value) > 255:
                    raise ValueError("派车文本格式或长度无效")
                values[key] = value.strip()
            if values["product_line"] not in known and not (
                id is not None
                and values["product_line"] == old[id].get("product_line", "")
            ):
                raise ValueError("请选择本人目录中的产品线")
            if values.get("km_total") in (None, ""):
                raise ValueError("请填写实际行驶公里数")
            for key in ("km_total", "toll_fee", "parking_fee"):
                values[key] = str(money(values.get(key) or 0))
            if values.get("km_start") not in (None, ""):
                values["km_start"] = str(money(values["km_start"]))
        except (ValueError, TypeError) as exc:
            raise service.MobileError(
                str(exc)
                if not str(exc).startswith("Invalid isoformat")
                else "请选择有效派车日期"
            ) from None
        prepared.append(values)
    prepared = _normalize_vehicle_rows(_sort_rows_by_date(prepared))
    new = {r["id"]: r for r in prepared if r["id"] is not None}
    for id, row in old.items():
        if row.get("toll_statement_id"):
            candidate = new.get(id)

            def equal(key):
                a, b = candidate.get(key), row.get(key)
                if key in {"km_total", "toll_fee", "parking_fee"}:
                    return money(a or 0) == money(b or 0)
                if (
                    key in {"km_start", "km_end"}
                    and a not in (None, "")
                    and b not in (None, "")
                ):
                    return money(a) == money(b)
                return str(a if a is not None else "") == str(
                    b if b is not None else ""
                )

            if candidate is None or any(not equal(k) for k in EDITABLE | {"km_end"}):
                raise service.MobileError(
                    "已分摊行受到修改，请先在网站撤销账单分摊", 409
                )
    db.session.add(
        ReimbursementAudit(
            owner_type="user",
            owner_id=str(current_user.id),
            period_id=period.id,
            action="vehicle.mobile.save",
            data_json=json.dumps(
                {"before": list(old.values()), "after": prepared}, ensure_ascii=False
            ),
        )
    )
    for id, row in current.items():
        if id not in seen:
            db.session.delete(row)
    for index, values in enumerate(prepared):
        id = values.pop("id")
        row = (
            current.get(id)
            if id is not None
            else ReimbursementAuxDetail(
                owner_type="user",
                owner_id=str(current_user.id),
                period_id=period.id,
                kind="vehicle",
            )
        )
        # Unknown server-owned metadata remains from the original row.
        row.sort_order = index
        row.data_json = json.dumps(values, ensure_ascii=False)
        db.session.add(row)
    db.session.commit()
    return dispatch_state(period)


def dashboard(period_id):
    period = period_owned(period_id)
    state = dispatch_state(period)
    invoices = ReimbursementInvoice.query.filter_by(
        period_id=period.id, owner_type="user", owner_id=str(current_user.id)
    )
    return {
        "period_name": period.name,
        "invoice_count": invoices.count(),
        "pending_count": invoices.filter_by(amount_confirmed=False).count(),
        "total_amount": str(_summary(period)["total_amount"]),
        "vehicle_count": len(state["rows"]),
        **state["totals"],
    }
