import runpy
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_commit_and_push")
commit_and_push = COORD_MODULE["commit_and_push"]


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

    commit_and_push(str(path), "coord: test commit_and_push happy path")

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

    commit_and_push(str(coord_repo.root / "tasks" / "sample-pending.md"), "coord: no-op commit")

    assert _commit_count(coord_repo.root) == before
    assert _latest_subject(coord_repo.root) == "seed fixture tasks"
    assert _git(coord_repo.root, "status", "--porcelain", "--untracked-files=all").stdout == ""


def test_commit_and_push_fails_loudly_but_keeps_local_commit_when_push_is_rejected(coord_repo, monkeypatch, capsys):
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

    # A rejected push is a real failure: callers must not report success while
    # the queue write never reached the remote. The local commit survives so
    # nothing is lost once the operator reconciles.
    with pytest.raises(SystemExit) as excinfo:
        commit_and_push(str(path), "coord: local divergent change")

    assert excinfo.value.code == 1
    assert "git push failed:" in capsys.readouterr().err
    assert _commit_count(coord_repo.root) == before + 1
    assert _latest_subject(coord_repo.root) == "coord: local divergent change"
    assert _git(coord_repo.root, "status", "--porcelain", "--untracked-files=all").stdout == ""


def test_commit_and_push_without_remote_commits_and_returns_success(coord_repo, monkeypatch, capsys):
    monkeypatch.chdir(coord_repo.root)
    _git(coord_repo.root, "remote", "remove", "origin")
    path = coord_repo.root / "tasks" / "sample-pending.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nlocal-only edit\n", encoding="utf-8")
    before = _commit_count(coord_repo.root)

    # No remote configured is a supported local-only state, not a failure.
    commit_and_push(str(path), "coord: local-only commit")

    assert _commit_count(coord_repo.root) == before + 1
    assert _latest_subject(coord_repo.root) == "coord: local-only commit"
    assert "git push failed:" not in capsys.readouterr().err


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

    with pytest.raises(SystemExit) as excinfo:
        commit_and_push(str(path), "coord: identity missing")

    assert excinfo.value.code == 1
    assert "git commit failed:" in capsys.readouterr().err
    assert _commit_count(coord_repo.root) == before
