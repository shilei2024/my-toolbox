"""Tool registry sync: stale DB rows are disabled when absent from YAML."""
from __future__ import annotations

import os
import unittest

os.environ.setdefault("FLASK_ENV", "production")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from app import app  # noqa: E402
from extensions import db  # noqa: E402
from models import Tool  # noqa: E402
from tools import sync_tool_registry  # noqa: E402


class ToolRegistrySyncTest(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self) -> None:
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_stale_tool_missing_from_yaml_is_disabled(self) -> None:
        db.session.add(
            Tool(
                id="doc-viewer",
                name="文档查看器",
                description="legacy row with no implementation",
                icon="bi-file-earmark-text",
                color="#0d6efd",
                route="/tools/doc-viewer",
                blueprint_module="tools.doc_viewer",
                enabled=True,
            )
        )
        db.session.commit()

        sync_tool_registry(app)

        tool = db.session.get(Tool, "doc-viewer")
        self.assertIsNotNone(tool)
        self.assertFalse(tool.enabled)

    def test_configured_tool_stays_enabled_after_sync(self) -> None:
        sync_tool_registry(app)
        tool = db.session.get(Tool, "pdf_merge")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.enabled)


if __name__ == "__main__":
    unittest.main()
