"""Tests for the (complexity, model_claude, reasoning_effort) baseline validator.

Locks in:
- validate_complexity_pair() catches off-baseline subtask metadata at task
  creation (the simple+opus drift you keep seeing from opus-driven shaping).
- coord new fails fast on a task-level frontmatter mismatch.
- coord update fails fast when a later --model-claude change drifts off baseline.
- Aligned combinations (simple+sonnet, complex+opus, trivial+haiku) pass clean.
- Architect/review role fields are validated against the same baseline.
"""

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"


def _load_coord_module():
    loader = SourceFileLoader("coord_cli", str(COORD))
    spec = importlib.util.spec_from_loader("coord_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def _coord(*args, cwd, check=False):
    return subprocess.run(
        [sys.executable, str(COORD), *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _init_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Coord Test"], cwd=root, check=True)
    origin = root / ".coord-test-origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text(".coord-test-origin.git/\n.coord/\n", encoding="utf-8")
    (root / "tasks").mkdir()
    (root / "tasks" / "archive").mkdir()
    (root / "tasks" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tasks/.gitkeep", "tasks/archive/.gitkeep"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=root, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=root, check=True, capture_output=True)


def _subtasks(meta_lines):
    """Build a 2-subtask block where each subtask carries the supplied metadata.

    meta_lines: list of "key: value" strings written under each S<n> header.
    """
    meta_block = "\n".join(f"  {m}" for m in meta_lines)
    return (
        "- [ ] **S1: First narrow step**\n"
        f"{meta_block}\n"
        "  Edit a single file. Local smoke: pytest tests/test_one.py.\n"
        "  Writes handoff: `.coord/handoffs/<task-id>/S1.md`.\n"
        "  Handoff to S2: name the single file touched so the second step can pick up the next narrow slice.\n\n"
        "- [ ] **S2: Second narrow step**\n"
        f"{meta_block}\n"
        "  Edit a single file. Local smoke: pytest tests/test_two.py.\n"
        "  Reads handoff: `.coord/handoffs/<task-id>/S1.md`.\n"
        "  Writes handoff: `.coord/handoffs/<task-id>/S2.md`.\n"
    )


class ValidateComplexityPairUnitTests(unittest.TestCase):
    """Direct unit tests for the helper, independent of the coord CLI."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_coord_module()

    def test_simple_plus_opus_flagged(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="simple", model_claude="opus"
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("simple", warnings[0])
        self.assertIn("opus", warnings[0])
        self.assertIn("sonnet", warnings[0])

    def test_simple_plus_sonnet_clean(self):
        self.assertEqual(
            self.mod.validate_complexity_pair(complexity="simple", model_claude="sonnet"),
            [],
        )

    def test_simple_review_role_allows_opus(self):
        self.assertEqual(
            self.mod.validate_complexity_pair(
                complexity="simple",
                model_claude="opus",
                role_label="review:",
                baseline_map=self.mod.COMPLEXITY_ROLE_MODEL_BASELINE,
            ),
            [],
        )

    def test_trivial_review_role_still_rejects_opus(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="trivial",
            model_claude="opus",
            role_label="review:",
            baseline_map=self.mod.COMPLEXITY_ROLE_MODEL_BASELINE,
        )
        self.assertEqual(len(warnings), 1)

    def test_task_level_baseline_accepts_opus_review_on_simple(self):
        warnings = self.mod.validate_task_level_baseline({
            "complexity": "simple",
            "model_claude": "sonnet",
            "reasoning_effort": "medium",
            "model_review": "opus",
            "reasoning_effort_review": "high",
        })
        self.assertEqual(warnings, [])

    def test_trivial_plus_sonnet_flagged(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="trivial", model_claude="sonnet"
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("haiku", warnings[0])

    def test_trivial_plus_haiku_clean(self):
        self.assertEqual(
            self.mod.validate_complexity_pair(complexity="trivial", model_claude="haiku"),
            [],
        )

    def test_complex_allows_both_sonnet_and_opus(self):
        self.assertEqual(
            self.mod.validate_complexity_pair(complexity="complex", model_claude="sonnet"),
            [],
        )
        self.assertEqual(
            self.mod.validate_complexity_pair(complexity="complex", model_claude="opus"),
            [],
        )

    def test_complex_plus_haiku_flagged(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="complex", model_claude="haiku"
        )
        self.assertEqual(len(warnings), 1)

    def test_simple_plus_xhigh_effort_flagged(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="simple", reasoning_effort="xhigh"
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("reasoning_effort", warnings[0])

    def test_trivial_plus_high_effort_flagged(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="trivial", reasoning_effort="high"
        )
        self.assertEqual(len(warnings), 1)

    def test_unknown_complexity_silent(self):
        self.assertEqual(
            self.mod.validate_complexity_pair(complexity="mythical", model_claude="opus"),
            [],
        )

    def test_missing_inputs_silent(self):
        self.assertEqual(self.mod.validate_complexity_pair(complexity=None), [])
        self.assertEqual(self.mod.validate_complexity_pair(complexity="simple"), [])

    def test_full_claude_id_normalized(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="simple", model_claude="claude-opus-4-7"
        )
        self.assertEqual(len(warnings), 1)
        self.assertIn("opus", warnings[0])

    def test_role_label_propagates(self):
        warnings = self.mod.validate_complexity_pair(
            complexity="simple",
            model_claude="opus",
            role_label="architect:",
        )
        self.assertTrue(warnings[0].startswith("architect: "))


class CoordNewBaselineTests(unittest.TestCase):
    """End-to-end: simple+opus at task or subtask level fails coord new fast."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _new(self, *extra, subtasks=None, status="shaping"):
        args = [
            "new",
            "--task=Baseline test task",
            "--kind=code-fix",
            "--scope=src/foo.py",
            "--set-plan=Run the focused baseline fixture path.",
            "--set-acceptance-test=Baseline fixture reaches the expected state.",
            f"--status={status}",
            *extra,
        ]
        if subtasks is not None:
            block_path = self.root / "subtasks.txt"
            block_path.write_text(subtasks, encoding="utf-8")
            args.append(f"--set-subtasks=@{block_path}")
        return _coord(*args, cwd=self.root)

    def test_task_level_simple_plus_opus_fails(self):
        result = self._new(
            "--complexity=simple",
            "--model_claude=opus",
            subtasks=_subtasks(
                ["complexity: simple", "model_claude: sonnet", "model_codex: gpt-5.5"]
            ),
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("off-baseline", result.stderr)
        self.assertIn("model_claude:opus", result.stderr)

    def test_task_level_simple_plus_sonnet_succeeds(self):
        result = self._new(
            "--complexity=simple",
            "--model_claude=sonnet",
            "--reasoning_effort=medium",
            subtasks=_subtasks(
                ["complexity: simple", "model_claude: sonnet", "model_codex: gpt-5.5"]
            ),
            status="pending",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_subtask_level_simple_plus_opus_fails(self):
        result = self._new(
            "--complexity=complex",
            "--model_claude=opus",
            "--reasoning_effort=high",
            subtasks=_subtasks(
                ["complexity: simple", "model_claude: opus", "model_codex: gpt-5.5"]
            ),
            status="pending",
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("S1:", result.stderr)
        self.assertIn("off-baseline", result.stderr)

    def test_task_level_complex_plus_opus_succeeds(self):
        result = self._new(
            "--complexity=complex",
            "--model_claude=opus",
            "--model_review=opus",
            "--reasoning_effort=high",
            "--reasoning_effort_review=high",
            subtasks=_subtasks(
                ["complexity: simple", "model_claude: sonnet", "model_codex: gpt-5.5"]
            ),
            status="pending",
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_task_level_review_role_simple_plus_opus_allowed(self):
        # Policy 2026-06-12: high-stakes reviews may opt the reviewer up to
        # opus on simple tasks while the coder stays complexity-matched.
        result = self._new(
            "--complexity=simple",
            "--model_claude=sonnet",
            "--model_review=opus",
            subtasks=_subtasks(
                ["complexity: simple", "model_claude: sonnet", "model_codex: gpt-5.5"]
            ),
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_task_level_review_role_trivial_plus_opus_still_fails(self):
        result = self._new(
            "--complexity=trivial",
            "--model_claude=haiku",
            "--reasoning_effort=low",
            "--model_review=opus",
            subtasks=_subtasks(
                ["complexity: trivial", "model_claude: haiku", "model_codex: gpt-5.5"]
            ),
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("review:", result.stderr)


class CoordUpdateBaselineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)
        # Seed a clean shaping task we can then drift.
        block_path = self.root / "seed.txt"
        block_path.write_text(
            _subtasks(
                ["complexity: simple", "model_claude: sonnet", "model_codex: gpt-5.5"]
            ),
            encoding="utf-8",
        )
        result = _coord(
            "new",
            "--task=Update baseline seed",
            "--kind=code-fix",
            "--scope=src/foo.py",
            "--complexity=simple",
            "--model_claude=sonnet",
            "--reasoning_effort=medium",
            "--status=shaping",
            f"--set-subtasks=@{block_path}",
            cwd=self.root,
        )
        assert result.returncode == 0, result.stderr
        self.task_id = result.stdout.strip()

    def tearDown(self):
        self.tmp.cleanup()

    def test_drifting_to_opus_fails(self):
        result = _coord(
            "update", self.task_id, "--model_claude=opus", cwd=self.root
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("off-baseline", result.stderr)

    def test_drifting_to_xhigh_effort_fails(self):
        result = _coord(
            "update", self.task_id, "--reasoning_effort=xhigh", cwd=self.root
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("reasoning_effort", result.stderr)

    def test_aligned_model_update_succeeds(self):
        result = _coord(
            "update", self.task_id, "--model_claude=sonnet", cwd=self.root
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()


def test_forced_done_demote_with_worker_args_warns_for_task_and_subtask_baselines(coord_repo):
    path = coord_repo.tasks["done"]
    task_id = "sample-done"
    path.write_text(path.read_text().replace(
        "reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus"
    ).replace("  model_claude: sonnet", "  model_claude: opus"))

    result = coord_repo.coord(
        "update", task_id, "--status=review-failed", "--force",
        "--add-issues=worker mechanical verify gate failed",
        "--append-codex-finding=Mechanical gate failed.",
    )

    assert result.returncode == 0, result.stderr
    assert "off-baseline" in result.stderr
    assert "warning only for forced demote" in result.stderr
    assert "S1:" in result.stderr
    active = coord_repo.root / "tasks" / f"{task_id}.md"
    assert active.exists()
    assert "status: pending" in active.read_text()


def test_unforced_update_still_rejects_off_baseline_task(coord_repo):
    path = coord_repo.tasks["pending"]
    path.write_text(path.read_text().replace(
        "reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus"
    ))

    result = coord_repo.coord("update", "sample-pending", "--add-issues=note")

    assert result.returncode == 3
    assert "off-baseline" in result.stderr
    assert "warning only" not in result.stderr


def test_release_warns_for_task_and_subtask_baselines(coord_repo):
    path = coord_repo.tasks["pending"]
    task_id = "sample-pending"
    text = path.read_text().replace(
        "reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus"
    )
    path.write_text(text.replace("  model_claude: sonnet", "  model_claude: opus").replace(
        "round: 1", "pickup_hold: true\nround: 1"
    ))

    result = coord_repo.coord("release", task_id)

    assert result.returncode == 0, result.stderr
    assert "off-baseline" in result.stderr
    assert "warning only for release" in result.stderr
    assert "S1:" in result.stderr
    released = path.read_text()
    assert "pickup_hold: true" not in released
    assert "status: pending" in released


def test_release_still_rejects_structurally_incomplete_task(coord_repo):
    path = coord_repo.tasks["pending"]
    text = path.read_text().replace("  complexity: simple\n", "", 1)
    path.write_text(text.replace("round: 1", "pickup_hold: true\nround: 1"))

    result = coord_repo.coord("release", "sample-pending")

    assert result.returncode == 3
    assert "runnable task shape is incomplete" in result.stderr


def _pending_complex_opus(coord_repo):
    path = coord_repo.tasks["pending"]
    path.write_text(path.read_text().replace("complexity: simple", "complexity: complex", 1).replace(
        "reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus\nmodel_codex: gpt-5.6-sol"
    ))
    return path


def test_update_complexity_swaps_to_a_cheaper_pair_in_one_call(coord_repo):
    path = _pending_complex_opus(coord_repo)

    result = coord_repo.coord("update", "sample-pending", "--complexity=simple", "--model_claude=sonnet")

    assert result.returncode == 0, result.stderr
    text = path.read_text()
    assert "complexity: simple\n" in text
    assert "model_claude: sonnet\n" in text
    assert "model_codex: gpt-5.6-sol\n" in text


@pytest.mark.parametrize("flags,expected", [
    (("--model_claude=haiku",), "off-baseline"),
    (("--complexity=simple",), "off-baseline"),
    (("--complexity=huge",), "invalid complexity 'huge'"),
])
def test_update_complexity_is_validated_against_the_resulting_pair(coord_repo, flags, expected):
    path = _pending_complex_opus(coord_repo)
    before = path.read_text()

    result = coord_repo.coord("update", "sample-pending", *flags)

    assert result.returncode == 3
    assert expected in result.stderr
    assert path.read_text() == before


@pytest.mark.parametrize("status", ["shaping", "needs-brainstorming"])
def test_forced_close_of_never_started_draft_skips_the_baseline(coord_repo, status):
    path = coord_repo.tasks[status]
    path.write_text(path.read_text().replace("reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus"))

    result = coord_repo.coord("update", f"sample-{status}", "--status=done", "--force", "--add-issues=Discarded: superseded.")

    assert result.returncode == 0, result.stderr
    assert not path.exists()
    assert "status: done" in (coord_repo.root / "tasks" / "archive" / path.name).read_text()


def test_forced_close_of_started_draft_keeps_the_baseline(coord_repo):
    path = coord_repo.tasks["needs-brainstorming"]
    path.write_text(path.read_text().replace(
        "reasoning_effort: medium", "reasoning_effort: medium\nmodel_claude: opus\nstarted: 2026-05-17T00:00:00+0100"
    ))

    result = coord_repo.coord("update", "sample-needs-brainstorming", "--status=done", "--force")

    assert result.returncode == 3
    assert "off-baseline" in result.stderr
    assert path.exists()
