from __future__ import annotations

import unittest
from pathlib import Path


ADR_DIR = Path(__file__).parents[1] / "docs" / "adr"
REQUIRED = (
    "## Why",
    "## Alternatives Considered",
    "## Future Impact",
    "## Performance",
    "## Cost",
    "## Security",
    "## Rollback Plan",
)


class PhaseADRTests(unittest.TestCase):
    def test_every_completed_phase_has_a_complete_adr(self):
        for phase in range(1, 11):
            matches = list(ADR_DIR.glob(f"*-phase-{phase}-*.md"))
            self.assertEqual(len(matches), 1, f"Phase {phase} must have exactly one ADR")
            content = matches[0].read_text(encoding="utf-8")
            for heading in REQUIRED:
                self.assertIn(heading, content, f"{matches[0].name} misses {heading}")


if __name__ == "__main__":
    unittest.main()
