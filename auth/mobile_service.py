"""WeChat adapter for shared accounts; registration is explicitly gated."""
import hashlib
import json
import re
import secrets
from datetime import timedelta
import requests
from flask import current_app, session
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import User, utcnow
from .mobile_models import BindingChallenge, ExternalIdentity, MobileAccountAudit, MobileSession
from . import account_service, session_service

PROVIDER = "wechat_miniprogram"
PASSWORD_PROVIDER = "website_password"


class MobileError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def configured():
    return bool(current_app.config.get("WECHAT_MINI_ENABLED") and
        re.fullmatch(r"wx[0-9a-f]{16}", current_app.config.get("WECHAT_MINI_APP_ID", "")) and
        len(current_app.config.get("WECHAT_MINI_APP_SECRET", "").strip()) >= 16)


def client_id():
    return current_app.config["WECHAT_MINI_APP_ID"]


def audit(user_id, action, **details):
    db.session.add(MobileAccountAudit(user_id=user_id, action=action,
        details_json=json.dumps(details, ensure_ascii=False)))


def exchange_code(code):
    if not isinstance(code, str) or not 1 <= len(code) <= 512:
        raise MobileError("微信登录凭证无效，请重试")
    try:
        response = requests.get("https://api.weixin.qq.com/sns/jscode2session", params={
            "appid":client_id(), "secret":current_app.config["WECHAT_MINI_APP_SECRET"],
            "js_code":code, "grant_type":"authorization_code"}, timeout=(3, 10), allow_redirects=False)
        if response.status_code != 200:
            raise ValueError()
        data = response.json()
        subject = data.get("openid")
        if data.get("errcode", 0) != 0 or not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", subject):
            raise ValueError()
        return subject
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        # Never log response bodies, session_key or exceptions containing URLs.
        raise MobileError("微信登录暂不可用，请重新登录后重试", 503) from None


def create_challenge(user_id):
    user = User.query.filter_by(id=user_id, is_active_user=True).with_for_update().first()
    if not user:
        raise MobileError("账号不可用", 403)
    now = utcnow()
    BindingChallenge.query.filter_by(user_id=user_id, provider=PROVIDER, client_id=client_id(), consumed_at=None).update({"consumed_at":now})
    token = secrets.token_urlsafe(24)
    reference = session.get("_user_id", "")
    source_hash = digest(reference[3:]) if isinstance(reference, str) and re.fullmatch(r"v2:[A-Za-z0-9_-]{43}", reference) else None
    if current_app.config.get("WECHAT_MINI_REGISTRATION_ENABLED") and not source_hash:
        raise MobileError("请重新登录网站后生成绑定码", 401)
    db.session.add(BindingChallenge(user_id=user_id, provider=PROVIDER, client_id=client_id(),
        token_hash=digest(token), expires_at=now+timedelta(minutes=10), source_session_hash=source_hash,
        auth_epoch=user.auth_epoch))
    audit(user_id, "binding.challenge_created")
    db.session.commit()
    return token


def identity_for_subject(subject):
    return account_service.identity_for_subject(PROVIDER, client_id(), subject)


