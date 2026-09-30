import runpy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD_MODULE = runpy.run_path(str(ROOT / "bin" / "coord"), run_name="coord_cli_tags")
parse_task = COORD_MODULE["parse_task"]


def test_new_preserves_supplied_tags_with_coordination_and_deduplicates(coord_repo):
    result = coord_repo.coord(
        "new",
        "--task=Preserve supplied tags",
        "--tags=triage-auto,2026-07-10,coordination,triage-auto",
    )

    assert result.returncode == 0, result.stderr
    fm, _ = parse_task(coord_repo.root / "tasks" / f"{result.stdout.strip()}.md")
    assert fm["tags"] == ["coordination", "triage-auto", "2026-07-10"]


def test_new_overnight_tags_are_merged_and_deduplicated(coord_repo):
    result = coord_repo.coord(
        "new",
        "--task=Preserve overnight tags",
        "--overnight",
        "--tags=overnight,triage-auto,coordination",
    )

    assert result.returncode == 0, result.stderr
    fm, _ = parse_task(coord_repo.root / "tasks" / f"{result.stdout.strip()}.md")
    assert fm["tags"] == ["coordination", "overnight", "triage-auto"]


def test_update_tags_replaces_existing_tags(coord_repo):
    result = coord_repo.coord(
        "update",
        "sample-shaping",
        "--tags=triage-auto,2026-07-10,triage-auto",
    )

    assert result.returncode == 0, result.stderr
    fm, _ = parse_task(coord_repo.tasks["shaping"])
    assert fm["tags"] == ["triage-auto", "2026-07-10"]


def test_update_empty_tags_removes_field(coord_repo):
    result = coord_repo.coord("update", "sample-shaping", "--tags=")

    assert result.returncode == 0, result.stderr
    fm, _ = parse_task(coord_repo.tasks["shaping"])
    assert "tags" not in fm
