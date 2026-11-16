from pathlib import Path
import unittest
import sqlalchemy as sa
from auth.identity_migration import backfill
from tests.test_auth_identity_phase1 import legacy_fixture, revision, snapshot, NEW

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION = 'd9e0f1a2b3c4_verified_registration.py'


def c8_fixture(conn):
    legacy_fixture(conn)
    revision(conn, NEW)
    backfill(conn)
    revision(conn, 'b7c8d9e0f1a2_unified_auth_sessions.py')
    revision(conn, 'c8d9e0f1a2b3_account_email_registration.py')
    conn.exec_driver_sql("UPDATE users SET email_verified_at='2026-01-02 00:00:00',auth_epoch=3 WHERE id=1")
    conn.exec_driver_sql("UPDATE alembic_version SET version_num='c8d9e0f1a2b3'")
    conn.exec_driver_sql("INSERT INTO account_mail_jobs(id,user_id,purpose,target_email,auth_epoch,status,attempts,next_attempt_at,updated_at) VALUES(1,1,'verify','member1@example.test',0,'pending',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)")


class RegistrationMigrationTests(unittest.TestCase):
    def test_additive_migration_preserves_old_jobs_rows_and_foreign_keys(self):
        engine = sa.create_engine('sqlite://')
        try:
            with engine.begin() as conn:
                c8_fixture(conn)
                before = snapshot(conn)
                job = conn.exec_driver_sql('SELECT * FROM account_mail_jobs').one()
                revision(conn, REGISTRATION)
                self.assertEqual(snapshot(conn), before)
                after = conn.exec_driver_sql('SELECT * FROM account_mail_jobs').one()
                self.assertEqual(tuple(after)[:len(job)], tuple(job))
                self.assertIsNone(after[-1])
                self.assertEqual(conn.exec_driver_sql('PRAGMA foreign_key_check').all(), [])
            with self.assertRaises(sa.exc.IntegrityError), engine.begin() as conn:
                conn.exec_driver_sql("UPDATE account_mail_jobs SET purpose='register' WHERE id=1")
            with self.assertRaises(RuntimeError), engine.begin() as conn:
                revision(conn, REGISTRATION, 'downgrade')
        finally:
            engine.dispose()
