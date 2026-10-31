"""Pinned, no-migration release adding reimbursement-period creation from the phone.

Copy this file and mobile_entry_release.py, invoice_release.py, invoice_backup.py
from the same approved main SHA into a private operator directory. Run as root in
/opt/mytoolbox.
"""
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import os
from pathlib import Path
import secrets
import sys

try:
    from . import mobile_entry_release as runner
except ImportError:
    import mobile_entry_release as runner

SOURCE = "29edd8b882138f0b62bde3a27a6d1bcc5f0024a2"
CANDIDATE = "be4e89d044a77fe0ce13e4dc0657762c12e39fdc"
REVISION = runner.REVISION
RELEASE_FILES = {
    "scripts/ops/mobile_period_release.py",
    "tests/test_mobile_period_release.py",
}


def preflight(root, target):
    return runner.preflight(
        root,
        target,
        source=SOURCE,
        candidate=CANDIDATE,
        release_files=RELEASE_FILES,
    )


def execute(root, target, log, **kwargs):
    return runner.execute(
        root,
        target,
        log,
        source=SOURCE,
        candidate=CANDIDATE,
        preflight_check=preflight,
        purpose="mobile period creation final; main service stopped; no migration",
        staging_evidence=(
            "operator MOBILE_PASSWORD_SMOKE_OK, MOBILE_TICKET_AMOUNTS_OK, "
            "MOBILE_ENTRY_SMOKE_OK, MOBILE_FORM_PARITY_OK, MOBILE_API_SMOKE_OK, "
            "MOBILE_HISTORY_OK and MOBILE_STAGING_SMOKE_OK"
        ),
        **kwargs,
    )


def main():
    os.umask(0o077)
    logpath = Path("/root") / (
        "mobile-period-release-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(3)
        + ".log"
    )
    try:
        runner.require(os.name == "posix" and os.geteuid() == 0, "server-root-required")
        runner.require(
            len(sys.argv) == 2 and Path.cwd().resolve() == Path("/opt/mytoolbox"),
            "deployment-path-and-sha-required",
        )
        with (
            runner.common.release_lock(),
            logpath.open("x", encoding="utf-8") as log,
            redirect_stdout(log),
            redirect_stderr(log),
        ):
            directory = execute(Path.cwd().resolve(), sys.argv[1], log)
        print("MOBILE_PERIOD_DEPLOY_OK")
        print("release_commit=" + sys.argv[1])
        print("migration_revision=" + REVISION + " (unchanged)")
        print("backup_dir=" + str(directory))
        print("service=active; HTTPS=OK; mobile=enabled; period-create=live")
        return 0
    except (Exception, SystemExit, KeyboardInterrupt) as exc:
        print(
            "MOBILE_PERIOD_DEPLOY_FAILED: "
            + (
                str(exc)
                if isinstance(exc, runner.common.ReleaseFailure)
                else "preflight-or-runtime-failed"
            )
        )
        if logpath.exists():
            print("private_log=" + str(logpath))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())