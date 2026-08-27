"""Tool registry sync: stale DB rows are disabled when absent from YAML."""
from __future__ import annotations

import os
import unittest

import yaml

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

    def test_invoice_tools_are_one_card_with_legacy_route_alias(self) -> None:
        config_path = app.config["TOOLS_CONFIG_PATH"]
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        entries = {entry["id"]: entry for entry in config["tools"]}

        self.assertNotIn("zip_extractor", entries)
        self.assertEqual(
            entries["invoice_printer"]["route_aliases"],
            ["/tools/zip-extractor"],
        )

        rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn("/tools/invoice-printer/", rules)
        self.assertIn("/tools/invoice-printer/analyze", rules)
        self.assertIn("/tools/zip-extractor/", rules)
        self.assertIn("/tools/zip-extractor/analyze", rules)

        response = app.test_client().get("/tools/zip-extractor/")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("发票提取与批量打印", body)
        self.assertIn('accept=".zip,.pdf', body)
        self.assertIn("/tools/invoice-printer/analyze", body)
        self.assertIn("单包最大 20MB", body)
        self.assertIn('data-action="clear-all"', body)
        self.assertIn('data-remove-queue-id=', body)
        self.assertNotIn("onclick=", body)
        self.assertNotIn("confirm(", body)
        self.assertNotIn(".tif", body)

    def test_removed_zip_extractor_card_is_disabled_during_sync(self) -> None:
        db.session.add(
            Tool(
                id="zip_extractor",
                name="批量提取PDF发票",
                description="legacy duplicate card",
                icon="bi-file-zip",
                color="#6f42c1",
                route="/tools/zip-extractor",
                blueprint_module="tools.zip_extractor",
                enabled=True,
            )
        )
        db.session.commit()

        sync_tool_registry(app)

        self.assertFalse(db.session.get(Tool, "zip_extractor").enabled)


if __name__ == "__main__":
    unittest.main()
