import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import subprocess
import shutil
import unittest
from unittest.mock import patch

from scripts.ops import mobile_entry_release as release


class MobileEntryReleaseTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("git"), "Git is required for code rollback verification"
    )
    def test_detached_old_code_rollback_preserves_local_config_and_database_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def git(*args):
                return (
                    subprocess.check_output(
                        ["git", *args], cwd=root, stderr=subprocess.DEVNULL
                    )
                    .decode()
                    .strip()
                )

            git("init", "--initial-branch=main")
            git("config", "user.name", "Synthetic release test")
            git("config", "user.email", "release@example.invalid")
            (root / "app.py").write_text("old", encoding="utf-8")
            (root / "Caddyfile").write_text("tracked", encoding="utf-8")
            git("add", "app.py", "Caddyfile")
            git("commit", "-m", "old")
            source = git("rev-parse", "HEAD")
            (root / "app.py").write_text("new", encoding="utf-8")
            git("add", "app.py")
            git("commit", "-m", "new")
            (root / "Caddyfile").write_text("operator change", encoding="utf-8")
            (root / ".env").write_text("synthetic config", encoding="utf-8")
            (root / "database.dump").write_bytes(b"synthetic backup")
            git("switch", "--detach", source)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "old")
            self.assertEqual(
                (root / "Caddyfile").read_text(encoding="utf-8"), "operator change"
            )
            self.assertEqual(
                (root / ".env").read_text(encoding="utf-8"), "synthetic config"
            )
            self.assertEqual((root / "database.dump").read_bytes(), b"synthetic backup")
            self.assertEqual(git("rev-parse", "HEAD"), source)

    def scenario(self, failure=None):
        events, head = [], [release.SOURCE]
        target = "a" * 40

        def run(command, **kwargs):
            events.append(command[1])
            return SimpleNamespace(returncode=3 if command[1] == "is-active" else 0)

        def backup(*args):
            events.append("backup")
            if failure == "backup":
                raise RuntimeError("private-connection-details")
            return {
                "migration_revisions": [release.REVISION],
                "source_commit": release.SOURCE,
            }

        def checkout(*args):
            events.append("checkout")
            head[0] = target

        def readable(*args):
            events.append("readable")
            if failure == "readable":
                raise RuntimeError("private-permission-details")

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(release, "preflight", return_value={".env": "unchanged"}),
            patch.object(
                release.backup, "service_database_url", return_value="private"
            ),
            patch.object(release.backup, "backup", side_effect=backup),
            patch.object(release.backup, "private_manifest"),
            patch.object(
                release,
                "database_state",
                side_effect=[{"rows": 1}, {"rows": 2 if failure == "history" else 1}],
            ),
            patch.object(release.common, "checkout_release", side_effect=checkout),
            patch.object(release.common, "file_digest", return_value="unchanged"),
            patch.object(
                release.common,
                "git",
                side_effect=lambda root, *args: head[0]
                if args == ("rev-parse", "HEAD")
                else "",
            ),
            patch.object(release.subprocess, "run", side_effect=run),
            patch.object(release, "runtime_readable", side_effect=readable),
            patch.object(release, "healthy_enabled", return_value=failure != "health"),
        ):
            if failure:
                with self.assertRaises(release.common.ReleaseFailure) as caught:
                    release.execute(
                        Path(directory),
                        target,
                        io.StringIO(),
                        base=Path(directory) / "backups",
                    )
                self.assertNotIn("private-", str(caught.exception))
            else:
                release.execute(
                    Path(directory),
                    target,
                    io.StringIO(),
                    base=Path(directory) / "backups",
                )
        return events

    def test_success_backup_precedes_checkout_and_readability_precedes_start(self):
        events = self.scenario()
        self.assertLess(events.index("stop"), events.index("backup"))
        self.assertLess(events.index("backup"), events.index("checkout"))
        self.assertLess(events.index("checkout"), events.index("readable"))
        self.assertLess(events.index("readable"), events.index("start"))

    def test_backup_failure_restarts_only_unchanged_old_code(self):
        events = self.scenario("backup")
        self.assertNotIn("checkout", events)
        self.assertEqual(events[-1], "start")

    def test_new_unreadable_code_keeps_service_stopped(self):
        events = self.scenario("readable")
        self.assertNotIn("start", events)
        self.assertEqual(events[-1], "stop")

    def test_history_change_keeps_service_stopped(self):
        events = self.scenario("history")
        self.assertNotIn("start", events)
        self.assertEqual(events[-1], "stop")

    def test_health_failure_stops_new_service(self):
        self.assertEqual(self.scenario("health")[-1], "stop")

    def test_enabled_health_checks_new_route_auth_and_rejects_cookie_or_disabled(self):
        def response(status=200, body=None, headers=None):
            return SimpleNamespace(
                status_code=status,
                json=lambda: body or {"status": "ok"},
                headers=headers or {},
            )

        for status, headers, expected in (
            (401, {"Cache-Control": "private, no-store"}, True),
            (404, {"Cache-Control": "no-store"}, False),
            (401, {"Set-Cookie": "unsafe", "Cache-Control": "no-store"}, False),
        ):
            with (
                patch(
                    "requests.get",
                    side_effect=[
                        response(),
                        response(),
                        response(status, {"error": "请先登录"}, headers),
                        response(status, {"error": "请先登录"}, headers),
                    ],
                ) as get,
                patch.object(
                    release.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
            ):
                self.assertEqual(
                    release.healthy_enabled(attempts=1, new_routes=True), expected
                )
                self.assertTrue(
                    get.call_args_list[-1].args[0].endswith("/api/mobile/dashboard/0")
                )

    def test_preflight_refuses_schema_or_unreviewed_business_changes(self):
        root = Path("synthetic-root")
        target = "a" * 40
        for failure in ("schema", "business", "old-sha"):

            def git(_root, *args):
                if args == ("branch", "--show-current"):
                    return "main"
                if args == ("rev-parse", "HEAD"):
                    return "b" * 40 if failure == "old-sha" else release.SOURCE
                if args == ("rev-parse", "origin/main"):
                    return target
                if args[:4] == ("diff", "--name-only", release.SOURCE, target):
                    return "migrations/new.py" if failure == "schema" else ""
                if args[:4] == ("diff", "--name-only", release.CANDIDATE, target):
                    return "app.py" if failure == "business" else ""
                return ""

            with (
                patch.object(release.common, "git", side_effect=git),
                patch.object(
                    release.subprocess,
                    "run",
                    return_value=SimpleNamespace(returncode=0),
                ),
                patch.object(release, "healthy_enabled") as healthy,
            ):
                with self.assertRaises(release.common.ReleaseFailure):
                    release.preflight(root, target)
                healthy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
