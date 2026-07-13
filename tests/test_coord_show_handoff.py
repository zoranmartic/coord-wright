"""Regression tests for `coord show --handoff` rendering of list-shaped frontmatter fields.

Before the fix in this PR, `acceptance` and `verify_commands` were read with
`fm.get(field) or []` and iterated. When the frontmatter authored those fields
as a YAML scalar string instead of a list, the iteration walked the string
character by character. These tests lock in the correct list-coercion behavior
for both list and scalar inputs.
"""

import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"


class CoordShowHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Coord Test"], cwd=self.root, check=True)
        (self.root / "tasks").mkdir()
        (self.root / "tasks" / "archive").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_task(self, task_id, acceptance_yaml, verify_yaml=""):
        body = textwrap.dedent("""\
            ## Task parameters

            ## Scope notes

            ## Plan
            placeholder

            ## Acceptance test
            placeholder
            """)
        lines = [
            "---",
            f"id: {task_id}",
            "task: Handoff render test",
            "status: pending",
            "assigned: codex",
            "round: 1",
            "created: 2026-05-16T00:00:00Z",
            "updated: 2026-05-16T00:00:00Z",
        ]
        if acceptance_yaml:
            lines.append(acceptance_yaml.rstrip("\n"))
        if verify_yaml:
            lines.append(verify_yaml.rstrip("\n"))
        lines.append("---")
        lines.append(body)
        path = self.root / "tasks" / f"{task_id}.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def run_handoff(self, task_id):
        result = subprocess.run(
            ["python3", str(COORD), "show", task_id, "--handoff"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def test_acceptance_as_list_renders_one_bullet_per_item(self):
        acceptance = textwrap.dedent("""\
            acceptance:
              - first item
              - second item with spaces
              - third item""")
        self.write_task("t-list", acceptance)
        out = self.run_handoff("t-list")
        self.assertIn("acceptance:\n  - first item\n  - second item with spaces\n  - third item", out)

    def test_acceptance_as_scalar_string_renders_as_single_bullet(self):
        # Regression: previously rendered one bullet per character because the
        # iteration walked the string instead of coercing it to [string].
        acceptance = "acceptance: Findings file with multiple sentences. Each sentence ends with a period."
        self.write_task("t-scalar", acceptance)
        out = self.run_handoff("t-scalar")
        self.assertIn(
            "acceptance:\n  - Findings file with multiple sentences. Each sentence ends with a period.",
            out,
        )
        self.assertNotIn("  - F\n  - i\n  - n", out)  # the regression signature

    def test_acceptance_absent_omits_section(self):
        self.write_task("t-empty", "")
        out = self.run_handoff("t-empty")
        self.assertNotIn("acceptance:", out)

    def test_verify_commands_scalar_string_renders_as_single_bullet(self):
        # Same coercion behavior must apply to verify_commands.
        verify = "verify_commands: bash tests/test_thing.sh"
        self.write_task("t-verify-scalar", "", verify)
        out = self.run_handoff("t-verify-scalar")
        self.assertIn("verify_commands:\n  - bash tests/test_thing.sh", out)
        self.assertNotIn("  - b\n  - a\n  - s\n  - h", out)


if __name__ == "__main__":
    unittest.main()
