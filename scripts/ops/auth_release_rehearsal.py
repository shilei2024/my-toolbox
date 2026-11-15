"""Run the complete release migration on an existing, isolated restored database."""
import argparse
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sqlalchemy.engine import make_url
from scripts.ops.auth_migration import verified_backup
from scripts.ops.auth_release import migrate


def run(args):
    if not args.ack_isolated_database or not args.writers_stopped:
        raise ValueError("isolated_stopped_database_required")
    url = os.environ.get("AUTH_MIGRATION_DATABASE_URL", "")
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql" or not re.fullmatch(
        r"auth_rehearsal_[a-z0-9_]{1,40}", parsed.database or ""
    ):
        raise ValueError("dedicated_rehearsal_database_required")
    verified_backup(args.backup_manifest)
    return migrate(ROOT, url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ack-isolated-database", action="store_true")
    parser.add_argument("--writers-stopped", action="store_true")
    parser.add_argument("--backup-manifest", required=True)
    try:
        revision = run(parser.parse_args())
        print("AUTH_REHEARSAL_OK revision=" + revision)
        return 0
    except Exception:
        print("AUTH_REHEARSAL_FAILED; check isolated database, backup and revision privately")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
