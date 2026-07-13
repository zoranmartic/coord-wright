import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "bin" / "coord-commit-agent.sh"


class CoordCommitAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, repo, *args, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            text=True,
            capture_output=True,
            check=check,
        )

    def init_repo(self):
        remote = self.root / "remote.git"
        repo = self.root / "repo"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        self.git(repo, "config", "user.email", "test@example.com")
        self.git(repo, "config", "user.name", "Coord Test")
        (repo / ".gitkeep").write_text("", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-m", "init")
        self.git(repo, "branch", "-M", "main")
        self.git(repo, "remote", "add", "origin", str(remote))
        self.git(repo, "push", "-u", "origin", "main")
        return repo

    def write_base_status(self, text=""):
        path = self.root / "base-status.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def write_scope_file(self, lines):
        path = self.root / "scope-specs.txt"
        path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
        return path

    def run_helper(self, cwd, base_status, log_path=None, scope_file=None):
        env = os.environ.copy()
        env.pop("COORD_SCOPE_FILE", None)
        env.update({
            "COORD_TASK_ID": "2026-05-16-test-helper",
            "COORD_AGENT": "codex",
            "COORD_BASE_GIT_STATUS_FILE": str(base_status),
        })
        if log_path is not None:
            env["LOG"] = str(log_path)
        if scope_file is not None:
            env["COORD_SCOPE_FILE"] = str(scope_file)
        return subprocess.run(
            ["bash", str(HELPER)],
            cwd=cwd,
            text=True,
            capture_output=True,
            env=env,
        )

    def run_tentative_helper(self, cwd, base_status, rc="7", log_path=None, scope_file=None):
        env = os.environ.copy()
        env.pop("COORD_SCOPE_FILE", None)
        env.update({
            "COORD_TASK_ID": "2026-05-16-test-helper",
            "COORD_AGENT": "codex",
            "COORD_BASE_GIT_STATUS_FILE": str(base_status),
        })
        if log_path is not None:
            env["LOG"] = str(log_path)
        if scope_file is not None:
            env["COORD_SCOPE_FILE"] = str(scope_file)
        return subprocess.run(
            ["bash", "-c", f"source {HELPER}; commit_tentative_changes \"$1\"", "tentative", rc],
            cwd=cwd,
            text=True,
            capture_output=True,
            env=env,
        )

    def commit_count(self, repo):
        return int(self.git(repo, "rev-list", "--count", "HEAD").stdout.strip())

    def latest_subject(self, repo):
        return self.git(repo, "log", "-1", "--pretty=%s").stdout.strip()

    def test_happy_path_commits_and_pushes_agent_edit(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        (repo / "agent-edit.txt").write_text("agent edit\n", encoding="utf-8")

        result = self.run_helper(repo, base_status)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(repo), 2)
        self.assertEqual(self.latest_subject(repo), "coord: work 2026-05-16-test-helper")
        self.assertEqual(self.git(repo, "status", "--porcelain", "--untracked-files=all").stdout, "")

    def test_clean_worktree_exits_zero_without_commit(self):
        repo = self.init_repo()
        base_status = self.write_base_status()

        result = self.run_helper(repo, base_status)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(repo), 1)
        self.assertEqual(self.latest_subject(repo), "init")

    def test_dirty_base_status_refuses_without_commit(self):
        repo = self.init_repo()
        base_status = self.write_base_status("?? pre-existing.txt\n")
        log_path = self.root / "helper.log"
        (repo / "agent-edit.txt").write_text("agent edit\n", encoding="utf-8")

        result = self.run_helper(repo, base_status, log_path=log_path)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.commit_count(repo), 1)
        self.assertEqual(self.latest_subject(repo), "init")
        self.assertIn("worktree was dirty before", log_path.read_text(encoding="utf-8"))

    def test_outside_git_worktree_exits_zero(self):
        workdir = self.root / "not-a-repo"
        workdir.mkdir()
        base_status = self.write_base_status()
        log_path = self.root / "helper.log"

        result = self.run_helper(workdir, base_status, log_path=log_path)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("not inside a git worktree", log_path.read_text(encoding="utf-8"))

    def test_tentative_happy_path_commits_pushes_and_prints_one(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        (repo / "agent-edit.txt").write_text("agent edit\n", encoding="utf-8")

        result = self.run_tentative_helper(repo, base_status, rc="42")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1\n")
        self.assertEqual(self.commit_count(repo), 2)
        self.assertEqual(
            self.latest_subject(repo),
            "coord: tentative 2026-05-16-test-helper (rc=42, needs human review)",
        )
        self.assertEqual(self.git(repo, "status", "--porcelain", "--untracked-files=all").stdout, "")

    def test_tentative_clean_worktree_exits_zero_without_commit(self):
        repo = self.init_repo()
        base_status = self.write_base_status()

        result = self.run_tentative_helper(repo, base_status)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.commit_count(repo), 1)
        self.assertEqual(self.latest_subject(repo), "init")

    def test_tentative_dirty_base_status_refuses_without_commit(self):
        repo = self.init_repo()
        base_status = self.write_base_status("?? pre-existing.txt\n")
        log_path = self.root / "helper.log"
        (repo / "agent-edit.txt").write_text("agent edit\n", encoding="utf-8")

        result = self.run_tentative_helper(repo, base_status, log_path=log_path)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertEqual(self.commit_count(repo), 1)
        self.assertEqual(self.latest_subject(repo), "init")
        self.assertIn("tentative commit skipped", log_path.read_text(encoding="utf-8"))

    def test_scoped_commit_leaves_out_of_scope_files_uncommitted(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        scope = self.write_scope_file(["src/**"])
        log_path = self.root / "helper.log"
        (repo / "src").mkdir()
        (repo / "src" / "in-scope.py").write_text("print('hi')\n", encoding="utf-8")
        (repo / "tasks").mkdir()
        (repo / "tasks" / "2026-05-16-test-helper.md").write_text("task\n", encoding="utf-8")
        (repo / "stray.txt").write_text("concurrent edit\n", encoding="utf-8")

        result = self.run_helper(repo, base_status, log_path=log_path, scope_file=scope)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(repo), 2)
        committed = self.git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
        self.assertIn("src/in-scope.py", committed)
        self.assertIn("tasks/2026-05-16-test-helper.md", committed)
        self.assertNotIn("stray.txt", committed)
        self.assertEqual(
            self.git(repo, "status", "--porcelain", "--untracked-files=all").stdout.strip(),
            "?? stray.txt",
        )
        self.assertIn(
            "out-of-scope changes left uncommitted",
            log_path.read_text(encoding="utf-8"),
        )

    def test_scoped_commit_with_only_out_of_scope_changes_skips_commit(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        scope = self.write_scope_file(["src/**"])
        log_path = self.root / "helper.log"
        (repo / "stray.txt").write_text("concurrent edit\n", encoding="utf-8")

        result = self.run_helper(repo, base_status, log_path=log_path, scope_file=scope)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(repo), 1)
        self.assertEqual(self.latest_subject(repo), "init")
        self.assertIn(
            "out-of-scope changes left uncommitted",
            log_path.read_text(encoding="utf-8"),
        )

    def test_empty_scope_file_falls_back_to_stage_everything(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        scope = self.write_scope_file([])
        (repo / "anything.txt").write_text("x\n", encoding="utf-8")

        result = self.run_helper(repo, base_status, scope_file=scope)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit_count(repo), 2)
        self.assertEqual(self.git(repo, "status", "--porcelain", "--untracked-files=all").stdout, "")

    def test_tentative_scoped_commit_leaves_out_of_scope_files(self):
        repo = self.init_repo()
        base_status = self.write_base_status()
        scope = self.write_scope_file(["src/**"])
        (repo / "src").mkdir()
        (repo / "src" / "in-scope.py").write_text("print('hi')\n", encoding="utf-8")
        (repo / "stray.txt").write_text("concurrent edit\n", encoding="utf-8")

        result = self.run_tentative_helper(repo, base_status, rc="42", scope_file=scope)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1\n")
        committed = self.git(repo, "show", "--name-only", "--pretty=", "HEAD").stdout.split()
        self.assertIn("src/in-scope.py", committed)
        self.assertNotIn("stray.txt", committed)

    def test_tentative_outside_git_worktree_exits_zero(self):
        workdir = self.root / "not-a-repo"
        workdir.mkdir()
        base_status = self.write_base_status()

        result = self.run_tentative_helper(workdir, base_status)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
