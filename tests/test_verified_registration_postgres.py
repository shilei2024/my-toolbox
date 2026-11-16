from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
import uuid
from unittest.mock import patch
import sqlalchemy as sa
from extensions import db
from models import User
from auth import registration_service, email_service
from auth.account_models import AccountRegistration, AuthMailJob
from tests import test_verified_registration as cases
from tests.test_registration_migration import c8_fixture, ROOT
from scripts.ops import auth_registration_release as release


class IsolatedSchema:
    def create_schema(self):
        self.schema = 'auth_rehearsal_'+uuid.uuid4().hex
        url = sa.engine.make_url(os.environ['AUTH_TEST_DATABASE_URL'])
        if url.get_backend_name() != 'postgresql': self.skipTest('PostgreSQL required')
        self.admin = sa.create_engine(url)
        with self.admin.begin() as conn: conn.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.database_uri = url.update_query_dict({'options':'-csearch_path='+self.schema})
        self.addCleanup(self.cleanup_schema)

    def cleanup_schema(self):
        if hasattr(self, 'app'):
            with self.app.app_context(): db.session.remove(); db.engine.dispose()
        if hasattr(self, 'engine'): self.engine.dispose()
        with self.admin.begin() as conn: conn.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()


@unittest.skipUnless(os.environ.get('AUTH_TEST_DATABASE_URL'), 'isolated PostgreSQL URL not configured')
class VerifiedRegistrationPostgresTests(IsolatedSchema, cases.VerifiedRegistrationTests):
    def setUp(self):
        self.create_schema()
        super().setUp()

    def test_concurrent_activation_creates_one_user_and_one_welcome(self):
        self.register()
        raw = self.registration_token()
        barrier = Barrier(2)
        def activate():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return registration_service.complete(raw, 'owner-password123') is not None
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(activate) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures), [False,True])
        with self.app.app_context():
            self.assertEqual(User.query.count(), 2)
            self.assertEqual(AuthMailJob.query.filter_by(purpose='welcome').count(), 1)

    def test_concurrent_requests_queue_one_job_without_creating_user(self):
        barrier = Barrier(2)
        def request():
            with self.app.app_context():
                barrier.wait(timeout=10)
                registration_service.request_registration('new@example.com',password='owner-password123')
                db.session.commit()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(request) for _ in range(2)]
            for f in futures: f.result(timeout=30)
        with self.app.app_context():
            self.assertEqual(AccountRegistration.query.count(), 1)
            self.assertEqual(AuthMailJob.query.filter_by(purpose='register').count(), 1)
            self.assertEqual(User.query.count(), 1)

    def test_operator_harness_preserves_original_pending_mail_and_records(self):
        from scripts.ops.verified_registration_smoke import exercise, history
        with self.app.app_context():
            db.session.add(AuthMailJob(user_id=1,purpose='verify',target_email='person@example.com',auth_epoch=0))
            db.session.commit()
            before = history(db.session.connection(),self.schema)
        exercise(self.app)
        with self.app.app_context():
            after = history(db.session.connection(),self.schema)
            self.assertTrue(all(not (rows-after[table]) for table,rows in before.items()))
            self.assertEqual(AuthMailJob.query.filter_by(user_id=1).one().status, 'pending')


@unittest.skipUnless(os.environ.get('AUTH_TEST_DATABASE_URL'), 'isolated PostgreSQL URL not configured')
class RegistrationMigrationPostgresTests(IsolatedSchema, unittest.TestCase):
    def test_password_first_production_migration_preserves_legacy_request(self):
        self.create_schema()
        self.engine = sa.create_engine(self.database_uri)
        url = os.environ['AUTH_TEST_DATABASE_URL']
        with self.engine.begin() as conn: c8_fixture(conn)
        release.migrate(ROOT,url,schema=self.schema)
        with self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO account_registrations(id,email,token_hash,expires_at,last_requested_at,created_at) VALUES(1,'pending@example.test','"+'b'*64+"','2099-01-01',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")
            tables = [t for t in sa.inspect(conn).get_table_names(schema=self.schema) if t != 'alembic_version']
            before = release.fingerprint(conn,self.schema,tables)
        with patch.object(release,'fingerprint',side_effect=[before,{}]):
            with self.assertRaises(release.common.ReleaseFailure):
                release.migrate(ROOT,url,schema=self.schema,password_first=True)
        with self.engine.begin() as conn:
            self.assertNotIn('password_hash',[c['name'] for c in sa.inspect(conn).get_columns('account_registrations')])
        self.assertEqual(release.migrate(ROOT,url,schema=self.schema,password_first=True),release.PASSWORD_HEAD)
        with self.engine.begin() as conn:
            self.assertEqual(release.fingerprint(conn,self.schema,tables),before)
            self.assertIsNone(conn.exec_driver_sql('SELECT password_hash FROM account_registrations WHERE id=1').scalar())

    def test_production_migrator_rolls_back_on_mismatch_then_preserves_all_history(self):
        self.create_schema()
        self.engine = sa.create_engine(self.database_uri)
        with self.engine.begin() as conn:
            c8_fixture(conn)
            tables = [t for t in sa.inspect(conn).get_table_names(schema=self.schema) if t != 'alembic_version']
            before = release.fingerprint(conn, self.schema, tables)
        url = os.environ['AUTH_TEST_DATABASE_URL']
        with patch.object(release, 'fingerprint', side_effect=[before,{}]):
            with self.assertRaises(release.common.ReleaseFailure): release.migrate(ROOT,url,schema=self.schema)
        with self.engine.begin() as conn:
            self.assertEqual(conn.exec_driver_sql('SELECT version_num FROM alembic_version').scalar(), release.PARENT)
            self.assertNotIn('account_registrations', sa.inspect(conn).get_table_names(schema=self.schema))
        self.assertEqual(release.migrate(ROOT,url,schema=self.schema), release.HEAD)
        with self.engine.begin() as conn:
            self.assertEqual(release.fingerprint(conn,self.schema,tables), before)
