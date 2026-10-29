import importlib.util
from pathlib import Path
import unittest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class MobileMigrationTests(unittest.TestCase):
    def test_legacy_originals_survive_upgrade_and_recovery(self):
        path=Path(__file__).parents[1]/'migrations/versions/f5a6b7c8d9e0_mobile_invoice_upload.py'
        spec=importlib.util.spec_from_file_location('mobile_revision',path)
        revision=importlib.util.module_from_spec(spec);spec.loader.exec_module(revision)
        engine=sa.create_engine('sqlite:///:memory:')
        with engine.begin() as conn:
            conn.exec_driver_sql('CREATE TABLE users(id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql('CREATE TABLE reimbursement_invoices(id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql('CREATE TABLE reimbursement_attachments(id INTEGER PRIMARY KEY, owner_type VARCHAR(8), owner_id VARCHAR(64), stored_name VARCHAR(255) UNIQUE, content BLOB)')
            conn.exec_driver_sql("INSERT INTO reimbursement_attachments VALUES(1,'user','1','first.pdf',X'0102FF'),(2,'user','1','legacy-duplicate.pdf',X'0102FF')")
            revision.op=Operations(MigrationContext.configure(conn))
            revision.upgrade()
            rows=conn.exec_driver_sql('SELECT content,content_sha256 FROM reimbursement_attachments ORDER BY id').all()
            self.assertEqual(rows,[(b'\x01\x02\xff',None),(b'\x01\x02\xff',None)])
            self.assertIn('account_external_identities',sa.inspect(conn).get_table_names())
            self.assertIn('reimbursement_upload_receipts',sa.inspect(conn).get_table_names())
            revision.downgrade()
            self.assertNotIn('content_sha256',[c['name'] for c in sa.inspect(conn).get_columns('reimbursement_attachments')])
            self.assertEqual(conn.exec_driver_sql('SELECT content FROM reimbursement_attachments ORDER BY id').all(),[(b'\x01\x02\xff',),(b'\x01\x02\xff',)])
