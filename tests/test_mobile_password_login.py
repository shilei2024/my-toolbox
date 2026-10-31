import unittest
from tests import test_mobile_invoice_upload as fixtures
from extensions import db
from models import User, UserToolGrant
from auth.mobile_models import ExternalIdentity, MobileSession, MobileAccountAudit
from auth import mobile_service


class PasswordLoginTests(unittest.TestCase):
    setUp=fixtures.MobileInvoiceTests.setUp
    challenge=fixtures.MobileInvoiceTests.challenge
    login=fixtures.MobileInvoiceTests.login
    upload=fixtures.MobileInvoiceTests.upload

    def password_sign_in(self,email="mobile0@example.test",password="test-password"):
        return self.mobile.post("/api/mobile/session/password",json={"email":email,"password":password})

    def test_normal_website_credentials_issue_short_scoped_session_and_share_owner(self):
        response=self.password_sign_in("  MOBILE0@example.test  ")
        self.assertEqual(response.status_code,200,response.json)
        self.assertNotIn("Set-Cookie",response.headers)
        self.assertIn("no-store",response.headers["Cache-Control"])
        self.assertEqual(response.json["auth_method"],"password")
        headers={"Authorization":"Bearer "+response.json["access_token"]}
        uploaded=self.upload(headers)
        self.assertEqual(uploaded.status_code,201,uploaded.json)
        invoice=uploaded.json["invoice"]
        self.assertEqual(self.mobile.get(invoice["file_endpoint"],headers=headers).status_code,200)
        self.assertEqual(self.web.get("/tools/reimbursement/api/invoices").json["invoices"][0]["id"],invoice["id"])
        with self.app.app_context():
            session=MobileSession.query.one()
            self.assertNotEqual(session.token_hash,response.json["access_token"])
            self.assertGreater((session.expires_at-session.created_at).total_seconds(),86000)
            self.assertLess((session.expires_at-session.created_at).total_seconds(),86401)
            identity=db.session.get(ExternalIdentity,session.identity_id)
            self.assertEqual(identity.provider,"website_password")
            self.assertNotIn("test-password",identity.subject)
            self.assertTrue(all("test-password" not in a.details_json for a in MobileAccountAudit.query.all()))
        self.assertEqual(self.mobile.get(f"/tools/reimbursement/api/summary/{self.period}",headers=headers).status_code,404)

    def test_failures_are_uniform_and_do_not_create_sessions(self):
        wrong=self.password_sign_in(password="wrong")
        self.assertEqual(wrong.status_code,401)
        self.assertEqual(self.password_sign_in(email="missing@example.test").json,wrong.json)
        with self.app.app_context():
            user=db.session.get(User,1);user.is_active_user=False;db.session.commit()
        self.assertEqual(self.password_sign_in().json,wrong.json)
        with self.app.app_context():
            user=db.session.get(User,1);user.is_active_user=True
            db.session.delete(db.session.get(UserToolGrant,{"user_id":1,"tool_id":"reimbursement"}));db.session.commit()
        self.assertEqual(self.password_sign_in().json,wrong.json)
        with self.app.app_context(): self.assertEqual(MobileSession.query.count(),0)

    def test_password_rotation_invalidates_password_sessions_but_not_wechat(self):
        wechat=self.login()
        first=self.password_sign_in().json["access_token"]
        with self.app.app_context():
            db.session.get(User,1).set_password("new-test-password");db.session.commit()
        headers={"Authorization":"Bearer "+first}
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=headers).status_code,401)
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=wechat).status_code,200)
        self.assertEqual(self.password_sign_in().status_code,401)
        self.assertEqual(self.password_sign_in(password="new-test-password").status_code,200)
        with self.app.app_context():
            self.assertEqual(ExternalIdentity.query.filter_by(provider=mobile_service.PROVIDER,active=True).count(),1)

    def test_independent_sessions_logout_grant_revocation_and_cross_owner(self):
        first=self.password_sign_in().json["access_token"]
        second=self.password_sign_in().json["access_token"]
        other=self.password_sign_in(email="mobile1@example.test").json["access_token"]
        h=lambda token:{"Authorization":"Bearer "+token}
        invoice=self.upload(h(first)).json["invoice"]
        self.assertEqual(self.mobile.get(invoice["file_endpoint"],headers=h(other)).status_code,404)
        self.assertEqual(self.mobile.post("/api/mobile/logout",headers=h(first)).status_code,200)
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=h(first)).status_code,401)
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=h(second)).status_code,200)
        with self.app.app_context():
            db.session.delete(db.session.get(UserToolGrant,{"user_id":1,"tool_id":"reimbursement"}));db.session.commit()
        self.assertEqual(self.mobile.get("/api/mobile/bootstrap",headers=h(second)).status_code,403)
        self.assertEqual(self.mobile.post("/api/mobile/logout",headers=h(second)).status_code,200)

    def test_strict_bounded_payload_and_cookie_rejection(self):
        for data in ({},[],{"email":True,"password":"x"},{"email":"x","password":[]},
                     {"email":"x"*256,"password":"x"},{"email":"x","password":"x"*257},
                     {"email":"x","password":"x","owner_id":"1"}):
            with self.subTest(data_type=type(data).__name__):
                response=self.mobile.post("/api/mobile/session/password",json=data)
                self.assertIn(response.status_code,(400,401),response.json)
                self.assertNotIn("Set-Cookie",response.headers)
        response=self.mobile.post("/api/mobile/session/password",data=b"x"*4097,content_type="application/json")
        self.assertEqual(response.status_code,413,response.json)
        self.assertEqual(self.mobile.post("/api/mobile/session/password",data="{",content_type="application/json").status_code,400)
        self.assertEqual(self.web.post("/api/mobile/session/password",json={"email":"mobile0@example.test","password":"test-password"}).status_code,401)

    def test_unusable_identifiers_fail_uniformly_instead_of_raising(self):
        baseline=self.password_sign_in(password="wrong").json
        for data in ({"email":"\ud800@example.test","password":"x"},
                     {"email":"mobile0\x00@example.test","password":"x"},
                     {"email":"mobile0@ example.test","password":"test-password"},
                     {"email":"mobile0@example.test","password":"\ud800"},
                     {"email":"mobile0@example.test","password":"line\nbreak"}):
            with self.subTest(email_type=type(data["email"]).__name__,value=repr(data)[:40]):
                response=self.mobile.post("/api/mobile/session/password",json=data)
                self.assertEqual(response.status_code,401,response.json)
                self.assertEqual(response.json,baseline)
        with self.app.app_context(): self.assertEqual(MobileSession.query.count(),0)

    def test_blank_occurrence_stages_original_without_inventing_month(self):
        signed=self.password_sign_in().json
        headers={"Authorization":"Bearer "+signed["access_token"]}
        staged=self.upload(headers,kind="invoice",occurrence="")
        self.assertEqual(staged.status_code,201,staged.json)
        self.assertEqual(staged.json["invoice"]["occurrence_month"],"")
        self.assertEqual(staged.json["invoice"]["inclusion_policy"],"review")
        self.assertFalse(staged.json["invoice"]["amount_confirmed"])
        self.assertEqual(self.upload(headers,key="invalid-month-key-00001",kind="invoice",occurrence="2026-99").status_code,400)


