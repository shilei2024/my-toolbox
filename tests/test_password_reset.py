import unittest
from unittest.mock import patch

from flask import Flask

import customer_projects.models  # noqa: F401  (register tables for create_all)
import tools.reimbursement.models  # noqa: F401
from auth import password_reset
from auth.routes import auth_bp
from extensions import csrf, db, limiter, login_manager
from models import User


class PasswordResetTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SECRET_KEY="test-secret-key-0123456789abcdef",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            WTF_CSRF_ENABLED=False,
            RATELIMIT_ENABLED=False,
            PASSWORD_RESET_MODE="admin",
            PASSWORD_RESET_TTL_MINUTES=30,
        )
        db.init_app(self.app)
        csrf.init_app(self.app)
        limiter.init_app(self.app)
        login_manager.init_app(self.app)
        login_manager.user_loader(lambda uid: db.session.get(User, int(uid)))
        self.app.register_blueprint(auth_bp, url_prefix="/auth")
        with self.app.app_context():
            db.create_all()
            user = User(email="member@example.test")
            user.set_password("old-password")
            db.session.add(user)
            db.session.commit()
            self.uid = user.id
        self.client = self.app.test_client()

    def code(self):
        with self.app.app_context():
            return password_reset.issue(db.session.get(User, self.uid))

    def test_code_binds_to_the_current_password_and_can_only_be_used_once(self):
        code = self.code()
        with self.app.app_context():
            user, reason = password_reset.verify(code)
            self.assertIsNone(reason)
            self.assertEqual(user.id, self.uid)
            self.assertEqual(password_reset.verify(code, max_age=-1)[1], "expired")
        with patch("auth.routes.render_template", return_value="ok"):
            response = self.client.post(
                "/auth/forgot",
                data={"email": "member@example.test", "code": code, "password": "new-password", "confirm": "new-password"},
            )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/auth/login"))
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.uid).check_password("new-password"))
            self.assertFalse(db.session.get(User, self.uid).check_password("old-password"))
            self.assertEqual(password_reset.verify(code)[1], "invalid")

    def test_wrong_account_short_password_and_mismatch_never_change_it(self):
        code = self.code()
        with patch("auth.routes.render_template", return_value="ok") as rendered:
            for data in (
                {"email": "other@example.test", "code": code, "password": "new-password", "confirm": "new-password"},
                {"email": "member@example.test", "code": code, "password": "short", "confirm": "short"},
                {"email": "member@example.test", "code": code, "password": "new-password", "confirm": "different"},
                {"email": "member@example.test", "code": "forged-code", "password": "new-password", "confirm": "new-password"},
            ):
                response = self.client.post("/auth/forgot", data=data)
                self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(rendered.call_count, 4)
        with self.app.app_context():
            self.assertTrue(db.session.get(User, self.uid).check_password("old-password"))

    def test_disabled_mode_hides_the_flow(self):
        self.app.config.update(PASSWORD_RESET_MODE="disabled")
        self.assertEqual(self.client.get("/auth/forgot").status_code, 404)
        with self.app.app_context(), self.assertRaises(ValueError):
            password_reset.issue(db.session.get(User, self.uid))
