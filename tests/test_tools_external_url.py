"""AI image external entry validation for local loopback development."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Tool  # noqa: E402
from tools import sync_tool_registry  # noqa: E402


class ExternalUrlLoopbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_loopback_http_external_url_is_kept_for_local_dev(self) -> None:
        app.config["AI_IMAGE_EXTERNAL_URL"] = "http://127.0.0.1:3000/create"
        sync_tool_registry(app)
        tool = db.session.get(Tool, "ai_image")
        self.assertEqual(tool.external_url, "http://127.0.0.1:3000/create")

    def test_remote_http_external_url_is_hidden(self) -> None:
        app.config["AI_IMAGE_EXTERNAL_URL"] = "http://evil.example/create"
        sync_tool_registry(app)
        tool = db.session.get(Tool, "ai_image")
        self.assertEqual(tool.external_url, "")

    def test_empty_external_url_is_hidden(self) -> None:
        app.config["AI_IMAGE_EXTERNAL_URL"] = ""
        sync_tool_registry(app)
        tool = db.session.get(Tool, "ai_image")
        self.assertEqual(tool.external_url, "")


if __name__ == "__main__":
    unittest.main()
