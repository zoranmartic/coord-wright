"""Installer regression tests (converted from the recorded prelaunch-fix
fixtures into durable coverage).

Locks in:
- jq fail-fast: a missing jq aborts install.sh with a clear message BEFORE any
  side effect (no ~/.claude, ~/.agents, or launchd writes).
- Settings merge: existing permissions.allow / additionalDirectories / hook
  arrays are preserved (union, not replacement) and ~/.claude/settings.json is
  backed up before writing; a fresh machine gets a valid settings file with no
  backup.
- Placeholder renderer: resolving __COORD_TOOLS__/__HOME__ inside the parsed
  JSON survives checkout paths containing shell/JSON metacharacters.
- Worker plist propagation: COORD_UNSAFE_AUTONOMOUS=1 at install time lands in
  the generated launchd environment; re-running install without it removes the
  key again (revocation path).
"""

import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_install(tools, home, env_extra=None, path=None):
    env = os.environ.copy()
    env["HOME"] = str(home)
    env.pop("COORD_UNSAFE_AUTONOMOUS", None)
    if path is not None:
        env["PATH"] = path
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(Path(tools) / "install.sh")],
        cwd=tools,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _copy_tree(dst):
    """Copy the shippable tree (no .git/caches) so install.sh runs from dst."""
    shutil.copytree(
        ROOT, dst,
        ignore=shutil.ignore_patterns(
            ".git", "__pycache__", ".pytest_cache", ".coord", "projects.txt",
        ),
    )
    return dst


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_jq_fails_fast_with_zero_side_effects(self):
        tools = _copy_tree(self.base / "tools")
        # A PATH with only what install.sh needs BEFORE the jq check (newer
        # macOS ships /usr/bin/jq, so real system paths cannot prove absence).
        shim = self.base / "nojq-bin"
        shim.mkdir()
        for name in ("dirname", "bash"):
            (shim / name).symlink_to(shutil.which(name))
        result = _run_install(tools, self.home, path=str(shim))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires jq", result.stderr)
        self.assertFalse((self.home / ".claude").exists(),
                         msg="no ~/.claude writes may happen before the jq check")
        self.assertFalse((self.home / ".agents").exists())
        self.assertFalse((self.home / "Library").exists())

    def test_settings_merge_preserves_user_arrays_and_backs_up(self):
        tools = _copy_tree(self.base / "tools")
        claude_dir = self.home / ".claude"
        claude_dir.mkdir()
        existing = {
            "permissions": {
                "allow": ["Read", "Bash(existing *)"],
                "additionalDirectories": ["/existing/dir"],
            },
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "/existing/hook.sh"}]}
                ],
                "UserPromptSubmit": [
                    {"hooks": [{"type": "command", "command": "/existing/prompt-hook.sh"}]}
                ],
            },
        }
        (claude_dir / "settings.json").write_text(json.dumps(existing, indent=2), encoding="utf-8")

        result = _run_install(tools, self.home)
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)

        merged = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
        allow = merged["permissions"]["allow"]
        self.assertIn("Bash(existing *)", allow, msg="user allow entries must survive the merge")
        self.assertIn("/existing/dir", merged["permissions"]["additionalDirectories"])
        self.assertTrue(any(len(a) > 0 and a != "Bash(existing *)" for a in allow),
                        msg="coord entries must be merged in")
        pre_hooks = json.dumps(merged["hooks"]["PreToolUse"])
        self.assertIn("/existing/hook.sh", pre_hooks, msg="user hooks must survive the merge")
        self.assertIn("pretooluse-bash.sh", pre_hooks, msg="coord hook must be appended")
        backups = list(claude_dir.glob("settings.json.bak.*"))
        self.assertEqual(len(backups), 1, msg="exactly one timestamped backup per changed run")
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8")), existing)

    def test_fresh_machine_gets_valid_settings_without_backup(self):
        tools = _copy_tree(self.base / "tools")
        result = _run_install(tools, self.home)
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        settings = json.loads((self.home / ".claude" / "settings.json").read_text(encoding="utf-8"))
        self.assertTrue(settings["permissions"]["allow"])
        self.assertEqual(list((self.home / ".claude").glob("settings.json.bak.*")), [])

    def test_placeholder_renderer_survives_metacharacter_checkout_path(self):
        nasty = self.base / 'we&ird\\pa|th"x'
        tools = _copy_tree(nasty / "tools")
        result = _run_install(tools, self.home)
        self.assertEqual(result.returncode, 0, msg=result.stderr + result.stdout)
        settings_text = (self.home / ".claude" / "settings.json").read_text(encoding="utf-8")
        settings = json.loads(settings_text)  # must stay valid JSON
        hook_cmd = settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        self.assertEqual(hook_cmd, f"{tools}/hooks/session-start.sh",
                         msg="parsed hook value must carry the metacharacter path verbatim")

    def test_worker_plist_gate_key_propagates_and_revokes(self):
        tools = _copy_tree(self.base / "tools")
        project = self.base / "proj"
        project.mkdir()
        subprocess.run(["git", "init"], cwd=project, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=project, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=project, check=True)
        (Path(tools) / "projects.txt").write_text(f"{project}\n", encoding="utf-8")
        # Shim launchctl/plutil: plist generation is under test, not launchd.
        shim = self.base / "shim"
        shim.mkdir()
        for name in ("launchctl", "plutil"):
            p = shim / name
            p.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            p.chmod(0o755)
        path = f"{shim}:{os.environ['PATH']}"
        plist_path = self.home / "Library" / "LaunchAgents" / "com.coord.worker.proj.plist"

        acked = _run_install(tools, self.home, env_extra={"COORD_UNSAFE_AUTONOMOUS": "1"}, path=path)
        self.assertEqual(acked.returncode, 0, msg=acked.stderr + acked.stdout)
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        self.assertEqual(data["EnvironmentVariables"].get("COORD_UNSAFE_AUTONOMOUS"), "1")

        revoked = _run_install(tools, self.home, path=path)
        self.assertEqual(revoked.returncode, 0, msg=revoked.stderr + revoked.stdout)
        with open(plist_path, "rb") as f:
            data = plistlib.load(f)
        self.assertNotIn("COORD_UNSAFE_AUTONOMOUS", data["EnvironmentVariables"],
                         msg="re-running install without the acknowledgement must revoke the key")

        # Removing the project from projects.txt must remove its plist too —
        # otherwise a previously-acknowledged worker would stay loaded forever.
        (Path(tools) / "projects.txt").write_text("", encoding="utf-8")
        swept = _run_install(tools, self.home, path=path)
        self.assertEqual(swept.returncode, 0, msg=swept.stderr + swept.stdout)
        self.assertFalse(plist_path.exists(),
                         msg="stale worker plist must be unloaded and removed")


if __name__ == "__main__":
    unittest.main()
