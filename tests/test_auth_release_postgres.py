"""Independent PostgreSQL schemas for real release concurrency gates."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
import uuid
import sqlalchemy as sa
from extensions import db
from models import User
from auth import mobile_service, email_service
from tests import test_auth_release as cases
from tests.test_auth_identity_phase1 import legacy_fixture, revision, NEW, snapshot


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "isolated PostgreSQL URL not configured")
class AuthReleasePostgresTests(cases.WechatRegistrationTests):
    def test_full_application_harness(self):
        from tests.test_auth_staging_smoke import AuthStagingTests
        AuthStagingTests.test_unified_restore_harness(self)

    def setUp(self):
        url=sa.engine.make_url(os.environ["AUTH_TEST_DATABASE_URL"])
        if url.get_backend_name() != "postgresql": self.skipTest("PostgreSQL required")
        self.schema="auth_rehearsal_"+uuid.uuid4().hex
        self.admin=sa.create_engine(url)
        with self.admin.begin() as conn: conn.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.addCleanup(self.cleanup)
        self.database_uri=url.update_query_dict({"options":"-csearch_path="+self.schema})
        super().setUp()

    def cleanup(self):
        if hasattr(self,"app"):
            with self.app.app_context():db.session.remove();db.engine.dispose()
        with self.admin.begin() as conn:conn.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()

    def test_concurrent_signup_creates_one_account_and_grant(self):
        self.app.config["WECHAT_MINI_REGISTRATION_ENABLED"]=True
        barrier=Barrier(2)
        def register():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return mobile_service.login("same-subject")["access_token"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(register) for _ in range(2)]
            self.assertEqual(len({f.result(timeout=30) for f in futures}),2)
        with self.app.app_context(): self.assertEqual(User.query.count(),3)

    def test_concurrent_email_token_has_one_winner(self):
        self.app.config.update(AUTH_MAIL_ADAPTER="capture",APP_BASE_URL="https://mindfulpenpal.com")
        with self.app.app_context():
            email_service.enqueue(1,"verify","mobile0@example.test");db.session.commit()
            email_service.dispatch()
            token=self.app.extensions["auth_mail_capture"][-1][2].split("#")[1].split("\n")[0]
        barrier=Barrier(2)
        def consume():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return email_service.consume(token,"verify")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(consume) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures),[False,True])


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "isolated PostgreSQL URL not configured")
class AuthReleaseMigrationPostgresTests(unittest.TestCase):
    def test_complete_migration_preserves_original_rows_and_foreign_keys(self):
        schema="auth_rehearsal_"+uuid.uuid4().hex
        admin=sa.create_engine(os.environ["AUTH_TEST_DATABASE_URL"])
        with admin.begin() as conn:conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine=sa.create_engine(sa.engine.make_url(os.environ["AUTH_TEST_DATABASE_URL"]).update_query_dict({"options":"-csearch_path="+schema}))
        try:
            with engine.begin() as conn:
                legacy_fixture(conn)
                before=snapshot(conn)
            from scripts.ops.auth_release import migrate
            from pathlib import Path
            self.assertEqual(migrate(Path(__file__).resolve().parents[1], os.environ["AUTH_TEST_DATABASE_URL"], schema=schema), "c8d9e0f1a2b3")
            with engine.begin() as conn:
                after=snapshot(conn)
                # New nullable challenge fields do not alter original values.
                after["challenges"]=[tuple(row)[:len(before["challenges"][0])] for row in after["challenges"]]
                self.assertEqual(after,before)
                self.assertEqual(conn.exec_driver_sql("SELECT is_nullable FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='users' AND column_name='email'").scalar(),"YES")
        finally:
            engine.dispose()
            with admin.begin() as conn:conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()
