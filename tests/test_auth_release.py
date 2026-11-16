"""Synthetic end-to-end tests for email, WeChat registration and safe binding."""
import unittest
from datetime import timedelta
from unittest.mock import patch
from flask import current_app
from extensions import db, login_manager
from models import User, UserToolGrant, utcnow
from auth import account_service, email_service, mobile_service, session_service
from auth.account_models import ActionToken, AuthMailJob, WebSession
from auth.mobile_models import ExternalIdentity, MobileSession
from auth.email_routes import security_bp
from tests import test_auth_service_phase2 as web_fixture
from tests import test_mobile_invoice_upload as mobile_fixture
from shared.mail import MailError


class EmailSecurityTests(unittest.TestCase):
    setUp = web_fixture.AuthServiceTests.setUp
    sign_in = web_fixture.AuthServiceTests.sign_in

    def capture(self):
        self.app.config.update(AUTH_MAIL_ADAPTER="capture", APP_BASE_URL="https://mindfulpenpal.com")

    def token(self):
        return current_app.extensions["auth_mail_capture"][-1][2].split("#")[1].split("\n")[0]

    def test_verified_email_required_and_full_reset_revokes_session(self):
        self.capture()
        self.sign_in()
        with self.app.app_context():
            self.assertFalse(email_service.enqueue(1,"reset","person@example.com"))
            self.assertTrue(email_service.enqueue(1,"verify","person@example.com"))
            self.assertTrue(email_service.enqueue(1,"verify","person@example.com"))
            db.session.commit()
            self.assertEqual(AuthMailJob.query.count(),1)
            self.assertEqual(email_service.dispatch()["sent"],1)
            raw=self.token()
            self.assertNotEqual(ActionToken.query.one().token_hash,raw)
            self.assertFalse(email_service.consume(raw,"reset","replacement123"))
            self.assertTrue(email_service.consume(raw,"verify"))
            self.assertFalse(email_service.consume(raw,"verify"))
            email_service.enqueue(1,"reset","person@example.com")
            db.session.commit()
            email_service.dispatch()
            raw=self.token()
            self.assertFalse(email_service.consume(raw,"reset","short"))
            self.assertTrue(email_service.consume(raw,"reset","replacement123"))
            self.assertTrue(db.session.get(User,1).check_password("replacement123"))
        self.assertIsNone(self.client.get("/who").json["id"])

    def test_expired_changed_target_and_epoch_tokens_cannot_be_consumed(self):
        self.capture()
        with self.app.app_context():
            email_service.enqueue(1,"verify","person@example.com");db.session.commit()
            email_service.dispatch();raw=self.token()
            user=account_service.lock_account(1)
            user.email="other@example.com";db.session.commit()
            self.assertFalse(email_service.consume(raw,"verify"))
            user=account_service.lock_account(1);user.email="person@example.com"
            user.auth_epoch+=1;db.session.commit()
            self.assertFalse(email_service.consume(raw,"verify"))
            user=account_service.lock_account(1);user.auth_epoch=0
            ActionToken.query.one().expires_at=utcnow()-timedelta(seconds=1);db.session.commit()
            self.assertFalse(email_service.consume(raw,"verify"))

    def test_failed_send_retries_with_new_token_without_persisting_links(self):
        self.capture()
        with self.app.app_context():
            email_service.enqueue(1,"verify","person@example.com");db.session.commit()
            self.app.config["AUTH_MAIL_ADAPTER"]="smtp"
            with patch("auth.email_service.ready",return_value=True), patch("auth.email_service.send_smtp",side_effect=MailError("SMTP_DELIVERY_FAILED")):
                self.assertEqual(email_service.dispatch()["failed"],1)
            old=ActionToken.query.one().token_hash
            job=AuthMailJob.query.one();job.next_attempt_at=utcnow()-timedelta(seconds=1);db.session.commit()
            self.app.config["AUTH_MAIL_ADAPTER"]="capture"
            email_service.dispatch()
            self.assertIsNotNone(ActionToken.query.filter_by(token_hash=old).one().consumed_at)
            self.assertEqual(AuthMailJob.query.one().status,"sent")
            self.assertTrue(email_service.consume(self.token(),"verify"))

    def test_disabled_mail_and_public_response_do_not_claim_delivery(self):
        self.app.register_blueprint(security_bp)
        with patch("auth.email_routes.render_template",side_effect=lambda name,**kw:kw.get("message","")):
            response=self.client.post("/account/recover",data={"email":"person@example.com"})
            self.assertIn("暂不可用",response.get_data(as_text=True))
            self.capture()
            first=self.client.post("/account/recover",data={"email":"person@example.com"})
            second=self.client.post("/account/recover",data={"email":"missing@example.com"})
            self.assertEqual(first.data,second.data)
        with self.app.app_context():
            self.app.testing=False
            self.assertFalse(email_service.ready())

    def test_landing_get_does_not_consume_and_uses_nonce_csp(self):
        self.app.register_blueprint(security_bp)
        from jinja2 import FileSystemLoader
        from pathlib import Path
        self.app.jinja_loader=FileSystemLoader(Path(__file__).resolve().parents[1]/"templates")
        response=self.client.get("/account/email/verify")
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers["Referrer-Policy"],"same-origin")
        self.assertIn("default-src 'none'",response.headers["Content-Security-Policy"])
        self.assertIn(b"history.replaceState",response.data)
        with self.app.app_context():
            self.assertEqual(ActionToken.query.count(),0)


