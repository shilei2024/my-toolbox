"""Exercise the new revision against an old-schema disposable SQLite DB."""
import importlib.util
from pathlib import Path
import unittest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class RetentionMigrationTests(unittest.TestCase):
    def test_upgrade_defaults_preserve_history_and_downgrade(self):
        path = Path(__file__).parents[1]/"migrations/versions/e4f5a6b7c8d9_invoice_retention.py"
        spec = importlib.util.spec_from_file_location("retention_revision", path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        engine = sa.create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE reimbursement_invoices (id INTEGER PRIMARY KEY, total_amount NUMERIC(14,2))")
            connection.exec_driver_sql("INSERT INTO reimbursement_invoices VALUES (1, 123.45)")
            revision.op = Operations(MigrationContext.configure(connection))
            revision.upgrade()
            row = connection.execute(sa.text("SELECT inclusion_policy, document_kind, print_selected, amount_confirmed, total_amount FROM reimbursement_invoices")).one()
            self.assertEqual(tuple(row), ("expense", "invoice", 1, 1, 123.45))
            self.assertIn("reimbursement_audits", sa.inspect(connection).get_table_names())
            revision.downgrade()
            self.assertEqual([c["name"] for c in sa.inspect(connection).get_columns("reimbursement_invoices")], ["id", "total_amount"])
            self.assertEqual(connection.exec_driver_sql("SELECT total_amount FROM reimbursement_invoices").scalar(), 123.45)
