"""One-release operator tool: stopped-service backup, pinned e4 upgrade, health.

Copy this file AND invoice_backup.py out of the reviewed release before running
as root from /opt/mytoolbox. No production downgrade or automatic Git reset.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import traceback

SOURCE = "f086b4fe01de583ba7dde71fa41c95767a390280"
BUSINESS_CANDIDATE = "7f751fe2a42e5cc8450be8efa1e6d074d8e33bc1"
OLD_REVISION = "d3e4f5a6b7c8"
NEW_REVISION = "e4f5a6b7c8d9"
CADDY = "services/generation-service/deploy/Caddyfile.production"
NEW_COLUMNS = ["inclusion_policy", "document_kind", "occurrence_month", "settlement_month", "print_selected", "amount_confirmed"]


class ReleaseFailure(Exception):
    pass


@contextmanager
def release_lock(path=Path("/root/mytoolbox-invoice-release.lock")):
    import fcntl
    with path.open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseFailure("another-release-is-running") from None
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def require(condition, label):
    if not condition:
        raise ReleaseFailure(label)


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()


def checkout_release(root, target, log):
    # Git creates files with 0666 and directories with 0777, masked by umask.
    # Public tracked source must be readable by the systemd service user.
    # Only this child gets 022; the parent keeps 077 for secrets and backups.
    subprocess.run(["git", "merge", "--ff-only", target], cwd=root, check=True,
        stdout=log, stderr=log, timeout=60, umask=0o022)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def preflight(root, target):
    require(re.fullmatch(r"[0-9a-f]{40}", target), "invalid-release-sha")
    require(git(root, "branch", "--show-current") == "main", "production-must-be-main")
    require(git(root, "rev-parse", "HEAD") == SOURCE, "unexpected-production-sha")
    require(git(root, "rev-parse", "origin/main") == target, "release-must-match-fetched-main")
    subprocess.run(["git", "merge-base", "--is-ancestor", BUSINESS_CANDIDATE, target], cwd=root, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    changes = git(root, "diff", "--name-only", "HEAD").splitlines()
    require(set(changes) <= {CADDY}, "unexpected-tracked-changes")
    require(not git(root, "diff", "--cached", "--name-only"), "staged-changes-present")
    require(not git(root, "diff", "--name-only", SOURCE, target, "--", "requirements.txt", CADDY), "dependency-or-proxy-change")
    release_only = git(root, "diff", "--name-only", BUSINESS_CANDIDATE, target).splitlines()
    require(all(p.startswith("docs/") or p in {"CHANGELOG.md", "scripts/ops/invoice_release.py", "tests/test_invoice_release.py"}
        for p in release_only), "unverified-business-change")
    require(subprocess.run(["systemctl", "is-active", "--quiet", "mytoolbox"]).returncode == 0, "service-not-active")
    return {name:file_digest(root / name) for name in (".env", CADDY)}


def history(connection):
    from sqlalchemy import text
    fields = ",".join("'" + key + "'" for key in NEW_COLUMNS)
    result = {}
    for table in ("reimbursement_invoices", "reimbursement_attachments"):
        expression = f"to_jsonb(t) - ARRAY[{fields}]" if table.endswith("invoices") else "to_jsonb(t)"
        result[table] = tuple(connection.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(md5(({expression})::text), '' ORDER BY t.id), '')) FROM public.{table} t")).one())
    return result


def migrate(root, url):
    """Normal Alembic upgrade with an explicit DB, without importing app/config."""
    from flask import Flask
    from flask_migrate import Migrate, upgrade
    from sqlalchemy import text
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from extensions import db
    migration_dir = str(root / "migrations")
    config = Config(str(root / "migrations/alembic.ini"))
    config.set_main_option("script_location", migration_dir)
    require(ScriptDirectory.from_config(config).get_heads() == [NEW_REVISION], "unexpected-migration-head")
    app = Flask(__name__)
    app.config.update(SECRET_KEY=secrets.token_urlsafe(32), SQLALCHEMY_DATABASE_URI=url,
        SQLALCHEMY_ENGINE_OPTIONS={"connect_args":{"connect_timeout":10,
            "options":"-c lock_timeout=15000 -c statement_timeout=120000"}})
    db.init_app(app)
    Migrate(app, db, directory=migration_dir)
    with app.app_context():
        with db.engine.connect() as connection:
            require(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() == [OLD_REVISION], "unexpected-database-revision")
            before = history(connection)
        upgrade(directory=migration_dir, revision=NEW_REVISION)
        with db.engine.connect() as connection:
            require(connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() == [NEW_REVISION], "migration-head-not-applied")
            require(history(connection) == before, "historical-data-changed")
            require(connection.execute(text("SELECT count(*) FROM public.reimbursement_invoices WHERE inclusion_policy IS DISTINCT FROM 'expense' OR document_kind IS DISTINCT FROM 'invoice' OR print_selected IS DISTINCT FROM true OR amount_confirmed IS DISTINCT FROM true")).scalar_one() == 0, "legacy-defaults-changed")
        db.session.remove()
        db.engine.dispose()


def healthy():
    import requests
    for attempt in range(5):
        active = subprocess.run(["systemctl", "is-active", "--quiet", "mytoolbox"]).returncode == 0
        try:
            response = requests.get("https://mindfulpenpal.com/healthz", timeout=(3, 8), allow_redirects=False)
            if active and response.status_code == 200 and response.json().get("status") == "ok":
                return True
        except (requests.RequestException, ValueError, AttributeError):
            pass
        if attempt < 4:
            time.sleep(2)
    return False


def execute(root, target, backup_module, log, backup_base=Path("/var/backups/mytoolbox")):
    protected = preflight(root, target)
    # Resolve the same running-service/config precedence BEFORE stopping it.
    url = backup_module.service_database_url(root)
    base = backup_base
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="invoice-final-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-", dir=base))
    stopped = False
    stage = "stop"
    try:
        subprocess.run(["systemctl", "stop", "mytoolbox"], check=True, stdout=log, stderr=log, timeout=60)
        stopped = True
        require(subprocess.run(["systemctl", "is-active", "--quiet", "mytoolbox"]).returncode != 0, "service-still-active")
        stage = "final-backup"
        metadata = backup_module.backup(root, directory, url)
        require(metadata["migration_revisions"] == [OLD_REVISION], "unexpected-backup-revision")
        metadata.update(purpose="final; mytoolbox stopped throughout backup", target_commit=target,
            staging_evidence="operator reported RESTORE_OK, MIGRATION_REHEARSAL_OK, STAGING_SMOKE_OK")
        backup_module.private_manifest(directory, metadata)
        (directory / "COMPLETE").write_text("Final stopped-service backup complete; prior restore and migration verified.\n", encoding="utf-8")
        require(git(root, "rev-parse", "HEAD") == SOURCE, "source-changed-during-backup")
        stage = "checkout"
        checkout_release(root, target, log)
        require(git(root, "rev-parse", "HEAD") == target, "release-sha-not-applied")
        require(all(file_digest(root / name) == digest for name, digest in protected.items()), "local-configuration-changed")
        stage = "migration"
        migrate(root, url)
        stage = "start"
        subprocess.run(["systemctl", "start", "mytoolbox"], check=True, stdout=log, stderr=log, timeout=60)
        stage = "https-health"
        require(healthy(), "health-not-ready")
        stopped = False
        return directory
    except (Exception, SystemExit, KeyboardInterrupt):
        traceback.print_exc(file=log)  # Private 0600 log only; never paste it into chat.
        # Only restore the OLD service automatically when code is still the OLD
        # checkout. Once new code/migration is involved, keep writes stopped.
        if stopped:
            safe_old = False
            try:
                safe_old = (git(root, "rev-parse", "HEAD") == SOURCE
                    and set(git(root, "diff", "--name-only", "HEAD").splitlines()) <= {CADDY}
                    and not git(root, "diff", "--cached", "--name-only")
                    and all(file_digest(root / name) == digest for name, digest in protected.items()))
            except Exception:
                pass
            try:
                subprocess.run(["systemctl", "start" if safe_old else "stop", "mytoolbox"], stdout=log, stderr=log, timeout=60)
            except (Exception, SystemExit, KeyboardInterrupt):
                traceback.print_exc(file=log)
        raise ReleaseFailure(f"stage={stage}; backup_dir={directory}") from None


def main():
    os.umask(0o077)
    log_path = Path("/root") / ("mytoolbox-invoice-release-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(3) + ".log")
    try:
        require(os.name == "posix" and os.geteuid() == 0, "run-as-server-root")
        require(len(sys.argv) == 2, "release-sha-required")
        root = Path.cwd().resolve()
        require(root == Path("/opt/mytoolbox"), "unexpected-deployment-directory")
        helper = Path(__file__).with_name("invoice_backup.py")
        spec = importlib.util.spec_from_file_location("invoice_release_backup", helper)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with release_lock(), log_path.open("x", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
            directory = execute(root, sys.argv[1], module, log)
        print("DEPLOY_OK")
        print("release_commit=" + sys.argv[1])
        print("migration_revision=" + NEW_REVISION)
        print("backup_dir=" + str(directory))
        print("service=active; HTTPS_health=OK")
        return 0
    except (Exception, SystemExit, KeyboardInterrupt) as exc:
        message = str(exc) if isinstance(exc, ReleaseFailure) else "preflight-or-runtime-check-failed"
        print("DEPLOY_FAILED: " + message + "; stop and report this line only")
        if log_path.exists():
            print("private_log=" + str(log_path))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
