import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from scripts.ops import auth_release_rehearsal as rehearsal


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
