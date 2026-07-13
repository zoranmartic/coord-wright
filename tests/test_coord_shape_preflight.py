"""Tests for bin/coord-shape-preflight.

Covers the cases that the upstream Codex review surfaced as P1
(hardcoded tasks/ + tasks/archive/ paths instead of using
`coord paths --json`), plus the core hard/advisory finding paths.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "bin" / "coord-shape-preflight"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def _run(args, cwd, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["python3", str(PREFLIGHT), *args],
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        capture_output=True,
        text=True,
    )


DEP_FILE = """---
task: 2026-05-21-dep
status: done
---
# dep
"""


@pytest.fixture
def custom_tasks_repo(tmp_path: Path) -> Path:
    """A project with COORD_TASKS_DIR=custom (not the default tasks/)."""
    _write(tmp_path / ".coord" / "config.env", "COORD_TASKS_DIR=custom\n")
    _write(tmp_path / "custom" / "2026-05-21-dep.md", DEP_FILE)
    return tmp_path


def _make_target(path: Path, deps: list[str] | None = None,
                 scope: list[str] | None = None) -> None:
    lines = [
        "---",
        "task: 2026-05-21-target",
        "status: shaping",
        "complexity: simple",
        "kind: code-fix",
        "acceptance:",
        "  - target passes",
        "verify_commands:",
        "  - echo ok",
    ]
    if deps:
        lines.append("depends_on:")
        lines.extend(f"  - {d}" for d in deps)
    if scope:
        lines.append("scope:")
        lines.extend(f"  - {s}" for s in scope)
    lines.extend([
        "---",
        "# target",
        "## Plan",
        "plan.",
        "## Scope notes",
        "- [ ] **S1: T**",
        "  complexity: simple",
        "  model_claude: sonnet",
        "  model_codex: gpt-5.6-sol",
        "  Body.",
        "",
    ])
    _write(path, "\n".join(lines))


def test_preflight_honors_custom_tasks_dir_for_depends_on(custom_tasks_repo):
    target = custom_tasks_repo / "custom" / "2026-05-21-target.md"
    _make_target(target, deps=["2026-05-21-dep"])
    result = _run(["--project-root", str(custom_tasks_repo), str(target)],
                  cwd=custom_tasks_repo)
    assert result.returncode == 0, (
        f"expected exit 0, got {result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "PREFLIGHT_DEPENDS_ON_MISSING_FILE" not in result.stdout


def test_preflight_honors_custom_tasks_dir_for_positional_id(custom_tasks_repo):
    _make_target(custom_tasks_repo / "custom" / "2026-05-21-target.md")
    result = _run(
        ["--project-root", str(custom_tasks_repo), "2026-05-21-target"],
        cwd=custom_tasks_repo,
    )
    assert result.returncode == 0, (
        f"positional id under custom tasks_dir should resolve: "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_preflight_reports_truly_missing_depends_on(custom_tasks_repo):
    target = custom_tasks_repo / "custom" / "2026-05-21-target.md"
    _make_target(target, deps=["2026-05-21-not-there"])
    result = _run(["--project-root", str(custom_tasks_repo), str(target)],
                  cwd=custom_tasks_repo)
    assert result.returncode == 1
    assert "PREFLIGHT_DEPENDS_ON_MISSING_FILE" in result.stdout


def test_preflight_flags_malformed_scope(tmp_path):
    target = tmp_path / "tasks" / "2026-05-21-target.md"
    _make_target(target, scope=["src/{a,b}/", "src;test"])
    result = _run(["--project-root", str(tmp_path), str(target)],
                  cwd=tmp_path)
    assert result.returncode == 1
    assert "PREFLIGHT_MALFORMED_SCOPE" in result.stdout


def test_preflight_advisory_scope_path_not_found(tmp_path):
    target = tmp_path / "tasks" / "2026-05-21-target.md"
    _make_target(target, scope=["does/not/exist.txt"])
    result = _run(["--project-root", str(tmp_path), str(target)],
                  cwd=tmp_path)
    assert result.returncode == 0  # advisory only
    assert "PREFLIGHT_SCOPE_PATH_NOT_FOUND" in result.stderr


def test_preflight_falls_back_when_coord_paths_unavailable(tmp_path):
    """If `coord paths --json` returns no data, the preflight must still
    work using the legacy tasks/ + tasks/archive/ fallback."""
    target = tmp_path / "tasks" / "2026-05-21-target.md"
    dep = tmp_path / "tasks" / "2026-05-21-dep.md"
    _write(dep, DEP_FILE)
    _make_target(target, deps=["2026-05-21-dep"])
    result = _run(["--project-root", str(tmp_path), str(target)],
                  cwd=tmp_path)
    assert result.returncode == 0
    assert "PREFLIGHT_DEPENDS_ON_MISSING_FILE" not in result.stdout
