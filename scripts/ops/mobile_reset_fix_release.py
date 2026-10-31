"""Pinned, no-migration release fixing the admin reset-code 500.

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

SOURCE = "dc98efcd28c41a929769dbb47db59dba53be1904"
# Base of the release PR: develop's verified code already merged with main's
# 0.11.1 artifacts, so the candidate-to-target diff is only docs and this
# release's ops script instead of unrelated earlier release files.
CANDIDATE = "957d643368f3f2f3211cb35a97d30aa2bf5d1b50"
REVISION = runner.REVISION
RELEASE_FILES = {
    "scripts/ops/mobile_reset_fix_release.py",
    "tests/test_mobile_reset_fix_release.py",
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
        purpose="admin reset-code render fix; main service stopped; no migration",
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
        "mobile-reset-fix-release-"
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
        print("MOBILE_RESET_FIX_DEPLOY_OK")
        print("release_commit=" + sys.argv[1])
        print("migration_revision=" + REVISION + " (unchanged)")
        print("backup_dir=" + str(directory))
        print("service=active; HTTPS=OK; mobile=enabled; admin-reset-code=ok")
        return 0
    except (Exception, SystemExit, KeyboardInterrupt) as exc:
        print(
            "MOBILE_RESET_FIX_DEPLOY_FAILED: "
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