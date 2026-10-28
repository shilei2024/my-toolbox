"""Legacy /favicon.ico requests must not log a 404 on every page load."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import app  # noqa: E402


class FaviconRouteTest(unittest.TestCase):
    def test_favicon_ico_redirects_to_svg(self) -> None:
        response = app.test_client().get("/favicon.ico")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/static/img/favicon.svg", response.headers["Location"])


if __name__ == "__main__":
    unittest.main()
