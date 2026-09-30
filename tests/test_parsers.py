import re
import runpy
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_parsers")
STATUS_ROUTING = COORD_MODULE["STATUS_ROUTING"]
complete_subtask_in_scope = COORD_MODULE["complete_subtask_in_scope"]
parse_task = COORD_MODULE["parse_task"]
write_task = COORD_MODULE["write_task"]
validate_subtask_shape = COORD_MODULE["validate_subtask_shape"]
as_list = COORD_MODULE["as_list"]
validate_runnable_shape = COORD_MODULE["validate_runnable_shape"]


@pytest.mark.parametrize("status", sorted(STATUS_ROUTING))
def test_frontmatter_parse_write_parse_is_stable_for_each_status(coord_repo, status):
    path = coord_repo.tasks[status]
    fm_before, body_before = parse_task(path)
    write_task(path, dict(fm_before), body_before)

    fm_after, body_after = parse_task(path)

    assert body_after == body_before
    for key, value in fm_before.items():
        if key == "updated":
            continue
        assert fm_after[key] == value
    assert fm_after["updated"]


def test_double_quoted_unicode_escape_frontmatter_is_stable(tmp_path):
    path = tmp_path / "unicode-title.md"
    path.write_text(
        textwrap.dedent("""\
            ---
            id: unicode-title
            task: "T13: V1 /ops simplification \\u2014 rewrite api/ops-metrics"
            status: pending
            assigned: codex
            ---
            Body.
            """),
        encoding="utf-8",
    )

    for _ in range(4):
        fm, body = parse_task(path)
        assert fm["task"] == "T13: V1 /ops simplification \u2014 rewrite api/ops-metrics"
        write_task(path, fm, body)

    task_line = next(line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("task:"))
    assert task_line.count("\\") == 1


