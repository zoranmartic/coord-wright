import os
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"
TASK_ID = "coder-close-gate"


def function_source(name):
    lines = WORKER.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}\n")
    return "".join(lines[start : end + 1])


def source_block(start_marker, end_marker):
    source = WORKER.read_text(encoding="utf-8")
    start = source.index(start_marker)
    end = source.index(end_marker, start)
    return source[start:end]


def fake_python3(tmp_path, failed_updates=1):
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    counter = tmp_path / "coord-update-count"
    (fake_bin / "python3").write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            if [[ "$1" == "{ROOT / 'bin' / 'coord'}" && "$2" == update ]]; then
              count=0
              [[ -f "{counter}" ]] && count=$(<"{counter}")
              if (( count < {failed_updates} )); then
                echo $((count + 1)) > "{counter}"
                exit 1
              fi
            fi
            exec "{os.sys.executable}" "$@"
            """
        ),
        encoding="utf-8",
    )
    (fake_bin / "python3").chmod(0o755)
    return fake_bin


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_done_coder_task(tmp_path, model_claude="sonnet"):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Coord Test")
    archive = repo / "tasks" / "archive"
    archive.mkdir(parents=True)
    (archive / f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            ---
            id: {TASK_ID}
            task: Coder close mechanical gate fixture
            status: done
            assigned: codex
            complexity: simple
            kind: bugfix
            reasoning_effort: medium
            model_claude: {model_claude}
            round: 1
            created: 2026-07-23T00:00:00+0100
            updated: 2026-07-23T00:00:00+0100
            scope:
              - fixture
            verify_commands:
              - false
            ---

            ## Scope notes

            - [x] **S1: Close fixture**
              complexity: simple
              model_claude: {model_claude}
              model_codex: gpt-5.6-sol
              Exercise the terminal close.
              Writes handoff: `.coord/handoffs/<task-id>/S1.md`

            ## Codex findings

            ## Open issues

            ## Plan

            Fixture.

            ## Acceptance test

            Fixture.
            """
        ),
        encoding="utf-8",
    )
    git(repo, "add", ".")
    git(repo, "commit", "-m", "seed done coder task")
    git(repo, "branch", "-M", "main")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")
    return repo


