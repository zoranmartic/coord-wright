import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "posttooluse-py-typecheck.sh"


def find_mypy():
    candidates = [shutil.which("mypy")]
    candidates.extend([
        ROOT / ".venv" / "bin" / "mypy",
        ROOT / "backend" / ".venv" / "bin" / "mypy",
        Path.home() / ".local" / "bin" / "mypy",
        Path("/opt/homebrew/bin/mypy"),
        Path("/usr/local/bin/mypy"),
    ])
    for candidate in candidates:
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return Path(candidate)
    return None


class PostToolUsePyTypecheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mypy = find_mypy()

    def setUp(self):
        if self.mypy is None:
            self.skipTest("mypy is not installed")

        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.fakebin = self.root / "fakebin"
        self.toolbin = self.root / "toolbin"
        self.repo.mkdir()
        self.fakebin.mkdir()
        self.toolbin.mkdir()
        (self.repo / ".venv" / "bin").mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)

        mypy_link = self.repo / ".venv" / "bin" / "mypy"
        mypy_link.symlink_to(self.mypy)
        self.sample = self.repo / "sample.py"
        self.sample.write_text('value: int = "bad"\n', encoding="utf-8")

        for name in ("python3", "git", "grep", "head", "cat", "dirname"):
            executable = shutil.which(name)
            if executable is not None:
                (self.toolbin / name).symlink_to(executable)

    def tearDown(self):
        if hasattr(self, "tmp"):
            self.tmp.cleanup()

    def env_without_timeout(self):
        entries = []
        for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
            if not raw_entry:
                continue
            entry = Path(raw_entry)
            if (entry / "timeout").exists() or (entry / "gtimeout").exists():
                continue
            entries.append(raw_entry)
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join([str(self.toolbin), *entries])
        return env

    def env_with_fake_timeout(self):
        timeout = self.fakebin / "timeout"
        timeout.write_text("#!/bin/sh\nshift\nexec \"$@\"\n", encoding="utf-8")
        timeout.chmod(0o755)
        env = self.env_without_timeout()
        env["PATH"] = os.pathsep.join([str(self.fakebin), env["PATH"]])
        return env

    def run_hook(self, env):
        payload = json.dumps({"tool_input": {"file_path": str(self.sample)}})
        bash = shutil.which("bash") or "/bin/bash"
        return subprocess.run(
            [bash, str(HOOK)],
            input=payload,
            text=True,
            capture_output=True,
            env=env,
        )

    def assert_mypy_error_visible(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("mypy (sample.py):", result.stdout)
        self.assertIn("sample.py:1: error:", result.stdout)
        self.assertNotIn("command not found", result.stderr)

    def test_type_errors_reach_stdout_with_timeout_available(self):
        result = self.run_hook(self.env_with_fake_timeout())

        self.assert_mypy_error_visible(result)
        self.assertEqual(result.stderr, "")

    def test_type_errors_reach_stdout_without_timeout_available(self):
        result = self.run_hook(self.env_without_timeout())

        self.assert_mypy_error_visible(result)
        self.assertIn("timeout/gtimeout unavailable; running mypy without watchdog", result.stderr)


if __name__ == "__main__":
    unittest.main()
