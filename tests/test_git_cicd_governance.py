from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
CI = ROOT / ".github" / "workflows" / "ci.yml"


class GitCiCdGovernanceTests(unittest.TestCase):
    def test_ci_is_read_only_and_covers_required_gates(self):
        content = CI.read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", content)
        for job_name in (
            "Python tests",
            "Generation Service",
            "Gallery Web",
            "PostgreSQL integration",
        ):
            self.assertIn(f"name: {job_name}", content)
        self.assertNotIn("secrets.", content)
        self.assertNotIn("vercel --prod", content)
        self.assertNotIn("docker compose up", content)

    def test_actions_are_pinned_to_full_commit_shas(self):
        content = CI.read_text(encoding="utf-8")
        uses = re.findall(r"^\s*uses:\s*([^\s#]+)", content, flags=re.MULTILINE)
        self.assertTrue(uses)
        for action in uses:
            self.assertRegex(action, r"^[\w.-]+/[\w.-]+@[0-9a-f]{40}$")

    def test_required_delivery_documents_exist(self):
        paths = (
            "CONTRIBUTING.md",
            ".github/PULL_REQUEST_TEMPLATE.md",
            "docs/operations/git-strategy.md",
            "docs/operations/branch-strategy.md",
            "docs/operations/github-workflow-guide.md",
            "docs/operations/ci-cd-guide.md",
            "docs/operations/release-guide.md",
            "docs/deployment/vercel-deployment.md",
            "docs/deployment/tencent-backend-deployment.md",
            "docs/deployment/environment-variables.md",
            "docs/operations/rollback-guide.md",
            "docs/operations/release-checklist.md",
            "docs/operations/deployment-checklist.md",
            "docs/adr/0013-gitflow-preview-and-immutable-release-promotion.md",
        )
        for path in paths:
            self.assertTrue((ROOT / path).is_file(), path)


if __name__ == "__main__":
    unittest.main()
