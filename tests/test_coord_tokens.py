import json
import os
import shlex
import subprocess
import tempfile
import textwrap
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"
COORD_TOKENS = ROOT / "bin" / "coord-tokens.sh"


class CoordTokenTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=self.root, check=True)
        subprocess.run(["git", "config", "user.name", "Coord Test"], cwd=self.root, check=True)
        origin = self.root / ".coord-test-origin.git"
        subprocess.run(["git", "init", "--bare", str(origin)], cwd=self.root, check=True, capture_output=True)
        (self.root / ".gitignore").write_text(".coord-test-origin.git/\n.coord/\n", encoding="utf-8")
        (self.root / "tasks").mkdir()
        (self.root / "tasks" / "archive").mkdir()
        (self.root / "tasks" / ".gitkeep").write_text("", encoding="utf-8")
        (self.root / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
        subprocess.run(["git", "add", ".gitignore", "tasks/.gitkeep", "tasks/archive/.gitkeep"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=self.root, check=True)
        subprocess.run(["git", "push", "-u", "origin", "main"], cwd=self.root, check=True, capture_output=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_task(self, task_id, frontmatter="", body=None, archive=False):
        base = self.root / "tasks" / "archive" if archive else self.root / "tasks"
        path = base / f"{task_id}.md"
        lines = [
            "---",
            f"id: {task_id}",
            "task: Token telemetry test",
            "status: pending",
            "assigned: codex",
            "complexity: simple",
            "kind: code-fix",
            "reasoning_effort: medium",
            "acceptance:",
            "  - Token telemetry fixture completes.",
            "round: 1",
            "created: 2026-05-09T00:00:00Z",
            "updated: 2026-05-09T00:00:00Z",
        ]
        if frontmatter.strip():
            lines.extend(frontmatter.strip().splitlines())
        task_body = body if body is not None else self.default_body()
        if "## Plan" not in task_body:
            task_body = task_body.rstrip() + "\n\n## Plan\nRun the focused token fixture path.\n"
        if "## Acceptance test" not in task_body:
            task_body = task_body.rstrip() + "\n\n## Acceptance test\nToken telemetry fixture completes.\n"
        lines.extend(["---", task_body])
        content = "\n".join(lines)
        path.write_text(content, encoding="utf-8")
        return path

    def default_body(self):
        return textwrap.dedent("""\
        ## Task parameters

        ## Scope notes

        ## Rules

        ## Open issues
        """)

    def write_handoff(self, task_id, sub_id):
        """Create the deterministic handoff file required by `--complete-subtask`."""
        sub_dir = self.root / ".coord" / "handoffs" / task_id
        sub_dir.mkdir(parents=True, exist_ok=True)
        path = sub_dir / f"{sub_id.upper()}.md"
        path.write_text(f"# {sub_id.upper()} handoff — {task_id}\nFixture handoff body.\n", encoding="utf-8")
        return path

    def run_coord_raw(self, *args):
        return subprocess.run(
            ["python3", str(COORD), *args],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def run_coord(self, *args):
        result = self.run_coord_raw(*args)
        result.check_returncode()
        return result

    def worker_token_reporter_script(self):
        text = (ROOT / "worker" / "worker.sh").read_text(encoding="utf-8")
        marker = 'python3 - "$TMPOUT" "$ID" "$TOOLS" "$PROJ" "$AGENT"'
        start = text.index(marker)
        start = text.index("<<'PYEOF'", start)
        start = text.index("\n", start) + 1
        end = text.index("\nPYEOF", start)
        return text[start:end]

    def valid_subtasks(self):
        return textwrap.dedent("""\
        - [ ] **S1: First pass**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Do the first focused pass.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
          Handoff to S2: artifact name and entry point so the second pass can pick up without re-discovering the first.

        - [ ] **S2: Second pass**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Do the second focused pass.
          Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
          Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
        """)

    def yaml_style_subtasks(self):
        return textwrap.dedent("""\
        - title: Bad shape
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          body: Do not accept this.
        """)

    def broad_review_subtasks(self):
        return textwrap.dedent("""\
        - [ ] **S1: Run full verification suite and audit ios/ and backend/**
          complexity: complex
          model_claude: opus
          model_codex: gpt-5.5
          Run the full verification suite, audit ios/ and backend/ against docs/mobileApp.md, open the app on simulator, exercise all five tabs, and create coord fix tasks for every gap found.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
        """)

    def mixed_fix_task_subtasks(self):
        return textwrap.dedent("""\
        - [ ] **S1: Audit backend contracts and create fix tasks**
          complexity: simple
          model_claude: sonnet
          model_codex: gpt-5.5
          Audit backend/ contract failures and create coord fix tasks for every FAIL item discovered in the same pass.
          Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
        """)

    def test_new_accepts_valid_s_checkbox_subtasks(self):
        result = self.run_coord(
            "new",
            "--task=Valid subtask creation",
            "--complexity=simple",
            "--kind=code-fix",
            f"--set-subtasks={self.valid_subtasks()}",
        )
        task_id = result.stdout.strip().splitlines()[-1]

        next_result = self.run_coord("next-subtask", task_id)

        self.assertTrue(next_result.stdout.startswith("S1\tFirst pass\t"))

    def test_new_allows_plain_shaping_task_without_subtasks(self):
        result = self.run_coord(
            "new",
            "--task=Draft task for later shaping",
            "--complexity=simple",
            "--kind=code-fix",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        path = next((self.root / "tasks").glob(f"{task_id}.md"))

        text = path.read_text(encoding="utf-8")
        self.assertIn("status: shaping", text)
        self.assertIn("_Paths or notes on what to read/change._", text)

    def test_new_plain_shaping_task_defaults_to_codex(self):
        result = self.run_coord(
            "new",
            "--task=Draft task default assignment",
            "--complexity=simple",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        path = next((self.root / "tasks").glob(f"{task_id}.md"))

        text = path.read_text(encoding="utf-8")
        self.assertIn("status: shaping", text)
        self.assertIn("assigned: codex", text)

    def test_new_runnable_task_without_kind_is_rejected(self):
        result = self.run_coord_raw(
            "new",
            "--task=Runnable missing kind",
            "--status=pending",
            "--complexity=simple",
            "--reasoning-effort=medium",
            f"--set-subtasks={self.valid_subtasks()}",
            "--set-plan=Run the focused fixture path.",
            "--acceptance=Done",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing kind", result.stderr)

    def test_new_code_fix_kind_defaults_to_codex(self):
        result = self.run_coord(
            "new",
            "--task=Code fix default assignment",
            "--complexity=simple",
            "--kind=code-fix",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        path = next((self.root / "tasks").glob(f"{task_id}.md"))

        self.assertIn("assigned: codex", path.read_text(encoding="utf-8"))

    def test_new_review_design_and_sql_diagnostic_kinds_default_to_codex(self):
        for kind in ("review", "design", "sql-diagnostic"):
            with self.subTest(kind=kind):
                result = self.run_coord(
                    "new",
                    f"--task={kind} default assignment",
                    "--complexity=simple",
                    f"--kind={kind}",
                )
                task_id = result.stdout.strip().splitlines()[-1]
                path = next((self.root / "tasks").glob(f"{task_id}.md"))

                self.assertIn("assigned: codex", path.read_text(encoding="utf-8"))

    def test_new_explicit_assigned_claude_still_routes_to_claude(self):
        result = self.run_coord(
            "new",
            "--task=Explicit claude assignment",
            "--complexity=simple",
            "--assigned=claude",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        path = next((self.root / "tasks").glob(f"{task_id}.md"))

        self.assertIn("assigned: claude", path.read_text(encoding="utf-8"))

    def test_new_explicit_architect_role_still_routes_to_claude(self):
        result = self.run_coord(
            "new",
            "--task=Explicit claude architect",
            "--complexity=simple",
            "--roles=architect:claude,coder:codex,reviewer:claude",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        path = next((self.root / "tasks").glob(f"{task_id}.md"))

        text = path.read_text(encoding="utf-8")
        self.assertIn("assigned: claude", text)
        self.assertIn("architect: claude", text)

    def test_new_rejects_runnable_task_without_subtasks(self):
        result = self.run_coord_raw(
            "new",
            "--task=Runnable task needs subtasks",
            "--status=pending",
            "--complexity=simple",
            "--kind=code-fix",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("subtask block is empty", result.stderr)
        self.assertEqual(list((self.root / "tasks").glob("*.md")), [])

    def test_solo_no_longer_bypasses_runnable_shape(self):
        result = self.run_coord_raw(
            "new",
            "--task=Solo still needs shaping",
            "--status=pending",
            "--solo",
            "--complexity=simple",
            "--kind=code-fix",
            "--reasoning-effort=medium",
            "--acceptance=Done",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("subtask block is empty", result.stderr)

    def test_overnight_no_longer_bypasses_runnable_shape(self):
        result = self.run_coord_raw(
            "new",
            "--task=Overnight still needs shaping",
            "--status=pending",
            "--overnight",
            "--complexity=simple",
            "--kind=code-fix",
            "--reasoning-effort=medium",
            "--acceptance=Done",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("subtask block is empty", result.stderr)

    def test_new_rejects_yaml_style_subtasks(self):
        result = self.run_coord_raw(
            "new",
            "--task=Reject yaml subtasks",
            "--complexity=simple",
            "--kind=code-fix",
            f"--set-subtasks={self.yaml_style_subtasks()}",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("YAML-style subtask blocks are not allowed", result.stderr)
        self.assertEqual(list((self.root / "tasks").glob("*.md")), [])

    def test_new_rejects_broad_all_in_one_review_subtask(self):
        result = self.run_coord_raw(
            "new",
            "--task=Reject broad review subtasks",
            "--complexity=complex",
            "--kind=review",
            f"--set-subtasks={self.broad_review_subtasks()}",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("audits iOS and backend in one subtask", result.stderr)
        self.assertIn("mixes execution modes", result.stderr)
        self.assertEqual(list((self.root / "tasks").glob("*.md")), [])

    def test_update_rejects_fix_task_creation_bundled_with_audit(self):
        path = self.write_task("2026-05-09-reject-mixed-fix-task")
        before = path.read_text(encoding="utf-8")

        result = self.run_coord_raw(
            "update",
            "2026-05-09-reject-mixed-fix-task",
            f"--set-subtasks={self.mixed_fix_task_subtasks()}",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mixes fix-task creation with other work", result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_update_rejects_yaml_style_subtasks_without_mutating_task(self):
        path = self.write_task(
            "2026-05-09-reject-yaml-update",
            body=textwrap.dedent("""\
            ## Task parameters

            ## Scope notes

            - [ ] **S1: Existing**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Keep this.

            ## Rules

            ## Open issues
            """),
        )
        before = path.read_text(encoding="utf-8")

        result = self.run_coord_raw(
            "update",
            "2026-05-09-reject-yaml-update",
            f"--set-subtasks={self.yaml_style_subtasks()}",
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("YAML-style subtask blocks are not allowed", result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_update_strips_legacy_yaml_subtasks_when_replacing_checklist(self):
        path = self.write_task(
            "2026-05-09-strip-legacy-yaml-prefix",
            body=textwrap.dedent("""\
            ## Task parameters

            ## Scope notes

            Keep this setup note.

            - title: Legacy bad shape
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              notes: Remove this.

            - [ ] **S1: Existing checkbox**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Replace this too.

            ## Rules

            ## Open issues
            """),
        )

        self.run_coord("update", "2026-05-09-strip-legacy-yaml-prefix", f"--set-subtasks={self.valid_subtasks()}")

        text = path.read_text(encoding="utf-8")
        self.assertIn("Keep this setup note.", text)
        self.assertNotIn("- title:", text)
        self.assertNotIn("Legacy bad shape", text)
        self.assertNotIn("Existing checkbox", text)
        self.assertIn("S1: First pass", text)
        self.assertIn("S2: Second pass", text)

    def test_promote_rejects_malformed_shaping_task(self):
        path = self.write_task(
            "2026-05-09-bad-shaping-task",
            "status: shaping",
            body=textwrap.dedent("""\
            ## Task parameters

            ## Scope notes

            - title: Bad shape
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              body: Do not accept this.

            ## Rules

            ## Open issues
            """),
        )

        result = self.run_coord_raw("promote", "2026-05-09-bad-shaping-task", "--status=pending")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("YAML-style subtask blocks are not allowed", result.stderr)
        self.assertIn("status: shaping", path.read_text(encoding="utf-8"))

    def test_promote_rejects_broad_shaping_task(self):
        path = self.write_task(
            "2026-05-09-broad-shaping-task",
            "status: shaping",
            body=(
                "## Task parameters\n\n"
                "## Scope notes\n\n"
                f"{self.broad_review_subtasks().strip()}\n\n"
                "## Rules\n\n"
                "## Open issues\n"
            ),
        )

        result = self.run_coord_raw("promote", "2026-05-09-broad-shaping-task", "--status=pending")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mixes execution modes", result.stderr)
        self.assertIn("status: shaping", path.read_text(encoding="utf-8"))

    def test_add_tokens_codex_renders_row(self):
        path = self.write_task("2026-05-09-codex-row")
        payload = json.dumps({"input": 12, "output": 5, "cache_read": 3, "effective": 17})

        self.run_coord("update", "2026-05-09-codex-row", f"--add-tokens-codex={payload}")

        text = path.read_text(encoding="utf-8")
        self.assertIn("token_log:", text)
        self.assertIn("R1:codex:12:5:3:17:", text)
        # Table format: (round=1, subtask="", agent=codex, input=12, output=5, cache_read=3, effective=17)
        self.assertRegex(text, r"\|\s*1\s*\|\s*\|\s*codex\s*\|\s*12\s*\|\s*5\s*\|\s*3\s*\|\s*17\s*\|")

    def test_add_tokens_codex_without_remote_updates_task(self):
        subprocess.run(["git", "remote", "remove", "origin"], cwd=self.root, check=True, capture_output=True)
        path = self.write_task("2026-05-09-no-remote-tokens")
        payload = json.dumps({"input": 100, "output": 10, "cache_read": 0, "effective": 160})

        result = self.run_coord_raw(
            "update",
            "2026-05-09-no-remote-tokens",
            f"--add-tokens-codex={payload}",
            "--subtask=S1",
        )

        self.assertEqual(result.returncode, 0)
        self.assertIn("updated 2026-05-09-no-remote-tokens", result.stdout)
        text = path.read_text(encoding="utf-8")
        self.assertIn("token_log:", text)

    def test_token_stage_labels_render_and_sort_after_subtasks(self):
        path = self.write_task(
            "2026-05-09-stage-sort",
            frontmatter=textwrap.dedent("""\
            token_log:
              - R1:fix:codex:50:5:0:55:1778930000
              - R1:S2:codex:20:2:0:22:1778930000
              - R1:code:codex:40:4:0:44:1778930000
              - R1:S1:codex:10:1:0:11:1778930000
              - R1:codex:5:1:0:6:1778930000
              - R1:review:claude:60:6:0:66:1778930000
            """),
        )

        self.run_coord(
            "update",
            "2026-05-09-stage-sort",
            "--add-token-warning=missing-usage",
            "--add-token-warning-agent=codex",
        )

        text = path.read_text(encoding="utf-8")
        rows = [line for line in text.splitlines() if line.startswith("|     1 |")]
        stages = [line.split("|")[2].strip() for line in rows]
        self.assertEqual(stages, ["", "S1", "S2", "code", "fix", "review"])
        self.assertIn("|     1 | code    | codex", text)
        self.assertIn("|     1 | fix     | codex", text)

    def test_cache_only_row_renders_warning_metadata(self):
        path = self.write_task("2026-05-09-cache-only")
        payload = json.dumps({
            "input": 0,
            "output": 0,
            "cache_read": 42,
            "effective": 0,
            "warnings": ["cache-only"],
        })

        self.run_coord("update", "2026-05-09-cache-only", f"--add-tokens-codex={payload}")

        text = path.read_text(encoding="utf-8")
        self.assertIn("token_warnings:", text)
        self.assertIn("R1:codex:cache-only:", text)
        self.assertIn("_Warnings:_", text)
        self.assertIn("R1 codex: cache-read tokens without input/output", text)

    def test_suspicious_payload_flags_are_inferred(self):
        path = self.write_task("2026-05-09-inferred-warning")
        payload = json.dumps({
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "effective": 0,
            "missing_usage": True,
            "agent_visible_work": True,
        })

        self.run_coord("update", "2026-05-09-inferred-warning", f"--add-tokens-claude={payload}")

        text = path.read_text(encoding="utf-8")
        self.assertIn("R1:claude:missing-usage:", text)
        self.assertIn("R1:claude:all-zero:", text)
        self.assertIn("R1:claude:output-zero-with-work:", text)

    def test_worker_claude_token_parser_uses_anthropic_formula(self):
        # Regression: the wrapper used to apply the Codex formula for both
        # agents, so Claude rounds were written with `input + 6*output +
        # cache_read/10` and cache_create entirely ignored. Lock in that the
        # Claude branch uses Anthropic's API-parity formula:
        #   input + 5*output + cache_read/10 + cache_create*5/4
        # Codex review's exact reproduction case: input=100, output=40,
        # cache_read=200, cache_create=80 should produce 420
        # (100 + 200 + 20 + 100), not 360 (the buggy Codex-formula result).
        path = self.write_task("2026-05-09-worker-claude-usage")
        tmpout = self.root / "claude-result.json"
        tmpout.write_text(json.dumps({
            "result": "Claude produced visible work.",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 40,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 80,
            },
        }) + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                "python3",
                "-",
                str(tmpout),
                "2026-05-09-worker-claude-usage",
                str(ROOT),
                str(self.root),
                "claude",
                "S1",
                "coder",
            ],
            input=self.worker_token_reporter_script(),
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

        text = path.read_text(encoding="utf-8")
        self.assertIn("tokens reported for 2026-05-09-worker-claude-usage (claude S1)", result.stdout)
        # Claude effective: 100 + 5*40 + 200//10 + (80*5)//4
        #                 = 100 + 200 + 20 + 100 = 420.
        self.assertIn("R1:S1:claude:100:40:200:420:", text)

    def test_worker_codex_token_parser_deducts_cached_input(self):
        path = self.write_task("2026-05-09-worker-codex-usage")
        tmpout = self.root / "codex-turn.jsonl"
        tmpout.write_text(json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": 20671,
                "cached_input_tokens": 11648,
                "output_tokens": 481,
            },
        }) + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                "python3",
                "-",
                str(tmpout),
                "2026-05-09-worker-codex-usage",
                str(ROOT),
                str(self.root),
                "codex",
                "S1",
                "coder",
            ],
            input=self.worker_token_reporter_script(),
            cwd=self.root,
            text=True,
            capture_output=True,
            check=True,
        )

        text = path.read_text(encoding="utf-8")
        self.assertIn("tokens reported for 2026-05-09-worker-codex-usage (codex S1)", result.stdout)
        # Effective via worker.sh codex GPT-5.5 formula:
        # 9023 + 6*481 + 11648//10 = 13073
        self.assertIn("R1:S1:codex:9023:481:11648:13073:", text)

    def test_archived_task_can_receive_token_warning(self):
        path = self.write_task(
            "2026-05-09-archived-warning",
            "status: done\ncompleted: 2026-05-09T00:00:00Z",
            archive=True,
        )

        self.run_coord(
            "update",
            "2026-05-09-archived-warning",
            "--add-token-warning=missing-usage",
            "--add-token-warning-agent=codex",
        )

        text = path.read_text(encoding="utf-8")
        self.assertIn("token_warnings:", text)
        self.assertIn("_Warnings:_", text)
        self.assertIn("R1 codex: usage data missing", text)

    def test_set_subtasks_replaces_completed_existing_checklist(self):
        path = self.write_task(
            "2026-05-09-replace-completed-subtasks",
            body=textwrap.dedent("""\
            ## Task parameters

            ## Scope notes

            Carry this note forward.

            /tmp/strategy-template-subtasks.txt
            /tmp/strategy-template-subtasks-s5-complete.txt

            - [x] **S1: Old completed**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Old completed work.

            - [x] **S2: Also completed**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              More old work.

            ## Rules

            ## Open issues
            """),
        )
        replacement = textwrap.dedent("""\
            - [x] **S1: Replacement completed**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Keep the completed state.
              Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
              Handoff to S2: artifact name and entry point so S2 picks up from the completed slice.

            - [ ] **S2: Replacement pending**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Continue here.
              Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
              Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
            """)

        self.run_coord("update", "2026-05-09-replace-completed-subtasks", f"--set-subtasks={replacement}")

        text = path.read_text(encoding="utf-8")
        self.assertIn("Carry this note forward.", text)
        self.assertNotIn("/tmp/strategy-template-subtasks.txt", text)
        self.assertNotIn("/tmp/strategy-template-subtasks-s5-complete.txt", text)
        self.assertIn("S1: Replacement completed", text)
        self.assertIn("S2: Replacement pending", text)
        self.assertNotIn("S1: Old completed", text)
        self.assertNotIn("S2: Also completed", text)
        self.assertEqual(text.count("**S1:"), 1)
        self.assertEqual(text.count("**S2:"), 1)

    def test_token_audit_flags_archived_missing_codex_row(self):
        self.write_task(
            "2026-05-09-missing-codex-row",
            textwrap.dedent("""\
            status: done
            completed: 2026-05-09T00:00:00Z
            roles:
              coder: codex
              reviewer: claude
            """),
            archive=True,
        )

        result = self.run_coord("token-audit", "--include-archive")

        self.assertIn("missing-codex-row", result.stdout)
        self.assertIn("2026-05-09-missing-codex-row", result.stdout)

    def test_pickup_resolves_claude_architect_model_alias(self):
        self.write_task(
            "2026-05-09-claude-model",
            textwrap.dedent("""\
            assigned: claude
            model_claude: sonnet
            reasoning_effort_architect: high
            roles:
              architect: claude
              coder: codex
              reviewer: claude
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: simple
              model_claude: haiku
              model_codex: gpt-5.5
              Do it.

            ## Claude findings

            _No findings yet._
            """),
        )

        result = self.run_coord("pickup", "--assigned=claude")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["round_role"], "architect")
        self.assertEqual(payload["resolved_model"], "claude-sonnet-5")
        self.assertEqual(payload["resolved_model_source"], "model_claude")
        self.assertEqual(payload["resolved_reasoning_effort"], "high")

    def test_pickup_keeps_failed_architect_retry_on_architect_role(self):
        self.write_task(
            "2026-05-09-claude-architect-retry",
            textwrap.dedent("""\
            assigned: claude
            model_claude: sonnet
            roles:
              architect: claude
              coder: codex
              reviewer: claude
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: trivial
              model_claude: haiku
              model_codex: gpt-5.5
              Do it.

            ## Claude findings

            ### Round 1

            Worker surfaced agent failure.

            ## Codex findings

            _No findings yet._
            """),
        )

        result = self.run_coord("pickup", "--assigned=claude")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["round_role"], "architect")
        self.assertEqual(payload["resolved_model"], "claude-sonnet-5")
        self.assertEqual(payload["resolved_model_source"], "model_claude")

    def test_precheck_does_not_run_needs_brainstorming(self):
        self.write_task(
            "2026-05-09-brainstorming",
            textwrap.dedent("""\
            status: needs-brainstorming
            assigned: claude
            """),
        )

        result = self.run_coord("precheck", "--assigned=claude")

        self.assertIn("skip\tNo active task for claude", result.stdout)

    def test_empty_inline_depends_on_does_not_block_pickup(self):
        self.write_task(
            "2026-05-09-empty-depends-on",
            textwrap.dedent("""\
            depends_on: []
            """),
        )

        precheck = self.run_coord("precheck", "--assigned=codex")
        pickup = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(pickup.stdout)

        self.assertIn("run\tFound runnable task: 2026-05-09-empty-depends-on", precheck.stdout)
        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["pickup"]["id"], "2026-05-09-empty-depends-on")

    def test_new_omits_empty_depends_on_literal(self):
        result = self.run_coord(
            "new",
            "--task=No empty dependency field",
            "--status=pending",
            "--complexity=simple",
            "--kind=code-fix",
            "--reasoning-effort=medium",
            f"--set-subtasks={self.valid_subtasks()}",
            "--set-plan=Run the focused fixture path.",
            "--acceptance=Done",
            "--depends-on=[]",
        )
        task_id = result.stdout.strip().splitlines()[-1]
        text = (self.root / "tasks" / f"{task_id}.md").read_text(encoding="utf-8")

        self.assertNotIn("depends_on", text)

    def test_pickup_resolves_codex_subtask_model(self):
        self.write_task(
            "2026-05-09-codex-model",
            textwrap.dedent("""\
            model_codex: gpt-5.5
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: simple
              model_claude: haiku
              model_codex: gpt-5.3-codex-spark
              Do it.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["round_role"], "coder")
        self.assertEqual(payload["resolved_model"], "gpt-5.3-codex-spark")
        self.assertEqual(payload["resolved_model_source"], "subtask.model_codex")
        self.assertEqual(payload["current_subtask"]["id"], "S1")

    def test_codex_policy_routes_subtask_success_to_configured_reviewer(self):
        self.write_task(
            "2026-05-09-codex-reviewer-handoff",
            textwrap.dedent("""\
            roles:
              architect: skip
              coder: codex
              reviewer: claude
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "subtask")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=needs-review", command)
        self.assertIn("--assigned=claude", command)

    def test_codex_policy_without_explicit_reviewer_completes_last_subtask_directly(self):
        self.write_task(
            "2026-05-09-codex-implicit-review",
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "subtask")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=review-passed", command)
        # No --force on the normal close path: the cmd_update close gate verifies
        # every subtask is [x] before allowing done; --force is reserved for
        # human escape hatches (cancel a stuck task), not normal handoff.
        self.assertNotIn("--force", command)
        self.assertIn("--complete-subtask=S1", command)
        self.assertNotIn("needs-review", command)

    def test_codex_policy_without_explicit_reviewer_keeps_multi_subtask_task_pending(self):
        self.write_task(
            "2026-05-09-codex-implicit-review-more-work",
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.

            - [ ] **S2: Second**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it next.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "subtask")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=pending", command)
        self.assertIn("--assigned=codex", command)
        self.assertIn("--complete-subtask=S1", command)
        self.assertNotIn("needs-review", command)

    def test_codex_policy_without_explicit_reviewer_completes_coder_work_directly(self):
        self.write_task(
            "2026-05-09-codex-implicit-review-no-subtask",
            body=textwrap.dedent("""\
            ## Scope notes

            Implement the scoped work.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "coder")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=review-passed", command)
        # No --force: a task with no subtasks has nothing to gate; the close
        # path is naturally permitted by the cmd_update gate.
        self.assertNotIn("--force", command)
        self.assertNotIn("needs-review", command)

    def test_codex_policy_with_explicit_reviewer_routes_no_subtask_work_to_review(self):
        self.write_task(
            "2026-05-09-codex-explicit-review-no-subtask",
            textwrap.dedent("""\
            roles:
              coder: codex
              reviewer: claude
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            Implement the scoped work.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "coder")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=needs-review", command)
        self.assertIn("--assigned=claude", command)
        self.assertNotIn("--status=review-passed", command)

    def test_codex_policy_with_invalid_reviewer_surfaces_brainstorming(self):
        self.write_task(
            "2026-05-09-codex-invalid-reviewer",
            textwrap.dedent("""\
            roles:
              coder: codex
              reviewer: clude
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: Example**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)
        command = payload["codex_execution_policy"]["success_update"]["command"]

        self.assertIn("--status=needs-brainstorming", command)
        self.assertNotIn("--status=review-passed", command)
        self.assertNotIn("--status=needs-review", command)

    def test_pickup_rejects_task_id_with_shell_metacharacters(self):
        bad_id = "2026-05-16-safe; touch /tmp/coord-security-proof #"
        path = self.root / "tasks" / "bad-id.md"
        path.write_text(textwrap.dedent(f"""\
        ---
        id: {bad_id}
        task: Bad id proof
        status: pending
        assigned: codex
        round: 1
        ---
        ## Scope notes

        Implement the task.
        """), encoding="utf-8")

        result = self.run_coord_raw("pickup", "--assigned=codex")

        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout, "")
        self.assertIn("pickup: invalid task id", result.stderr)
        self.assertIn(bad_id, result.stderr)
        self.assertIn("tasks/bad-id.md", result.stderr)

    def test_success_update_task_id_round_trips_through_shlex_split(self):
        task_id = "2026-05-16-safe"
        self.write_task(
            task_id,
            body=textwrap.dedent("""\
            ## Scope notes

            Implement the task.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)
        command = payload["codex_execution_policy"]["success_update"]["command"]
        argv = shlex.split(command.replace("@<file>", "/tmp/finding.txt"))

        self.assertEqual(payload["decision"], "run")
        self.assertNotIn(";", command)
        self.assertEqual(argv[:3], ["python3", str(COORD), "update"])
        self.assertEqual(argv[3], task_id)
        self.assertEqual(argv.count(task_id), 1)

    def test_update_complete_subtask_marks_checkbox(self):
        path = self.write_task(
            "2026-05-09-complete-subtask",
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.

            - [ ] **S2: Second**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it next.
            """),
        )
        self.write_handoff("2026-05-09-complete-subtask", "S1")

        self.run_coord("update", "2026-05-09-complete-subtask", "--complete-subtask=S1")

        text = path.read_text(encoding="utf-8")
        self.assertIn("- [x] **S1: First**", text)
        self.assertIn("- [ ] **S2: Second**", text)

    def test_update_complete_subtask_rejects_malformed_values_without_mutation(self):
        path = self.write_task(
            "2026-05-09-complete-subtask-malformed",
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
            """),
        )
        before = path.read_text(encoding="utf-8")

        for value in ("1", "S", ""):
            with self.subTest(value=value):
                result = self.run_coord_raw("update", "2026-05-09-complete-subtask-malformed", f"--complete-subtask={value}")

                self.assertNotEqual(result.returncode, 0)
                self.assertIn(value or "<empty>", result.stderr)
                self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_update_complete_subtask_rejects_already_completed_without_mutation(self):
        path = self.write_task(
            "2026-05-09-complete-subtask-already-done",
            body=textwrap.dedent("""\
            ## Scope notes

            - [x] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Done.
            """),
        )
        before = path.read_text(encoding="utf-8")

        result = self.run_coord_raw("update", "2026-05-09-complete-subtask-already-done", "--complete-subtask=S1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S1 is not an incomplete subtask", result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_update_complete_subtask_rejects_missing_scope_subtasks_without_mutation(self):
        path = self.write_task(
            "2026-05-09-complete-subtask-no-scope",
            body=textwrap.dedent("""\
            ## Task parameters

            ## Rules

            ## Open issues
            """),
        )
        before = path.read_text(encoding="utf-8")

        result = self.run_coord_raw("update", "2026-05-09-complete-subtask-no-scope", "--complete-subtask=S1")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S1 is not an incomplete subtask", result.stderr)
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_update_terminal_completion_applies_subtask_before_done_guard(self):
        path = self.write_task(
            "2026-05-09-complete-last-subtask",
            "status: codex-working",
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
            """),
        )
        self.write_handoff("2026-05-09-complete-last-subtask", "S1")

        self.run_coord("update", "2026-05-09-complete-last-subtask", "--status=review-passed", "--complete-subtask=S1")

        archived = self.root / "tasks" / "archive" / "2026-05-09-complete-last-subtask.md"
        self.assertFalse(path.exists())
        self.assertTrue(archived.exists())
        text = archived.read_text(encoding="utf-8")
        self.assertIn("status: done", text)
        self.assertIn("- [x] **S1: First**", text)

    def test_codex_policy_routes_architect_success_to_configured_coder(self):
        self.write_task(
            "2026-05-09-codex-architect-handoff",
            textwrap.dedent("""\
            roles:
              architect: codex
              coder: claude
              reviewer: codex
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            Decide the implementation split.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["round_role"], "architect")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "architect")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=pending", command)
        self.assertIn("--assigned=claude", command)

    def test_codex_reviewer_pickup_uses_reviewer_policy(self):
        self.write_task(
            "2026-05-09-codex-reviewer-policy",
            textwrap.dedent("""\
            status: needs-review
            assigned: codex
            roles:
              architect: claude
              coder: claude
              reviewer: codex
            """),
            body=textwrap.dedent("""\
            ## Scope notes

            Review the completed Claude work.
            """),
        )

        result = self.run_coord("pickup", "--assigned=codex")
        payload = json.loads(result.stdout)

        self.assertEqual(payload["decision"], "run")
        self.assertEqual(payload["round_role"], "reviewer")
        self.assertEqual(payload["codex_execution_policy"]["work_mode"], "reviewer")
        command = payload["codex_execution_policy"]["success_update"]["command"]
        self.assertIn("--status=review-passed", command)

    def run_codex_success_command(self, command, finding_text="done", task_id=None):
        # Production coord-check marks `codex-working` before running the
        # success command. Mirror that here so the transition table accepts
        # the success_cmd without needing --force.
        if task_id:
            mark = subprocess.run(
                ["python3", str(COORD), "update", task_id, "--status=codex-working"],
                cwd=self.root,
                text=True,
                capture_output=True,
            )
            if mark.returncode != 0 and "no-op is always fine" not in mark.stderr:
                # Best-effort: if the prev status isn't pending (e.g. already
                # working), let the success command itself surface the issue.
                pass
        finding = self.root / "finding.txt"
        finding.write_text(finding_text, encoding="utf-8")
        resolved = command.replace("@<file>", f"@{finding}")
        result = subprocess.run(
            shlex.split(resolved),
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        result.check_returncode()
        return result

    def test_codex_multi_subtask_success_chain_requeues_then_completes(self):
        task_id = "2026-05-09-codex-subtask-chain"
        path = self.write_task(
            task_id,
            body=textwrap.dedent("""\
            ## Scope notes

            - [ ] **S1: First**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it.
              Writes handoff: `.coord/handoffs/<task-id>/S1.md`.
              Handoff to S2: name the artifact so the second pass can pick up without re-discovering the first.

            - [ ] **S2: Second**
              complexity: simple
              model_claude: sonnet
              model_codex: gpt-5.5
              Do it next.
              Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
              Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
            """),
        )

        first_pickup = json.loads(self.run_coord("pickup", "--assigned=codex").stdout)
        self.assertEqual(first_pickup["current_subtask"]["id"], "S1")
        self.write_handoff(task_id, "S1")
        self.run_codex_success_command(first_pickup["codex_execution_policy"]["success_update"]["command"], "S1 done", task_id=task_id)

        text = path.read_text(encoding="utf-8")
        self.assertIn("status: pending", text)
        self.assertIn("- [x] **S1: First**", text)
        self.assertIn("- [ ] **S2: Second**", text)

        second_pickup = json.loads(self.run_coord("pickup", "--assigned=codex").stdout)
        self.assertEqual(second_pickup["current_subtask"]["id"], "S2")
        self.write_handoff(task_id, "S2")
        self.run_codex_success_command(second_pickup["codex_execution_policy"]["success_update"]["command"], "S2 done", task_id=task_id)

        archived = self.root / "tasks" / "archive" / f"{task_id}.md"
        self.assertTrue(archived.exists())
        text = archived.read_text(encoding="utf-8")
        self.assertIn("status: done", text)
        self.assertIn("- [x] **S1: First**", text)
        self.assertIn("- [x] **S2: Second**", text)


class CoordTokensShellTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def day_dir(self, day=None):
        day = day or datetime.now()
        path = self.home / ".codex" / "sessions" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_rollout(self, name, events, *, mtime=None):
        path = self.day_dir() / name
        path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return path

    def token_event(self, input_tokens, cached_input_tokens, output_tokens):
        return {
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": input_tokens,
                        "cached_input_tokens": cached_input_tokens,
                        "output_tokens": output_tokens,
                        "total_tokens": input_tokens + output_tokens,
                    },
                },
            },
        }

    def run_tokens(self, *args):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        return subprocess.run(
            ["bash", str(COORD_TOKENS), *args],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

    def test_codex_count_and_cumulative_delta_from_temp_rollout(self):
        rollout = self.write_rollout(
            "rollout-2026-05-16T00-00-00-test.jsonl",
            [
                self.token_event(100, 20, 5),
                {"type": "event_msg", "payload": {"type": "token_count", "info": None}},
                self.token_event(180, 50, 25),
            ],
        )

        count = self.run_tokens("--agent=codex", "--count").stdout.strip()
        full = json.loads(self.run_tokens("--agent=codex").stdout)
        delta = json.loads(self.run_tokens("--agent=codex", "--since=1").stdout)

        self.assertEqual(count, f"3:{rollout}")
        # Codex GPT-5.5 effective = input + 6*output + cache_read//10
        # full:  130 + 6*25 + 50//10 = 130 + 150 + 5 = 285
        # delta:  50 + 6*20 + 30//10 =  50 + 120 + 3 = 173
        self.assertEqual(full, {
            "input": 130,
            "output": 25,
            "cache_read": 50,
            "cache_create": 0,
            "effective": 285,
            "lines": 3,
        })
        self.assertEqual(delta, {
            "input": 50,
            "output": 20,
            "cache_read": 30,
            "cache_create": 0,
            "effective": 173,
            "lines": 3,
        })

    def test_codex_since_baseline_path_rotation_reads_newest_rollout_from_zero(self):
        old_path = self.write_rollout(
            "rollout-2026-05-16T00-00-00-old.jsonl",
            [self.token_event(100, 20, 5)],
            mtime=100,
        )
        self.write_rollout(
            "rollout-2026-05-16T00-00-00-new.jsonl",
            [self.token_event(20671, 11648, 481)],
            mtime=200,
        )

        payload = json.loads(self.run_tokens("--agent=codex", f"--since=99:{old_path}").stdout)

        # Codex GPT-5.5 effective = 9023 + 6*481 + 11648//10
        #                         = 9023 + 2886 + 1164 = 13073
        self.assertEqual(payload, {
            "input": 9023,
            "output": 481,
            "cache_read": 11648,
            "cache_create": 0,
            "effective": 13073,
            "lines": 1,
        })

    def test_codex_missing_rollout_exits_zero_json(self):
        result = self.run_tokens("--agent=codex")

        self.assertEqual(json.loads(result.stdout), {
            "input": 0,
            "output": 0,
            "cache_read": 0,
            "cache_create": 0,
            "effective": 0,
            "lines": 0,
        })

    def test_codex_coord_stats_js_text_output_reports_corrected_effective(self):
        # Regression: the text path printed raw total_tokens (full-rate cache
        # double-counted), even after the --json formula was corrected. Lock in
        # that the text path now reports the same effective number as --json.
        rollout = self.write_rollout(
            "rollout-2026-05-24T00-00-00-text-effective.jsonl",
            [self.token_event(input_tokens=1000, cached_input_tokens=600, output_tokens=40)],
        )

        text = subprocess.run(
            ["node", str(ROOT / "bin" / "codex-coord-stats.js"), str(rollout)],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.strip()
        json_payload = json.loads(subprocess.run(
            ["node", str(ROOT / "bin" / "codex-coord-stats.js"), "--json", str(rollout)],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout)

        # effective = 400 + 6*40 + 600//10 = 700
        self.assertEqual(json_payload["effective"], 700)
        # Text path should now say "effective", not "total", and the number
        # must match the corrected effective — not the rollout's total_tokens
        # (which would have been 1000 + 40 = 1040).
        self.assertIn("700 effective", text)
        self.assertNotIn("1040 total", text)
        self.assertNotIn("1.0K total", text)

    def test_codex_coord_stats_js_recognizes_snake_case_rate_limits(self):
        # Regression: extractRateLimits only matched camelCase rateLimits /
        # rateLimitsByLimitId, so the current rollout shape
        #   {payload: {rate_limits: {primary: {used_percent, window_minutes}}}}
        # produced no gauge output. Lock in snake_case + primary/secondary
        # + window_minutes recognition.
        rollout = self.write_rollout(
            "rollout-2026-05-24T00-00-00-rate-limits.jsonl",
            [
                self.token_event(input_tokens=100, cached_input_tokens=0, output_tokens=10),
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "rate_limits": {
                            "limit_id": "codex",
                            "limit_name": None,
                            "primary": {
                                "used_percent": 12.0,
                                "window_minutes": 300,
                                "resets_at": 1779572608,
                            },
                            "secondary": {
                                "used_percent": 4.0,
                                "window_minutes": 10080,
                                "resets_at": 1780000000,
                            },
                        },
                    },
                },
            ],
        )

        text = subprocess.run(
            ["node", str(ROOT / "bin" / "codex-coord-stats.js"), str(rollout)],
            cwd=ROOT, text=True, capture_output=True, check=True,
        ).stdout.strip()

        # 300 min = 5h, 10080 min = week.
        self.assertIn("12% used", text)
        self.assertIn("5h", text)
        self.assertIn("4% used", text)
        self.assertIn("week", text)

    def test_codex_coord_stats_js_parses_current_token_count_rollouts(self):
        # Regression: the JS parser previously did not recognize the dominant
        # Codex CLI rollout event shape
        #   {type: "event_msg", payload: {type: "token_count",
        #     info: {total_token_usage: {...}}}}
        # so codex-coord-stats.js returned blank for entire sessions.
        # This test exercises the parser end-to-end and locks the corrected
        # effective formula (same as coord-tokens.sh codex path).
        rollout = self.write_rollout(
            "rollout-2026-05-24T00-00-00-stats-js.jsonl",
            [self.token_event(input_tokens=1000, cached_input_tokens=600, output_tokens=40)],
        )

        result = subprocess.run(
            ["node", str(ROOT / "bin" / "codex-coord-stats.js"), "--json", str(rollout)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertNotEqual(
            result.stdout.strip(), "",
            "codex-coord-stats.js returned blank — parser regression on token_count events",
        )
        payload = json.loads(result.stdout)
        # input is normalized to uncached (1000 - 600 = 400) for parity with
        # coord-tokens.sh. effective = 400 + 6*40 + 600//10 = 400 + 240 + 60 = 700.
        self.assertEqual(payload["input"], 400)
        self.assertEqual(payload["output"], 40)
        self.assertEqual(payload["cache_read"], 600)
        self.assertEqual(payload["effective"], 700)

    def test_claude_effective_formula_weights_output_and_discounts_cache(self):
        # Locks in the Claude effective formula:
        #   input + 5*output + cache_read//10 + cache_create*5//4
        # Anthropic API parity: out=5x, cache_read=0.1x, cache_create=1.25x.
        # Chosen so each term contributes a distinct round number:
        #   100 + 5*40 + 200//10 + 80*5//4 = 100 + 200 + 20 + 100 = 420.
        proj_dir = self.home / ".claude" / "projects" / "-tmp-test-project"
        proj_dir.mkdir(parents=True)
        session = proj_dir / "test-session.jsonl"
        session.write_text(json.dumps({
            "requestId": "req-effective-formula-test",
            "message": {
                "id": "msg-effective",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 40,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 80,
                },
            },
        }) + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["COORD_PROJ_DIR"] = str(proj_dir)
        result = subprocess.run(
            ["bash", str(COORD_TOKENS), "--agent=claude"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)

        self.assertEqual(payload["input"], 100)
        self.assertEqual(payload["output"], 40)
        self.assertEqual(payload["cache_read"], 200)
        self.assertEqual(payload["cache_create"], 80)
        self.assertEqual(payload["effective"], 420)

    def test_codex_effective_formula_weights_output_6x_and_discounts_cache(self):
        # Locks in the Codex GPT-5.5 rate-card formula:
        #   effective = input + 6*output + cache_read//10
        # input_tokens here is total-including-cache per Codex's reporting
        # convention; cached_input_tokens=600 is subtracted so the uncached
        # input contribution is 400. cache_read field in output is 600.
        # Expected: 400 + 6*40 + 600//10 = 400 + 240 + 60 = 700.
        # Numbers chosen so a regression to any prior formula
        # (input+output | +5*output+cache/2 | +6*output+cache/2)
        # produces a distinct wrong total and fails clearly.
        self.write_rollout(
            "rollout-2026-05-24T00-00-00-effective.jsonl",
            [self.token_event(input_tokens=1000, cached_input_tokens=600, output_tokens=40)],
        )

        payload = json.loads(self.run_tokens("--agent=codex").stdout)

        self.assertEqual(payload["input"], 400)
        self.assertEqual(payload["output"], 40)
        self.assertEqual(payload["cache_read"], 600)
        self.assertEqual(payload["effective"], 700)


if __name__ == "__main__":
    unittest.main()
