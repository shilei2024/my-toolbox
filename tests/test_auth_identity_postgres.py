"""Opt-in PG rehearsal; every test uses a fresh auth_rehearsal_* schema."""
from concurrent.futures import ThreadPoolExecutor
import os
from threading import Barrier
import unittest
import uuid

import sqlalchemy as sa

from auth.identity_migration import backfill, preflight
from tests.test_auth_identity_phase1 import legacy_fixture, revision, snapshot, NEW


@unittest.skipUnless(os.environ.get("AUTH_TEST_DATABASE_URL"), "isolated PostgreSQL URL not configured")
class AuthIdentityPostgresTests(unittest.TestCase):
    def setUp(self):
        url = os.environ["AUTH_TEST_DATABASE_URL"]
        if sa.engine.make_url(url).get_backend_name() != "postgresql":
            self.skipTest("PostgreSQL required")
        self.schema = "auth_rehearsal_" + uuid.uuid4().hex
        self.admin = sa.create_engine(url, connect_args={"connect_timeout": 10})
        with self.admin.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{self.schema}"')
        self.engine = sa.create_engine(url, connect_args={"connect_timeout": 10, "options": "-csearch_path=" + self.schema})
        self.addCleanup(self.cleanup_schema)
        with self.engine.begin() as conn:
            legacy_fixture(conn)
            self.before = snapshot(conn)
            revision(conn, NEW)

    def cleanup_schema(self):
        self.engine.dispose()
        with self.admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{self.schema}" CASCADE')
        self.admin.dispose()

    def test_concurrent_backfills_serialize_without_duplicate_accounts_or_credentials(self):
        barrier = Barrier(2)
        def worker():
            with self.engine.begin() as conn:
                barrier.wait(timeout=10)
                return backfill(conn)["inserted"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures), [0, 2])
        with self.engine.begin() as conn:
            self.assertEqual(snapshot(conn), self.before)
            self.assertTrue(preflight(conn)["ready"])
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM account_legacy_mappings").scalar(), 2)

    def test_rollback_preserves_legacy_rows_and_allows_retry(self):
        with self.assertRaisesRegex(RuntimeError, "fixture_failure"), self.engine.begin() as conn:
            backfill(conn)
            raise RuntimeError("fixture_failure")
        with self.engine.begin() as conn:
            self.assertEqual(snapshot(conn), self.before)
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM auth_migration_runs").scalar(), 0)
            self.assertEqual(backfill(conn)["inserted"], 2)

    def test_schema_recovery_before_backfill_and_constraints_after_backfill(self):
        with self.engine.begin() as conn:
            revision(conn, NEW, "downgrade")
            self.assertEqual(snapshot(conn), self.before)
            revision(conn, NEW)
            backfill(conn)
        with self.assertRaises(sa.exc.IntegrityError), self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO account_external_identities(provider,client_id,subject,user_id,active,created_at) VALUES('web_password','web','invalid',NULL,true,now())")


if __name__ == "__main__":
    unittest.main()