def test_frontmatter_lists_preserve_scalars_and_parse_flow_lists(tmp_path):
    path = tmp_path / "lists.md"
    path.write_text(
        "---\n"
        "depends_on:\n"
        "- true\n"
        "- false\n"
        "- null\n"
        "- 17\n"
        "- [ -f x ]\n"
        "- \"quoted\"\n"
        "- 'single quoted'\n"
        "- \"bad\\q\"\n"
        "tags: [dependency, \"x, y\", 'true']\n"
        "verify_command: [ -f x ]\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )

    fm, body = parse_task(path)

    assert fm["depends_on"] == ["true", "false", "null", "17", "[ -f x ]", '"quoted"', "'single quoted'", '"bad\\q"']
    assert fm["tags"] == ["dependency", '"x, y"', "'true'"]
    assert fm["verify_command"] == "[ -f x ]"
    write_task(path, fm, body)
    parsed, _ = parse_task(path)
    assert parsed["depends_on"] == fm["depends_on"]
    assert parsed["tags"] == fm["tags"]
    assert not any(line.endswith(" ") for line in path.read_text(encoding="utf-8").splitlines())


def test_flow_list_parsing_is_limited_to_list_keys(tmp_path):
    path = tmp_path / "flow.md"
    path.write_text(
        "---\n"
        "task: [P1] a, b [x]\n"
        "tags: [a, , b,]\n"
        "---\n"
        "Body.\n",
        encoding="utf-8",
    )

    fm, body = parse_task(path)

    assert fm["task"] == "[P1] a, b [x]"
    assert fm["tags"] == ["a", "b"]
    write_task(path, fm, body)
    assert parse_task(path)[0]["task"] == "[P1] a, b [x]"


def test_malformed_double_quoted_top_level_value_drops_its_quotes(tmp_path):
    path = tmp_path / "bad-quote.md"
    path.write_text('---\ntask: "bad\\q"\nroles:\n  coder: "x\\q"\n---\nBody.\n', encoding="utf-8")

    fm, body = parse_task(path)

    assert fm["task"] == "bad\\q"
    assert fm["roles"] == {"coder": "x\\q"}
    write_task(path, fm, body)
    assert "task: bad\\q\n" in path.read_text(encoding="utf-8")


def test_empty_and_multiline_list_items_round_trip(tmp_path):
    path = tmp_path / "items.md"
    path.write_text('---\ntags: [a, "", b]\n---\nBody.\n', encoding="utf-8")
    fm, body = parse_task(path)
    assert fm["tags"] == ["a", "", "b"]

    fm["verify_commands"] = ["", "line one\nline two", "cr\ronly", '"kept quoted"']
    write_task(path, fm, body)
    text = path.read_text(encoding="utf-8")
    assert '  - ""\n' in text
    assert '  - "line one\\nline two"\n' in text

    parsed, _ = parse_task(path)
    assert parsed["tags"] == ["a", "", "b"]
    assert parsed["verify_commands"] == fm["verify_commands"]
    write_task(path, parsed, body)
    assert parse_task(path)[0]["verify_commands"] == fm["verify_commands"]


def test_scalar_list_items_are_written_bare(tmp_path):
    path = tmp_path / "scalars.md"
    write_task(path, {"id": "scalars", "scope": [17, -3, True, False, None]}, "Body.\n")

    text = path.read_text(encoding="utf-8")

    assert "scope:\n  - 17\n  - -3\n  - true\n  - false\n  - null\n" in text
    assert parse_task(path)[0]["scope"] == ["17", "-3", "true", "false", "null"]


def test_frontmatter_list_writes_keep_existing_command_and_mapping_forms(tmp_path, monkeypatch):
    path = tmp_path / "stable.md"
    original = (
        "---\n"
        "id: stable\n"
        "task: Stable\n"
        "status: pending\n"
        "assigned: codex\n"
        "verify_commands:\n"
        "  - python3 -c \"print(1,2)\"\n"
        "  - [ -f x ]\n"
        "  - `command`\n"
        "updated: 2026-09-30T01:00:00+0100\n"
        "scope_budget:\n"
        "  abort_if_exceeded_by_pct: 50\n"
        "---\n"
        "Body.\n"
    )
    path.write_text(original, encoding="utf-8")
    monkeypatch.setitem(write_task.__globals__, "_now", lambda: "2026-09-30T01:00:00+0100")

    fm, body = parse_task(path)
    write_task(path, fm, body)

    assert path.read_text(encoding="utf-8") == original



def test_now_uses_coord_tz_with_numeric_offset(monkeypatch):
    now = COORD_MODULE["_now"]
    monkeypatch.setenv("COORD_TZ", "Asia/Kolkata")
    assert now().endswith("+0530")
    monkeypatch.delenv("COORD_TZ")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d{4}", now())

def test_list_flags_accept_json_items_with_commas():
    assert as_list('["python3 -c \\"print(1,2)\\"", "git diff --check"]') == [
        'python3 -c "print(1,2)"',
        "git diff --check",
    ]
    assert as_list("first item, second item") == ["first item", "second item"]


@pytest.mark.parametrize("field", ["round", "max_seconds"])
def test_runnable_shape_rejects_non_integer_numeric_frontmatter(field):
    fm = {
        "status": "pending",
        "complexity": "simple",
        "kind": "code-fix",
        "reasoning_effort": "medium",
        field: "not-a-number",
    }

    errors = validate_runnable_shape(fm, "## Plan\nConcrete plan.\n\n## Acceptance test\nConcrete acceptance.\n")

    assert f"{field} must be an integer" in errors


def test_complete_subtask_in_scope_marks_only_target_subtask():
    scope = textwrap.dedent("""\
        Intro text.

        - [ ] **S1: First**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          First body.

        - [ ] **S2: Second**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Second body.
        """)

    updated = complete_subtask_in_scope(scope, "S1")

    assert "- [x] **S1: First**" in updated
    assert "- [ ] **S2: Second**" in updated
    assert updated.count("- [x]") == 1


@pytest.mark.parametrize(
    ("subtask_id", "expected"),
    [
        ("", "expected S<n>"),
        ("1", "expected S<n>"),
        ("S9", "S9 is not an incomplete subtask"),
    ],
)
def test_complete_subtask_in_scope_rejects_invalid_targets(subtask_id, expected):
    with pytest.raises(ValueError) as exc:
        complete_subtask_in_scope("- [ ] **S1: First**\n  body\n", subtask_id)

    assert expected in str(exc.value)


def test_set_subtasks_replaces_existing_checklist(coord_repo):
    subtasks = textwrap.dedent("""\
        - [ ] **S1: Replacement**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Replace the existing fixture checklist.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
          Handoff to S2: shape and entry point of the replacement so S2 covers the second parser step against the same surface.

        - [ ] **S2: Follow-up**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Cover a second parser step.
          Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
          Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)
    shown = coord_repo.coord("show", "sample-shaping")

    assert result.returncode == 0, result.stderr
    assert "- [ ] **S1: Replacement**" in shown.stdout
    assert "- [ ] **S2: Follow-up**" in shown.stdout
    assert "Sample subtask" not in shown.stdout


def test_set_subtasks_rejects_yaml_style_fallback(coord_repo):
    yaml_style = textwrap.dedent("""\
        - title: Legacy fallback
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          body: Not accepted.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", yaml_style)

    assert result.returncode == 3
    assert "update --set-subtasks: invalid subtasks" in result.stderr
    assert "YAML-style subtask blocks are not allowed" in result.stderr
    assert "no parseable subtasks found" in result.stderr


def test_set_subtasks_rejects_missing_required_metadata(coord_repo):
    missing_meta = textwrap.dedent("""\
        - [ ] **S1: Missing metadata**
          complexity: simple
          model_codex: gpt-5.5
          Missing the Claude model metadata line.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", missing_meta)

    assert result.returncode == 3
    assert "S1: missing model_claude" in result.stderr


def test_validate_subtask_shape_ignores_handoff_to_line_when_counting_surfaces():
    # S1's work is purely frontend (Playwright); the shaper-prescribed
    # `Handoff to S2:` line mentions S2's README work (docs surface). The
    # validator must scrub the Handoff to S<N+1> line before classifying
    # surfaces, otherwise every multi-subtask shape with the new sentence
    # would falsely flag "mixes major surfaces".
    body = textwrap.dedent("""\
          Add Playwright config and write tests/smoke/admin.spec.ts asserting the SPA shell loads.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
          Handoff to S2: README runbook references the playwright config path and the npm script name.
        """)

    warnings = validate_subtask_shape("S1: Playwright smoke harness", body)

    assert not any("mixes major surfaces" in w for w in warnings), warnings


def test_validate_subtask_shape_still_flags_real_surface_mix():
    # Without the Handoff to line, a body that genuinely mixes frontend
    # (Playwright) and docs (README) work should still be flagged. This locks
    # in that the scrub only removes the prescribed-handoff sentence, not
    # legitimate surface signals elsewhere.
    body = textwrap.dedent("""\
          Add Playwright config and write the README runbook for the admin surface.
        """)

    warnings = validate_subtask_shape("S1: harness and docs", body)

    assert any("mixes major surfaces" in w for w in warnings), warnings


def test_validate_subtask_shape_excludes_handoff_policy_lines_from_length_budget():
    # The three handoff-policy lines (Reads handoff / Writes handoff /
    # Handoff to S<N+1>) add ~250 chars of boilerplate per subtask. They
    # must not count toward the 900-char work budget, otherwise every
    # subtask shaped to the new convention loses meaningful work room.
    work_paragraph = "Add a focused implementation paragraph " * 18  # ~720 chars
    body = (
        f"  {work_paragraph}\n"
        "  Reads handoff: `.coord/handoffs/<task-id>/S0.md`.\n"
        "  Writes handoff: `.coord/handoffs/<task-id>/S1.md`.\n"
        "  Handoff to S2: pass the API signature, the test fixture path, "
        "and the chosen retry budget so S2 can wire the consumer without "
        "re-discovering the contract.\n"
    )

    warnings = validate_subtask_shape("S1: focused implementation", body)

    # The work paragraph is comfortably under 900 chars on its own; the
    # combined text including handoff boilerplate would exceed it.
    assert not any("too long" in w for w in warnings), warnings


def test_validate_subtask_shape_still_flags_truly_long_subtask():
    # Conversely, a subtask whose actual work paragraph exceeds 900 chars
    # (ignoring handoff boilerplate) should still be rejected.
    work_paragraph = "Implement a meaningful slice of the feature surface. " * 20
    body = (
        f"  {work_paragraph}\n"
        "  Writes handoff: `.coord/handoffs/<task-id>/S1.md`.\n"
    )

    warnings = validate_subtask_shape("S1: oversized work", body)

    assert any("too long" in w for w in warnings), warnings


def test_set_subtasks_rejects_missing_writes_handoff_on_s1(coord_repo):
    # agent-workflow-policy.md rule 6: every subtask MUST carry a
    # `Writes handoff:` line. The runtime --complete-subtask gate already
    # enforces the file's existence; this is the shape-time twin so the
    # missing scope-notes line is caught before any worker runs.
    subtasks = textwrap.dedent("""\
        - [ ] **S1: Lone subtask**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body but no handoff line.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)

    assert result.returncode == 3
    assert "S1: missing `Writes handoff:" in result.stderr


def test_set_subtasks_rejects_missing_reads_handoff_on_s2(coord_repo):
    subtasks = textwrap.dedent("""\
        - [ ] **S1: First**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
          Handoff to S2: artifact name so S2 picks up cleanly.

        - [ ] **S2: Second**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body without Reads handoff.
          Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)

    assert result.returncode == 3
    assert "S2: missing `Reads handoff:" in result.stderr


def test_set_subtasks_rejects_missing_handoff_to_next_on_non_final_subtask(coord_repo):
    subtasks = textwrap.dedent("""\
        - [ ] **S1: First**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body without Handoff-to-S2 sentence.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.

        - [ ] **S2: Second**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
          Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)

    assert result.returncode == 3
    assert "S1: missing `Handoff to S2:" in result.stderr


def test_set_subtasks_accepts_single_subtask_with_writes_handoff_only(coord_repo):
    # Single-subtask tasks need only `Writes handoff:`; no Reads (no
    # predecessor) and no `Handoff to S2:` (no successor).
    subtasks = textwrap.dedent("""\
        - [ ] **S1: Lone**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)

    assert result.returncode == 0, result.stderr


def test_set_subtasks_accepts_three_subtask_chain_with_all_handoff_lines(coord_repo):
    # Middle subtask carries Reads + Writes + Handoff-to. Last subtask omits
    # the Handoff-to line.
    subtasks = textwrap.dedent("""\
        - [ ] **S1: First**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
          Handoff to S2: artifact name and entry point.

        - [ ] **S2: Middle**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
          Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
          Handoff to S3: artifact name and entry point.

        - [ ] **S3: Last**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Body.
          Reads handoff: `.coord/handoffs/<task-id>/S2.md`.
          Writes handoff: `.coord/handoffs/<task-id>/S3.md`.
        """)

    result = coord_repo.coord("update", "sample-shaping", "--set-subtasks", subtasks)

    assert result.returncode == 0, result.stderr
