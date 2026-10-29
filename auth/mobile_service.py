"""Account linking does not create accounts or grant website sessions."""
import hashlib
import json
import re
import secrets
from datetime import timedelta
import requests
from flask import current_app
from sqlalchemy.exc import IntegrityError
from extensions import db
from models import User, utcnow
from .mobile_models import BindingChallenge, ExternalIdentity, MobileAccountAudit, MobileSession

PROVIDER = "wechat_miniprogram"


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
    db.session.add(BindingChallenge(user_id=user_id, provider=PROVIDER, client_id=client_id(),
        token_hash=digest(token), expires_at=now+timedelta(minutes=10)))
    audit(user_id, "binding.challenge_created")
    db.session.commit()
    return token


def identity_for_subject(subject):
    return ExternalIdentity.query.filter_by(provider=PROVIDER, client_id=client_id(), subject=subject).first()


def login(subject, binding_code=None):
    now = utcnow()
    identity = identity_for_subject(subject)
    if binding_code:
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
        if not identity or not identity.active or not identity.user_id:
            raise MobileError("请先在网站个人资料生成绑定码", 428)
        user = User.query.filter_by(id=identity.user_id, is_active_user=True).with_for_update().first()
        identity = ExternalIdentity.query.filter_by(id=identity.id).populate_existing().with_for_update().one()
        if not user or not identity.active or identity.user_id != user.id:
            raise MobileError("账号绑定已失效，请重新绑定", 401)
    now = utcnow()
    token = secrets.token_urlsafe(32)
    expires = now + timedelta(days=7)
    db.session.add(MobileSession(identity_id=identity.id, user_id=user.id, token_hash=digest(token), expires_at=expires))
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
    if not identity or not identity.active or identity.client_id != client_id() or identity.provider != PROVIDER or identity.user_id != row.user_id or not user or not user.is_active_user:
        return None
    return user, row


def unbind(user_id, identity_id):
    User.query.filter_by(id=user_id).with_for_update().one()
    identity = ExternalIdentity.query.filter_by(id=identity_id, user_id=user_id,
        provider=PROVIDER, client_id=client_id(), active=True).with_for_update().first()
    if not identity:
        raise MobileError("绑定不存在", 404)
    MobileSession.query.filter_by(identity_id=identity.id, revoked_at=None).update({"revoked_at":utcnow()})
    BindingChallenge.query.filter_by(user_id=user_id, provider=PROVIDER, client_id=client_id(), consumed_at=None).update({"consumed_at":utcnow()})
    identity.active, identity.user_id = False, None
    audit(user_id, "binding.unbound", identity_id=identity.id)
    db.session.commit()
