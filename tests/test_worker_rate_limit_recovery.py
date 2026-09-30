import os
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"


def function_source(name):
    lines = WORKER.read_text(encoding="utf-8").splitlines()
    start = None
    collected = []
    for line in lines:
        if start is None and line.startswith(f"{name}() {{"):
            start = True
        if start:
            collected.append(line)
            if line == "}":
                break
    assert collected and collected[-1] == "}", f"{name} not found"
    return "\n".join(collected) + "\n"


def run_restore(repo, task_id, orig_status="", orig_assigned=""):
    log = repo.root / ".coord" / "restore-rate-limit-test.log"
    env = os.environ.copy()
    env.update({
        "COORD_TASKS_DIR": "tasks",
        "COORD_ARCHIVE_DIR": "tasks/archive",
        "COORD_FINDINGS_DIR": "tasks/findings",
        "COORD_CHANGES_FILE": "tasks/CHANGES.md",
    })
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={ROOT}\n"
        f"LOG={log}\n"
        f"ID={task_id}\n"
        f"ORIG_STATUS={orig_status}\n"
        f"ORIG_ASSIGNED={orig_assigned}\n"
        "ts() { echo TS; }\n"
        + function_source("restore_rate_limited_task")
        + "restore_rate_limited_task\n"
    )
    return subprocess.run(
        ["bash", "-c", driver],
        cwd=repo.root,
        env=env,
        text=True,
        capture_output=True,
    )


def test_restore_rate_limited_working_task_to_original_runnable_status(coord_repo):
    result = run_restore(
        coord_repo,
        "sample-codex-working",
        orig_status="pending",
        orig_assigned="codex",
    )

    assert result.returncode == 0, result.stderr
    shown = coord_repo.coord("show", "sample-codex-working")
    assert "status: pending" in shown.stdout
    assert "assigned: codex" in shown.stdout


def test_restore_rate_limited_working_task_requires_original_state(coord_repo):
    result = run_restore(coord_repo, "sample-codex-working")

    assert result.returncode == 1
    shown = coord_repo.coord("show", "sample-codex-working")
    assert "status: codex-working" in shown.stdout


def test_restore_rate_limited_empty_status_fails_closed(coord_repo):
    result = run_restore(
        coord_repo,
        "missing-task",
        orig_status="pending",
        orig_assigned="codex",
    )

    assert result.returncode == 1
    log = (coord_repo.root / ".coord" / "restore-rate-limit-test.log").read_text(encoding="utf-8")
    assert "current status unreadable" in log


def test_restore_rate_limited_claude_task_keeps_original_role(coord_repo):
    result = run_restore(
        coord_repo,
        "sample-claude-working",
        orig_status="needs-review",
        orig_assigned="claude",
    )

    assert result.returncode == 0, result.stderr
    shown = coord_repo.coord("show", "sample-claude-working")
    assert "status: needs-review" in shown.stdout
    assert "assigned: claude" in shown.stdout


def run_cooldown_driver(tmp_path, command, claude_task="", codex_task=""):
    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    (tools / "bin" / "coord").write_text(
        """import json
import os
import sys

agent = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--assigned=")), "")
task_id = os.environ.get(f"FAKE_{agent.upper()}_TASK", "")
if task_id:
    print(json.dumps({"decision": "run", "pickup": {"id": task_id}}))
else:
    print(json.dumps({"decision": "skip"}))
""",
        encoding="utf-8",
    )
    (tmp_path / ".coord").mkdir(exist_ok=True)
    log = tmp_path / ".coord" / "cooldown-test.log"
    env = os.environ.copy()
    env.update({
        "FAKE_CLAUDE_TASK": claude_task,
        "FAKE_CODEX_TASK": codex_task,
    })
    functions = "".join(
        function_source(name)
        for name in (
            "rate_limit_marker_active",
            "all_agents_rate_limited",
            "pickup_id_from_json",
            "select_runnable_task",
        )
    )
    driver = (
        "set -euo pipefail\n"
        f"TOOLS={tools}\n"
        f"LOG={log}\n"
        "ts() { echo TS; }\n"
        + functions
        + command
        + "\n"
    )
    return subprocess.run(
        ["bash", "-c", driver],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )


def test_claude_cooldown_routes_already_assigned_codex_work(tmp_path):
    future = int(time.time()) + 3600
    coord = tmp_path / ".coord"
    coord.mkdir()
    (coord / "sleep-until.claude").write_text(f"{future}\n", encoding="utf-8")

    result = run_cooldown_driver(
        tmp_path,
        'select_runnable_task; printf "%s|%s\\n" "$AGENT" "$ID"',
        claude_task="claude-task",
        codex_task="codex-task",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "codex|codex-task"
    assert (coord / "sleep-until.claude").exists()
    assert not (coord / "sleep-until.codex").exists()


def test_codex_cooldown_does_not_block_already_assigned_claude_work(tmp_path):
    future = int(time.time()) + 3600
    coord = tmp_path / ".coord"
    coord.mkdir()
    (coord / "sleep-until.codex").write_text(f"{future}\n", encoding="utf-8")

    result = run_cooldown_driver(
        tmp_path,
        'select_runnable_task; printf "%s|%s\\n" "$AGENT" "$ID"',
        claude_task="claude-task",
        codex_task="codex-task",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "claude|claude-task"
    assert (coord / "sleep-until.codex").exists()
    assert not (coord / "sleep-until.claude").exists()


def test_worker_stops_cheaply_when_both_provider_cooldowns_are_active(tmp_path):
    future = int(time.time()) + 3600
    coord = tmp_path / ".coord"
    coord.mkdir()
    (coord / "sleep-until.claude").write_text(f"{future}\n", encoding="utf-8")
    (coord / "sleep-until.codex").write_text(f"{future}\n", encoding="utf-8")

    result = run_cooldown_driver(
        tmp_path,
        'if all_agents_rate_limited; then printf "both-active\\n"; else exit 3; fi',
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "both-active"


def test_expired_agent_marker_is_removed(tmp_path):
    expired = int(time.time()) - 60
    coord = tmp_path / ".coord"
    coord.mkdir()
    (coord / "sleep-until.claude").write_text(f"{expired}\n", encoding="utf-8")

    result = run_cooldown_driver(tmp_path, "! rate_limit_marker_active claude")

    assert result.returncode == 0, result.stderr
    assert not list(coord.glob("sleep-until*"))
