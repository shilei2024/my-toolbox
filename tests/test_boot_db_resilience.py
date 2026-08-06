"""Boot resilience: a dead database must not crash the whole Vercel function."""
from __future__ import annotations

import os
import unittest
from unittest import mock

import sqlalchemy.exc

os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import app as app_module  # noqa: E402


class BootDbResilienceTests(unittest.TestCase):
    def test_create_app_survives_boot_database_failure(self) -> None:
        with mock.patch.object(
            app_module,
            "_seed_admin",
            side_effect=sqlalchemy.exc.OperationalError("db down", None, None),
        ):
            flask_app = app_module.create_app()
        self.assertTrue(flask_app.config.get("_BOOT_DB_FAILED"))

    def test_create_app_survives_schema_init_database_failure(self) -> None:
        with mock.patch.object(
            app_module,
            "apply_runtime_settings",
            side_effect=sqlalchemy.exc.OperationalError("db down", None, None),
        ):
            flask_app = app_module.create_app()
        self.assertTrue(flask_app.config.get("_BOOT_DB_FAILED"))


if __name__ == "__main__":
    unittest.main()
