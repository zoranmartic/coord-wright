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


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (("new", "--task=Invalid status", "--status=codex-working"), "invalid initial status"),
        (("new", "--task=Invalid assignee", "--assigned=human"), "not allowed for status 'shaping'"),
    ],
)
def test_new_rejects_invalid_initial_status_and_assignee(coord_repo, command, expected):
    result = coord_repo.coord(*command)

    assert result.returncode == 3
    assert expected in result.stderr


def test_new_allows_either_agent_on_unrestricted_status(coord_repo):
    result = coord_repo.coord("new", "--task=Shaping for claude", "--assigned=claude")

    assert result.returncode == 0, result.stderr


def test_update_rejects_assignee_not_allowed_for_resulting_status(coord_repo):
    result = coord_repo.coord("update", "sample-pending", "--assigned=invalid")

    assert result.returncode == 3
    assert "not allowed for status 'pending'" in result.stderr


def test_runnable_shape_rejects_invalid_role_agent():
    fm = {
        "status": "pending",
        "roles": {"coder": "Codex"},
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
    }
    errors = COORD_MODULE["validate_runnable_shape"](fm, "## Plan\nConcrete plan.\n\n## Acceptance test\nConcrete acceptance.\n")

    assert "roles.coder must be claude or codex" in errors


@pytest.mark.parametrize("agent", ["skip", "none"])
def test_runnable_shape_allows_non_agent_role_markers(agent):
    fm = {
        "status": "pending",
        "roles": {"architect": agent, "coder": "codex"},
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
    }
    errors = COORD_MODULE["validate_runnable_shape"](fm, "## Plan\nConcrete plan.\n\n## Acceptance test\nConcrete acceptance.\n")

    assert not [error for error in errors if error.startswith("roles.")]


def test_promote_and_release_validate_explicit_status_transition(coord_repo):
    promoted = coord_repo.coord("promote", "sample-shaping", "--status=needs-review")

    assert promoted.returncode == 3
    assert "allowed transition table" in promoted.stderr

    path = coord_repo.tasks["shaping"]
    text = path.read_text(encoding="utf-8").replace("status: shaping", "status: pending")
    text = text.replace("assigned: codex", "assigned: codex\npickup_hold: true")
    path.write_text(text, encoding="utf-8")
    released = coord_repo.coord("release", "sample-shaping", "--status=needs-review")

    assert released.returncode == 3
    assert "allowed transition table" in released.stderr


def _add_frontmatter(path, extra):
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("priority: 5\n", "priority: 5\n" + extra, 1), encoding="utf-8")


def _frontmatter(path):
    return COORD_MODULE["parse_task"](path)[0]


def _reject(coord_repo, task_id="sample-needs-review"):
    result = coord_repo.coord("update", task_id, "--status=review-failed")
    assert result.returncode == 0, result.stderr


def test_review_failed_within_review_rounds_max_returns_to_coder(coord_repo):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, "roles:\n  coder: codex\n  reviewer: claude\nreview_rounds_max: 2\n")

    _reject(coord_repo)

    fm = _frontmatter(path)
    assert (fm["status"], fm["assigned"], fm["review_round"]) == ("pending", "codex", 1)
    assert "pickup_hold" not in fm


def test_review_failed_at_review_rounds_max_parks_on_hold(coord_repo):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, "roles:\n  coder: codex\n  reviewer: claude\nreview_rounds_max: 2\nreview_round: 1\n")

    _reject(coord_repo)

    fm, body = COORD_MODULE["parse_task"](path)
    assert (fm["status"], fm["assigned"], fm["review_round"]) == ("needs-brainstorming", "codex", 2)
    assert fm["pickup_hold"] is True
    assert "review_rounds_max=2 reached" in COORD_MODULE["get_section"](body, "Open issues")


def test_review_rounds_max_absent_keeps_cross_side_loop_uncapped(coord_repo):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, "roles:\n  coder: codex\n  reviewer: claude\n")

    _reject(coord_repo)

    assert _frontmatter(path)["status"] != "needs-brainstorming"


@pytest.mark.parametrize("extra", [
    "",
    "roles:\n  reviewer: claude\n",
    "roles:\n  coder: claude\n  reviewer: claude\nreview_rounds_max: 1\n",
])
def test_review_failed_without_a_cross_side_cap_keeps_looping(coord_repo, extra):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, extra + "review_round: 5\n")

    _reject(coord_repo)

    fm = _frontmatter(path)
    assert fm["status"] == "pending"
    assert fm["review_round"] == 6


def test_review_rounds_max_raised_in_the_same_call_applies(coord_repo):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, "roles:\n  coder: codex\n  reviewer: claude\nreview_rounds_max: 1\n")

    result = coord_repo.coord("update", "sample-needs-review", "--status=review-failed", "--review-rounds-max=3")

    assert result.returncode == 0, result.stderr
    assert _frontmatter(path)["status"] == "pending"


def test_needs_review_without_assigned_goes_to_roles_reviewer(coord_repo):
    path = coord_repo.tasks["claude-working"]
    _add_frontmatter(path, "roles:\n  coder: claude\n  reviewer: codex\n")

    result = coord_repo.coord("update", "sample-claude-working", "--status=needs-review")

    assert result.returncode == 0, result.stderr
    assert _frontmatter(path)["assigned"] == "codex"


def test_needs_review_to_needs_review_keeps_a_manual_reassignment(coord_repo):
    path = coord_repo.tasks["needs-review"]
    _add_frontmatter(path, "roles:\n  coder: claude\n  reviewer: codex\n")
    assert coord_repo.coord("update", "sample-needs-review", "--assigned=claude").returncode == 0

    result = coord_repo.coord("update", "sample-needs-review", "--status=needs-review")

    assert result.returncode == 0, result.stderr
    assert _frontmatter(path)["assigned"] == "claude"


@pytest.mark.parametrize("extra", ["", "roles:\n  coder: claude\n  reviewer: skip\n"])
def test_needs_review_without_a_reviewer_role_keeps_assigned(coord_repo, extra):
    path = coord_repo.tasks["claude-working"]
    _add_frontmatter(path, extra)

    result = coord_repo.coord("update", "sample-claude-working", "--status=needs-review")

    assert result.returncode == 0, result.stderr
    assert _frontmatter(path)["assigned"] == "claude"