def login(subject, binding_code=None):
    now = utcnow()
    identity = identity_for_subject(subject)
    if binding_code:
        if current_app.config.get("WECHAT_MINI_REGISTRATION_ENABLED"):
            raise MobileError("请更新小程序，通过扫码确认完成绑定", 409)
        if not isinstance(binding_code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", binding_code):
            raise MobileError("绑定码无效或已过期")
        challenge = BindingChallenge.query.filter_by(token_hash=digest(binding_code), provider=PROVIDER, client_id=client_id()).first()
        if not challenge:
            raise MobileError("绑定码无效或已过期")
        user = User.query.filter_by(id=challenge.user_id, is_active_user=True).with_for_update().first()
        challenge = BindingChallenge.query.filter_by(id=challenge.id).populate_existing().with_for_update().one()
        now = utcnow()
        if not user or challenge.consumed_at or challenge.expires_at <= now:
            raise MobileError("绑定码无效或已过期")
        identity = ExternalIdentity.query.filter_by(provider=PROVIDER, client_id=client_id(), subject=subject).populate_existing().with_for_update().first()
        if identity and identity.active and identity.user_id != user.id:
            raise MobileError("此微信已绑定其他账号，请先在原网站账号解绑", 409)
        other = ExternalIdentity.query.filter_by(provider=PROVIDER, client_id=client_id(), user_id=user.id, active=True).first()
        if other and (not identity or other.id != identity.id):
            raise MobileError("网站账号已绑定其他微信，请先解绑", 409)
        if not identity:
            identity = ExternalIdentity(provider=PROVIDER, client_id=client_id(), subject=subject)
            db.session.add(identity)
        identity.user_id, identity.active = user.id, True
        challenge.consumed_at = now
        db.session.flush()
        audit(user.id, "binding.bound", identity_id=identity.id)
    else:
        if identity is None and current_app.config.get("WECHAT_MINI_REGISTRATION_ENABLED", False):
            from models import Tool, UserToolGrant
            if not db.session.get(Tool, "reimbursement"):
                raise MobileError("发票助手暂未准备就绪，请稍后再试", 503)
            try:
                user = User(email=None, password_hash=None, is_admin=False, is_active_user=True, nickname="微信用户")
                db.session.add(user)
                db.session.flush()
                identity = ExternalIdentity(provider=PROVIDER, client_id=client_id(), subject=subject,
                    user_id=user.id, active=True, identity_type="wechat")
                db.session.add(identity)
                db.session.add(UserToolGrant(user_id=user.id, tool_id="reimbursement"))
                db.session.flush()
                account_service.audit(user.id, "account.registered", "wechat")
            except IntegrityError:
                db.session.rollback()
                identity = identity_for_subject(subject)
                if identity is None:
                    raise MobileError("注册状态已变化，请重试", 409) from None
        if not identity or not identity.active or not identity.user_id:
            raise MobileError("请先在网站个人资料生成绑定码", 428)
        user = User.query.filter_by(id=identity.user_id, is_active_user=True).with_for_update().first()
        identity = ExternalIdentity.query.filter_by(id=identity.id).populate_existing().with_for_update().one()
        if not user or not identity.active or identity.user_id != user.id:
            raise MobileError("账号绑定已失效，请重新绑定", 401)
    now = utcnow()
    token, expires = session_service.issue_mobile_session(user, identity, channel="wechat", lifetime=timedelta(days=7))
    audit(user.id, "session.created", identity_id=identity.id)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise MobileError("绑定状态已变化，请重试", 409) from None
    return {"access_token":token, "expires_at":expires.isoformat()+"Z", "display_name":user.nickname or "网站账号"}


def authenticate(raw_token):
    if not configured() or not isinstance(raw_token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw_token):
        return None
    row = MobileSession.query.filter_by(token_hash=digest(raw_token)).populate_existing().first()
    if not row or row.revoked_at or row.expires_at <= utcnow():
        return None
    identity = db.session.get(ExternalIdentity, row.identity_id, populate_existing=True)
    user = db.session.get(User, row.user_id, populate_existing=True)
    if not identity or not identity.active or identity.client_id != client_id() or identity.provider not in {PROVIDER,PASSWORD_PROVIDER} or identity.user_id != row.user_id or not user or not user.is_active_user:
        return None
    if row.auth_epoch != user.auth_epoch:
        return None
    if identity.provider == PASSWORD_PROVIDER and identity.subject != digest(f'{user.id}:{user.password_hash}'):
        return None
    return user, row


normalized_email = account_service.normalized_email


def password_login(email, password):
    """Normal website credentials issue only a scoped, short-lived mobile session."""
    message = "账号或密码不正确，或账号暂不可用"
    user = account_service.authenticate_password(email, password, channel="mobile_password")
    from models import UserToolGrant

    if (not user or (not user.is_admin
            and not db.session.get(UserToolGrant, {"user_id": user.id, "tool_id": "reimbursement"}))):
        db.session.rollback()
        account_service.audit(None, "login.failed", "mobile_password")
        db.session.commit()
        raise MobileError(message, 401)
    subject = digest(f"{user.id}:{user.password_hash}")
    identity = ExternalIdentity.query.filter_by(provider=PASSWORD_PROVIDER, client_id=client_id(), subject=subject).first()
    if not identity:
        identity = ExternalIdentity(provider=PASSWORD_PROVIDER, client_id=client_id(), subject=subject, user_id=user.id, active=True)
        db.session.add(identity)
        db.session.flush()
    if not identity.active or identity.user_id != user.id:
        raise MobileError(message, 401)
    token, expires = session_service.issue_mobile_session(user, identity, channel="mobile_password", lifetime=timedelta(hours=24))
    audit(user.id, "password_session.created", identity_id=identity.id)
    db.session.commit()
    return {"access_token": token, "expires_at": expires.isoformat()+"Z", "display_name": user.nickname or "网站账号", "auth_method": "password"}


def unbind(user_id, identity_id):
    user = account_service.lock_account(user_id)
    if not user or not user.email or not user.password_hash or user.password_hash == "!":
        raise MobileError("请先设置网站登录方式，再解绑微信", 409)
    identity = ExternalIdentity.query.filter_by(id=identity_id, user_id=user_id,
        provider=PROVIDER, client_id=client_id(), active=True).with_for_update().first()
    if not identity:
        raise MobileError("绑定不存在", 404)
    MobileSession.query.filter_by(identity_id=identity.id, revoked_at=None).update({"revoked_at":utcnow()})
    BindingChallenge.query.filter_by(user_id=user_id, provider=PROVIDER, client_id=client_id(), consumed_at=None).update({"consumed_at":utcnow()})
    identity.active, identity.user_id = False, None
    audit(user_id, "binding.unbound", identity_id=identity.id)
    account_service.audit(user_id, "identity.unbound", "web")
    db.session.commit()


def _valid_source(challenge, user):
    from .account_models import WebSession
    if not user or not user.is_active_user or challenge.consumed_at or challenge.expires_at <= utcnow() or challenge.auth_epoch != user.auth_epoch:
        return False
    if challenge.source_session_hash:
        row = WebSession.query.filter_by(token_hash=challenge.source_session_hash, user_id=user.id).populate_existing().first()
        return bool(row and not row.revoked_at and row.expires_at > utcnow() and row.auth_epoch == user.auth_epoch)
    return False


def prepare_binding(subject, code):
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32}", code):
        raise MobileError("绑定码无效或已过期")
    challenge = BindingChallenge.query.filter_by(token_hash=digest(code), provider=PROVIDER, client_id=client_id()).first()
    if not challenge:
        raise MobileError("绑定码无效或已过期")
    user = account_service.lock_account(challenge.user_id)
    challenge = BindingChallenge.query.filter_by(id=challenge.id).populate_existing().with_for_update().one()
    if not _valid_source(challenge, user):
        raise MobileError("网站登录或绑定码已失效，请重新生成", 409)
    identity = identity_for_subject(subject)
    if identity and identity.active and identity.user_id != user.id:
        raise MobileError("微信已有独立账号，为保护已有数据不能自动合并；请使用原账号或联系管理员", 409)
    confirmation = secrets.token_urlsafe(32)
    challenge.prepared_subject, challenge.confirmation_hash = subject, digest(confirmation)
    db.session.commit()
    return {"confirmation_token": confirmation, "account_label": (user.email[:2]+"***@"+user.email.split("@")[-1]) if user.email else "目标账号",
            "expires_in": max(0, int((challenge.expires_at-utcnow()).total_seconds()))}


