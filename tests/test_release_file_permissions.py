"""Exercise documented checkout umasks against real Git on POSIX runners."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "Requires POSIX permission semantics and Git")
class ReleasePermissionTests(unittest.TestCase):
    def test_documented_git_updates_leave_templates_readable_and_backups_private(self):
        document = (Path(__file__).parents[1] / "docs/deployment/gallery-ui-release-2026-11-17.md").read_text(encoding="utf-8")
        blocks = [s for s in re.findall(r"```bash\n(.*?)```", document, re.S)
                  if re.search(r"^git (?:merge|switch)", s, re.M)]
        self.assertGreaterEqual(len(blocks), 2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def git(*args):
                subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
            git("init", "--quiet")
            template = root / "index.html"
            template.write_text("<h1>Fixture</h1>")
            git("add", "index.html")
            git("-c", "user.name=Release Test", "-c", "user.email=release@example.test", "commit", "--quiet", "-m", "fixture")
            for index, block in enumerate(blocks):
                mode = re.search(r"^umask ([0-7]{3,4})$", block, re.M)
                self.assertIsNotNone(mode, "Every source checkout must set an explicit umask")
                with self.subTest(block=index):
                    template.unlink()
                    previous = os.umask(int(mode.group(1), 8))
                    try:
                        git("checkout", "HEAD", "--", "index.html")
                    finally:
                        os.umask(previous)
                    self.assertEqual(stat.S_IMODE(template.stat().st_mode), 0o644)
            previous = os.umask(0o077)
            try:
                private = root / "backup-state"
                private.write_text("synthetic release metadata")
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o600)
