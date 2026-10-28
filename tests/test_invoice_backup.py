import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

path = Path(__file__).parents[1] / "scripts/ops/invoice_backup.py"
spec = importlib.util.spec_from_file_location("invoice_backup", path)
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class InvoiceBackupTests(unittest.TestCase):
    def test_credentials_only_in_private_file_and_uri_decoded(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch.dict(os.environ, {"PGDATABASE":"old", "PGPASSWORD":"old-secret", "DATABASE_URL":"old-secret", "SECRET_KEY":"unrelated-secret"}):
                env = backup.private_connection_environment(
                    "postgresql://test:pass%3Aword%40one@localhost:5432/business?sslmode=require", directory)
            self.assertNotIn("PGPASSWORD", env)
            self.assertNotIn("DATABASE_URL", env)
            self.assertNotIn("PGDATABASE", env)
            self.assertNotIn("SECRET_KEY", env)
            self.assertEqual(env["PGSERVICE"], "invoice_backup")
            service = (directory / "database.service.conf").read_text()
            self.assertIn("password=pass:word@one\n", service)
            self.assertIn("sslmode=require\n", service)
            if os.name != "nt":
                self.assertEqual((directory/"database.service.conf").stat().st_mode & 0o777, 0o600)

    def test_service_line_injection_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                backup.private_connection_environment("postgresql://test:bad%0Avalue@localhost/db", Path(temp))
            self.assertFalse((Path(temp)/"database.service.conf").exists())

    def test_manifest_hashes_but_does_not_copy_secret_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory/"app.env").write_text("SECRET=private-test-value")
            result = backup.private_manifest(directory, {"restore_verified":False})
            self.assertEqual(result["files"]["app.env"]["bytes"], 25)
            manifest = (directory/"manifest.json").read_text()
            self.assertNotIn("private-test-value", manifest)
            self.assertFalse(json.loads(manifest)["restore_verified"])
