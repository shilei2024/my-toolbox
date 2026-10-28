"""Release safety: no writes before guards; backup before Git/schema changes."""
import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from scripts.ops import invoice_release as release

TARGET = "a" * 40


class InvoiceReleaseTests(unittest.TestCase):
    def test_second_release_is_rejected_before_entering_operation(self):
        from unittest.mock import Mock
        fcntl = SimpleNamespace(LOCK_EX=2,LOCK_NB=4,LOCK_UN=8,flock=Mock(side_effect=BlockingIOError()))
        with tempfile.TemporaryDirectory() as directory, patch.dict('sys.modules',{'fcntl':fcntl}):
            with self.assertRaisesRegex(release.ReleaseFailure,'another-release-is-running'):
                with release.release_lock(Path(directory)/'lock'):
                    self.fail('must not enter release operations')
            self.assertEqual(fcntl.flock.call_count,1)

    def test_preflight_rejects_unreviewed_business_or_local_configuration(self):
        for changed, added in ((".env", ""), ("", "auth/mobile_routes.py"), ("app.py", "")):
            with self.subTest(changed=changed, added=added):
                def git(_root, *args):
                    return {("branch","--show-current"):"main", ("rev-parse","HEAD"):release.SOURCE,
                        ("rev-parse","origin/main"):TARGET, ("diff","--name-only","HEAD"):changed,
                        ("diff","--name-only",release.BUSINESS_CANDIDATE,TARGET):added}.get(args, "")
                with patch.object(release,"git",side_effect=git), patch.object(release.subprocess,"run",return_value=SimpleNamespace(returncode=0)) as run:
                    with self.assertRaises(release.ReleaseFailure):
                        release.preflight(Path("."),TARGET)
                    self.assertFalse(any(call.args[0][:2] == ["systemctl","stop"] for call in run.call_args_list))

    def scenario(self, failure=None):
        events = []
        head = [release.SOURCE]
        def run(command, **_kwargs):
            events.append(tuple(command))
            if command[:2] == ["git","merge"]:
                if failure == 'partial-checkout':
                    raise OSError('interrupted checkout')
                head[0] = TARGET
            return SimpleNamespace(returncode=3 if command[:2] == ["systemctl","is-active"] else 0)
        def backup(_root, directory, _url):
            events.append(("backup",))
            self.assertIn(("systemctl","stop","mytoolbox"),events)
            if failure == "backup":
                raise OSError("private database details must never reach the caller")
            (directory / "database.dump").write_bytes(b"archive")
            return {"migration_revisions":[release.OLD_REVISION]}
        def migrate(*_args):
            events.append(("migrate",))
            self.assertLess(events.index(("backup",)), next(i for i,e in enumerate(events) if e[:2] == ("git","merge")))
            if failure == "migration":
                raise RuntimeError("private migration exception")
            if failure == "migration-exit":
                raise SystemExit(1)
        module = SimpleNamespace(service_database_url=lambda _root:"postgresql://private",
            backup=backup,private_manifest=lambda *_args:None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(_root,*args):
                if args == ('rev-parse','HEAD'): return head[0]
                if failure == 'partial-checkout' and args == ('diff','--name-only','HEAD'): return 'app.py'
                return ''
            with patch.object(release,"preflight",return_value={}), patch.object(release,"git",side_effect=git), \
                patch.object(release.subprocess,"run",side_effect=run), patch.object(release,"migrate",side_effect=migrate), \
                patch.object(release,"healthy",return_value=failure != "health"):
                if failure:
                    with self.assertRaises(release.ReleaseFailure) as caught:
                        release.execute(root,TARGET,module,io.StringIO(),backup_base=root/"backups")
                    self.assertNotIn("private", str(caught.exception))
                else:
                    result = release.execute(root,TARGET,module,io.StringIO(),backup_base=root/"backups")
                    self.assertTrue((result/"COMPLETE").is_file())
        return events

    def test_success_orders_stop_backup_checkout_migrate_start(self):
        events = self.scenario()
        self.assertLess(events.index(("migrate",)), events.index(("systemctl","start","mytoolbox")))

    def test_backup_failure_never_changes_git_or_migrates_and_restarts_old_service(self):
        events = self.scenario("backup")
        self.assertNotIn(("migrate",), events)
        self.assertFalse(any(e[:2] == ("git","merge") for e in events))
        self.assertEqual(events[-1], ("systemctl","start","mytoolbox"))

    def test_migration_failure_keeps_new_code_stopped_without_rollback(self):
        events = self.scenario("migration")
        self.assertNotIn(("systemctl","start","mytoolbox"), events)
        self.assertEqual(events[-1], ("systemctl","stop","mytoolbox"))

    def test_flask_migrate_system_exit_reports_failure_and_keeps_writes_stopped(self):
        events = self.scenario("migration-exit")
        self.assertNotIn(("systemctl","start","mytoolbox"),events)
        self.assertEqual(events[-1], ("systemctl","stop","mytoolbox"))

    def test_failed_health_stops_new_version_without_starting_old_code(self):
        events = self.scenario("health")
        self.assertEqual(events[-1], ("systemctl","stop","mytoolbox"))
        self.assertEqual(sum(e[:2] == ("git","merge") for e in events), 1)

    def test_interrupted_checkout_with_old_head_but_changed_files_cannot_restart(self):
        events = self.scenario('partial-checkout')
        self.assertNotIn(("systemctl","start","mytoolbox"),events)
        self.assertNotIn(("migrate",),events)
        self.assertEqual(events[-1],("systemctl","stop","mytoolbox"))
