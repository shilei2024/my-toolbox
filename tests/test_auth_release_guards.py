import os
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.ops import auth_release_rehearsal as rehearsal
from scripts.ops.auth_release import require_fast_forward
from scripts.ops.invoice_release import ReleaseFailure


class ReleaseAncestryTests(unittest.TestCase):
    def test_real_history_accepts_fast_forward_and_rejects_divergence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            git('init', '-b', 'main')
            git('config', 'user.name', 'Release Test')
            git('config', 'user.email', 'release@example.invalid')
            (root/'fixture').write_text('base')
            git('add', 'fixture'); git('commit', '-m', 'base')
            base = git('rev-parse', 'HEAD')
            (root/'fixture').write_text('candidate')
            git('commit', '-am', 'candidate')
            target = git('rev-parse', 'HEAD')
            require_fast_forward(root, base, target)
            require_fast_forward(root, target, target)
            git('checkout', '-b', 'diverged', base)
            (root/'fixture').write_text('local')
            git('commit', '-am', 'local')
            for source in (git('rev-parse', 'HEAD'), '0'*40):
                with self.assertRaisesRegex(ReleaseFailure, 'source-not-ancestor'):
                    require_fast_forward(root, source, target)


class RehearsalGuardTests(unittest.TestCase):
    def test_production_names_and_missing_ack_never_open_database(self):
        args = SimpleNamespace(ack_isolated_database=True, writers_stopped=True, backup_manifest="unused")
        with patch.object(rehearsal, "migrate") as migrate:
            for url in ("postgresql://localhost/mytoolbox", "sqlite:///auth_rehearsal_test.db", "postgresql://localhost/auth_rehearsal_"):
                with self.subTest(url=url), patch.dict(os.environ, AUTH_MIGRATION_DATABASE_URL=url):
                    with self.assertRaises(ValueError): rehearsal.run(args)
            args.writers_stopped = False
            with patch.dict(os.environ, AUTH_MIGRATION_DATABASE_URL="postgresql://localhost/auth_rehearsal_test"):
                with self.assertRaises(ValueError): rehearsal.run(args)
            migrate.assert_not_called()

    def test_verified_backup_is_required_before_complete_migration(self):
        args = SimpleNamespace(ack_isolated_database=True, writers_stopped=True, backup_manifest="manifest.json")
        with patch.dict(os.environ, AUTH_MIGRATION_DATABASE_URL="postgresql://localhost/auth_rehearsal_test"), patch.object(rehearsal, "verified_backup", side_effect=ValueError), patch.object(rehearsal, "migrate") as migrate:
            with self.assertRaises(ValueError): rehearsal.run(args)
            migrate.assert_not_called()
