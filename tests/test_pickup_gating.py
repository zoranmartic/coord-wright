import json
import runpy
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_pickup_gating")
content_hash = COORD_MODULE["content_hash"]
dependency_blockers = COORD_MODULE["dependency_blockers"]
parse_task = COORD_MODULE["parse_task"]
write_task = COORD_MODULE["write_task"]
validate_runnable_shape = COORD_MODULE["validate_runnable_shape"]


def _set_content_hash(path, agent="codex", value="stored-hash"):
    fm, body = parse_task(path)
    fm[f"content_hash_{agent}"] = value
    write_task(path, fm, body)


def _write_pending_task(repo, task_id, title):
    path = repo.root / "tasks" / f"{task_id}.md"
    path.write_text(
        textwrap.dedent(f"""\
            ---
            id: {task_id}
            task: {title}
            status: pending
            assigned: codex
            complexity: simple
            kind: code-fix
            reasoning_effort: medium
            round: 1
            created: 2026-05-17T00:00:00+0100
            updated: 2026-05-17T00:00:00+0100
            scope:
              - pickup fixture
            tags:
              - fixture
            priority: 5
            max_turns: 3
            ---
            ## Task parameters

            ## Scope notes

            - [ ] **S1: Pickup fixture**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Fixture body.

            ## Plan
            Fixture plan.

            ## Acceptance test
            Fixture acceptance.
            """),
        encoding="utf-8",
    )
    return path


def _valid_subtasks():
    return textwrap.dedent("""\
        - [ ] **S1: Release fixture**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Run the focused release fixture.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
        """)


def test_content_hash_ignores_volatile_frontmatter_fields():
    body = "## Scope notes\n\nFixture body.\n"
    fm = {
        "id": "hash-fixture",
        "task": "Hash fixture",
        "status": "pending",
        "assigned": "codex",
        "round": 1,
        "updated": "2026-05-17T00:00:00+0100",
        "content_hash_codex": "old",
        "token_log": ["R1:S1:codex:1:2:3:4:0"],
    }
    volatile_changed = {
        **fm,
        "round": 9,
        "updated": "2026-05-17T01:00:00+0100",
        "content_hash_codex": "new",
        "token_log": ["R9:S1:codex:9:9:9:9:0"],
    }
    meaningful_changed = {**fm, "assigned": "claude"}

    assert content_hash(fm, body) == content_hash(volatile_changed, body)
    assert content_hash(fm, body) != content_hash(meaningful_changed, body)
    assert content_hash(fm, body) != content_hash(fm, body + "changed\n")


