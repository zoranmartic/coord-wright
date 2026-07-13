import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "pretooluse-bash.sh"


class PreToolUseBashHookTests(unittest.TestCase):
    def run_hook(self, command):
        bash = shutil.which("bash") or "/bin/bash"
        payload = json.dumps({"tool_input": {"command": command}})
        return subprocess.run(
            [bash, str(HOOK)],
            input=payload,
            text=True,
            capture_output=True,
            cwd=ROOT,
        )

    def assert_blocked(self, command):
        result = self.run_hook(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("decision"), "block", result.stdout)

    def assert_allowed(self, command):
        result = self.run_hook(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_scan_proven_bypasses_are_blocked(self):
        blocked = [
            "rm -rf $HOME/Projects/coord-wright",
            "rm -rf ~/Projects/*",
            "python3 -c open('$HOME/Projects/coord-wright/PWNED','w').write('x')",
        ]
        for command in blocked:
            with self.subTest(command=command):
                self.assert_blocked(command)

    def test_legitimate_commands_are_allowed(self):
        allowed = [
            "git status",
            "npm test",
            "python3 bin/coord show 2026-05-17-harden-pretooluse-bash-hook-against-scan-proven-de",
            "rm -rf node_modules",
        ]
        for command in allowed:
            with self.subTest(command=command):
                self.assert_allowed(command)


if __name__ == "__main__":
    unittest.main()
