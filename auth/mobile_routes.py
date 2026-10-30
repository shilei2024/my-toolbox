"""A strictly scoped Bearer entry point; website cookies never authorize it."""
import hashlib
import io
import json
import re
from flask import Blueprint, current_app, g, jsonify, request, send_file
from flask_login import current_user, login_fresh
from sqlalchemy.exc import IntegrityError
from extensions import csrf, db, limiter, login_manager
from models import ReimbursementAttachment, ReimbursementInvoice, ReimbursementPeriod, User, utcnow
from auth.decorators import commit_usage, remaining_for
from auth.tool_access import can_access_private_tool
from . import mobile_service as service
from .mobile_models import ExternalIdentity

mobile_bp = Blueprint("mobile_api", __name__, url_prefix="/api/mobile")
binding_bp = Blueprint("mobile_binding", __name__, url_prefix="/auth/mobile")
csrf.exempt(mobile_bp)


@login_manager.request_loader
def load_mobile_request(req):
    if req.blueprint != "mobile_api" or req.headers.get("Cookie"):
        return None
    supplied = req.headers.get("Authorization", "")
    if not supplied.startswith("Bearer "):
        return None
    principal = service.authenticate(supplied[7:])
    if principal:
        user, g.mobile_session = principal
        return user
    return None


@mobile_bp.before_request
def mobile_guard():
    if not service.configured():
        return jsonify(error="手机录入暂未开放"), 404
    if request.headers.get("Cookie"):
        return jsonify(error="手机接口只接受独立登录凭证"), 401
    if request.content_length and request.content_length > 21 * 1024 * 1024:
        return jsonify(error="文件大小不能超过 20MB"), 413
    if request.endpoint != "mobile_api.mobile_login" and (not current_user.is_authenticated or not hasattr(g, "mobile_session")):
        return jsonify(error="登录已失效，请重新登录"), 401
    if request.endpoint not in {"mobile_api.mobile_login", "mobile_api.mobile_logout"} and not can_access_private_tool("reimbursement"):
        return jsonify(error="你的账号尚未获得报销助手的使用权限，请在网站联系管理员授权。"), 403


@binding_bp.before_request
def binding_guard():
    if not service.configured():
        return jsonify(error="手机录入暂未开放"), 404
    if not current_user.is_authenticated or not current_user.is_active_user:
        return jsonify(error="请先登录网站"), 401


def no_store(response):
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Vary"] = "Authorization, Cookie"
    return response


mobile_bp.after_request(no_store)
binding_bp.after_request(no_store)


def mobile_error(error):
    db.session.rollback()
    return jsonify(error=error.message), error.status


mobile_bp.errorhandler(service.MobileError)(mobile_error)
binding_bp.errorhandler(service.MobileError)(mobile_error)


def database_conflict(_error):
    db.session.rollback()
    return jsonify(error="状态已变化，请重试"), 409


mobile_bp.errorhandler(IntegrityError)(database_conflict)
binding_bp.errorhandler(IntegrityError)(database_conflict)


def require_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not login_fresh():
        raise service.MobileError("请重新登录网站后操作", 401)
    password = data.get("password")
    if not isinstance(password, str) or len(password) > 256 or not current_user.check_password(password):
        raise service.MobileError("网站密码不正确", 403)
    return data


@binding_bp.post("/challenge")
@limiter.limit("5/minute")
def binding_challenge():
    if not can_access_private_tool("reimbursement"):
        raise service.MobileError("你的账号尚未获得报销助手的使用权限", 403)
    require_password()
    token = service.create_challenge(current_user.id)
    import base64
    import qrcode
    image = qrcode.make(token)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return jsonify(binding_code=token, expires_in=600,
        qr_image="data:image/png;base64,"+base64.b64encode(stream.getvalue()).decode("ascii"))


@binding_bp.get("/bindings")
def bindings():
    rows = ExternalIdentity.query.filter_by(provider=service.PROVIDER, client_id=service.client_id(), user_id=current_user.id, active=True).all()
    return jsonify(bindings=[{"id":row.id, "created_at":row.created_at.isoformat()+"Z"} for row in rows])


@binding_bp.delete("/bindings/<int:identity_id>")
@limiter.limit("5/minute")
def unbind(identity_id):
    require_password()
    service.unbind(current_user.id, identity_id)
    return jsonify(success=True)


@mobile_bp.post("/session")
@limiter.limit("10/minute")
def mobile_login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) - {"code", "binding_code"}:
        raise service.MobileError("登录参数无效")
    return jsonify(success=True, **service.login(service.exchange_code(data.get("code")), data.get("binding_code")))


@mobile_bp.post("/logout")
def mobile_logout():
    g.mobile_session.revoked_at = utcnow()
    service.audit(current_user.id, "session.revoked", session_id=g.mobile_session.id)
    db.session.commit()
    return jsonify(success=True)