def test_dependency_blockers_reports_unfinished_and_missing_dependencies(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    blockers = dependency_blockers({
        "depends_on": ["sample-done", "sample-pending", "missing-dependency"],
    })

    assert blockers == [
        {"id": "sample-pending", "status": "pending"},
        {"id": "missing-dependency", "status": "missing"},
    ]


def test_pickup_returns_lexicographically_first_runnable_task(coord_repo):
    _write_pending_task(coord_repo, "zzz-priority", "Later pickup task")
    _write_pending_task(coord_repo, "aaa-priority", "Earlier pickup task")

    result = coord_repo.coord("pickup", "--assigned=codex")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "run"
    assert payload["task"]["id"] == "aaa-priority"


def test_pickup_prefers_lower_priority_number_over_name(coord_repo):
    _write_pending_task(coord_repo, "aaa-low-urgency", "Alphabetically first, low urgency")
    _write_pending_task(coord_repo, "zzz-chain-gate", "Alphabetically last, high urgency")
    for task_id, prio in (("aaa-low-urgency", 9), ("zzz-chain-gate", 2)):
        path = coord_repo.root / "tasks" / f"{task_id}.md"
        fm, body = parse_task(path)
        fm["priority"] = prio
        write_task(path, fm, body)

    result = coord_repo.coord("pickup", "--assigned=codex")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "run"
    assert payload["task"]["id"] == "zzz-chain-gate"


def test_pickup_skips_unchanged_task_when_no_subtasks_remain(coord_repo):
    path = coord_repo.tasks["pending"]
    fm, body = parse_task(path)
    body = body.replace("- [ ] **S1:", "- [x] **S1:")
    write_task(path, fm, body)
    fm, body = parse_task(path)
    fm["content_hash_codex"] = content_hash(fm, body)
    write_task(path, fm, body)

    result = coord_repo.coord("pickup", "--assigned=codex", "--task-id=sample-pending")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload == {"decision": "skip", "reason": "no runnable task for codex"}


def test_pickup_runs_unchanged_task_when_subtasks_remain(coord_repo):
    path = coord_repo.tasks["pending"]
    fm, body = parse_task(path)
    fm["content_hash_codex"] = content_hash(fm, body)
    write_task(path, fm, body)

    result = coord_repo.coord("pickup", "--assigned=codex", "--task-id=sample-pending")
    payload = json.loads(result.stdout)

    assert result.returncode == 0
    assert payload["decision"] == "run"
    assert payload["task"]["id"] == "sample-pending"
    assert payload["stored_hash"] == payload["current_hash"]


def test_pending_to_pending_update_does_not_clear_content_hash(coord_repo):
    _set_content_hash(coord_repo.tasks["pending"])

    result = coord_repo.coord("update", "sample-pending", "--status=pending")
    shown = coord_repo.coord("show", "sample-pending")

    assert result.returncode == 0, result.stderr
    assert "content_hash_codex: stored-hash" in shown.stdout


def test_non_runnable_to_runnable_update_clears_content_hash(coord_repo):
    _set_content_hash(coord_repo.tasks["shaping"])

    result = coord_repo.coord("update", "sample-shaping", "--status=pending")
    shown = coord_repo.coord("show", "sample-shaping")

    assert result.returncode == 0, result.stderr
    assert "content_hash_codex:" not in shown.stdout


def test_pickup_skips_held_task(coord_repo):
    path = _write_pending_task(coord_repo, "held-pending", "Held pickup task")
    fm, body = parse_task(path)
    fm["pickup_hold"] = True
    write_task(path, fm, body)

    precheck = coord_repo.coord("precheck", "--assigned=codex")
    pickup = coord_repo.coord("pickup", "--assigned=codex", "--task-id=held-pending")
    payload = json.loads(pickup.stdout)

    assert "held-pending" not in precheck.stdout
    assert payload == {"decision": "skip", "reason": "no runnable task for codex"}


def test_release_clears_hold_and_makes_task_pickup_visible(coord_repo):
    result = coord_repo.coord(
        "new",
        "--task=Held release fixture",
        "--status=pending",
        "--hold",
        "--complexity=simple",
        "--kind=code-fix",
        "--reasoning-effort=medium",
        "--set-plan=Run the held release fixture.",
        "--acceptance=Release fixture is runnable.",
        f"--set-subtasks={_valid_subtasks()}",
    )
    task_id = result.stdout.strip().splitlines()[-1]

    held_pickup = coord_repo.coord("pickup", "--assigned=codex", f"--task-id={task_id}")
    assert json.loads(held_pickup.stdout)["decision"] == "skip"

    released = coord_repo.coord("release", task_id)
    pickup = coord_repo.coord("pickup", "--assigned=codex", f"--task-id={task_id}")
    payload = json.loads(pickup.stdout)
    shown = coord_repo.coord("show", task_id)

    assert released.returncode == 0, released.stderr
    assert payload["decision"] == "run"
    assert payload["pickup"]["id"] == task_id
    assert "pickup_hold:" not in shown.stdout


def test_release_validates_all_held_tasks_before_writing(coord_repo):
    result = coord_repo.coord(
        "new",
        "--task=Held invalid release fixture",
        "--status=pending",
        "--hold",
        "--complexity=simple",
        "--kind=code-fix",
        "--reasoning-effort=medium",
        "--acceptance=Done",
    )
    task_id = result.stdout.strip().splitlines()[-1]

    released = coord_repo.coord("release", task_id)
    shown = coord_repo.coord("show", task_id)

    assert released.returncode == 3
    assert "runnable task shape is incomplete" in released.stderr
    assert "pickup_hold: true" in shown.stdout


def test_office_artifact_gate_fires_when_pptx_in_plan_only():
    body = textwrap.dedent("""\
        ## Scope notes

        - [ ] **S1: Upgrade deck**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Upgrade the deck.

        ## Plan
        Rewrite docs/slides/Deck.pptx to add a new section.

        ## Acceptance test
        Deck renders correctly.
        """)
    fm = {
        "id": "office-plan-only",
        "task": "Upgrade presentation",
        "status": "pending",
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
        "assigned": "codex",
        "round": 1,
    }
    errors = validate_runnable_shape(fm, body)
    assert any("verify_profile: pptx-html" in e for e in errors), errors
    assert any("roles.reviewer" in e for e in errors), errors


def test_office_artifact_gate_fires_when_pptx_in_task_description():
    body = textwrap.dedent("""\
        ## Scope notes

        - [ ] **S1: Fix deck**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Fix the deck.

        ## Plan
        Apply edits.

        ## Acceptance test
        Done.
        """)
    fm = {
        "id": "office-task-desc",
        "task": "Update AWS_Setup.pptx with new architecture diagram",
        "status": "pending",
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
        "assigned": "codex",
        "round": 1,
    }
    errors = validate_runnable_shape(fm, body)
    assert any("verify_profile: pptx-html" in e for e in errors), errors
    assert any("roles.reviewer" in e for e in errors), errors


def test_office_artifact_gate_passes_when_profile_and_reviewer_set():
    body = textwrap.dedent("""\
        ## Scope notes

        - [ ] **S1: Upgrade deck**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Upgrade the deck.

        ## Plan
        Rewrite docs/slides/Deck.pptx to add a new section.

        ## Acceptance test
        Deck renders correctly.
        """)
    fm = {
        "id": "office-plan-valid",
        "task": "Upgrade presentation",
        "status": "pending",
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
        "assigned": "codex",
        "verify_profile": "pptx-html",
        "roles": {"coder": "codex", "reviewer": "claude"},
        "round": 1,
    }
    errors = validate_runnable_shape(fm, body)
    office_errors = [e for e in errors if "Office" in e]
    assert not office_errors, office_errors