class WechatRegistrationTests(unittest.TestCase):
    setUp=mobile_fixture.MobileInvoiceTests.setUp

    def signup(self,subject="new-wechat"):
        self.app.config["WECHAT_MINI_REGISTRATION_ENABLED"]=True
        with patch("auth.mobile_service.exchange_code",return_value=subject):
            response=self.mobile.post("/api/mobile/session",json={"code":"synthetic-code"})
        self.assertEqual(response.status_code,200,response.json)
        return {"Authorization":"Bearer "+response.json["access_token"]}

    def test_register_has_only_invoice_grant_and_repeat_same_account(self):
        headers=self.signup()
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=headers).status_code,200)
        self.assertEqual(self.mobile.get("/api/mobile/account",headers=headers).json["account_id"],3)
        self.signup()
        with self.app.app_context():
            self.assertEqual(User.query.count(),3)
            user=db.session.get(User,3)
            self.assertIsNone(user.email);self.assertIsNone(user.password_hash);self.assertFalse(user.is_admin)
            self.assertEqual([g.tool_id for g in UserToolGrant.query.filter_by(user_id=3)], ["reimbursement"])
            with self.assertRaises(mobile_service.MobileError):
                mobile_service.unbind(3,ExternalIdentity.query.filter_by(user_id=3).one().id)

    def test_wechat_user_sets_website_password_same_id_old_token_revoked(self):
        headers=self.signup()
        with patch("auth.mobile_service.exchange_code",return_value="new-wechat"):
            response=self.mobile.post("/api/mobile/account/password",headers=headers,
                json={"code":"fresh-code","email":"new@example.com","password":"password123"})
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(self.mobile.get("/api/mobile/account",headers=headers).status_code,401)
        newer={"Authorization":"Bearer "+response.json["access_token"]}
        self.assertTrue(self.mobile.get("/api/mobile/account",headers=newer).json["has_password"])
        with self.app.app_context():
            user=account_service.authenticate_password("new@example.com","password123",channel="web")
            self.assertEqual(user.id,3)
            self.assertEqual(User.query.count(),3)

    def test_failed_wechat_exchange_never_creates_user(self):
        self.app.config["WECHAT_MINI_REGISTRATION_ENABLED"]=True
        with patch("auth.mobile_service.exchange_code",side_effect=mobile_service.MobileError("暂不可用",503)):
            self.assertEqual(self.mobile.post("/api/mobile/session",json={"code":"bad"}).status_code,503)
        with self.app.app_context(): self.assertEqual(User.query.count(),2)

    def prepare_source(self):
        self.app.config["WECHAT_MINI_REGISTRATION_ENABLED"]=True
        login_manager.user_loader(session_service.load_web_user)
        with self.app.app_context():
            db.session.add(WebSession(user_id=1,token_hash=session_service.digest("a"*43),auth_epoch=0,expires_at=utcnow()+timedelta(hours=1)))
            db.session.commit()
        with self.web.session_transaction() as value:
            value["_user_id"]="v2:"+"a"*43;value["_fresh"]=True
        response=self.web.post("/auth/mobile/challenge",json={"password":"test-password"})
        self.assertEqual(response.status_code,200,response.json)
        return response.json["binding_code"]

    def test_binding_requires_confirmation_and_live_source_session(self):
        code=self.prepare_source()
        with patch("auth.mobile_service.exchange_code",return_value="fresh-wechat"):
            prepared=self.mobile.post("/api/mobile/binding/prepare",json={"code":"wx-code","binding_code":code})
            self.assertEqual(prepared.status_code,200,prepared.json)
            with self.app.app_context(): self.assertEqual(ExternalIdentity.query.filter_by(provider=mobile_service.PROVIDER).count(),0)
            token=prepared.json["confirmation_token"]
            with self.app.app_context():
                WebSession.query.one().revoked_at=utcnow();db.session.commit()
            response=self.mobile.post("/api/mobile/binding/confirm",json={"code":"new-code","confirmation_token":token})
            self.assertEqual(response.status_code,409)

    def test_binding_confirm_once_and_existing_account_conflict(self):
        code=self.prepare_source()
        with patch("auth.mobile_service.exchange_code",return_value="fresh-wechat"):
            prepared=self.mobile.post("/api/mobile/binding/prepare",json={"code":"wx-code","binding_code":code})
            payload={"code":"new-code","confirmation_token":prepared.json["confirmation_token"]}
            self.assertEqual(self.mobile.post("/api/mobile/binding/confirm",json=payload).status_code,200)
            self.assertEqual(self.mobile.post("/api/mobile/binding/confirm",json=payload).status_code,409)
        self.signup("different-account")
        with patch("auth.mobile_service.exchange_code",return_value="different-account"):
            newer=self.web.post("/auth/mobile/challenge",json={"password":"test-password"}).json["binding_code"]
            response=self.mobile.post("/api/mobile/binding/prepare",json={"code":"code","binding_code":newer})
            self.assertEqual(response.status_code,409)
        with self.app.app_context():self.assertEqual(User.query.count(),3)


if __name__ == "__main__": unittest.main()
