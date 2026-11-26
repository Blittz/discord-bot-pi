"""Exercises tools/update-bot.sh against throwaway git repos and a fake systemctl.

Nothing here touches the real service: sudo/systemctl/journalctl are stubs on PATH.
A commit that adds a file named BROKEN makes the stub service unhealthy, which
lets us test the rollback path with a realistic "bad deploy".
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "update-bot.sh"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
}

FAKE_SUDO = '#!/usr/bin/env bash\nexec "$@"\n'
FAKE_SYSTEMCTL = r'''#!/usr/bin/env bash
case "$1" in
  restart) echo restart >> "$FAKE_DIR/calls" ;;
  is-active) [[ ! -e "$REPO_DIR/BROKEN" ]] ;;
esac
'''
FAKE_JOURNALCTL = r'''#!/usr/bin/env bash
[[ -e "$REPO_DIR/BROKEN" ]] || echo "bot: Logged in as TestBot#0000"
'''


def git(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **GIT_ENV},
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@unittest.skipUnless(shutil.which("bash") and shutil.which("git") and shutil.which("flock") and os.name == "posix",
                     "needs bash, git and flock on a POSIX system")
class UpdateScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        origin, self.repo, self.pusher = (self.tmp / n for n in ("origin.git", "repo", "pusher"))
        git(self.tmp, "init", "-q", "--bare", "-b", "main", str(origin))
        git(self.tmp, "clone", "-q", str(origin), str(self.pusher))
        git(self.pusher, "checkout", "-q", "-b", "main")
        (self.pusher / "tests").mkdir()
        (self.pusher / "tests" / "test_ok.py").write_text(
            "import unittest\nclass T(unittest.TestCase):\n    def test_ok(self): pass\n")
        (self.pusher / "requirements.txt").write_text("")
        self.commit("v1")
        git(self.pusher, "push", "-q", "-u", "origin", "main")
        git(self.tmp, "clone", "-q", str(origin), str(self.repo))

        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("sudo", FAKE_SUDO), ("systemctl", FAKE_SYSTEMCTL), ("journalctl", FAKE_JOURNALCTL)):
            (self.bin / name).write_text(body)
            (self.bin / name).chmod(0o755)
        venv_bin = self.tmp / "venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "python").symlink_to(sys.executable)
        (self.tmp / "calls").write_text("")

    def commit(self, message, files=None):
        for name, content in (files or {}).items():
            path = self.pusher / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        (self.pusher / "marker.txt").write_text(message)
        git(self.pusher, "add", "-A")
        git(self.pusher, "commit", "-q", "-m", message)

    def push(self):
        git(self.pusher, "push", "-q", "origin", "main")

    def run_script(self, *args):
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "REPO_DIR": str(self.repo),
               "VENV_DIR": str(self.tmp / "venv"), "FAKE_DIR": str(self.tmp), "LOCK_FILE": str(self.tmp / "lock"),
               "HEALTH_TIMEOUT": "2", "POLL_SECONDS": "0.1", "SETTLE_SECONDS": "0", **GIT_ENV}
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)

    def restarts(self):
        return (self.tmp / "calls").read_text().split().count("restart")

    def head_message(self):
        return git(self.repo, "log", "-1", "--format=%s")

    def test_up_to_date_does_nothing(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("nothing to do", result.stdout)
        self.assertEqual(self.restarts(), 0)

    def test_force_restarts_and_verifies(self):
        result = self.run_script("--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.restarts(), 1)
        self.assertIn("Healthy", result.stdout)

    def test_good_update_is_applied_tested_and_restarted(self):
        self.commit("v2")
        self.push()
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.head_message(), "v2")
        self.assertEqual(self.restarts(), 1)
        self.assertIn("Tests passed", result.stdout)

    def test_failing_tests_roll_back_without_restarting(self):
        self.commit("bad tests", {"tests/test_bad.py": "import unittest\nclass T(unittest.TestCase):\n    def test_x(self): self.fail('no')\n"})
        self.push()
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.head_message(), "v1")
        self.assertEqual(self.restarts(), 0)
        self.assertIn("Tests FAILED", result.stdout)

    def test_unhealthy_service_rolls_back_and_restarts_again(self):
        self.commit("bad deploy", {"BROKEN": "x"})
        self.push()
        result = self.run_script()
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.head_message(), "v1")
        self.assertEqual(self.restarts(), 2)  # onto the bad code, then back
        self.assertIn("previous version is running again", result.stdout)

    def test_wrong_branch_aborts_untouched(self):
        git(self.repo, "checkout", "-q", "-b", "feature")
        self.commit("v2")
        self.push()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("not 'main'", result.stdout)
        self.assertEqual(self.restarts(), 0)

    def test_uncommitted_tracked_changes_abort(self):
        (self.repo / "marker.txt").write_text("local edit")
        self.commit("v2")
        self.push()
        result = self.run_script()
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted", result.stdout)
        self.assertEqual((self.repo / "marker.txt").read_text(), "local edit")
        self.assertEqual(self.restarts(), 0)


if __name__ == "__main__":
    unittest.main()