def confirm_binding(subject, confirmation):
    if not isinstance(confirmation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", confirmation):
        raise MobileError("确认已失效，请重新扫码")
    challenge = BindingChallenge.query.filter_by(confirmation_hash=digest(confirmation), provider=PROVIDER, client_id=client_id()).first()
    if not challenge:
        raise MobileError("确认已失效，请重新扫码")
    user = account_service.lock_account(challenge.user_id)
    challenge = BindingChallenge.query.filter_by(id=challenge.id).populate_existing().with_for_update().one()
    if not _valid_source(challenge, user) or challenge.prepared_subject != subject:
        raise MobileError("确认已失效，请重新扫码", 409)
    identity = identity_for_subject(subject)
    if identity and identity.active and identity.user_id != user.id:
        raise MobileError("微信已属于其他账号，不能自动合并数据", 409)
    other = ExternalIdentity.query.filter_by(provider=PROVIDER, client_id=client_id(), user_id=user.id, active=True).first()
    if other and (not identity or other.id != identity.id):
        raise MobileError("网站账号已有微信，请先解绑", 409)
    try:
        if not identity:
            identity = ExternalIdentity(provider=PROVIDER, client_id=client_id(), subject=subject, identity_type="wechat")
            db.session.add(identity)
        identity.user_id, identity.active = user.id, True
        challenge.consumed_at = utcnow()
        db.session.flush()
        token, expires = session_service.issue_mobile_session(user, identity, channel="wechat", lifetime=timedelta(days=7))
        account_service.audit(user.id, "identity.bound", "wechat")
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        raise MobileError("绑定状态已变化，请重新扫码", 409) from None
    return {"access_token":token, "expires_at":expires.isoformat()+"Z", "display_name":user.display_name, "auth_method":"wechat"}
