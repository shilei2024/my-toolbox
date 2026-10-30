"""Pinned, no-migration release from the observed 0.10.0 main backend.

Copy this file, invoice_release.py and invoice_backup.py from the same approved
main SHA into a private operator directory. Run as root in /opt/mytoolbox.
"""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
import traceback

try:
    from . import invoice_release as common
    from . import invoice_backup as backup
except ImportError:
    import invoice_release as common
    import invoice_backup as backup

SOURCE = "8cd9d31d3ee3ac9429c4ffe0da2a646042098cb1"
CANDIDATE = "8e8ca491f29135c3f90178f66008cb56d0f0fdeb"
REVISION = "f5a6b7c8d9e0"
require = common.require


def preflight(root, target):
    require(re.fullmatch(r"[0-9a-f]{40}", target), "invalid-target")
    require(common.git(root, "branch", "--show-current") == "main", "main-required")
    require(
        common.git(root, "rev-parse", "HEAD") == SOURCE, "unexpected-production-sha"
    )
    require(
        common.git(root, "rev-parse", "origin/main") == target,
        "target-not-fetched-main",
    )
    for ancestor in (SOURCE, CANDIDATE):
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, target],
            cwd=root,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    require(
        set(common.git(root, "diff", "--name-only", "HEAD").splitlines())
        <= {common.CADDY},
        "unexpected-local-changes",
    )
    require(not common.git(root, "diff", "--cached", "--name-only"), "staged-changes")
    require(
        not common.git(
            root,
            "diff",
            "--name-only",
            SOURCE,
            target,
            "--",
            "requirements.txt",
            "migrations/",
            common.CADDY,
        ),
        "schema-dependency-or-proxy-change",
    )
    allowed = {
        "CHANGELOG.md",
        "scripts/ops/mobile_entry_release.py",
        "tests/test_mobile_entry_release.py",
        "tests/test_mobile_postgres.py",
    }
    require(
        all(
            p.startswith("docs/") or p in allowed
            for p in common.git(
                root, "diff", "--name-only", CANDIDATE, target
            ).splitlines()
        ),
        "unverified-business-change",
    )
    require(
        subprocess.run(["systemctl", "is-active", "--quiet", "mytoolbox"]).returncode
        == 0,
        "service-not-active",
    )
    require(
        healthy_enabled(attempts=1), "existing-health-or-enabled-mobile-check-failed"
    )
    protected = {
        name: common.file_digest(root / name) for name in (".env", common.CADDY)
    }
    require(all(protected.values()), "configuration-file-missing")
    return protected


def database_state(url):
    """Read-only fingerprint; never imports the application or runs migrations."""
    from sqlalchemy import create_engine, text

    engine = create_engine(
        url,
        connect_args={"connect_timeout": 10, "options": "-c statement_timeout=30000"},
    )
    try:
        with engine.begin() as connection:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            require(
                connection.execute(
                    text("SELECT version_num FROM public.alembic_version")
                )
                .scalars()
                .all()
                == [REVISION],
                "unexpected-db-revision",
            )
            return {
                table: tuple(
                    connection.execute(
                        text(
                            f"SELECT count(*), md5(COALESCE(string_agg(md5(to_jsonb(t)::text), '' ORDER BY t.id), '')) FROM public.{table} t"
                        )
                    ).one()
                )
                for table in (
                    "users",
                    "reimbursement_invoices",
                    "reimbursement_attachments",
                    "reimbursement_aux_details",
                )
            }
    finally:
        engine.dispose()


def runtime_readable(root, log):
    user = (
        subprocess.check_output(
            ["systemctl", "show", "mytoolbox", "-p", "User", "--value"], text=True
        ).strip()
        or "root"
    )
    require(re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_-]*", user), "unexpected-service-user")
    for name in (
        "app.py",
        "models.py",
        "auth/mobile_routes.py",
        "auth/mobile_service.py",
        "auth/mobile_models.py",
        "tools/reimbursement/__init__.py",
        "tools/reimbursement/manager.py",
        "tools/reimbursement/models.py",
        "tools/reimbursement/retention.py",
        "tools/reimbursement/attachments.py",
        "tools/reimbursement/mobile_models.py",
        "tools/reimbursement/mobile_recognition.py",
        "tools/reimbursement/mobile_dispatch.py",
    ):
        require(
            subprocess.run(
                ["sudo", "-u", user, "--", "test", "-r", str(root / name)],
                stdout=log,
                stderr=log,
            ).returncode
            == 0,
            "service-cannot-read-code",
        )


