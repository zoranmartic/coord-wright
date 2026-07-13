import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"


def restore_function_source():
    lines = WORKER.read_text(encoding="utf-8").splitlines()
    start = None
    collected = []
    for line in lines:
        if start is None and line.startswith("restore_rate_limited_task() {"):
            start = True
        if start:
            collected.append(line)
            if line == "}":
                break
    assert collected and collected[-1] == "}", "restore_rate_limited_task not found"
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
        + restore_function_source()
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
