import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"
COMMIT_HELPER = ROOT / "bin" / "coord-commit-agent.sh"


def function_source(name):
    lines = WORKER.read_text(encoding="utf-8").splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{name}() {{"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}\n")
    return "".join(lines[start : end + 1])


def git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(tmp_path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--bare", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Coord Test")
    archive = repo / "tasks" / "archive"
    archive.mkdir(parents=True)
    (archive / "finished.md").write_text("status: done\n", encoding="utf-8")
    (repo / "source.py").write_text("value = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".coord/\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-m", "seed")
    git(repo, "branch", "-M", "main")
    git(repo, "remote", "add", "origin", str(origin))
    git(repo, "push", "-u", "origin", "main")
    return repo


def run_tick_start(repo):
    log = repo / ".coord" / "worker.log"
    log.parent.mkdir(exist_ok=True)
    driver = (
        "set -euo pipefail\n"
        f"LOG={log}\n"
        'ts() { echo "TS"; }\n'
        + f'source "{COMMIT_HELPER}"\n'
        + function_source("recover_interrupted_task_bookkeeping")
        + function_source("sync_clean_checkout")
        + 'select_runnable_task() { echo "pickup reached" >> "$LOG"; }\n'
        + "recover_interrupted_task_bookkeeping\n"
        + "sync_clean_checkout || exit 0\n"
        + "select_runnable_task\n"
    )
    env = os.environ.copy()
    env["COORD_TASKS_DIR"] = "tasks"
    result = subprocess.run(
        ["bash", "-c", driver],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
    )
    return result, log.read_text(encoding="utf-8")


def test_staged_archive_only_dirt_recovers_and_proceeds_to_pickup(tmp_path):
    repo = init_repo(tmp_path)
    archive_task = repo / "tasks" / "archive" / "finished.md"
    archive_task.write_text("status: done\nresolved: true\n", encoding="utf-8")
    git(repo, "add", str(archive_task.relative_to(repo)))

    result, log = run_tick_start(repo)

    assert result.returncode == 0, result.stderr
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == (
        "coord: recover interrupted task bookkeeping (1 file(s))"
    )
    assert git(repo, "status", "--porcelain").stdout == ""
    assert "tick-start task bookkeeping recovery: committed tasks/archive/finished.md" in log
    assert "pickup reached" in log


def test_staged_deletion_and_untracked_archive_copy_recovers_and_proceeds_to_pickup(tmp_path):
    repo = init_repo(tmp_path)
    active_task = repo / "tasks" / "finished.md"
    active_task.write_text("status: done\n", encoding="utf-8")
    git(repo, "add", str(active_task.relative_to(repo)))
    git(repo, "commit", "-m", "add active task")
    git(repo, "push")
    git(repo, "rm", str(active_task.relative_to(repo)))
    archive_copy = repo / "tasks" / "archive" / "finished-copy.md"
    archive_copy.write_text("status: done\n", encoding="utf-8")

    result, log = run_tick_start(repo)

    assert result.returncode == 0, result.stderr
    assert git(repo, "status", "--porcelain").stdout == ""
    changed_paths = git(repo, "show", "--format=", "--name-only", "HEAD").stdout.splitlines()
    assert changed_paths == ["tasks/archive/finished-copy.md"]
    assert "tick-start task bookkeeping recovery: committed" in log
    assert "pickup reached" in log


def test_mixed_dirt_keeps_existing_dirty_skip_and_does_not_pick_up(tmp_path):
    repo = init_repo(tmp_path)
    archive_task = repo / "tasks" / "archive" / "finished.md"
    archive_task.write_text("status: done\nresolved: true\n", encoding="utf-8")
    git(repo, "add", str(archive_task.relative_to(repo)))
    (repo / "source.py").write_text("value = 2\n", encoding="utf-8")

    result, log = run_tick_start(repo)

    assert result.returncode == 0, result.stderr
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "seed"
    assert "[TS] git sync skipped: worktree dirty before pickup\n" in log
    assert "tick-start task bookkeeping recovery" not in log
    assert "pickup reached" not in log


def test_recovery_stops_when_git_operation_is_in_progress(tmp_path):
    repo = init_repo(tmp_path)
    archive_task = repo / "tasks" / "archive" / "finished.md"
    archive_task.write_text("status: done\nresolved: true\n", encoding="utf-8")
    git(repo, "add", str(archive_task.relative_to(repo)))
    (repo / ".git" / "rebase-merge").mkdir()

    result, log = run_tick_start(repo)

    assert result.returncode != 0
    assert git(repo, "log", "-1", "--format=%s").stdout.strip() == "seed"
    assert "recovery skipped: git operation in progress" in log
    assert "pickup reached" not in log
