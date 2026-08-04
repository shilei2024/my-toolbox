from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
AGENT_RULES = ROOT / "AGENTS.md"
HUMAN_RULES = ROOT / "docs" / "architecture" / "engineering-principles.md"

GOLDEN_RULE_CONCEPTS = (
    "production website",
    "future AI modules",
    "lower operational cost",
    "beginner",
    "long-term architecture",
)

REQUIRED_GOVERNANCE = (
    "Requirement review",
    "Architecture review",
    "Risk assessment",
    "Implementation plan",
    "Verification",
    "Documentation standard",
    "Definition of done",
)


class EngineeringGovernanceTests(unittest.TestCase):
    def test_root_agent_rules_preserve_golden_rule(self):
        content = AGENT_RULES.read_text(encoding="utf-8")
        for concept in GOLDEN_RULE_CONCEPTS:
            self.assertIn(concept, content)
        for section in REQUIRED_GOVERNANCE:
            self.assertIn(section, content)

    def test_human_readable_policy_and_adr_exist(self):
        self.assertTrue(HUMAN_RULES.is_file())
        self.assertTrue(
            (ROOT / "docs" / "adr" / "0012-permanent-engineering-governance.md").is_file()
        )


if __name__ == "__main__":
    unittest.main()
