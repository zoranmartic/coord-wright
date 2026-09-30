import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD_LOG = ROOT / "bin" / "coord-log"

TASK = "2026-01-02-add-json-flag"
LOG = f"""\
[2026-01-02T10:00:00+0000] git sync skipped: worktree dirty
[2026-01-02T10:00:30+0000] git sync skipped: worktree dirty
[2026-01-02T10:01:00+0000] tick: running {TASK} with codex
[2026-01-02T10:01:01+0000] pickup: role=coder model=gpt-5.6-sol model_source=model_codex reasoning=medium reasoning_source=reasoning_effort
[2026-01-02T10:03:00+0000] tokens reported for {TASK} (codex S1)
[2026-01-02T10:03:05+0000] mechanical verify gate: all verify_commands passed for {TASK}
[2026-01-02T10:03:10+0000] tick: done {TASK} with codex
[2026-01-02T10:04:00+0000] tick failed rc=3 for {TASK}
"""


def _render(tmp_path):
    log = tmp_path / ".coord" / "worker.log"
    log.parent.mkdir()
    log.write_text(LOG, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(COORD_LOG), str(tmp_path), "--once"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.splitlines()


def test_once_renders_one_line_per_round_and_collapses_noise(tmp_path):
    lines = _render(tmp_path)

    assert sum("worker waiting" in line for line in lines) == 1
    done = [line for line in lines if line.startswith("10:03 ✓ codex")]
    assert len(done) == 1
    assert "sol·med" in done[0]
    assert "add-json-flag" in done[0]
    assert "S1" in done[0]
    assert "2m10s" in done[0]
    assert "✓verify" in done[0]
    assert any("failed rc=3" in line and "add-json-flag" in line for line in lines)


def test_once_without_log_exits_nonzero(tmp_path):
    result = subprocess.run(
        [sys.executable, str(COORD_LOG), str(tmp_path), "--once"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode != 0
    assert "no log at" in result.stderr
