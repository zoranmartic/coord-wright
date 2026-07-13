def test_coord_repo_fixture_creates_usable_repo(coord_repo, status_routing):
    assert coord_repo.root.exists()
    assert coord_repo.origin.exists()
    assert set(coord_repo.tasks) == set(status_routing)

    upstream = coord_repo.git(
        "rev-parse",
        "--abbrev-ref",
        "--symbolic-full-name",
        "@{u}",
    )
    assert upstream.stdout.strip() == "origin/main"

    status = coord_repo.git("status", "--porcelain", "--untracked-files=all")
    assert status.stdout == ""

    result = coord_repo.coord("list", "--format=ids")
    assert result.returncode == 0
    assert "sample-pending" in result.stdout.splitlines()