class PasswordRateLimitTests(unittest.TestCase):
    setUp=fixtures.MobileInvoiceTests.setUp
    rate_limits_enabled=True

    def test_real_ip_and_normalized_account_limits_return_sanitized_json(self):
        from extensions import limiter
        with self.app.app_context(): limiter.reset()
        for index in range(6):
            response=self.mobile.post("/api/mobile/session/password",json={"email":"mobile0@example.test","password":"wrong"})
            self.assertEqual(response.status_code,401 if index<5 else 429,response.data)
        for index in range(11):
            response=self.mobile.post("/api/mobile/session/password",json={"email":" MOBILE1@EXAMPLE.TEST ","password":"wrong"},
                environ_base={"REMOTE_ADDR":f"198.51.100.{index+1}"})
            self.assertEqual(response.status_code,401 if index<10 else 429,response.data)
        self.assertEqual(response.json,{"error":"尝试次数过多，请稍后再试"})
        self.assertIn("no-store",response.headers["Cache-Control"])
        self.assertNotIn("Set-Cookie",response.headers)

    def test_unusable_identifiers_are_limited_not_a_server_error(self):
        from extensions import limiter
        with self.app.app_context(): limiter.reset()
        statuses=[]
        for index in range(12):
            email=("\ud800" if index%2 else "probe\x00")+f"{index}@example.test"
            response=self.mobile.post("/api/mobile/session/password",json={"email":email,"password":"wrong"},
                environ_base={"REMOTE_ADDR":f"203.0.113.{index+1}"})
            self.assertNotEqual(response.status_code,500,response.data)
            statuses.append(response.status_code)
            if response.status_code==429: break
        self.assertIn(429,statuses)
