"""Exercise the new revision against an old-schema disposable SQLite DB."""
import importlib.util
import hashlib
import io
from pathlib import Path
import unittest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


class RetentionMigrationTests(unittest.TestCase):
    def test_rehearsal_sql_uses_actual_postgres_migration_and_exact_database_guard(self):
        root = Path(__file__).parents[1]
        path = root/"migrations/versions/e4f5a6b7c8d9_invoice_retention.py"
        source = (root/"scripts/ops/invoice_retention_rehearsal.sql").read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location("retention_revision_sql", path)
        revision = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(revision)
        self.assertIn(hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest(), source)
        for action, count in (("upgrade", 2), ("downgrade", 1)):
            output = io.StringIO()
            revision.op = Operations(MigrationContext.configure(dialect_name="postgresql", opts={"as_sql":True, "output_buffer":output}))
            getattr(revision, action)()
            self.assertEqual(source.count(output.getvalue().strip()), count)
        self.assertLess(source.index("current_database() <> 'mytoolbox_invoice_verify_20261028_111850'"), source.index("CREATE TEMP TABLE"))
        self.assertIn("\\set ON_ERROR_STOP on", source)
        self.assertIn("Historical attachments changed during rehearsal", source)
        self.assertNotIn("DROP DATABASE", source)

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
