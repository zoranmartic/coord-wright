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
