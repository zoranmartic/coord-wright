import subprocess
import sys
from pathlib import Path

COORD = Path(__file__).resolve().parents[1] / "bin" / "coord"


def _repo(tmp_path):
    for cmd in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
        ["git", "commit", "-q", "--allow-empty", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=tmp_path, check=True)
    (tmp_path / "tasks" / "archive").mkdir(parents=True)
    return tmp_path


def _coord(repo, *args):
    return subprocess.run([sys.executable, str(COORD), *args], cwd=repo, text=True, capture_output=True)


def _new(repo, *extra):
    result = _coord(repo, "new", "--task=Budget probe", *extra)
    assert result.returncode == 0, result.stderr
    return next((repo / "tasks").glob("*budget-probe.md"))


def test_new_sets_scope_budget_band(tmp_path):
    path = _new(_repo(tmp_path), "--scope-budget-loc=+8 to +25")

    text = path.read_text(encoding="utf-8")
    assert "scope_budget:\n  net_loc_delta_target: +8 to +25\n  abort_if_exceeded_by_pct: 50\n" in text


def test_first_finding_replaces_the_placeholder(tmp_path):
    repo = _repo(tmp_path)
    path = _new(repo)
    task_id = path.stem

    for text in ("first finding", "second finding"):
        assert _coord(repo, "update", task_id, f"--append-claude-finding={text}").returncode == 0

    body = path.read_text(encoding="utf-8")
    section = body.split("## Claude findings\n", 1)[1].split("## Codex findings", 1)[0]
    assert "_No findings yet._" not in section
    assert section.startswith("\n### Round 1\n\nfirst finding\n\n### Round 2\n\nsecond finding\n")
    assert "## Codex findings\n\n_No findings yet._" in body
