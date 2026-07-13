import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_state_machine")
STATUS_ROUTING = COORD_MODULE["STATUS_ROUTING"]
VALID_TRANSITIONS = COORD_MODULE["VALID_TRANSITIONS"]
validate_transition = COORD_MODULE["validate_transition"]
runnable_for = COORD_MODULE["runnable_for"]


@pytest.mark.parametrize(("prev_status", "new_status"), sorted(VALID_TRANSITIONS))
def test_validate_transition_accepts_every_legal_pair(prev_status, new_status):
    assert validate_transition(prev_status, new_status, in_archive=False) is None


@pytest.mark.parametrize(
    ("prev_status", "new_status", "expected"),
    [
        ("pending", "done", "allowed transition table"),
        ("shaping", "codex-working", "allowed transition table"),
        ("needs-brainstorming", "done", "allowed transition table"),
        ("done", "pending", "status 'done' is terminal"),
    ],
)
def test_validate_transition_rejects_representative_illegal_pairs(prev_status, new_status, expected):
    assert expected in validate_transition(prev_status, new_status, in_archive=False)


def test_validate_transition_rejects_active_transition_from_archive():
    error = validate_transition("pending", "codex-working", in_archive=True)
    assert "requires the task to be in tasks/" in error
    assert "archived" in error


@pytest.mark.parametrize("status", sorted(STATUS_ROUTING))
def test_runnable_for_matches_status_routing(status):
    runnable = STATUS_ROUTING[status]["runnable"]
    assert runnable_for(status) is bool(runnable)
    assert runnable_for(status, "claude") is ("claude" in runnable)
    assert runnable_for(status, "codex") is ("codex" in runnable)


def test_runnable_for_unknown_status_is_false():
    assert runnable_for("not-a-status") is False
    assert runnable_for("not-a-status", "codex") is False


@pytest.mark.parametrize(("prev_status", "new_status"), sorted(VALID_TRANSITIONS))
def test_cli_update_accepts_every_legal_transition_pair(coord_repo, prev_status, new_status):
    args = ["update", f"sample-{prev_status}", f"--status={new_status}"]
    if new_status == "done":
        args.append("--complete-subtask=S1")

    result = coord_repo.coord(*args)

    assert result.returncode == 0, result.stderr
    assert f"updated sample-{prev_status}" in result.stdout


@pytest.mark.parametrize(
    ("task_id", "new_status", "expected"),
    [
        ("sample-pending", "done", "allowed transition table"),
        ("sample-shaping", "codex-working", "allowed transition table"),
        ("sample-needs-brainstorming", "done", "allowed transition table"),
        ("sample-done", "pending", "status 'done' is terminal"),
    ],
)
def test_cli_update_rejects_representative_illegal_transition_pairs(coord_repo, task_id, new_status, expected):
    result = coord_repo.coord("update", task_id, f"--status={new_status}")

    assert result.returncode == 3
    assert "update:" in result.stderr
    assert expected in result.stderr


def test_cli_update_rejects_active_transition_from_archive(coord_repo):
    archived_path = coord_repo.root / "tasks" / "archive" / "sample-pending.md"
    coord_repo.tasks["pending"].rename(archived_path)

    result = coord_repo.coord("update", "sample-pending", "--status=codex-working")

    assert result.returncode == 3
    assert "requires the task to be in tasks/" in result.stderr
    assert "archived" in result.stderr
