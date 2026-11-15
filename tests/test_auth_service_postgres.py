"""PG16-only concurrency gates; never use the production schema."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
from flask import Flask
from extensions import db, login_manager
from models import User
from auth import account_service, password_reset, session_service
from auth.account_models import WebSession
from tests import test_auth_identity_postgres as fixtures
from tests.test_auth_identity_phase1 import revision


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "isolated PostgreSQL URL not configured")
class AuthServicePostgresTests(unittest.TestCase):
    def setUp(self):
        fixtures.AuthIdentityPostgresTests.setUp(self)
        with self.engine.begin() as conn:
            revision(conn, "b7c8d9e0f1a2_unified_auth_sessions.py")
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY="phase2-isolated-test",
            SQLALCHEMY_DATABASE_URI=os.environ["AUTH_TEST_DATABASE_URL"],
            SQLALCHEMY_ENGINE_OPTIONS={"connect_args": {"options":"-csearch_path="+self.schema, "connect_timeout":10}})
        db.init_app(self.app)
        login_manager.init_app(self.app)

    def cleanup_schema(self):
        if hasattr(self, "app"):
            with self.app.app_context():
                db.session.remove()
                db.engine.dispose()
        fixtures.AuthIdentityPostgresTests.cleanup_schema(self)

    def test_concurrent_legacy_code_redemption_has_exactly_one_winner(self):
        with self.app.app_context():
            user = db.session.get(User, 1)
            email = user.email
            code = password_reset.issue(user)
        barrier = Barrier(2)
        def redeem():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return password_reset.redeem(code, email, "replacement123")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(redeem) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures), [False, True])
        with self.app.app_context():
            self.assertEqual(db.session.get(User, 1).auth_epoch, 1)

    def test_login_racing_password_reset_never_leaves_old_password_session_live(self):
        with self.app.app_context():
            user = db.session.get(User, 1)
            email, code = user.email, password_reset.issue(user)
        barrier = Barrier(2)
        def login():
            with self.app.test_request_context():
                barrier.wait(timeout=10)
                user = account_service.authenticate_password(email, "fixture-password-123", channel="web")
                if user:
                    session_service.start_web_session(user, remember=True)
                else:
                    db.session.commit()
        def reset():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return password_reset.redeem(code, email, "replacement123")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = pool.submit(login), pool.submit(reset)
            first.result(timeout=30)
            self.assertTrue(second.result(timeout=30))
        with self.app.app_context():
            self.assertEqual(WebSession.query.filter_by(revoked_at=None).count(), 0)
            self.assertEqual(db.session.get(User, 1).auth_epoch, 1)
