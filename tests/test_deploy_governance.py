"""Deployment-doc contract guards for the unified Gallery admin console.

These tests exist because DEPLOY_GUIDE §8.1 previously omitted
GALLERY_SERVICE_BASE_URL / GALLERY_INTERNAL_HMAC_SECRET, which caused the
production Flask admin page to report "缺少有效的 GALLERY_INTERNAL_HMAC_SECRET".
"""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


class DeploymentEnvContractTests(unittest.TestCase):
    def test_deploy_guide_vercel_flask_section_lists_admin_vars(self):
        guide = (ROOT / "deploy" / "DEPLOY_GUIDE.md").read_text(encoding="utf-8")
        section = guide.split("### 8.1", 1)[1].split("### 8.2", 1)[0]
        self.assertIn("GALLERY_SERVICE_BASE_URL", section)
        self.assertIn("GALLERY_INTERNAL_HMAC_SECRET", section)

    def test_deployment_checklist_requires_unified_admin_env(self):
        checklist = (
            ROOT / "docs" / "operations" / "deployment-checklist.md"
        ).read_text(encoding="utf-8")
        self.assertIn("GALLERY_SERVICE_BASE_URL", checklist)
        self.assertIn("GALLERY_INTERNAL_HMAC_SECRET", checklist)

    def test_root_env_example_has_admin_vars(self):
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("GALLERY_SERVICE_BASE_URL=", example)
        self.assertIn("GALLERY_INTERNAL_HMAC_SECRET=", example)

    def test_admin_client_errors_mention_vercel_location(self):
        source = (ROOT / "utils" / "gallery_admin_client.py").read_text(encoding="utf-8")
        self.assertIn("Vercel my-toolbox", source)
        self.assertIn("重新部署", source)


if __name__ == "__main__":
    unittest.main()
