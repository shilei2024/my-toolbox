import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from scripts.ops import mobile_invoice_release as release


class MobileReleaseTests(unittest.TestCase):
    def scenario(self,failure=None):
        events=[];head=[release.SOURCE];target='a'*40
        def run(command,**kwargs):
            events.append(command[1] if command[0]=='systemctl' else command[0])
            return SimpleNamespace(returncode=3 if command[1]=='is-active' else 0)
        def backup(root,directory,url):
            events.append('backup')
            if failure=='backup': raise RuntimeError('private-connection')
            return {'migration_revisions':[release.OLD]}
        def checkout(*args):
            events.append('checkout');head[0]=target
        def readable(*args):
            events.append('readable')
            if failure=='readable': raise RuntimeError('permission-error')
        def migrate(*args):
            events.append('migrate')
            if failure=='migration': raise SystemExit(1)
        with tempfile.TemporaryDirectory() as directory,patch.object(release,'preflight',return_value={}), \
            patch.object(release.backup,'service_database_url',return_value='private'),patch.object(release.backup,'backup',side_effect=backup), \
            patch.object(release.backup,'private_manifest'),patch.object(release.common,'checkout_release',side_effect=checkout), \
            patch.object(release.common,'git',side_effect=lambda root,*a:head[0] if a==('rev-parse','HEAD') else ''), \
            patch.object(release.subprocess,'run',side_effect=run),patch.object(release,'runtime_readable',side_effect=readable), \
            patch.object(release,'migrate',side_effect=migrate),patch.object(release,'healthy_disabled',return_value=failure!='health'):
            if failure:
                with self.assertRaises(release.common.ReleaseFailure) as caught:
                    release.execute(Path(directory),target,io.StringIO(),base=Path(directory)/'backups')
                self.assertNotIn('private-connection',str(caught.exception))
            else: release.execute(Path(directory),target,io.StringIO(),base=Path(directory)/'backups')
        return events

    def test_success_preserves_backup_checkout_permissions_migration_order(self):
        events=self.scenario()
        self.assertLess(events.index('stop'),events.index('backup'))
        self.assertLess(events.index('backup'),events.index('checkout'))
        self.assertLess(events.index('checkout'),events.index('readable'))
        self.assertLess(events.index('readable'),events.index('migrate'))
        self.assertLess(events.index('migrate'),events.index('start'))

    def test_backup_failure_restarts_only_unchanged_old_code(self):
        events=self.scenario('backup');self.assertNotIn('checkout',events);self.assertEqual(events[-1],'start')

    def test_unreadable_new_code_stops_before_migration(self):
        events=self.scenario('readable');self.assertNotIn('migrate',events);self.assertNotIn('start',events);self.assertEqual(events[-1],'stop')

    def test_migration_exit_keeps_new_code_stopped(self):
        events=self.scenario('migration');self.assertNotIn('start',events);self.assertEqual(events[-1],'stop')

    def test_health_failure_keeps_new_code_stopped(self):
        self.assertEqual(self.scenario('health')[-1],'stop')