def test_max_turns_done_close_runs_guards(tmp_path):
    repo = init_done_coder_task(tmp_path)
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir()
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={TASK_ID}\n"
        f"TASK_PATH={repo / 'tasks' / f'{TASK_ID}.md'}\n"
        'ROUND_ROLE="coder"\n'
        'AGENT="codex"\n'
        'ROUND_TIMEOUT_SECONDS=""\n'
        'TIMEOUT_CMD=""\n'
        'ts() { echo TS; }\n'
        'structured_current_round_verdict() { return 1; }\n'
        + "".join(
            function_source(name)
            for name in (
                "mktemp_suffix",
                "run_with_timeout",
                "mech_verify_tree",
                "mechanical_verify_gate",
                "mech_verify_restore_dirt",
            )
        )
        + 'MECH_VERIFY_ISSUE=""\n'
        + 'MECH_PRE_TRACKED_COMMIT=""\n'
        + "MECH_VERIFY_RESTORED=0\n"
        + function_source("park_failed_demote")
        + function_source("run_close_guards")
        + function_source("handle_max_turns_done_close")
        + 'MAX_TURNS_TERMINAL="max_turns"\n'
        + 'ROUND_TIMEOUT_TERMINAL=0\n'
        + 'ORIG_STATUS="pending"\n'
        + 'ORIG_ASSIGNED="codex"\n'
        + source_block(
            "  # Auto-requeue once on max-turns",
            "  # A closing agent can update the task to done",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
            "PATH": f"{fake_python3(tmp_path)}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["/bin/bash", "-c", driver],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    text = log.read_text(encoding="utf-8")
    assert "mechanical verify gate: 'false' exited rc=1" in text
    assert (
        f"mechanical verify gate failed after coder close; demoting {TASK_ID} "
        "to review-failed"
    ) in text
    assert "mechanical verify demote failed; attempting second-chance park" in text
    assert f"second-chance park succeeded for {TASK_ID}" in text
    shown = subprocess.run(
        ["python3", str(ROOT / "bin" / "coord"), "show", TASK_ID, "--compact"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "status: needs-brainstorming" in shown
    assert "pickup_hold: true" in shown
    assert "mechanical verify gate: 'false' exited rc=1" in shown
    assert "forced review-failed demote also failed" in shown


def test_trailing_failure_close_continues_when_demote_and_park_fail(tmp_path):
    repo = init_done_coder_task(tmp_path)
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir()
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={TASK_ID}\n"
        f"TASK_PATH={repo / 'tasks' / f'{TASK_ID}.md'}\n"
        'ROUND_ROLE="coder"\n'
        'AGENT="codex"\n'
        'ROUND_TIMEOUT_SECONDS=""\n'
        'TIMEOUT_CMD=""\n'
        'ts() { echo TS; }\n'
        'structured_current_round_verdict() { return 1; }\n'
        + "".join(
            function_source(name)
            for name in (
                "mktemp_suffix",
                "run_with_timeout",
                "mech_verify_tree",
                "mechanical_verify_gate",
                "mech_verify_restore_dirt",
            )
        )
        + 'MECH_VERIFY_ISSUE=""\n'
        + 'MECH_PRE_TRACKED_COMMIT=""\n'
        + "MECH_VERIFY_RESTORED=0\n"
        + function_source("park_failed_demote")
        + function_source("run_close_guards")
        + function_source("handle_failed_round_done_close")
        + source_block(
            "  # A closing agent can update the task to done",
            "  FINDING_FLAG=",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
            "PATH": f"{fake_python3(tmp_path, failed_updates=2)}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["/bin/bash", "-c", driver], cwd=repo, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    text = log.read_text(encoding="utf-8")
    assert "mechanical verify demote failed; attempting second-chance park" in text
    assert "second-chance park update failed" in text


def test_mechanical_gate_runs_later_command_after_stdin_reader(tmp_path):
    repo = init_done_coder_task(tmp_path)
    task_file = repo / "tasks" / "archive" / f"{TASK_ID}.md"
    task_file.write_text(
        task_file.read_text(encoding="utf-8").replace(
            "- false", "- read -r ignored || true\n              - exit 7"
        ),
        encoding="utf-8",
    )
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir()
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={TASK_ID}\n"
        f"TASK_PATH={task_file}\n"
        'ROUND_TIMEOUT_SECONDS=""\n'
        'TIMEOUT_CMD=""\n'
        'ts() { echo TS; }\n'
        + "".join(
            function_source(name)
            for name in (
                "mktemp_suffix",
                "run_with_timeout",
                "mech_verify_tree",
                "mechanical_verify_gate",
                "mech_verify_restore_dirt",
            )
        )
        + 'MECH_VERIFY_ISSUE=""\n'
        + 'MECH_PRE_TRACKED_COMMIT=""\n'
        + "MECH_VERIFY_RESTORED=0\n"
        + "if mechanical_verify_gate \"$TASK_PATH\"; then exit 1; fi\n"
    )

    result = subprocess.run(
        ["bash", "-c", driver], cwd=repo, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "mechanical verify gate: 'exit 7' exited rc=7" in log.read_text(
        encoding="utf-8"
    )


def test_failed_false_approve_demote_parks_done_task(tmp_path):
    repo = init_done_coder_task(tmp_path)
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir()
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={TASK_ID}\n"
        f"TASK_PATH={repo / 'tasks' / f'{TASK_ID}.md'}\n"
        'ROUND_ROLE="reviewer"\n'
        'AGENT="codex"\n'
        'ts() { echo TS; }\n'
        'structured_current_round_verdict() { return 0; }\n'
        + function_source("park_failed_demote")
        + function_source("run_close_guards")
        + "run_close_guards\n"
    )
    env = os.environ.copy()
    env.update(
        {
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
            "PATH": f"{fake_python3(tmp_path)}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["/bin/bash", "-c", driver], cwd=repo, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    text = log.read_text(encoding="utf-8")
    assert "false-approve guard demote failed; attempting second-chance park" in text
    assert f"second-chance park succeeded for {TASK_ID}" in text
    shown = subprocess.run(
        ["python3", str(ROOT / "bin" / "coord"), "show", TASK_ID, "--compact"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "status: needs-brainstorming" in shown
    assert "pickup_hold: true" in shown
    assert "reviewer finding for this round says REJECT" in shown
    assert "forced review-failed demote also failed" in shown


def test_off_baseline_failed_demote_parks_with_hold_and_continues(tmp_path):
    # simple + opus is off-baseline and the fixture has no `started:`, so a
    # non-forced follow-up update after the park would be rejected.
    repo = init_done_coder_task(tmp_path, model_claude="opus")
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir()
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={TASK_ID}\n"
        f"TASK_PATH={repo / 'tasks' / f'{TASK_ID}.md'}\n"
        'ROUND_ROLE="reviewer"\n'
        'AGENT="codex"\n'
        'ts() { echo TS; }\n'
        'structured_current_round_verdict() { return 0; }\n'
        + function_source("park_failed_demote")
        + function_source("run_close_guards")
        + "run_close_guards\n"
        + "echo worker-continued\n"
    )
    env = os.environ.copy()
    env.update(
        {
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
            "PATH": f"{fake_python3(tmp_path)}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        ["/bin/bash", "-c", driver], cwd=repo, env=env, text=True, capture_output=True
    )

    assert result.returncode == 0, result.stderr
    assert "worker-continued" in result.stdout
    text = log.read_text(encoding="utf-8")
    assert "off-baseline" in text
    assert f"second-chance park succeeded for {TASK_ID}" in text
    shown = subprocess.run(
        ["python3", str(ROOT / "bin" / "coord"), "show", TASK_ID, "--compact"],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "status: needs-brainstorming" in shown
    assert "pickup_hold: true" in shown
    assert "forced review-failed demote also failed" in shown
