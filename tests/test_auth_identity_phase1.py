"""Phase 1 rehearsals use synthetic records and isolated databases only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from werkzeug.security import generate_password_hash

from auth.identity_migration import MigrationConflict, backfill, legacy_account_id, preflight
from scripts.ops import auth_migration as cli

ROOT = Path(__file__).resolve().parents[1]
NEW = "a6b7c8d9e0f1_unified_identity_compat.py"
OLD = "f5a6b7c8d9e0_mobile_invoice_upload.py"
HASH = generate_password_hash("fixture-password-123", method="pbkdf2:sha256:1000")


def revision(conn, filename, method="upgrade"):
    spec = importlib.util.spec_from_file_location("fixture_revision", ROOT / "migrations/versions" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.op = Operations(MigrationContext.configure(conn))
    getattr(module, method)()


def legacy_fixture(conn):
    metadata = sa.MetaData()
    users = sa.Table("users", metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean, nullable=False),
        sa.Column("is_active_user", sa.Boolean, nullable=False),
        sa.Column("nickname", sa.String(80)), sa.Column("plan", sa.String(32)),
        sa.Column("custom_limits", sa.Text), sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("last_login_at", sa.DateTime))
    sa.Table("alembic_version", metadata, sa.Column("version_num", sa.String(32), primary_key=True))
    sa.Table("reimbursement_invoices", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_type", sa.String(8)), sa.Column("owner_id", sa.String(64)))
    sa.Table("reimbursement_attachments", metadata, sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("owner_type", sa.String(8)), sa.Column("owner_id", sa.String(64)),
        sa.Column("stored_name", sa.String(255), unique=True), sa.Column("content", sa.LargeBinary))
    sa.Table("user_tool_grants", metadata, sa.Column("user_id", sa.Integer, primary_key=True),
        sa.Column("tool_id", sa.String(64), primary_key=True))
    metadata.create_all(conn)
    now = datetime(2026, 1, 1)
    conn.execute(users.insert(), [dict(id=i, email=f"member{i}@example.test", password_hash=HASH,
        is_admin=i == 1, is_active_user=True, nickname=None, plan="free", custom_limits='{"reimbursement":20}',
        created_at=now, last_login_at=now) for i in (1, 2)])
    conn.execute(metadata.tables["reimbursement_invoices"].insert().values(id=1, owner_type="user", owner_id="1"))
    conn.execute(metadata.tables["reimbursement_attachments"].insert().values(id=1, owner_type="user", owner_id="1", stored_name="fixture.pdf", content=b"\x01\x02\xff"))
    conn.execute(metadata.tables["user_tool_grants"].insert().values(user_id=2, tool_id="reimbursement"))
    revision(conn, OLD)
    tables = sa.MetaData()
    identities = sa.Table("account_external_identities", tables, autoload_with=conn)
    sessions = sa.Table("account_mobile_sessions", tables, autoload_with=conn)
    challenges = sa.Table("account_binding_challenges", tables, autoload_with=conn)
    conn.execute(identities.insert().values(id=1, provider="wechat_miniprogram", client_id="wx0123456789abcdef",
        subject="fixture-openid", user_id=1, active=True, created_at=now))
    conn.execute(identities.insert().values(id=2, provider="website_password", client_id="wx0123456789abcdef",
        subject=hashlib.sha256(f"1:{HASH}".encode()).hexdigest(), user_id=1, active=True, created_at=now))
    # Let PostgreSQL generate all new IDs beyond the explicitly seeded identity.
    if conn.dialect.name == "postgresql":
        conn.exec_driver_sql("SELECT setval(pg_get_serial_sequence('account_external_identities','id'),2,true)")
    conn.execute(sessions.insert().values(id=1, identity_id=1, user_id=1, token_hash=hashlib.sha256(b"A"*43).hexdigest(),
        expires_at=datetime(2099, 1, 1), created_at=now))
    conn.execute(sessions.insert().values(id=2, identity_id=2, user_id=1, token_hash=hashlib.sha256(b"B"*43).hexdigest(),
        expires_at=datetime(2099, 1, 1), created_at=now))
    conn.execute(challenges.insert().values(id=1, user_id=1, provider="wechat_miniprogram", client_id="wx0123456789abcdef",
        token_hash="c"*64, expires_at=datetime(2099, 1, 1)))
    conn.execute(metadata.tables["alembic_version"].insert().values(version_num=cli.PARENT))


def snapshot(conn):
    return {name: conn.exec_driver_sql(query).all() for name, query in {
        "users": "SELECT id,email,password_hash,is_admin,is_active_user,nickname,plan,custom_limits,created_at,last_login_at FROM users ORDER BY id",
        "identity": "SELECT id,provider,client_id,subject,user_id,active,created_at FROM account_external_identities WHERE provider != 'web_password' ORDER BY id",
        "sessions": "SELECT id,identity_id,user_id,token_hash,expires_at,revoked_at,created_at FROM account_mobile_sessions ORDER BY id",
        "challenges": "SELECT * FROM account_binding_challenges ORDER BY id",
        "invoices": "SELECT * FROM reimbursement_invoices ORDER BY id",
        "originals": "SELECT * FROM reimbursement_attachments ORDER BY id",
        "grants": "SELECT * FROM user_tool_grants ORDER BY user_id",
    }.items()}


class IdentityPhase1Tests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite:///:memory:")
        with self.engine.begin() as conn:
            legacy_fixture(conn)
            self.before = snapshot(conn)
            revision(conn, NEW)

    def tearDown(self):
        self.engine.dispose()

    def test_read_only_preflight_repeat_and_exact_historical_preservation(self):
        with self.engine.begin() as conn:
            self.assertTrue(preflight(conn)["ready"])
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM auth_migration_runs").scalar(), 0)
            first = backfill(conn)
            second = backfill(conn)
            self.assertEqual((first["inserted"], second["inserted"], second["skipped"]), (2, 0, 2))
            self.assertEqual(snapshot(conn), self.before)
            self.assertEqual(conn.exec_driver_sql("SELECT source_user_id, account_id FROM account_legacy_mappings ORDER BY account_id").all(), [(1, 1), (2, 2)])
            self.assertEqual(conn.exec_driver_sql("SELECT password_hash FROM account_external_identities WHERE provider='web_password'").scalars().all(), [HASH, HASH])
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM users WHERE email_verified_at IS NOT NULL").scalar(), 0)
            report = json.dumps(first)
            for sensitive in (HASH, "member1", "fixture-openid", "A"*43):
                self.assertNotIn(sensitive, report)

    def test_normalized_email_collision_stops_before_writes(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE users SET email=' MEMBER1@EXAMPLE.TEST ' WHERE id=2")
            with self.assertRaises(MigrationConflict) as caught:
                backfill(conn)
            self.assertIn("normalized_email_collision", caught.exception.report["errors"])
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM auth_migration_runs").scalar(), 0)

    def test_old_anonymized_disabled_user_is_preserved_without_login_identity(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE users SET password_hash='!',is_active_user=0 WHERE id=2")
            report = backfill(conn)
            self.assertEqual(report["excluded_disabled"], 1)
            self.assertEqual(conn.exec_driver_sql("SELECT identity_id FROM account_legacy_mappings WHERE account_id=2").scalar(), None)
            self.assertEqual(conn.exec_driver_sql("SELECT password_hash FROM users WHERE id=2").scalar(), "!")

    def test_unknown_hash_and_incomplete_email_block_without_overwriting_user(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE users SET password_hash='unknown',email='' WHERE id=2")
            report = preflight(conn)
            self.assertFalse(report["ready"])
            self.assertIn("password_format_requires_manual_review", report["errors"])
            self.assertIn("email_requires_manual_review", report["errors"])
            with self.assertRaises(MigrationConflict):
                backfill(conn)
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM users").scalar(), 2)

    def test_credential_drift_never_silently_overwrites_shadow(self):
        with self.engine.begin() as conn:
            backfill(conn)
            conn.exec_driver_sql("UPDATE users SET password_hash=:hash WHERE id=1", {"hash": HASH.replace("1000", "2000")})
            with self.assertRaises(MigrationConflict):
                backfill(conn)
            self.assertEqual(conn.exec_driver_sql("SELECT password_hash FROM account_external_identities WHERE provider='web_password' AND user_id=1").scalar(), HASH)

    def test_failed_backfill_transaction_rolls_back_every_insert(self):
        def fail_midway(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO account_legacy_mappings"):
                raise RuntimeError("injected_failure")
        sa.event.listen(self.engine, "before_cursor_execute", fail_midway)
        try:
            with self.assertRaises(RuntimeError), self.engine.begin() as conn:
                backfill(conn)
        finally:
            sa.event.remove(self.engine, "before_cursor_execute", fail_midway)
        with self.engine.begin() as conn:
            self.assertEqual(snapshot(conn), self.before)
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM auth_migration_runs").scalar(), 0)
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM account_external_identities WHERE provider='web_password'").scalar(), 0)
            self.assertEqual(backfill(conn)["inserted"], 2)

    def test_empty_upgrade_can_downgrade_but_backfilled_data_cannot_be_deleted(self):
        with self.engine.begin() as conn:
            revision(conn, NEW, "downgrade")
            self.assertEqual(snapshot(conn), self.before)
            revision(conn, NEW)
            backfill(conn)
            with self.assertRaisesRegex(RuntimeError, "has_data"):
                revision(conn, NEW, "downgrade")
            self.assertEqual(conn.exec_driver_sql("SELECT count(*) FROM account_legacy_mappings").scalar(), 2)

    def test_duplicate_web_identity_for_same_account_is_rejected(self):
        with self.engine.begin() as conn:
            backfill(conn)
        with self.assertRaises(sa.exc.IntegrityError), self.engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO account_external_identities(provider,client_id,subject,user_id,active,created_at,identifier,password_hash) VALUES('web_password','web','other',1,1,CURRENT_TIMESTAMP,'other@example.test','x')")

    def test_session_owner_mismatch_blocks_backfill(self):
        with self.engine.begin() as conn:
            conn.exec_driver_sql("UPDATE account_mobile_sessions SET user_id=2 WHERE id=1")
            self.assertIn("session_owner_mismatch", preflight(conn)["errors"])

    def test_numeric_compatibility_parser_rejects_identity_and_ambiguous_values(self):
        self.assertEqual(legacy_account_id("123"), 123)
        for invalid in ("openid", True, "01", "1:0", 0, -1, " 1", "2147483648"):
            with self.assertRaises(ValueError):
                legacy_account_id(invalid)

    def test_real_legacy_mobile_token_authenticates_after_backfill(self):
        from flask import Flask
        from extensions import db, login_manager
        from models import User
        from auth.routes import auth_bp
        from auth.mobile_service import authenticate
        with tempfile.TemporaryDirectory() as directory:
            url = "sqlite:///" + str(Path(directory) / "auth_rehearsal_compat.db")
            engine = sa.create_engine(url)
            with engine.begin() as conn:
                legacy_fixture(conn)
                revision(conn, NEW)
                backfill(conn)
            engine.dispose()
            app = Flask(__name__)
            app.config.update(SQLALCHEMY_DATABASE_URI=url, WECHAT_MINI_ENABLED=True,
                WECHAT_MINI_APP_ID="wx0123456789abcdef", WECHAT_MINI_APP_SECRET="fixture-secret-not-real",
                SECRET_KEY="fixture-cookie-secret", GALLERY_INTROSPECTION_SECRET="fixture-bridge-secret-01234567890123456789")
            db.init_app(app)
            login_manager.init_app(app)
            login_manager.user_loader(lambda uid: db.session.get(User, int(uid)))
            app.register_blueprint(auth_bp)
            client = app.test_client()
            # Legacy Flask cookies carry numeric IDs; no new account format required.
            old_cookie = app.session_interface.get_signing_serializer(app).dumps({"_user_id": "1", "_fresh": True})
            client.set_cookie("session", old_cookie)
            response = client.get("/internal/gallery/session", headers={"X-Mavis-Introspection-Secret": app.config["GALLERY_INTROSPECTION_SECRET"]})
            self.assertEqual(response.json["userId"], 1)
            with app.app_context():
                user, session = authenticate("A"*43)
                self.assertEqual(user.account_id, 1)
                self.assertEqual(session.id, 1)
                password_user, password_session = authenticate("B"*43)
                self.assertEqual((password_user.account_id, password_session.id), (1, 2))
                self.assertTrue(user.check_password("fixture-password-123"))
                db.session.remove()
                db.engine.dispose()

    def test_cli_upgrade_repeat_preflight_backup_and_apply_on_isolated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth_rehearsal_cli.db"
            engine = sa.create_engine("sqlite:///" + str(path))
            with engine.begin() as conn:
                legacy_fixture(conn)
            engine.dispose()
            backup = Path(directory) / "backup.db"
            backup.write_bytes(path.read_bytes())
            manifest = Path(directory) / "backup.json"
            manifest.write_text(json.dumps({"kind": "auth-rehearsal-backup-v1", "files": {
                backup.name: hashlib.sha256(backup.read_bytes()).hexdigest()}}))
            args = SimpleNamespace(action="upgrade", schema=None, ack_isolated_database=True,
                writers_stopped=True, backup_manifest=str(manifest))
            with patch.dict(os.environ, {"AUTH_MIGRATION_DATABASE_URL": "sqlite:///" + str(path)}):
                args.action = "check"
                self.assertFalse(cli.run(args)["phase1_schema_present"])
                args.action = "upgrade"
                self.assertEqual(cli.run(args)["status"], "applied")
                self.assertEqual(cli.run(args)["status"], "already_applied")
                args.action = "check"
                self.assertTrue(cli.run(args)["ready"])
                args.action = "apply"
                self.assertEqual(cli.run(args)["inserted"], 2)
                args.action = "upgrade-auth"
                self.assertEqual(cli.run(args)["revision"], cli.SESSION_REVISION)
                self.assertEqual(cli.run(args)["status"], "already_applied")
                args.action = "check"
                self.assertTrue(cli.run(args)["ready"])
                args.action = "upgrade-auth"
                args.writers_stopped = False
                with self.assertRaises(ValueError):
                    cli.run(args)
            restored = Path(directory) / "auth_rehearsal_restored.db"
            restored.write_bytes(backup.read_bytes())
            restored_engine = sa.create_engine("sqlite:///" + str(restored))
            with restored_engine.connect() as conn:
                self.assertEqual(snapshot(conn), self.before)
                self.assertEqual(conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar(), cli.PARENT)
                self.assertNotIn("account_legacy_mappings", sa.inspect(conn).get_table_names())
            restored_engine.dispose()
            backup.write_bytes(b"corrupt")
            with self.assertRaises(ValueError):
                cli.verified_backup(manifest)
        with self.assertRaises(ValueError):
            cli.isolated_engine("postgresql://example/test", "public")


if __name__ == "__main__":
    unittest.main()
