"""Create a private rehearsal backup without starting Flask or changing the DB.

Run as root from the deployed checkout on Linux. Copy this script out of Git
before running; no checkout, schema migration, restart, restore or deletion.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


DATABASE_KEYS = ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL")


def private_connection_environment(url: str, directory: Path) -> dict:
    from psycopg2.extensions import parse_dsn

    parameters = parse_dsn(url)
    # libpq service files support every connection parameter. Keep credentials
    # out of both command arguments and environment variables.
    if any("\n" in value or "\r" in value or value != value.strip() for value in parameters.values()):
        raise ValueError("service_parameter_requires_manual_configuration")
    service = directory / "database.service.conf"
    service.write_text("[invoice_backup]\n" + "".join(f"{key}={value}\n" for key, value in parameters.items()), encoding="utf-8")
    os.chmod(service, 0o600)
    child_env = {key: os.environ[key] for key in ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "HOME") if key in os.environ}
    child_env.update(PGSERVICEFILE=str(service), PGSERVICE="invoice_backup", PGCONNECT_TIMEOUT="10")
    return child_env


def service_database_url(root: Path) -> str:
    pid = subprocess.check_output(
        ["systemctl", "show", "mytoolbox", "-p", "MainPID", "--value"], text=True
    ).strip()
    if not pid.isdigit() or int(pid) <= 0:
        raise RuntimeError("service_not_running")
    service_env = {}
    for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        if b"=" in entry:
            key, value = entry.split(b"=", 1)
            service_env[key.decode()] = value.decode()
    for key in DATABASE_KEYS:
        os.environ.pop(key, None)
        if key in service_env:
            os.environ[key] = service_env[key]
    sys.path.insert(0, str(root))
    # config loads .env for missing values; it does not initialize Flask.
    from config import _auto_db_url

    url = _auto_db_url()
    if not url.startswith("postgresql://"):
        raise RuntimeError("postgresql_required")
    return url


def private_manifest(directory: Path, metadata: dict) -> dict:
    """Manifest contains checksums, never connection configuration or contents."""
    metadata = dict(metadata)
    metadata["files"] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.name not in {"manifest.json", "COMPLETE"}:
            os.chmod(path, 0o600)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            metadata["files"][path.name] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(manifest, 0o600)
    return metadata


def backup(root: Path, directory: Path, url: str) -> dict:
    from sqlalchemy import create_engine, text

    engine = create_engine(url, connect_args={"connect_timeout": 10})
    try:
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            version = connection.execute(text("SHOW server_version")).scalar_one()
            size = connection.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
            revisions = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    finally:
        engine.dispose()
    major = version.split(".", 1)[0]
    for program in ("pg_dump", "pg_restore"):
        client = subprocess.check_output([program, "--version"], text=True)
        if f") {major}." not in client:
            raise RuntimeError("postgresql_client_version_mismatch")
    originals = root / "uploads" / "reimbursement"
    original_size = sum(p.stat().st_size for p in originals.rglob("*") if p.is_file() and not p.is_symlink()) if originals.exists() else 0
    if shutil.disk_usage(directory).free < max(512 * 1024 * 1024, 3 * (size + original_size)):
        raise RuntimeError("insufficient_backup_space")

    metadata = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "server_version": version,
        "migration_revisions": revisions,
        "purpose": "rehearsal; take a fresh final backup before production release",
        "restore_verified": False,
    }
    child_env = private_connection_environment(url, directory)
    with (directory / "backup.log").open("wb") as log:
        subprocess.run(["pg_dump", "--format=custom", "--lock-wait-timeout=15s", "--file", str(directory / "database.dump")],
                       env=child_env, stdout=log, stderr=log, check=True, timeout=600)
        subprocess.run(["pg_restore", "--list", str(directory / "database.dump")],
                       stdout=subprocess.DEVNULL, stderr=log, check=True)
        if originals.exists():
            subprocess.run(["tar", "-czf", str(directory / "invoice-files.tar.gz"), "-C", str(root),
                            "uploads/reimbursement"], stdout=log, stderr=log, check=True)
        for source, target in ((root / ".env", "app.env"),
                               (root / "services/generation-service/deploy/Caddyfile.production", "Caddyfile.production")):
            if source.exists():
                shutil.copyfile(source, directory / target)
        with (directory / "server-changes.patch").open("wb") as output:
            subprocess.run(["git", "diff", "--binary", "--", "services/generation-service/deploy/Caddyfile.production"],
                           cwd=root, stdout=output, stderr=log, check=True)
        with (directory / "git-status.txt").open("wb") as output:
            subprocess.run(["git", "status", "--short", "--branch"], cwd=root, stdout=output, stderr=log, check=True)
        with (directory / "mytoolbox.service.txt").open("wb") as output:
            subprocess.run(["systemctl", "cat", "mytoolbox"], stdout=output, stderr=log, check=True)
    result = private_manifest(directory, metadata)
    (directory / "COMPLETE").write_text("Backup created; restore not yet verified.\n", encoding="utf-8")
    os.chmod(directory / "COMPLETE", 0o600)
    return result


def main() -> int:
    os.umask(0o077)
    directory = None
    stage = "check"
    try:
        if not hasattr(os, "geteuid") or os.geteuid() != 0:
            raise RuntimeError("run_as_root_on_server")
        root = Path.cwd().resolve()
        if not (root / "config.py").is_file() or not (root / "app.py").is_file():
            raise RuntimeError("run_from_deployed_checkout")
        url = service_database_url(root)
        base = Path("/var/backups/mytoolbox")
        base.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(prefix="invoice-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-", dir=base))
        stage = "backup"
        result = backup(root, directory, url)
        print("BACKUP_OK")
        print("backup_dir=" + str(directory))
        print("source_commit=" + result["source_commit"])
        print("database_dump_bytes=" + str(result["files"]["database.dump"]["bytes"]))
        print("archive_catalog=OK; restore_verified=NO")
        return 0
    except Exception:
        print("BACKUP_FAILED stage=" + stage + "; connection details hidden")
        if directory is not None:
            print("partial_backup_dir=" + str(directory))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
