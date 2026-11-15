"""Isolated authentication rehearsal. Never loads Flask/config/.env or accepts a URL argument."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from auth.identity_migration import MigrationConflict, backfill, preflight  # noqa: E402

REVISION = "a6b7c8d9e0f1"
PARENT = "f5a6b7c8d9e0"
SESSION_REVISION = "b7c8d9e0f1a2"


def verified_backup(path):
    """Require a locally verifiable backup; this does not claim a restore was tested."""
    manifest_path = Path(path).resolve(strict=True)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("kind") != "auth-rehearsal-backup-v1":
        raise ValueError("invalid_backup_manifest")
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("backup_files_required")
    for name, expected in files.items():
        if not isinstance(name, str) or Path(name).name != name or name in {".", ".."}:
            raise ValueError("invalid_backup_file")
        candidate = (manifest_path.parent / name).resolve(strict=True)
        if candidate.parent != manifest_path.parent or not candidate.is_file():
            raise ValueError("invalid_backup_file")
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("invalid_backup_digest")
        digest = hashlib.sha256()
        with candidate.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected:
            raise ValueError("backup_checksum_mismatch")


def isolated_engine(url, schema):
    parsed = sa.engine.make_url(url)
    if parsed.get_backend_name() == "sqlite":
        path = Path(parsed.database or "").resolve()
        if not path.is_file() or not re.fullmatch(r"auth_rehearsal_[A-Za-z0-9_-]+\.db", path.name):
            raise ValueError("existing_isolated_sqlite_file_required")
        engine = sa.create_engine(url)
        @sa.event.listens_for(engine, "connect")
        def enable_fk(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
        return engine
    if parsed.get_backend_name() == "postgresql":
        if not schema or not re.fullmatch(r"auth_rehearsal_[a-z0-9_]{1,40}", schema):
            raise ValueError("isolated_schema_required")
        return sa.create_engine(url, connect_args={"connect_timeout": 10})
    raise ValueError("unsupported_rehearsal_database")


def run(args):
    url = os.environ.get("AUTH_MIGRATION_DATABASE_URL")
    if not url:
        raise ValueError("AUTH_MIGRATION_DATABASE_URL_required")
    if args.action != "check":
        if not args.ack_isolated_database or not args.writers_stopped or not args.backup_manifest:
            raise ValueError("isolated_ack_stopped_writers_and_backup_required")
        verified_backup(args.backup_manifest)
    engine = isolated_engine(url, args.schema)
    try:
        with engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                if args.action == "check":
                    conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                exists = conn.execute(sa.text("SELECT 1 FROM pg_namespace WHERE nspname=:name"), {"name": args.schema}).scalar()
                if not exists:
                    raise ValueError("isolated_schema_not_found")
                conn.exec_driver_sql(f'SET LOCAL search_path TO "{args.schema}"')
                # No public fallback: never read/write production tables by accident.
            elif args.action == "check":
                conn.exec_driver_sql("PRAGMA query_only=ON")
            else:
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            versions = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalars().all()
            if versions not in ([PARENT], [REVISION], [SESSION_REVISION]):
                raise ValueError("unexpected_schema_revision")
            if args.action == "upgrade-auth":
                if versions == [SESSION_REVISION]:
                    return {"action": args.action, "status": "already_applied", "revision": SESSION_REVISION}
                if versions != [REVISION]:
                    raise ValueError("phase1_schema_upgrade_required")
                before = preflight(conn)
                if not before["ready"]:
                    raise MigrationConflict(before)
                if before["identities_to_create"] or before["mappings_to_create"]:
                    raise ValueError("phase1_backfill_required")
                path = ROOT / "migrations/versions/b7c8d9e0f1a2_unified_auth_sessions.py"
                spec = importlib.util.spec_from_file_location("auth_phase2_revision", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.op = Operations(MigrationContext.configure(conn))
                module.upgrade()
                conn.execute(sa.text("UPDATE alembic_version SET version_num=:new WHERE version_num=:old"),
                    {"new": SESSION_REVISION, "old": REVISION})
                return {"action": args.action, "status": "applied", "revision": SESSION_REVISION}
            if args.action == "upgrade":
                if versions == [SESSION_REVISION]:
                    raise ValueError("phase2_already_installed")
                if versions == [REVISION]:
                    return {"action": "upgrade", "status": "already_applied", "revision": REVISION}
                before = preflight(conn)
                if not before["ready"]:
                    raise MigrationConflict(before)
                path = ROOT / "migrations/versions/a6b7c8d9e0f1_unified_identity_compat.py"
                spec = importlib.util.spec_from_file_location("auth_phase1_revision", path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.op = Operations(MigrationContext.configure(conn))
                module.upgrade()
                conn.execute(sa.text("UPDATE alembic_version SET version_num=:new WHERE version_num=:old"),
                             {"new": REVISION, "old": PARENT})
                return {"action": "upgrade", "status": "applied", "revision": REVISION}
            if args.action == "apply" and versions != [REVISION]:
                raise ValueError("phase1_schema_upgrade_required")
            return backfill(conn) if args.action == "apply" else preflight(conn)
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "upgrade", "apply", "upgrade-auth"), nargs="?", default="check")
    parser.add_argument("--schema", help="Existing auth_rehearsal_* schema, PostgreSQL only")
    parser.add_argument("--ack-isolated-database", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--backup-manifest")
    args = parser.parse_args()
    try:
        report = run(args)
        print(json.dumps(report, sort_keys=True))
        return 0 if report.get("ready", True) else 2
    except MigrationConflict as exc:
        print(json.dumps(exc.report, sort_keys=True))
        return 2
    except Exception:
        # Drivers/URLs/SQL parameters may contain credentials; never print exception text.
        print(json.dumps({"ready": False, "error": "auth_rehearsal_failed", "hint": "Check isolated database, revision, backup and arguments; no exception details are logged."}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
