import os
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_commit_and_push")
commit_and_push = COORD_MODULE["commit_and_push"]
commit_and_push_paths = COORD_MODULE["commit_and_push_paths"]


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _commit_count(repo):
    return int(_git(repo, "rev-list", "--count", "HEAD").stdout.strip())


def _latest_subject(repo):
    return _git(repo, "log", "-1", "--pretty=%s").stdout.strip()


def test_commit_and_push_commits_file_and_pushes_to_origin(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    path = coord_repo.root / "tasks" / "sample-pending.md"
    before = _commit_count(coord_repo.root)
    path.write_text(path.read_text(encoding="utf-8") + "\nagent edit\n", encoding="utf-8")

    assert commit_and_push(str(path), "coord: test commit_and_push happy path")

    assert _commit_count(coord_repo.root) == before + 1
    assert _latest_subject(coord_repo.root) == "coord: test commit_and_push happy path"
    assert _git(coord_repo.root, "status", "--porcelain", "--untracked-files=all").stdout == ""
    assert (
        _git(coord_repo.root, "rev-parse", "HEAD").stdout
        == _git(coord_repo.root, "rev-parse", "origin/main").stdout
    )


def test_commit_and_push_noops_clean_worktree_without_failing(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    before = _commit_count(coord_repo.root)

    assert commit_and_push(str(coord_repo.root / "tasks" / "sample-pending.md"), "coord: no-op commit")

    assert _commit_count(coord_repo.root) == before
    assert _latest_subject(coord_repo.root) == "seed fixture tasks"
    assert _git(coord_repo.root, "status", "--porcelain", "--untracked-files=all").stdout == ""


def test_commit_and_push_retries_non_fast_forward_rejection(coord_repo, monkeypatch):
    competitor = coord_repo.root.parent / "competitor"
    _git(coord_repo.root.parent, "clone", str(coord_repo.origin), str(competitor))
    _git(competitor, "config", "user.email", "other@example.com")
    _git(competitor, "config", "user.name", "Other Test")
    (competitor / "remote-only.txt").write_text("remote change\n", encoding="utf-8")
    _git(competitor, "add", ".")
    _git(competitor, "commit", "-m", "remote competing change")
    _git(competitor, "push")

    monkeypatch.chdir(coord_repo.root)
    path = coord_repo.root / "local-change.txt"
    path.write_text("local change\n", encoding="utf-8")
    before = _commit_count(coord_repo.root)

    assert commit_and_push(str(path), "coord: local divergent change")

    assert _commit_count(coord_repo.root) == before + 2
    assert _latest_subject(coord_repo.root) == "coord: local divergent change"
    assert _git(coord_repo.root, "status", "--porcelain", "--untracked-files=all").stdout == ""
    assert (
        _git(coord_repo.root, "rev-parse", "HEAD").stdout
        == _git(coord_repo.root, "rev-parse", "origin/main").stdout
    )


def test_commit_and_push_retries_with_unstaged_changes(coord_repo, monkeypatch):
    competitor = coord_repo.root.parent / "competitor"
    _git(coord_repo.root.parent, "clone", str(coord_repo.origin), str(competitor))
    _git(competitor, "config", "user.email", "other@example.com")
    _git(competitor, "config", "user.name", "Other Test")
    (competitor / "remote-only.txt").write_text("remote change\n", encoding="utf-8")
    _git(competitor, "add", ".")
    _git(competitor, "commit", "-m", "remote competing change")
    _git(competitor, "push")

    monkeypatch.chdir(coord_repo.root)
    path = coord_repo.root / "local-change.txt"
    dirty = coord_repo.root / "unstaged.txt"
    path.write_text("local change\n", encoding="utf-8")
    dirty.write_text("keep me\n", encoding="utf-8")

    assert commit_and_push(str(path), "coord: dirty divergent change")

    assert _git(coord_repo.root, "rev-parse", "HEAD").stdout == _git(
        coord_repo.root, "rev-parse", "origin/main"
    ).stdout
    assert _git(coord_repo.root, "status", "--porcelain").stdout == "?? unstaged.txt\n"


def test_commit_and_push_leaves_unrelated_staged_file_out_of_commit(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    path = coord_repo.root / "tasks" / "sample-pending.md"
    unrelated = coord_repo.root / "other-agent.md"
    path.write_text(path.read_text(encoding="utf-8") + "\ncoord edit\n", encoding="utf-8")
    unrelated.write_text("staged elsewhere\n", encoding="utf-8")
    _git(coord_repo.root, "add", str(unrelated))

    assert commit_and_push(str(path), "coord: scoped commit")

    assert _git(coord_repo.root, "show", "--name-only", "--format=").stdout.splitlines() == [
        "tasks/sample-pending.md"
    ]
    assert _git(coord_repo.root, "diff", "--cached", "--name-only").stdout == "other-agent.md\n"


def test_commit_and_push_returns_false_when_push_remains_rejected(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    path = coord_repo.root / "local-change.txt"
    path.write_text("local change\n", encoding="utf-8")
    _git(coord_repo.root, "remote", "set-url", "origin", str(coord_repo.root / "missing-origin.git"))

    assert commit_and_push(str(path), "coord: rejected push") is False


def test_commit_and_push_aborts_conflicting_rebase(coord_repo, monkeypatch):
    competitor = coord_repo.root.parent / "competitor"
    _git(coord_repo.root.parent, "clone", str(coord_repo.origin), str(competitor))
    _git(competitor, "config", "user.email", "other@example.com")
    _git(competitor, "config", "user.name", "Other Test")
    path = coord_repo.root / "tasks" / "sample-pending.md"
    competitor_path = competitor / "tasks" / "sample-pending.md"
    competitor_path.write_text("remote conflict\n", encoding="utf-8")
    _git(competitor, "add", str(competitor_path.relative_to(competitor)))
    _git(competitor, "commit", "-m", "remote conflict")
    _git(competitor, "push")

    monkeypatch.chdir(coord_repo.root)
    path.write_text("local conflict\n", encoding="utf-8")

    assert commit_and_push(str(path), "coord: local conflict") is False

    assert _git(coord_repo.root, "branch", "--show-current").stdout.strip() == "main"
    assert not (coord_repo.root / ".git" / "rebase-merge").exists()
    assert not (coord_repo.root / ".git" / "rebase-apply").exists()


def test_commit_and_push_archives_committed_and_uncommitted_paths(coord_repo, monkeypatch):
    monkeypatch.chdir(coord_repo.root)
    old_path = coord_repo.root / "tasks" / "sample-pending.md"
    archived_path = coord_repo.root / "tasks" / "archive" / "sample-pending.md"
    old_path.rename(archived_path)

    assert commit_and_push_paths([str(archived_path), str(old_path)], "coord: archive committed")
    assert _git(coord_repo.root, "show", "--no-renames", "--format=", "--name-only", "HEAD").stdout.splitlines() == [
        "tasks/archive/sample-pending.md",
        "tasks/sample-pending.md",
    ]

    uncommitted = coord_repo.root / "tasks" / "uncommitted.md"
    archive_copy = coord_repo.root / "tasks" / "archive" / "uncommitted.md"
    uncommitted.write_text("uncommitted\n", encoding="utf-8")
    uncommitted.rename(archive_copy)

    assert commit_and_push_paths([str(archive_copy), str(uncommitted)], "coord: archive uncommitted")
    assert _git(coord_repo.root, "show", "--format=", "--name-only", "HEAD").stdout.splitlines() == [
        "tasks/archive/uncommitted.md"
    ]


def test_commit_and_push_allows_no_configured_push_destination(coord_repo, monkeypatch, capsys):
    monkeypatch.chdir(coord_repo.root)
    _git(coord_repo.root, "remote", "remove", "origin")
    path = coord_repo.root / "local-change.txt"
    path.write_text("local change\n", encoding="utf-8")

    assert commit_and_push(str(path), "coord: no remote")

    assert "no configured push destination" in capsys.readouterr().err


def test_commit_and_push_allows_origin_without_upstream(coord_repo, monkeypatch, capsys):
    monkeypatch.chdir(coord_repo.root)
    _git(coord_repo.root, "branch", "--unset-upstream")
    path = coord_repo.root / "local-change.txt"
    path.write_text("local change\n", encoding="utf-8")

    assert commit_and_push(str(path), "coord: no upstream")

    assert "no configured push destination" in capsys.readouterr().err


def test_commit_and_push_fails_loudly_when_git_identity_is_missing(coord_repo, monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(coord_repo.root)
    # Simulate a machine with no resolvable identity. useConfigOnly stops git
    # from auto-detecting user@host, which it otherwise does even with HOME
    # redirected — that auto-detection is exactly what a strict setup disables.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    _git(coord_repo.root, "config", "user.useConfigOnly", "true")
    _git(coord_repo.root, "config", "--unset", "user.email")
    _git(coord_repo.root, "config", "--unset", "user.name")
    path = coord_repo.root / "tasks" / "sample-pending.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nidentity edit\n", encoding="utf-8")
    before = _commit_count(coord_repo.root)

    assert commit_and_push(str(path), "coord: identity missing") is False

    assert "git commit failed:" in capsys.readouterr().err
    assert _commit_count(coord_repo.root) == before


def test_update_exits_4_when_the_queue_commit_fails(coord_repo):
    coord_repo.git("config", "user.useConfigOnly", "true")
    coord_repo.git("config", "--unset", "user.email")
    coord_repo.git("config", "--unset", "user.name")

    env_home = coord_repo.root.parent / "empty-home"
    env_home.mkdir()
    result = subprocess.run(
        ["python3", str(ROOT / "bin" / "coord"), "update", "sample-pending", "--add-issues=identity check"],
        cwd=coord_repo.root,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(env_home),
            "XDG_CONFIG_HOME": str(env_home / ".config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "COORD_TASKS_DIR": "tasks",
            "COORD_ARCHIVE_DIR": "tasks/archive",
            "COORD_FINDINGS_DIR": "tasks/findings",
            "COORD_CHANGES_FILE": "tasks/CHANGES.md",
        },
    )

    assert result.returncode == 4, result.stderr
    assert "update: git side effect failed" in result.stderr