def healthy_enabled(attempts=20, *, new_routes=False):
    import requests

    for attempt in range(attempts):
        try:
            active = (
                subprocess.run(
                    ["systemctl", "is-active", "--quiet", "mytoolbox"]
                ).returncode
                == 0
            )
            local = requests.get(
                "http://127.0.0.1:8000/healthz", timeout=(2, 3), allow_redirects=False
            )
            public = requests.get(
                "https://mindfulpenpal.com/healthz",
                timeout=(3, 8),
                allow_redirects=False,
            )
            paths = ["/api/mobile/bootstrap"] + (
                ["/api/mobile/dashboard/0"] if new_routes else []
            )
            mobile = [
                requests.get(
                    "https://mindfulpenpal.com" + path,
                    timeout=(3, 8),
                    allow_redirects=False,
                )
                for path in paths
            ]
            if (
                active
                and local.status_code == 200
                and public.status_code == 200
                and public.json().get("status") == "ok"
                and all(
                    r.status_code == 401
                    and r.json().get("error")
                    and "Set-Cookie" not in r.headers
                    and "no-store" in r.headers.get("Cache-Control", "")
                    for r in mobile
                )
            ):
                return True
        except (requests.RequestException, ValueError, AttributeError):
            pass
        if attempt < attempts - 1:
            time.sleep(2)
    return False


def execute(root, target, log, base=Path("/var/backups/mytoolbox")):
    protected = preflight(root, target)
    url = backup.service_database_url(root)
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="mobile-entry-final-", dir=base))
    stage, stopped = "stop", False
    try:
        subprocess.run(
            ["systemctl", "stop", "mytoolbox"],
            check=True,
            stdout=log,
            stderr=log,
            timeout=60,
        )
        stopped = True
        require(
            subprocess.run(
                ["systemctl", "is-active", "--quiet", "mytoolbox"]
            ).returncode
            != 0,
            "service-still-active",
        )
        stage = "backup"
        before = database_state(url)
        metadata = backup.backup(root, directory, url)
        require(
            metadata["migration_revisions"] == [REVISION]
            and metadata["source_commit"] == SOURCE,
            "unexpected-backup-source",
        )
        metadata.update(
            purpose="mobile entry final; main service stopped; no migration",
            target_commit=target,
            business_candidate=CANDIDATE,
            staging_evidence="operator MOBILE_ENTRY_SMOKE_OK, MOBILE_FORM_PARITY_OK, MOBILE_API_SMOKE_OK, MOBILE_HISTORY_OK and MOBILE_STAGING_SMOKE_OK",
        )
        backup.private_manifest(directory, metadata)
        require(
            common.git(root, "rev-parse", "HEAD") == SOURCE,
            "source-changed-during-backup",
        )
        stage = "checkout"
        common.checkout_release(root, target, log)
        require(common.git(root, "rev-parse", "HEAD") == target, "target-not-applied")
        require(
            all(
                common.file_digest(root / name) == digest
                for name, digest in protected.items()
            ),
            "configuration-changed",
        )
        stage = "code-readability"
        runtime_readable(root, log)
        stage = "history"
        require(database_state(url) == before, "historical-data-changed")
        stage = "start"
        subprocess.run(
            ["systemctl", "start", "mytoolbox"],
            check=True,
            stdout=log,
            stderr=log,
            timeout=60,
        )
        stage = "health-enabled"
        require(
            healthy_enabled(new_routes=True), "health-or-enabled-mobile-check-failed"
        )
        return directory
    except (Exception, SystemExit, KeyboardInterrupt):
        traceback.print_exc(file=log)
        if stopped:
            safe_old = False
            try:
                safe_old = (
                    common.git(root, "rev-parse", "HEAD") == SOURCE
                    and set(
                        common.git(root, "diff", "--name-only", "HEAD").splitlines()
                    )
                    <= {common.CADDY}
                    and not common.git(root, "diff", "--cached", "--name-only")
                    and all(
                        common.file_digest(root / name) == digest
                        for name, digest in protected.items()
                    )
                )
            except Exception:
                pass
            try:
                subprocess.run(
                    ["systemctl", "start" if safe_old else "stop", "mytoolbox"],
                    stdout=log,
                    stderr=log,
                    timeout=60,
                )
            except (Exception, SystemExit, KeyboardInterrupt):
                traceback.print_exc(file=log)
        raise common.ReleaseFailure(f"stage={stage}; backup_dir={directory}") from None


def main():
    os.umask(0o077)
    logpath = Path("/root") / (
        "mobile-entry-release-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(3)
        + ".log"
    )
    try:
        require(os.name == "posix" and os.geteuid() == 0, "server-root-required")
        require(
            len(sys.argv) == 2 and Path.cwd().resolve() == Path("/opt/mytoolbox"),
            "deployment-path-and-sha-required",
        )
        with (
            common.release_lock(),
            logpath.open("x", encoding="utf-8") as log,
            redirect_stdout(log),
            redirect_stderr(log),
        ):
            directory = execute(Path.cwd().resolve(), sys.argv[1], log)
        print("MOBILE_ENTRY_DEPLOY_OK")
        print("release_commit=" + sys.argv[1])
        print("migration_revision=" + REVISION + " (unchanged)")
        print("backup_dir=" + str(directory))
        print("service=active; HTTPS=OK; mobile=enabled; new_routes=authenticated")
        return 0
    except (Exception, SystemExit, KeyboardInterrupt) as exc:
        print(
            "MOBILE_ENTRY_DEPLOY_FAILED: "
            + (
                str(exc)
                if isinstance(exc, common.ReleaseFailure)
                else "preflight-or-runtime-failed"
            )
        )
        if logpath.exists():
            print("private_log=" + str(logpath))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
