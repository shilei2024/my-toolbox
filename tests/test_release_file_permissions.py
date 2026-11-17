"""Exercise documented checkout umasks against real Git on POSIX runners."""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import unittest
import shlex


@unittest.skipUnless(os.name == "posix" and shutil.which("git"), "Requires POSIX permission semantics and Git")
class ReleasePermissionTests(unittest.TestCase):
    def test_recovery_update_and_failed_homepage_rollback(self):
        document = (Path(__file__).parents[1] / "docs/deployment/gallery-ui-release-2026-11-17.md").read_text(encoding="utf-8")
        script = re.findall(r"```bash\n(.*?)```", document, re.S)[0]
        for fail_home in (False, True):
            with self.subTest(fail_home=fail_home), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                def git(*args):
                    return subprocess.check_output(["git", *args], cwd=root, stderr=subprocess.DEVNULL, text=True).strip()
                git("init", "--quiet", "--initial-branch=main")
                templates = root / "templates"
                templates.mkdir()
                for name in ("base.html", "index.html", "tools_base.html"):
                    (templates / name).write_text("original")
                caddy = root / "services/generation-service/deploy/Caddyfile.production"
                caddy.parent.mkdir(parents=True)
                caddy.write_text("synthetic proxy fixture")
                def commit(message):
                    git("add", ".")
                    git("-c", "user.name=Release Test", "-c", "user.email=release@example.test", "commit", "--quiet", "-m", message)
                    return git("rev-parse", "HEAD")
                source = commit("source")
                (templates / "index.html").write_text("updated")
                target = commit("target")
                git("switch", "--detach", source)
                # External commands are synthetic; never contact a service or DB.
                binaries = root / "fake-bin"
                binaries.mkdir()
                mocks = {
                    "systemctl": '#!/bin/sh\ncase "$*" in *--value*) echo release-test;; *) echo active;; esac\n',
                    "sudo": '#!/bin/sh\nshift 2\nexec "$@"\n',
                    "curl": '#!/bin/sh\ncase "$*" in *127.0.0.1:8000/) test "$FAIL_HOME" != 1;; *) exit 0;; esac\n',
                }
                for name, body in mocks.items():
                    file = binaries / name
                    file.write_text(body)
                    file.chmod(0o755)
                # Mocks must not be visible to the worktree cleanliness guard.
                (root / ".git/info/exclude").write_text("fake-bin/\n")
                isolated = script.replace("cd /opt/mytoolbox", "cd " + shlex.quote(str(root)))
                isolated = isolated.replace("1893ad51f6a65dc977981a26a64c6769135575d3", source)
                isolated = isolated.replace("31f58bc9d8620ba9633ab20e364ce354fe5c1522", target)
                isolated = isolated.replace("/opt/mytoolbox/.venv/bin/python scripts/ops/invoice_backup.py", "true")
                env = dict(os.environ, PATH=str(binaries) + os.pathsep + os.environ["PATH"], FAIL_HOME="1" if fail_home else "0")
                result = subprocess.run(["bash", "-c", isolated], cwd=root, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(result.returncode, 1 if fail_home else 0, result.stderr)
                self.assertEqual(git("rev-parse", "HEAD"), source if fail_home else target)
                self.assertIn("UPDATE_FAILED_ROLLED_BACK" if fail_home else "UI_GALLERY_SERVER_RELEASE_OK", result.stdout)
                for file in templates.iterdir():
                    self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o644)
                self.assertEqual(caddy.read_text(), "synthetic proxy fixture")

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
