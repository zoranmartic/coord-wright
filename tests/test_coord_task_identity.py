from datetime import date

from conftest import _write_task


def test_show_rejects_ambiguous_fuzzy_id(coord_repo):
    result = coord_repo.coord("show", "sample")

    assert result.returncode == 2
    assert "ambiguous task id: sample" in result.stderr
    assert "sample-pending" in result.stderr


def test_update_requires_an_exact_id(coord_repo):
    result = coord_repo.coord("update", "sample", "--status=codex-working")

    assert result.returncode == 2
    assert "task not found: sample" in result.stderr
    assert "status: pending" in coord_repo.tasks["pending"].read_text(encoding="utf-8")


def test_dependency_resolution_requires_an_exact_id(coord_repo):
    done = coord_repo.root / "tasks" / "dependency-complete.md"
    pending = coord_repo.root / "tasks" / "dependent.md"
    _write_task(done, "dependency-complete", "done")
    _write_task(pending, "dependent", "pending")
    pending.write_text(
        pending.read_text(encoding="utf-8").replace(
            "priority: 5\n", "priority: 5\ndepends_on:\n  - dependency\n"
        ),
        encoding="utf-8",
    )
    sample_pending = coord_repo.tasks["pending"]
    sample_pending.write_text(
        sample_pending.read_text(encoding="utf-8").replace("status: pending", "status: done"),
        encoding="utf-8",
    )

    result = coord_repo.coord("precheck", "--assigned=codex")

    assert "No active task" in result.stdout


def test_new_uses_next_available_suffix_across_active_and_archive(coord_repo):
    slug = "identity-collision"
    task_id = f"{date.today().isoformat()}-{slug}"
    _write_task(coord_repo.root / "tasks" / f"{task_id}.md", task_id, "shaping")
    archive = coord_repo.root / "tasks" / "archive" / f"{task_id}-2.md"
    _write_task(archive, f"{task_id}-2", "done")
    coord_repo.git("add", "tasks")
    coord_repo.git("commit", "-m", "seed colliding task ids")
    coord_repo.git("push")

    result = coord_repo.coord("new", "--task", "Identity collision")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{task_id}-3"
    assert archive.exists()
    assert (coord_repo.root / "tasks" / f"{task_id}-3.md").exists()


def test_new_skips_a_non_task_file_with_the_target_id(coord_repo):
    task_id = f"{date.today().isoformat()}-identity-collision"
    (coord_repo.root / "tasks" / f"{task_id}.md").write_text("not a task\n", encoding="utf-8")

    result = coord_repo.coord("new", "--task", "Identity collision")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"{task_id}-2"
