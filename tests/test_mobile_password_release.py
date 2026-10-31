import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import tempfile
import unittest
from scripts.ops import mobile_password_release as release


class PasswordReleaseTests(unittest.TestCase):
    def scenario(self, failure=None):
        events = []
        head = [release.SOURCE]
        target = "a" * 40

        def command(args, **kwargs):
            events.append(args[1])
            return SimpleNamespace(returncode=3 if args[1] == "is-active" else 0)

        def backup(*args):
            events.append("backup")
            if failure == "backup":
                raise RuntimeError("private-detail")
            return {"migration_revisions": [release.REVISION], "source_commit": release.SOURCE}

        def checkout(*args):
            events.append("checkout")
            head[0] = target

        with tempfile.TemporaryDirectory() as folder, \
             patch.object(release, "preflight", return_value={".env": "same"}), \
             patch.object(release.runner.backup, "service_database_url", return_value="private"), \
             patch.object(release.runner.backup, "backup", side_effect=backup), \
             patch.object(release.runner.backup, "private_manifest") as manifest, \
             patch.object(release.runner, "database_state", side_effect=[{"rows": 1}, {"rows": 1}]), \
             patch.object(release.runner.common, "checkout_release", side_effect=checkout), \
             patch.object(release.runner.common, "file_digest", return_value="same"), \
             patch.object(release.runner.common, "git",
                          side_effect=lambda root, *args: head[0] if args == ("rev-parse", "HEAD") else ""), \
             patch.object(release.runner.subprocess, "run", side_effect=command), \
             patch.object(release.runner, "runtime_readable",
                          side_effect=lambda *args: events.append("readable")), \
             patch.object(release.runner, "healthy_enabled", return_value=failure != "health"):
            if failure:
                with self.assertRaises(release.runner.common.ReleaseFailure) as caught:
                    release.execute(Path(folder), target, io.StringIO(), base=Path(folder) / "backups")
                self.assertNotIn("private-detail", str(caught.exception))
            else:
                release.execute(Path(folder), target, io.StringIO(), base=Path(folder) / "backups")
                metadata = manifest.call_args.args[1]
                self.assertEqual(metadata["source_commit"], release.SOURCE)
                self.assertEqual(metadata["business_candidate"], release.CANDIDATE)
                self.assertIn("MOBILE_PASSWORD_SMOKE_OK", metadata["staging_evidence"])
        return events

    def test_new_source_uses_stopped_backup_and_readability_before_start(self):
        events = self.scenario()
        self.assertLess(events.index("stop"), events.index("backup"))
        self.assertLess(events.index("backup"), events.index("checkout"))
        self.assertLess(events.index("checkout"), events.index("readable"))
        self.assertLess(events.index("readable"), events.index("start"))

    def test_backup_failure_at_new_source_restarts_unchanged_service(self):
        events = self.scenario("backup")
        self.assertNotIn("checkout", events)
        self.assertEqual(events[-1], "start")

    def test_failed_new_health_keeps_changed_code_stopped(self):
        events = self.scenario("health")
        self.assertEqual(events[-1], "stop")

    def test_new_preflight_has_its_own_fixed_origin_and_artifact_allowlist(self):
        with patch.object(release.runner, "preflight", return_value={}) as check:
            release.preflight(Path("synthetic"), "a" * 40)
        self.assertEqual(check.call_args.kwargs["source"], release.SOURCE)
        self.assertEqual(check.call_args.kwargs["candidate"], release.CANDIDATE)
        self.assertEqual(check.call_args.kwargs["release_files"], release.RELEASE_FILES)
