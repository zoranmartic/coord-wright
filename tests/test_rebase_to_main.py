import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "rebase-to-main.sh"


def git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_file(repo, text, message):
    (repo / "a.txt").write_text(text, encoding="utf-8")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-m", message)


def conflicting_session(tmp_path):
    tmp_path = tmp_path.resolve()
    origin = tmp_path / "origin.git"
    main = tmp_path / "proj"
    session = tmp_path / "proj-session-x"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(origin), str(main)], check=True, capture_output=True)
    git(main, "config", "user.email", "test@example.com")
    git(main, "config", "user.name", "Coord Test")
    git(main, "checkout", "-B", "main")
    commit_file(main, "base\n", "base")
    git(main, "push", "-u", "origin", "main")
    git(main, "worktree", "add", "-b", "task/x", str(session), "origin/main")
    commit_file(session, "task\n", "task change")
    git(session, "push", "-u", "origin", "task/x")
    commit_file(main, "main\n", "main change")
    git(main, "push", "origin", "main")

    tools = tmp_path / "tools"
    (tools / "bin").mkdir(parents=True)
    shutil.copy2(ROOT / "bin" / "coord-project-root", tools / "bin" / "coord-project-root")
    (tools / "projects.txt").write_text(f"{main}\n", encoding="utf-8")
    env = os.environ.copy()
    env["COORD_TOOLS"] = str(tools)
    return origin, session, env


def run_script(session, env):
    return subprocess.run(
        ["/bin/bash", str(SCRIPT)], cwd=session, env=env, text=True, capture_output=True
    )


def test_conflict_hint_prints_finish_commands_that_complete_the_rebase(tmp_path):
    origin, session, env = conflicting_session(tmp_path)
    pushed_before = git(session, "rev-parse", "origin/task/x")

    result = run_script(session, env)

    assert result.returncode == 1, result.stderr
    lines = result.stderr.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("Then finish by hand"))
    finish = [line.strip() for line in lines[start + 1 : start + 3]]
    assert finish == [
        "git diff --check origin/main..HEAD",
        f"git push --force-with-lease=task/x:{pushed_before} origin HEAD:task/x",
    ]

    (session / "a.txt").write_text("resolved\n", encoding="utf-8")
    git(session, "add", "a.txt")
    subprocess.run(
        ["git", "rebase", "--continue"], cwd=session, check=True, capture_output=True,
        env={**env, "GIT_EDITOR": "true"},
    )

    # The script's preflight refuses a re-run once HEAD is rebased.
    rerun = run_script(session, env)
    assert rerun.returncode == 2
    assert "differs from upstream" in rerun.stderr

    for command in finish:
        subprocess.run(["/bin/bash", "-c", command], cwd=session, check=True, capture_output=True)
    head = git(session, "rev-parse", "HEAD")
    assert git(origin, "rev-parse", "refs/heads/task/x") == head
    git(session, "merge-base", "--is-ancestor", "origin/main", "HEAD")
