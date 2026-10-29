"""Opt-in PostgreSQL tests use a fresh private schema, never public tables."""
import os
import re
import secrets
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from tests import test_mobile_invoice_upload as fixtures
from extensions import db
from models import ReimbursementAttachment, ReimbursementInvoice, UsageLog
from auth.mobile_models import MobileSession
from tools.reimbursement.mobile_models import UploadReceipt


@unittest.skipUnless(os.environ.get('MOBILE_TEST_DATABASE_URL'), 'isolated PostgreSQL URL not configured')
class MobilePostgresTests(fixtures.MobileInvoiceTests):
    def test_operator_business_smoke_against_postgres(self):
        from scripts.ops.mobile_invoice_staging_smoke import exercise
        exercise(self.app)

    def setUp(self):
        url = make_url(os.environ['MOBILE_TEST_DATABASE_URL'])
        if url.host not in {'127.0.0.1', 'localhost'} or not re.fullmatch(r'(?:mytoolbox_mobile_test_[a-z0-9_]+|mindfulpenpal_ci)', url.database or ''):
            raise RuntimeError('Only an explicitly named local test database is allowed')
        schema = 'mobile_test_' + secrets.token_hex(12)
        admin = sa.create_engine(url)
        with admin.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        def cleanup():
            if hasattr(self, 'app'):
                with self.app.app_context():
                    db.session.remove()
                    db.engine.dispose()
            with admin.begin() as conn:
                conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()
        self.addCleanup(cleanup)
        self.database_uri = url.update_query_dict({'options':f'-csearch_path={schema}'})
        super().setUp()

    def test_parallel_retry_has_one_invoice_original_receipt_and_charge(self):
        headers = self.login()
        barrier = Barrier(2)
        def send():
            barrier.wait(timeout=10)
            with self.app.test_client(use_cookies=False) as client:
                import io
                from tests.test_mobile_invoice_upload import PNG
                response = client.post('/api/mobile/invoices', headers=headers, data={
                    'file':(io.BytesIO(PNG),'parallel.png'), 'period_id':str(self.period),
                    'office_id':str(self.office), 'document_kind':'fuel', 'occurrence_month':'2026-06',
                    'idempotency_key':'parallel-upload-key-00001'})
                return response.status_code, response.json['invoice']['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: send(), range(2)))
        self.assertEqual(sorted(status for status, _ in outcomes), [200,201])
        self.assertEqual(len({key for _, key in outcomes}), 1)
        with self.app.app_context():
            for model in (ReimbursementAttachment, ReimbursementInvoice, UploadReceipt, UsageLog):
                self.assertEqual(model.query.count(), 1, model.__name__)

    def test_parallel_binding_consumes_challenge_only_once(self):
        code = self.challenge()
        barrier = Barrier(2)
        def bind(index):
            barrier.wait(timeout=10)
            with self.app.test_client(use_cookies=False) as client:
                return client.post('/api/mobile/session', json={'code':f'subject-{index}', 'binding_code':code}).status_code
        with patch('auth.mobile_service.exchange_code', side_effect=lambda code:code):
            with ThreadPoolExecutor(max_workers=2) as pool:
                statuses = sorted(pool.map(bind, range(2)))
        self.assertEqual(statuses, [200,400])
        with self.app.app_context():
            self.assertEqual(MobileSession.query.count(), 1)

    def test_postgres_migration_preserves_duplicate_legacy_originals(self):
        import importlib.util
        from pathlib import Path
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        path = Path(__file__).parents[1] / 'migrations/versions/f5a6b7c8d9e0_mobile_invoice_upload.py'
        spec = importlib.util.spec_from_file_location('pg_mobile_revision', path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        with self.app.app_context():
            with db.engine.begin() as conn:
                revision.op = Operations(MigrationContext.configure(conn))
                revision.downgrade()
                conn.execute(sa.text("INSERT INTO reimbursement_attachments (owner_type,owner_id,stored_name,original_name,mime_type,file_size,content,created_at) VALUES ('user','1','legacy-a.pdf','a.pdf','application/pdf',3,:content,CURRENT_TIMESTAMP),('user','1','legacy-b.pdf','b.pdf','application/pdf',3,:content,CURRENT_TIMESTAMP)"), {'content':b'\x01\x02\xff'})
                revision.upgrade()
                rows = conn.execute(sa.text('SELECT content,content_sha256 FROM reimbursement_attachments ORDER BY id')).all()
                self.assertEqual([(bytes(content), digest) for content, digest in rows], [(b'\x01\x02\xff',None),(b'\x01\x02\xff',None)])

    def test_rehearsal_sql_executes_on_isolated_database_and_rejects_wrong_database(self):
        import importlib.util
        import shutil
        import subprocess
        import tempfile
        from pathlib import Path
        from flask import Flask
        from alembic.operations import Operations
        from alembic.migration import MigrationContext
        from models import User, ReimbursementPeriod
        from scripts.ops.invoice_backup import private_connection_environment
        psql=os.environ.get('MOBILE_TEST_PSQL') or shutil.which('psql')
        self.assertTrue(psql,'psql is required for the configured PostgreSQL test')
        root=Path(__file__).parents[1]
        sql=(root/'scripts/ops/mobile_invoice_rehearsal.sql').read_bytes()
        base=make_url(os.environ['MOBILE_TEST_DATABASE_URL'])
        name='mytoolbox_invoice_verify_20261028_111850'
        target=base.set(database=name)
        admin=sa.create_engine(base,isolation_level='AUTOCOMMIT')
        created=False
        target_engine=None
        try:
            with admin.connect() as conn:
                conn.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created=True
            app=Flask(__name__)
            app.config['SQLALCHEMY_DATABASE_URI']=target
            db.init_app(app)
            with app.app_context():
                target_engine=db.engine
                db.create_all()
                user=User(email='migration@example.invalid',password_hash='synthetic-only')
                db.session.add(user);db.session.flush()
                period=ReimbursementPeriod(owner_type='user',owner_id=str(user.id),name='test',start_year=2026,start_month=6,end_year=2026,end_month=7)
                db.session.add(period);db.session.flush()
                db.session.add(ReimbursementInvoice(owner_type='user',owner_id=str(user.id),period_id=period.id,
                    inclusion_policy='retain',document_kind='fuel',total_amount=88.12,occurrence_month='2026-08',print_selected=False,amount_confirmed=False))
                for filename in ('legacy-a.pdf','legacy-b.pdf'):
                    db.session.add(ReimbursementAttachment(owner_type='user',owner_id=str(user.id),stored_name=filename,
                        original_name=filename,mime_type='application/pdf',file_size=3,content=b'\x01\x02\xff'))
                db.session.commit()
                path=root/'migrations/versions/f5a6b7c8d9e0_mobile_invoice_upload.py'
                spec=importlib.util.spec_from_file_location('rehearsal_pg_revision',path)
                revision=importlib.util.module_from_spec(spec);spec.loader.exec_module(revision)
                with db.engine.begin() as conn:
                    revision.op=Operations(MigrationContext.configure(conn));revision.downgrade()
                    conn.exec_driver_sql('CREATE TABLE public.alembic_version (version_num varchar(32) PRIMARY KEY)')
                    conn.exec_driver_sql("INSERT INTO public.alembic_version VALUES ('e4f5a6b7c8d9')")
                db.session.remove();db.engine.dispose()
            with tempfile.TemporaryDirectory() as folder:
                environment=private_connection_environment(target.set(drivername='postgresql').render_as_string(hide_password=False),Path(folder))
                if os.name == 'nt':
                    environment['SYSTEMROOT']=os.environ['SYSTEMROOT']
                result=subprocess.run([psql,'-X','--set=ON_ERROR_STOP=1'],input=sql,env=environment,capture_output=True,timeout=90)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertIn(b'MOBILE_MIGRATION_REHEARSAL_OK',result.stdout)
                # The unchanged script must reject the original test DB before
                # even reading schema revision or writing public objects.
                environment=private_connection_environment(base.set(drivername='postgresql').render_as_string(hide_password=False),Path(folder))
                if os.name == 'nt':
                    environment['SYSTEMROOT']=os.environ['SYSTEMROOT']
                wrong=subprocess.run([psql,'-X','--set=ON_ERROR_STOP=1'],input=sql,env=environment,capture_output=True,timeout=30)
                self.assertNotEqual(wrong.returncode,0)
                self.assertIn(b'Refusing to run outside',wrong.stderr)
            with target_engine.connect() as conn:
                self.assertEqual(conn.exec_driver_sql('SELECT version_num FROM public.alembic_version').scalar(),'f5a6b7c8d9e0')
                self.assertEqual(conn.exec_driver_sql('SELECT inclusion_policy,occurrence_month,total_amount,print_selected FROM public.reimbursement_invoices').one(),('retain','2026-08',__import__('decimal').Decimal('88.12'),False))
        finally:
            if target_engine is not None:
                target_engine.dispose()
            if created:
                with admin.connect() as conn:
                    conn.exec_driver_sql(f'DROP DATABASE "{name}"')
            admin.dispose()