@mobile_bp.get("/bootstrap")
def mobile_bootstrap():
    from tools.reimbursement.manager import (_seed_offices, _seed_categories, _seed_product_lines,
        _category_dict, _product_line_dict, _customer_directory, _customer_dict,
        _customer_creation_membership, CUSTOMER_LEVELS)
    owner_id = str(current_user.id)
    offices = _seed_offices("user", owner_id)
    periods = ReimbursementPeriod.query.filter_by(owner_type="user", owner_id=owner_id).order_by(ReimbursementPeriod.start_year.desc(), ReimbursementPeriod.start_month.desc()).all()
    return jsonify(display_name=current_user.nickname or "网站账号",
        periods=[{"id":p.id, "name":p.name, "is_active":p.is_active} for p in periods],
        offices=[{"id":o.id, "name":o.name} for o in offices],
        categories=[_category_dict(c) for c in _seed_categories('user',owner_id)],
        product_lines=[_product_line_dict(p) for p in _seed_product_lines('user',owner_id)],
        customers=[_customer_dict(c) for c in _customer_directory()],
        customer_levels=list(CUSTOMER_LEVELS),
        customer_creation_enabled=_customer_creation_membership() is not None)


@mobile_bp.post('/customers')
@limiter.limit('10/minute')
def mobile_customer_create():
    from tools.reimbursement.manager import _customer_creation_membership, _customer_dict
    from tools.reimbursement.mobile_recognition import reauthorize
    from customer_projects.services.projects import create_customer, DomainError
    data=request.get_json(silent=True)
    if not isinstance(data,dict) or set(data)-{'name','short_name','grade'}:
        raise service.MobileError('客户参数无效')
    User.query.filter_by(id=current_user.id).with_for_update().one()
    db.session.expire_all(); reauthorize()
    membership=_customer_creation_membership()
    if membership is None: raise service.MobileError('当前账号无权录入客户，请联系组织管理员',403)
    try:
        customer=create_customer(data,membership)
        db.session.commit()
    except DomainError as exc:
        raise service.MobileError(exc.message) from None
    return jsonify(success=True,customer=_customer_dict(customer)),201


@mobile_bp.get('/invoices/<int:invoice_id>')
def mobile_detail(invoice_id):
    from tools.reimbursement.mobile_recognition import owned,state
    data,token=state(owned(invoice_id))
    return jsonify(invoice=data,snapshot=token)


@mobile_bp.get('/dispatch/<int:period_id>')
def mobile_dispatch_get(period_id):
    from tools.reimbursement.mobile_dispatch import period_owned,dispatch_state
    return jsonify(**dispatch_state(period_owned(period_id)))


@mobile_bp.put('/dispatch/<int:period_id>')
@limiter.limit('20/minute')
def mobile_dispatch_save(period_id):
    from tools.reimbursement.mobile_dispatch import save_dispatch
    return jsonify(success=True,**save_dispatch(period_id,request.get_json(silent=True)))


@mobile_bp.get('/dashboard/<int:period_id>')
def mobile_dashboard(period_id):
    from tools.reimbursement.mobile_dispatch import dashboard
    return jsonify(**dashboard(period_id))


@mobile_bp.post('/invoices/<int:invoice_id>/recognize')
@limiter.limit('10/minute')
def mobile_recognize(invoice_id):
    from tools.reimbursement.mobile_recognition import recognize
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict) or set(data)-{'retry'} or not isinstance(data.get('retry',False),bool):
        raise service.MobileError('识别参数无效')
    return jsonify(**recognize(invoice_id,data.get('retry',False)))


@mobile_bp.post('/invoices/<int:invoice_id>/confirm')
@limiter.limit('20/minute')
def mobile_confirm(invoice_id):
    from tools.reimbursement.mobile_recognition import confirm
    return jsonify(success=True,**confirm(invoice_id,request.get_json(silent=True)))


def invoice_data(invoice):
    from tools.reimbursement.manager import _owned_customer, _invoice_customer_level
    customer = _owned_customer(invoice.customer_id)
    return {"id":invoice.id, "period_id":invoice.period_id, "file_name":invoice.file_name,
        "document_kind":invoice.document_kind, "inclusion_policy":invoice.inclusion_policy,
        "amount_confirmed":invoice.amount_confirmed, "occurrence_month":invoice.occurrence_month,
        "customer":(customer.short_name or customer.name) if customer else "",
        "customer_level":_invoice_customer_level(invoice),
        "uploaded_at":invoice.upload_date.isoformat()+"Z",
        "file_endpoint":f"/api/mobile/invoices/{invoice.id}/file" if invoice.file_url else None}


@mobile_bp.get("/invoices")
def mobile_invoices():
    period_id = request.args.get("period_id", type=int)
    if not period_id or not ReimbursementPeriod.query.filter_by(id=period_id, owner_type="user", owner_id=str(current_user.id)).first():
        raise service.MobileError("报销周期不存在", 404)
    page = max(request.args.get("page", 1, type=int), 1)
    query = ReimbursementInvoice.query.filter_by(owner_type="user", owner_id=str(current_user.id), period_id=period_id)
    rows = query.order_by(ReimbursementInvoice.id.desc()).offset((page-1)*20).limit(21).all()
    return jsonify(invoices=[invoice_data(i) for i in rows[:20]], page=page, has_more=len(rows)>20)


