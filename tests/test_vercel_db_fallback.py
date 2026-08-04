"""Regression tests: Vercel read-only FS must honor DATABASE_URL."""
from __future__ import annotations

import os
import unittest

from app import _has_external_database


class VercelDatabaseFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            key: os.environ.get(key)
            for key in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL")
        }

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_postgres_url_non_pooling_counts_as_external(self) -> None:
        os.environ.pop("DATABASE_URL", None)
        os.environ["POSTGRES_URL_NON_POOLING"] = "postgres://u:p@h/db"
        self.assertTrue(_has_external_database())

    def test_postgres_url_counts_as_external(self) -> None:
        os.environ.pop("DATABASE_URL", None)
        os.environ["POSTGRES_URL"] = "postgres://u:p@h/db"
        self.assertTrue(_has_external_database())

    def test_postgres_database_url_counts_as_external(self) -> None:
        for key in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL"):
            os.environ.pop(key, None)
        os.environ["DATABASE_URL"] = (
            "postgresql://mavis:pw@101.43.122.182:5432/mindfulpenpal?sslmode=require"
        )
        self.assertTrue(_has_external_database())

    def test_no_external_db_returns_false(self) -> None:
        for key in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL", "DATABASE_URL"):
            os.environ.pop(key, None)
        self.assertFalse(_has_external_database())

    def test_sqlite_database_url_does_not_count_as_external(self) -> None:
        for key in ("POSTGRES_URL_NON_POOLING", "POSTGRES_URL"):
            os.environ.pop(key, None)
        os.environ["DATABASE_URL"] = "sqlite:///app.db"
        self.assertFalse(_has_external_database())


if __name__ == "__main__":
    unittest.main()
