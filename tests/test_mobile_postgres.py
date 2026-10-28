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
