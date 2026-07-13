"""Regression tests for the interactive-effort default in bin/agent-launch.sh.

The VS Code task buttons launch a bare `agent-launch.sh claude` (no -p), which
should get `--effort max` by default. Headless coord callers (worker.sh,
watchdog.sh) pass -p and must be left untouched so each task honours its own
reasoning_effort. Codex launches are never affected.
"""

import os
import stat
import subprocess
from pathlib import Path

LAUNCH = Path(__file__).resolve().parent.parent / "bin" / "agent-launch.sh"


def _run(args, extra_env=None, tmp_path=None):
    """Invoke agent-launch.sh with a stub agent bin that echoes its argv.

    Returns (recorded_argv_list, stderr_text). The stub is wired in via
    CLAUDE_BIN / CODEX_BIN, which agent-launch.sh prefers over PATH lookup.
    """
    stub = tmp_path / "stub-agent"
    stub.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = dict(os.environ)
    env["CLAUDE_BIN"] = str(stub)
    env["CODEX_BIN"] = str(stub)
    # Mimic the VS Code buttons, which set this to 0; keeps the legacy
    # permission fallback from prepending --dangerously-skip-permissions and
    # keeps the recorded argv focused on what this test cares about.
    env["CLAUDE_LAUNCH_BYPASS_PERMISSIONS"] = "0"
    if extra_env:
        env.update(extra_env)

    proc = subprocess.run(
        [str(LAUNCH), *args],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    argv = [line for line in proc.stdout.splitlines() if line != ""]
    return argv, proc.stderr


def _effort_value(argv):
    if "--effort" not in argv:
        return None
    return argv[argv.index("--effort") + 1]


def test_interactive_claude_defaults_to_max(tmp_path):
    argv, _ = _run(["claude"], tmp_path=tmp_path)
    assert _effort_value(argv) == "max"


def test_headless_print_launch_is_untouched(tmp_path):
    # worker.sh / watchdog.sh shape: -p drives the headless print mode.
    argv, _ = _run(
        ["claude", "-p", "/coord-run 2026-x", "--output-format", "json"],
        tmp_path=tmp_path,
    )
    assert "--effort" not in argv


def test_long_print_flag_is_untouched(tmp_path):
    argv, _ = _run(["claude", "--print", "hello"], tmp_path=tmp_path)
    assert "--effort" not in argv


def test_management_command_is_untouched(tmp_path):
    argv, _ = _run(["claude", "--version"], tmp_path=tmp_path)
    assert "--effort" not in argv


def test_env_override_selects_level(tmp_path):
    argv, _ = _run(
        ["claude"], extra_env={"CLAUDE_LAUNCH_EFFORT": "high"}, tmp_path=tmp_path
    )
    assert _effort_value(argv) == "high"


def test_empty_env_disables_default(tmp_path):
    argv, _ = _run(
        ["claude"], extra_env={"CLAUDE_LAUNCH_EFFORT": ""}, tmp_path=tmp_path
    )
    assert "--effort" not in argv


def test_explicit_effort_flag_is_respected(tmp_path):
    argv, _ = _run(["claude", "--effort", "low"], tmp_path=tmp_path)
    # Not doubled, not overridden to max.
    assert argv.count("--effort") == 1
    assert _effort_value(argv) == "low"


def test_invalid_env_is_ignored_with_warning(tmp_path):
    argv, stderr = _run(
        ["claude"], extra_env={"CLAUDE_LAUNCH_EFFORT": "bogus"}, tmp_path=tmp_path
    )
    assert "--effort" not in argv
    assert "invalid CLAUDE_LAUNCH_EFFORT" in stderr


def test_codex_launch_never_gets_effort(tmp_path):
    argv, _ = _run(["codex"], tmp_path=tmp_path)
    assert "--effort" not in argv
