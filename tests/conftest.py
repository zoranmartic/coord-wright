import os
import runpy
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"
COORD_MODULE = runpy.run_path(str(COORD), run_name="coord_cli")
STATUS_ROUTING = COORD_MODULE["STATUS_ROUTING"]

# Worker/watchdog behavior tests exercise the ACKNOWLEDGED autonomous path, so
# the suite runs with the unattended-autonomy gate satisfied. Tests that cover
# the gate itself (tests/test_unsafe_autonomous_gate.py) strip this variable
# from the subprocess environment explicitly.
os.environ.setdefault("COORD_UNSAFE_AUTONOMOUS", "1")


class CoordRepo:
    def __init__(self, root, origin, tasks):
        self.root = root
        self.origin = origin
        self.tasks = tasks

    def coord(self, *args, check=False):
        env = os.environ.copy()
        env.update({
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
        })
        return subprocess.run(
            ["python3", str(COORD), *args],
            cwd=self.root,
            env=env,
            check=check,
            capture_output=True,
            text=True,
        )

    def git(self, *args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=check,
            capture_output=True,
            text=True,
        )


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _assigned_for(status):
    if status in {"claude-working", "needs-review"}:
        return "claude"
    return "codex"


def _write_task(path, task_id, status):
    body = textwrap.dedent("""\
        ## Task parameters

        ## Scope notes

        - [ ] **S1: Sample subtask**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.6-sol
          Fixture body.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.

        ## Plan
        Fixture plan.

        ## Acceptance test
        Fixture acceptance.

        ## Claude findings

        ## Codex findings

        ## Open issues

        ## Resolved issues
        """)
    path.write_text(
        textwrap.dedent(f"""\
            ---
            id: {task_id}
            task: Fixture task for {status}
            status: {status}
            assigned: {_assigned_for(status)}
            complexity: simple
            kind: code-fix
            reasoning_effort: medium
            round: 1
            created: 2026-05-17T00:00:00+0100
            updated: 2026-05-17T00:00:00+0100
            scope:
              - tests fixture
            tags:
              - fixture
            priority: 5
            max_turns: 3
            ---
            """)
        + body,
        encoding="utf-8",
    )


@pytest.fixture
def status_routing():
    return STATUS_ROUTING


@pytest.fixture
def coord_repo(tmp_path):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", str(origin))
    _git(tmp_path, "init", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Coord Test")

    tasks_dir = repo / "tasks"
    tasks_dir.mkdir()
    (tasks_dir / "archive").mkdir()
    (tasks_dir / "findings").mkdir()

    tasks = {}
    handoffs_dir = repo / ".coord" / "handoffs"
    for status in STATUS_ROUTING:
        task_id = f"sample-{status}"
        path = tasks_dir / f"{task_id}.md"
        _write_task(path, task_id, status)
        tasks[status] = path
        sub_dir = handoffs_dir / task_id
        sub_dir.mkdir(parents=True, exist_ok=True)
        (sub_dir / "S1.md").write_text(
            f"# S1 handoff — {task_id}\nFixture handoff for {status}.\n",
            encoding="utf-8",
        )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed fixture tasks")
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    return CoordRepo(repo, origin, tasks)