@mobile_bp.get("/invoices/<int:invoice_id>/file")
def mobile_file(invoice_id):
    invoice = ReimbursementInvoice.query.filter_by(id=invoice_id, owner_type="user", owner_id=str(current_user.id)).first()
    if not invoice:
        raise service.MobileError("票据不存在", 404)
    from tools.reimbursement import _owned_attachment_for_name
    attachment = _owned_attachment_for_name(invoice.file_url.rsplit("/", 1)[-1])
    if not attachment:
        raise service.MobileError("原件不可用", 404)
    return send_file(io.BytesIO(attachment.content), mimetype=attachment.mime_type,
        as_attachment=True, download_name=attachment.original_name, max_age=0, etag=False)


@mobile_bp.post("/invoices")
@limiter.limit("20/minute")
def mobile_upload():
    from tools.reimbursement.attachments import read_original, persist_original
    from tools.reimbursement.manager import create_invoice_record, InvoiceConflictError
    from tools.reimbursement.mobile_models import UploadReceipt
    from tools.reimbursement.retention import KINDS, month
    fields = request.form
    if set(fields) - {"period_id", "office_id", "document_kind", "occurrence_month", "customer_id", "customer_level", "idempotency_key", "file_name"}:
        raise service.MobileError("上传参数无效")
    key = fields.get("idempotency_key", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", key):
        raise service.MobileError("上传凭证无效，请重新选择文件")
    try:
        period_id, office_id = int(fields.get("period_id", "")), int(fields.get("office_id", ""))
        kind = fields.get("document_kind", "")
        if kind not in KINDS:
            raise ValueError("请选择票据用途")
        occurrence = month(fields.get("occurrence_month", ""))
        customer_id = fields.get("customer_id", "").strip()
        customer_level = fields.get("customer_level", "").strip()
        if len(customer_id) > 64 or len(customer_level) > 8:
            raise ValueError("客户信息无效")
        original = read_original(request.files.get("file"), fields.get("file_name"))
    except (ValueError, TypeError) as exc:
        message = str(exc) if isinstance(exc, ValueError) and str(exc) and not str(exc).startswith("invalid literal") else "请填写有效的归属周期与办事处"
        raise service.MobileError(message, 413 if "20MB" in message else 400) from None
    fingerprint = hashlib.sha256(json.dumps([period_id, office_id, kind, occurrence, customer_id, customer_level, original.sha256]).encode()).hexdigest()
    user_id = current_user.id
    User.query.filter_by(id=user_id).with_for_update().one()
    # Authentication and quota must be rechecked after waiting for the user lock.
    db.session.expire_all()
    if not can_access_private_tool("reimbursement"):
        raise service.MobileError("报销助手使用权限已撤销", 403)
    if not service.authenticate(request.headers.get("Authorization", "")[7:]):
        raise service.MobileError("登录已失效，请重新登录", 401)
    receipt = UploadReceipt.query.filter_by(user_id=user_id, idempotency_key=key).first()
    if receipt:
        if receipt.fingerprint != fingerprint:
            raise service.MobileError("同一上传凭证的文件或用途已改变，请重新选择文件", 409)
        invoice = db.session.get(ReimbursementInvoice, receipt.invoice_id) if receipt.invoice_id else None
        if not invoice or invoice.owner_type != "user" or invoice.owner_id != str(user_id):
            raise service.MobileError("该票据已删除，请重新选择文件", 409)
        return jsonify(success=True, duplicate=True, invoice=invoice_data(invoice))
    if remaining_for("reimbursement") <= 0:
        raise service.MobileError("今日可用次数已用完，请在网站查看账户用量", 429)
    try:
        attachment, _created = persist_original(original, "user", str(user_id))
        invoice, created = create_invoice_record({"period_id":period_id, "office_id":office_id,
            "document_kind":kind, "inclusion_policy":"review" if kind=="invoice" else "retain",
            "occurrence_month":occurrence, "customer_id":customer_id, "customer_level":customer_level,
            "amount_confirmed":False,
            "print_selected":kind in {"invoice", "fuel"}, "file_url":"/tools/reimbursement/preview/"+attachment.stored_name,
            "file_name":original.name, "file_size":len(original.data)}, "user", str(user_id), deduplicate_file=True)
    except InvoiceConflictError as exc:
        raise service.MobileError(str(exc), 409) from None
    except ValueError as exc:
        raise service.MobileError(str(exc)) from None
    db.session.add(UploadReceipt(user_id=user_id, idempotency_key=key, fingerprint=fingerprint, invoice_id=invoice.id))
    if created:
        commit_usage("reimbursement", commit=False)
    db.session.commit()
    return jsonify(success=True, duplicate=not created, invoice=invoice_data(invoice)), 201 if created else 200
