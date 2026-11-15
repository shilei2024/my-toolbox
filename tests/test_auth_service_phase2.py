"""Real Flask cookie/remember flows and shared cross-channel revocation."""
import importlib
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

import sqlalchemy as sa
from flask import Flask
from flask_login import current_user
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from werkzeug.security import generate_password_hash
import customer_projects.models  # noqa: F401
import tools.reimbursement.models  # noqa: F401
from extensions import csrf, db, limiter, login_manager
from models import User, utcnow
from auth import account_service as accounts, mobile_service, password_reset, session_service as sessions
from auth.account_models import AuthAudit, WebSession
from auth.mobile_models import BindingChallenge, ExternalIdentity, MobileSession
from auth.routes import auth_bp
from tests.test_auth_identity_phase1 import legacy_fixture, revision, NEW


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="phase2-synthetic-secret",
            SQLALCHEMY_DATABASE_URI="sqlite://", WTF_CSRF_ENABLED=False,
            RATELIMIT_ENABLED=False, WECHAT_MINI_ENABLED=True,
            WECHAT_MINI_APP_ID="wx0123456789abcdef", WECHAT_MINI_APP_SECRET="x"*32,
            GALLERY_INTROSPECTION_SECRET="g"*32)
        db.init_app(self.app)
        csrf.init_app(self.app)
        limiter.init_app(self.app)
        login_manager.init_app(self.app)
        login_manager.user_loader(sessions.load_web_user)
        self.app.register_blueprint(auth_bp)
        self.app.add_url_rule("/", "home", lambda: "home")
        self.app.add_url_rule("/who", "who", lambda: {"id": current_user.id if current_user.is_authenticated else None})
        with self.app.app_context():
            db.create_all()
            user = User(email="person@example.com", is_admin=False,
                        password_hash=generate_password_hash("password123", method="pbkdf2:sha256:1000"))
            db.session.add(user)
            db.session.commit()
        self.client = self.app.test_client()

    def sign_in(self, client=None):
        return (client or self.client).post("/login", data={"email": "PERSON@example.com", "password": "password123", "remember": "y"})

    def test_login_opaque_cookie_remember_and_gallery_keep_numeric_account(self):
        self.assertEqual(self.sign_in().status_code, 302)
        with self.client.session_transaction() as value:
            self.assertTrue(value["_user_id"].startswith("v2:"))
        self.assertEqual(self.client.get("/who").json, {"id": 1})
        response = self.client.get("/internal/gallery/session", headers={"X-Mavis-Introspection-Secret":"g"*32})
        self.assertEqual(response.json["userId"], 1)
        self.client.delete_cookie("session")
        self.assertEqual(self.client.get("/who").json, {"id": 1})
        with self.app.app_context():
            self.assertEqual(WebSession.query.count(), 1)
            identity = ExternalIdentity.query.filter_by(provider="web_password").one()
            self.assertEqual(identity.password_hash, db.session.get(User, 1).password_hash)

    def test_logout_revokes_replayed_cookie_and_remember_but_other_session_survives(self):
        self.sign_in()
        other = self.app.test_client()
        self.sign_in(other)
        cookie = self.client.get_cookie("session").value
        remember = self.client.get_cookie("remember_token").value
        with patch("auth.routes.render_template", return_value="confirm"):
            self.assertEqual(self.client.get("/logout").status_code, 200)
        self.assertEqual(self.client.get("/who").json["id"], 1)
        self.assertEqual(self.client.post("/logout").status_code, 302)
        replay = self.app.test_client()
        replay.set_cookie("session", cookie)
        self.assertIsNone(replay.get("/who").json["id"])
        replay.delete_cookie("session")
        replay.set_cookie("remember_token", remember)
        self.assertIsNone(replay.get("/who").json["id"])
        self.assertEqual(other.get("/who").json["id"], 1)

    def test_register_mirrors_identity_without_private_grants(self):
        response = self.client.post("/register", data={"email":"new@example.com", "password":"password123", "confirm":"password123"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/who").json["id"], 2)
        with self.app.app_context():
            from models import UserToolGrant
            self.assertEqual(UserToolGrant.query.count(), 0)
            identity = ExternalIdentity.query.filter_by(user_id=2, provider="web_password").one()
            self.assertIsNone(identity.verified_at)
            self.assertFalse(db.session.get(User, 2).is_admin)

    def test_logout_confirmation_and_csrf_protect_mutation(self):
        self.sign_in()
        self.app.config["WTF_CSRF_ENABLED"] = True
        self.app.jinja_loader = ChoiceLoader([
            DictLoader({"base.html": "{% block content %}{% endblock %}"}),
            FileSystemLoader(Path(__file__).resolve().parents[1] / "templates")])
        response = self.client.get("/logout")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'name="csrf_token"', response.data)
        self.assertEqual(self.client.post("/logout").status_code, 400)
        self.assertEqual(self.client.get("/who").json["id"], 1)

    def test_failed_login_is_generic_and_audit_has_no_identifier(self):
        with patch("auth.routes.render_template", return_value="failed"):
            self.assertEqual(self.client.post("/login", data={"email":"person@example.com", "password":"wrong123"}).status_code, 401)
        with self.app.app_context():
            record = AuthAudit.query.one()
            self.assertEqual(record.action, "login.failed")
            self.assertIsNone(record.user_id)
            self.assertEqual(WebSession.query.count(), 0)

    def mobile_tokens(self):
        user = accounts.lock_account(1)
        results = []
        for provider, subject in ((mobile_service.PROVIDER, "synthetic-openid"),
                (mobile_service.PASSWORD_PROVIDER, mobile_service.digest(f"1:{user.password_hash}"))):
            identity = ExternalIdentity(provider=provider, client_id=self.app.config["WECHAT_MINI_APP_ID"],
                subject=subject, user_id=1, active=True)
            db.session.add(identity)
            db.session.flush()
            results.append(sessions.issue_mobile_session(user, identity, channel="test", lifetime=timedelta(hours=1))[0])
        db.session.add(BindingChallenge(user_id=1, provider=mobile_service.PROVIDER, client_id=self.app.config["WECHAT_MINI_APP_ID"],
            token_hash="c"*64, expires_at=utcnow()+timedelta(minutes=10)))
        db.session.commit()
        return results

    def test_reset_revokes_web_remember_both_mobile_channels_and_challenges(self):
        self.sign_in()
        with self.app.app_context():
            tokens = self.mobile_tokens()
            self.assertTrue(all(mobile_service.authenticate(t) for t in tokens))
            code = password_reset.issue(db.session.get(User, 1))
            self.assertTrue(password_reset.redeem(code, "person@example.com", "replacement123"))
            self.assertFalse(password_reset.redeem(code, "person@example.com", "replacement456"))
            self.assertTrue(all(mobile_service.authenticate(t) is None for t in tokens))
            self.assertIsNotNone(BindingChallenge.query.one().consumed_at)
            self.assertEqual(db.session.get(User, 1).auth_epoch, 1)
            self.assertEqual(ExternalIdentity.query.filter_by(provider="web_password").one().password_hash, db.session.get(User, 1).password_hash)
        self.assertIsNone(self.client.get("/who").json["id"])
        self.client.delete_cookie("session")
        self.assertIsNone(self.client.get("/who").json["id"])
        self.assertEqual(self.client.post("/login", data={"email":"person@example.com", "password":"replacement123"}).status_code, 302)
        self.assertEqual(self.client.get("/who").json["id"], 1)

    def test_disable_enable_never_revives_old_sessions(self):
        self.sign_in()
        with self.app.app_context():
            tokens = self.mobile_tokens()
            accounts.toggle_active(1)
            db.session.commit()
            accounts.toggle_active(1)
            db.session.commit()
            self.assertTrue(all(mobile_service.authenticate(t) is None for t in tokens))
            self.assertEqual(db.session.get(User, 1).auth_epoch, 2)
        self.assertIsNone(self.client.get("/who").json["id"])
        self.assertEqual(self.sign_in().status_code, 302)

    def test_legacy_cookie_window_epoch_and_logout(self):
        with self.client.session_transaction() as value:
            value["_user_id"] = "1"
        self.assertIsNone(self.client.get("/who").json["id"])
        self.app.config["AUTH_LEGACY_COOKIE_UNTIL"] = "2999-01-01T00:00:00Z"
        self.assertEqual(self.client.get("/who").json["id"], 1)
        self.client.post("/logout")
        with self.client.session_transaction() as value:
            value["_user_id"] = "1"
        self.assertIsNone(self.client.get("/who").json["id"])
        with self.app.app_context():
            self.assertEqual(db.session.get(User, 1).auth_epoch, 1)
            for cutoff in ("", "bad", "2999-01-01", "2000-01-01T00:00:00Z"):
                self.app.config["AUTH_LEGACY_COOKIE_UNTIL"] = cutoff
                self.assertFalse(sessions.legacy_cookie_allowed())

    def test_expiry_and_malformed_identifiers_fail_closed(self):
        self.sign_in()
        with self.app.app_context():
            WebSession.query.one().expires_at = utcnow()-timedelta(seconds=1)
            db.session.commit()
            for identifier in (None, "v2:bad", "-1", "01", "1:x", "999999999999999999"):
                self.assertIsNone(sessions.load_web_user(identifier))
        self.assertIsNone(self.client.get("/who").json["id"])

    def test_transaction_rollback_preserves_password_epoch_and_sessions(self):
        self.sign_in()
        with self.app.app_context():
            user = db.session.get(User, 1)
            old = user.password_hash
            self.assertTrue(accounts.change_password(1, "replacement123", expected_hash=old))
            db.session.flush()
            db.session.rollback()
            self.assertEqual(db.session.get(User, 1).password_hash, old)
            self.assertEqual(db.session.get(User, 1).auth_epoch, 0)
            self.assertIsNone(WebSession.query.one().revoked_at)
            self.assertFalse(accounts.change_password(1, "replacement123", expected_hash="stale"))
        self.assertEqual(self.client.get("/who").json["id"], 1)

    def test_soft_delete_retains_id_disables_canonical_identity(self):
        self.sign_in()
        with self.app.app_context():
            accounts.soft_delete(1)
            db.session.commit()
            self.assertEqual(User.query.count(), 1)
            self.assertFalse(ExternalIdentity.query.filter_by(provider="web_password").one().active)
            self.assertEqual(db.session.get(User, 1).auth_epoch, 1)
        self.assertIsNone(self.client.get("/who").json["id"])


class AuthSessionMigrationTests(unittest.TestCase):
    def test_additive_upgrade_empty_downgrade_and_used_schema_guard(self):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        module = importlib.import_module("migrations.versions.b7c8d9e0f1a2_unified_auth_sessions")
        engine = sa.create_engine("sqlite://")
        with engine.begin() as conn:
            legacy_fixture(conn)
            revision(conn, NEW)
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
                module.downgrade()
                module.upgrade()
                conn.exec_driver_sql("INSERT INTO account_auth_audits(user_id,action,channel,created_at) VALUES(1,'test','test',CURRENT_TIMESTAMP)")
                with self.assertRaisesRegex(RuntimeError, "keep_compatible"):
                    module.downgrade()
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
