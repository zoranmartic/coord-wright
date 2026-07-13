"""Tests for subtask-aware lifecycle and token rendering.

Locks in:
- `coord update --status=review-passed` refuses to close while any subtask `[ ]` remains,
  and the error message lists the open subtask ids.
- `coord update --status=review-passed --force` overrides the gate (human escape hatch).
- The Codex handoff packet `success_update.command` for a subtask coder round:
  - includes `--complete-subtask=S<n>`
  - never includes `--force`
  - advances to the next coder round when more subtasks remain
  - hands off to the reviewer only on the LAST subtask when a reviewer is configured
  - hands off to review-passed (no force) on the last subtask when no reviewer
- `coord show <id>` "Token usage" section labels each row with its subtask when present.
"""

import json
import os
import runpy
import shlex
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"
WORKER = ROOT / "worker" / "worker.sh"
COORD_MODULE = runpy.run_path(str(COORD), run_name="coord_cli")


def _coord(*args, cwd, check=True):
    return subprocess.run(
        ["python3", str(COORD), *args],
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
    (root / ".gitignore").write_text(".coord-test-origin.git/\n.coord/\nfake-claude\nfake-codex\nfakebin/\n", encoding="utf-8")
    (root / "tasks").mkdir()
    (root / "tasks" / "archive").mkdir()
    (root / "tasks" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tasks/.gitkeep", "tasks/archive/.gitkeep"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=root, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=root, check=True, capture_output=True)


class SubtaskLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_task(
        self,
        task_id,
        *,
        subtasks,
        roles=None,
        status="pending",
        assigned="codex",
        token_log=None,
        max_seconds=None,
    ):
        roles_block = ""
        if roles:
            roles_block = "roles:\n" + "".join(f"  {k}: {v}\n" for k, v in roles.items())
        token_block = ""
        if token_log:
            token_block = "token_log:\n" + "".join(f"  - {entry}\n" for entry in token_log)
        max_seconds_line = f"max_seconds: {max_seconds}\n" if max_seconds is not None else ""
        # Subtask checkboxes must sit at column 0 — SUBTASK_RE anchors on ^- \[.
        subtask_list = list(subtasks)
        last_n = subtask_list[-1][0] if subtask_list else None

        def _handoff_lines(n):
            lines = []
            if n > 1:
                lines.append(f"  Reads handoff: `.coord/handoffs/<task-id>/S{n - 1}.md`.")
            lines.append(f"  Writes handoff: `.coord/handoffs/<task-id>/S{n}.md`.")
            if n != last_n:
                lines.append(
                    f"  Handoff to S{n + 1}: artifact name and entry point so the next subtask picks up without re-discovering it."
                )
            return "\n".join(lines)

        subtask_text = "\n\n".join(
            f"- [{'x' if done else ' '}] **S{n}: {title}**\n"
            f"  complexity: simple\n"
            f"  model_claude: sonnet\n"
            f"  model_codex: gpt-5.5\n"
            f"  One-line body for S{n}.\n"
            f"{_handoff_lines(n)}"
            for n, title, done in subtask_list
        )
        body = (
            "## Task parameters\n\n"
            "## Scope notes\n\n"
            f"{subtask_text}\n\n"
            "## Plan\nRun the focused lifecycle fixture path.\n\n"
            "## Acceptance test\nLifecycle fixture reaches the expected terminal state.\n"
        )
        header = (
            "---\n"
            f"id: {task_id}\n"
            "task: Lifecycle test\n"
            f"status: {status}\n"
            f"assigned: {assigned}\n"
            "complexity: simple\n"
            "kind: code-fix\n"
            "reasoning_effort: medium\n"
            "round: 1\n"
            "created: 2026-05-16T00:00:00Z\n"
            "updated: 2026-05-16T00:00:00Z\n"
        )
        header += roles_block
        header += token_block
        header += max_seconds_line
        header += "---\n"
        path = self.root / "tasks" / f"{task_id}.md"
        path.write_text(header + body, encoding="utf-8")
        return path

    def frontmatter_value(self, path, key):
        prefix = f"{key}: "
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(prefix):
                return line.split(": ", 1)[1]
        return None

    def fake_claude(self):
        path = self.root / "fake-claude"
        path.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            set -eu
            case "${{FAKE_CLAUDE_MODE:-tail_only}}" in
              structured_approve)
                python3 "{COORD}" update "$COORD_TASK_ID" --append-claude-finding 'Outcome: APPROVE. Structured current-round reviewer finding.'
                ;;
              timeout)
                printf 'partial timeout finding\\n' > "/tmp/claude-finding-$COORD_TASK_ID.txt"
                sleep 10
                printf '{{"result":"late success"}}\\n'
                exit 0
                ;;
            esac
            cat <<'JSON'
            {{"result":"Outcome: APPROVE\\nreviewer tail", "is_error": true}}
            JSON
            exit 1
        """), encoding="utf-8")
        path.chmod(0o755)
        return path

    def commit_task_changes(self):
        subprocess.run(["git", "add", "tasks"], cwd=self.root, check=True)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        if staged.returncode == 0:
            return
        subprocess.run(["git", "commit", "-m", "seed worker task"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=self.root, check=True, capture_output=True)

    def run_worker_with_fake_claude(self, mode, *, force_py_timeout=False):
        self.commit_task_changes()
        env = os.environ.copy()
        env["CLAUDE_BIN"] = str(self.fake_claude())
        env["FAKE_CLAUDE_MODE"] = mode
        if force_py_timeout:
            env["COORD_FORCE_PY_TIMEOUT"] = "1"
            env["ROUND_TIMEOUT_GRACE_SECONDS"] = "1"
        return subprocess.run(
            ["bash", str(WORKER), str(self.root)],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def fake_codex(self, marker):
        path = self.root / "fake-codex"
        path.write_text(textwrap.dedent(f"""\
            #!/bin/sh
            set -eu
            if [ "${{1:-}}" = "doctor" ]; then
              printf '{{"overallStatus":"ok","codexVersion":"test"}}\\n'
              exit 0
            fi
            if [ -n "${{FAKE_CODEX_ARGS_FILE:-}}" ]; then
              printf '%s\\n' "$@" > "$FAKE_CODEX_ARGS_FILE"
            fi
            if [ "${{FAKE_CODEX_MODE:-}}" = "fail" ]; then
              exit 2
            fi
            if [ "${{FAKE_CODEX_MODE:-}}" = "closed_stdin_success" ]; then
              python3 "{COORD}" update "$COORD_TASK_ID" --status=codex-working >/dev/null
              mkdir -p ".coord/handoffs/$COORD_TASK_ID"
              echo "fixture S1 handoff" > ".coord/handoffs/$COORD_TASK_ID/S1.md"
              python3 "{COORD}" update "$COORD_TASK_ID" --status=review-passed --complete-subtask=S1 --append-codex-finding 'done' >/dev/null
              cat <<'JSONL'
            {{"type":"item.completed","item":{{"type":"agent_message","text":"write_stdin failed: stdin is closed for this session"}}}}
            {{"type":"turn.completed","usage":{{"input_tokens":10,"output_tokens":5,"cached_input_tokens":0}}}}
            JSONL
              exit 0
            fi
            printf ran > "{marker}"
            cat <<'JSONL'
            {{"type":"turn.completed","usage":{{"input_tokens":1,"output_tokens":1,"cached_input_tokens":0}}}}
            JSONL
        """), encoding="utf-8")
        path.chmod(0o755)
        return path

    def run_worker_with_fake_codex(self, marker, extra_env=None):
        self.commit_task_changes()
        env = os.environ.copy()
        env["CODEX_BIN"] = str(self.fake_codex(marker))
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            ["bash", str(WORKER), str(self.root)],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def fake_vnu_dir(self, rc):
        fakebin = self.root / "fakebin"
        fakebin.mkdir(exist_ok=True)
        args_file = self.root / "vnu-args.txt"
        (fakebin / "vnu").write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}\n"
            f"exit {rc}\n",
            encoding="utf-8",
        )
        (fakebin / "vnu").chmod(0o755)
        return fakebin

    def worker_log(self):
        path = self.root / ".coord" / "worker.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    # ── close gate ────────────────────────────────────────────────────────────

    def test_review_passed_refused_while_subtasks_open(self):
        self.write_task(
            "t-gate-open",
            subtasks=[(1, "First", True), (2, "Second", False), (3, "Third", False)],
            assigned="claude",
            status="needs-review",
        )
        result = _coord(
            "update", "t-gate-open", "--status=review-passed",
            cwd=self.root,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("incomplete subtask", result.stderr)
        # All open subtask ids must appear in the error so the operator knows
        # what is left without re-reading the file.
        self.assertIn("S2", result.stderr)
        self.assertIn("S3", result.stderr)
        self.assertNotIn("S1", result.stderr.split("remain:", 1)[-1])

    def test_review_passed_allowed_when_all_subtasks_done(self):
        self.write_task(
            "t-gate-clear",
            subtasks=[(1, "First", True), (2, "Second", True)],
            assigned="claude",
            status="needs-review",
        )
        result = _coord(
            "update", "t-gate-clear", "--status=review-passed",
            cwd=self.root,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_force_overrides_close_gate(self):
        self.write_task(
            "t-gate-force",
            subtasks=[(1, "First", False), (2, "Second", False)],
            assigned="claude",
            status="needs-review",
        )
        result = _coord(
            "update", "t-gate-force", "--status=review-passed", "--force",
            cwd=self.root,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    # ── handoff-present gate ──────────────────────────────────────────────────

    def _write_handoff(self, task_id, sub_id):
        sub_dir = self.root / ".coord" / "handoffs" / task_id
        sub_dir.mkdir(parents=True, exist_ok=True)
        path = sub_dir / f"{sub_id.upper()}.md"
        path.write_text(
            f"# {sub_id.upper()} handoff — {task_id}\nFixture handoff body.\n",
            encoding="utf-8",
        )
        return path

    def test_complete_subtask_refuses_when_handoff_file_missing(self):
        self.write_task(
            "t-handoff-missing",
            subtasks=[(1, "First", False), (2, "Second", False)],
            assigned="codex",
            status="codex-working",
        )
        result = _coord(
            "update", "t-handoff-missing", "--complete-subtask=S1",
            cwd=self.root,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("handoff file missing", result.stderr)
        self.assertIn(".coord/handoffs/t-handoff-missing/S1.md", result.stderr)
        # Refusal must leave the checkbox unchanged.
        text = (self.root / "tasks" / "t-handoff-missing.md").read_text(encoding="utf-8")
        self.assertIn("- [ ] **S1: First**", text)

    def test_complete_subtask_succeeds_when_handoff_file_present(self):
        path = self.write_task(
            "t-handoff-present",
            subtasks=[(1, "First", False), (2, "Second", False)],
            assigned="codex",
            status="codex-working",
        )
        self._write_handoff("t-handoff-present", "S1")
        result = _coord(
            "update", "t-handoff-present", "--complete-subtask=S1",
            cwd=self.root,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("- [x] **S1: First**", text)
        self.assertIn("- [ ] **S2: Second**", text)

    def test_force_overrides_missing_handoff_gate(self):
        path = self.write_task(
            "t-handoff-force",
            subtasks=[(1, "First", False), (2, "Second", False)],
            assigned="codex",
            status="codex-working",
        )
        # Deliberately no handoff file written.
        result = _coord(
            "update", "t-handoff-force", "--complete-subtask=S1", "--force",
            cwd=self.root,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        text = path.read_text(encoding="utf-8")
        self.assertIn("- [x] **S1: First**", text)

    def test_reviewer_tail_approve_without_structured_finding_does_not_promote(self):
        path = self.write_task(
            "t-worker-tail-only",
            subtasks=[(1, "First", True), (2, "Second", True)],
            roles={"coder": "codex", "reviewer": "claude"},
            assigned="claude",
            status="needs-review",
        )

        result = self.run_worker_with_fake_claude("tail_only")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.frontmatter_value(path, "status"), "needs-brainstorming")
        self.assertIn("Worker failure", path.read_text(encoding="utf-8"))
        self.assertNotIn("auto-promoting", self.worker_log())

    def test_reviewer_structured_approve_with_open_subtasks_preserves_close_gate(self):
        path = self.write_task(
            "t-worker-open-subtask",
            subtasks=[(1, "First", True), (2, "Second", False)],
            roles={"coder": "codex", "reviewer": "claude"},
            assigned="claude",
            status="needs-review",
        )

        result = self.run_worker_with_fake_claude("structured_approve")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.frontmatter_value(path, "status"), "needs-brainstorming")
        log = self.worker_log()
        self.assertIn("reviewer approve recovery failed", log)
        self.assertIn("incomplete subtask", log)

    def test_reviewer_structured_approve_with_closed_subtasks_promotes(self):
        self.write_task(
            "t-worker-closed-subtasks",
            subtasks=[(1, "First", True), (2, "Second", True)],
            roles={"coder": "codex", "reviewer": "claude"},
            assigned="claude",
            status="needs-review",
        )

        result = self.run_worker_with_fake_claude("structured_approve")

        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.root / "tasks" / "archive" / "t-worker-closed-subtasks.md"
        self.assertEqual(self.frontmatter_value(path, "status"), "done")
        self.assertIsNotNone(self.frontmatter_value(path, "completed"))
        self.assertIn("auto-promoting", self.worker_log())

    def test_python_timeout_fallback_enforces_max_seconds_and_annotates_artifact(self):
        task_id = "t-worker-timeout-fallback"
        tmp_finding = Path(f"/tmp/claude-finding-{task_id}.txt")
        tmp_finding.unlink(missing_ok=True)
        path = self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            assigned="claude",
            status="pending",
            max_seconds=1,
        )

        result = self.run_worker_with_fake_claude("timeout", force_py_timeout=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = path.read_text(encoding="utf-8")
        self.assertEqual(self.frontmatter_value(path, "status"), "needs-brainstorming")
        self.assertIn("terminal_reason=round_timeout", rendered)
        self.assertIn("elapsed", rendered)
        self.assertIn("budget 1s", rendered)
        preserved = list((self.root / ".coord").glob(f"finding-{task_id}-*.txt"))
        self.assertEqual(len(preserved), 1)
        self.assertEqual(preserved[0].read_text(encoding="utf-8"), "partial timeout finding\n")

        debug_files = list((self.root / ".coord" / "agent-runs").glob(f"{task_id}-r1-*.json"))
        self.assertEqual(len(debug_files), 1)
        payload = json.loads(debug_files[0].read_text(encoding="utf-8"))
        self.assertEqual(payload["terminal_reason"], "round_timeout")
        self.assertEqual(payload["coord_worker"]["terminal_reason"], "round_timeout")
        self.assertEqual(payload["coord_worker"]["budget_seconds"], 1)
        self.assertEqual(payload["coord_worker"]["agent"], "claude")
        self.assertIn("round timeout", self.worker_log())
        tmp_finding.unlink(missing_ok=True)

    def test_worker_stale_pickup_exits_before_launch_when_reasoning_changes(self):
        task_id = "t-worker-stale-pickup"
        marker = self.root / "codex-ran"
        path = self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            assigned="codex",
            status="pending",
        )

        result = self.run_worker_with_fake_codex(
            marker,
            {
                "COORD_TEST_STALE_PICKUP_HOOK": f'python3 "{COORD}" update "{task_id}" --reasoning-effort=high',
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(self.frontmatter_value(path, "status"), "pending")
        self.assertEqual(self.frontmatter_value(path, "reasoning_effort"), "high")
        self.assertIn("stale-pickup", self.worker_log())

    def test_worker_passes_codex_runtime_config_and_captures_doctor_on_failure(self):
        task_id = "t-worker-codex-runtime-config"
        marker = self.root / "codex-ran"
        args_file = self.root / "codex-args.txt"
        path = self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            assigned="codex",
            status="pending",
        )
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("reasoning_effort: medium", "reasoning_effort: high"), encoding="utf-8")
        (self.root / ".coord").mkdir(exist_ok=True)
        (self.root / ".coord" / "config.env").write_text("CODEX_SERVICE_TIER=fast\n", encoding="utf-8")

        result = self.run_worker_with_fake_codex(
            marker,
            {
                "FAKE_CODEX_MODE": "fail",
                "FAKE_CODEX_ARGS_FILE": str(args_file),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        args = args_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("-a", args)
        self.assertIn("never", args)
        self.assertIn("-s", args)
        self.assertIn("danger-full-access", args)
        self.assertIn("--enable", args)
        self.assertIn("fast_mode", args)
        self.assertIn('service_tier="fast"', args)
        self.assertIn('model_reasoning_effort="high"', args)
        self.assertIn("exec", args)
        self.assertIn("--cd", args)
        self.assertIn(str(self.root), args)
        log = self.worker_log()
        self.assertIn("codex doctor snapshot (agent-failure): /tmp/coord-codex-doctor-", log)

    def test_worker_records_closed_stdin_runtime_warning_without_failing_success(self):
        task_id = "t-worker-closed-stdin-warning"
        marker = self.root / "codex-ran"
        self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            assigned="codex",
            status="pending",
        )

        result = self.run_worker_with_fake_codex(marker, {"FAKE_CODEX_MODE": "closed_stdin_success"})

        self.assertEqual(result.returncode, 0, result.stderr)
        archived = self.root / "tasks" / "archive" / f"{task_id}.md"
        rendered = archived.read_text(encoding="utf-8")
        self.assertIn("status: done", rendered)
        self.assertIn("runtime_warnings:", rendered)
        self.assertIn("closed-stdin", rendered)
        self.assertIn("Runtime warnings", rendered)

    def test_worker_routes_declared_verifier_failure_to_brainstorming(self):
        task_id = "t-worker-verifier-failure"
        marker = self.root / "codex-ran"
        (self.root / "bad.html").write_text("<!doctype html><html><p>bad</html>\n", encoding="utf-8")
        subprocess.run(["git", "add", "bad.html"], cwd=self.root, check=True)
        path = self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            assigned="codex",
            status="pending",
        )
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "reasoning_effort: medium\n",
            "reasoning_effort: medium\nverify_profile: html5\nscope:\n  - bad.html\n",
        )
        path.write_text(text, encoding="utf-8")
        fakebin = self.fake_vnu_dir(1)

        result = self.run_worker_with_fake_codex(
            marker,
            {
                "FAKE_CODEX_MODE": "closed_stdin_success",
                "PATH": f"{fakebin}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        active = self.root / "tasks" / f"{task_id}.md"
        self.assertTrue(active.exists())
        rendered = active.read_text(encoding="utf-8")
        self.assertIn("status: needs-brainstorming", rendered)
        self.assertIn("Artifact verifier failure", rendered)
        self.assertIn("artifact verifier failed", rendered)

    def test_worker_routes_declared_verifier_failure_to_reviewer_when_configured(self):
        task_id = "t-worker-verifier-review"
        marker = self.root / "codex-ran"
        (self.root / "bad.html").write_text("<!doctype html><html><p>bad</html>\n", encoding="utf-8")
        subprocess.run(["git", "add", "bad.html"], cwd=self.root, check=True)
        path = self.write_task(
            task_id,
            subtasks=[(1, "First", False)],
            roles={"coder": "codex", "reviewer": "claude"},
            assigned="codex",
            status="pending",
        )
        text = path.read_text(encoding="utf-8")
        text = text.replace(
            "reasoning_effort: medium\n",
            "reasoning_effort: medium\nverify_profile: html5\nscope:\n  - bad.html\n",
        )
        path.write_text(text, encoding="utf-8")
        fakebin = self.fake_vnu_dir(1)

        result = self.run_worker_with_fake_codex(
            marker,
            {
                "FAKE_CODEX_MODE": "closed_stdin_success",
                "PATH": f"{fakebin}:{os.environ['PATH']}",
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        active = self.root / "tasks" / f"{task_id}.md"
        rendered = active.read_text(encoding="utf-8")
        self.assertIn("status: needs-review", rendered)
        self.assertIn("assigned: claude", rendered)
        self.assertIn("Artifact verifier failure", rendered)

    # ── handoff success_cmd ──────────────────────────────────────────────────

    def _pickup_policy(self, task_id):
        result = _coord("pickup", "--assigned=codex", cwd=self.root, check=True)
        payload = json.loads(result.stdout)
        self.assertEqual(payload.get("decision"), "run", msg=result.stdout)
        self.assertEqual(payload.get("pickup", {}).get("id"), task_id, msg=result.stdout)
        return payload.get("codex_execution_policy", {})

    def test_subtask_coder_advances_to_next_when_more_remain(self):
        self.write_task(
            "t-advance",
            subtasks=[(1, "First", False), (2, "Second", False), (3, "Third", False)],
            roles={"coder": "codex", "reviewer": "claude"},
        )
        policy = self._pickup_policy("t-advance")
        self.assertEqual(policy.get("work_mode"), "subtask")
        cmd = policy.get("success_update", {}).get("command", "")
        self.assertIn("--complete-subtask=S1", cmd)
        self.assertIn("--status=pending", cmd)
        self.assertIn("--assigned=codex", cmd)
        self.assertNotIn("--force", cmd)
        # Review-once-at-end: must NOT request review while S2/S3 are open.
        self.assertNotIn("needs-review", cmd)

    def test_subtask_coder_hands_to_reviewer_on_last_subtask(self):
        self.write_task(
            "t-last-with-reviewer",
            subtasks=[(1, "First", True), (2, "Second", True), (3, "Last", False)],
            roles={"coder": "codex", "reviewer": "claude"},
        )
        policy = self._pickup_policy("t-last-with-reviewer")
        cmd = policy.get("success_update", {}).get("command", "")
        self.assertIn("--complete-subtask=S3", cmd)
        self.assertIn("--status=needs-review", cmd)
        self.assertIn("--assigned=claude", cmd)
        self.assertNotIn("--force", cmd)

    def test_subtask_coder_closes_on_last_subtask_without_reviewer(self):
        self.write_task(
            "t-last-no-reviewer",
            subtasks=[(1, "First", True), (2, "Last", False)],
        )
        policy = self._pickup_policy("t-last-no-reviewer")
        cmd = policy.get("success_update", {}).get("command", "")
        self.assertIn("--complete-subtask=S2", cmd)
        self.assertIn("--status=review-passed", cmd)
        self.assertNotIn("--force", cmd)

    # ── token render ─────────────────────────────────────────────────────────

    def test_token_section_labels_subtask(self):
        # Mix of subtask-labelled and round-level rows; the rendered section
        # must surface the S<n> prefix on labelled rows.
        path = self.write_task(
            "t-tokens",
            subtasks=[(1, "First", True), (2, "Second", True)],
            token_log=[
                "R1:S1:codex:1000:200:50:1200:1778930000",
                "R1:S2:codex:2000:400:100:2400:1778930060",
                "R1:codex:3000:600:150:3600:1778930120",
            ],
            assigned="claude",
            status="needs-review",
        )
        # Trigger a Token usage re-render by adding a warning; pre-existing
        # token_log rows are then formatted with the current renderer.
        _coord(
            "update", "t-tokens",
            "--add-token-warning=missing-usage",
            "--add-token-warning-agent=codex",
            cwd=self.root,
            check=True,
        )
        rendered = path.read_text(encoding="utf-8")
        # Table format: one row per token_log entry, sorted by (round, stage, agent).
        self.assertIn("| Round | Stage   | Agent", rendered)
        # S1 labelled row with real numbers.
        self.assertRegex(rendered, r"\|\s*1\s*\|\s*S1\s*\|\s*codex\s*\|\s*1000\s*\|\s*200\s*\|\s*50\s*\|\s*1200\s*\|")
        # S2 labelled row.
        self.assertRegex(rendered, r"\|\s*1\s*\|\s*S2\s*\|\s*codex\s*\|\s*2000\s*\|\s*400\s*\|\s*100\s*\|\s*2400\s*\|")
        # Round-level (unlabelled) row — Subtask column empty.
        self.assertRegex(rendered, r"\|\s*1\s*\|\s*\|\s*codex\s*\|\s*3000\s*\|\s*600\s*\|\s*150\s*\|\s*3600\s*\|")
        # Total line still present.
        self.assertIn("**Total effective:", rendered)

    # ── started timing ───────────────────────────────────────────────────────

    def test_started_stamped_once_on_first_pending_to_working_transition(self):
        path = self.write_task("t-started-once", subtasks=[(1, "First", False)])

        _coord("update", "t-started-once", "--status=claude-working", cwd=self.root, check=True)
        first_started = self.frontmatter_value(path, "started")
        self.assertIsNotNone(first_started)

        _coord("update", "t-started-once", "--status=pending", "--force", cwd=self.root, check=True)
        _coord("update", "t-started-once", "--status=claude-working", cwd=self.root, check=True)
        self.assertEqual(first_started, self.frontmatter_value(path, "started"))

    def test_handoff_without_started_omits_timing_lines(self):
        self.write_task("t-handoff-no-started", subtasks=[])

        result = _coord("show", "t-handoff-no-started", "--handoff", cwd=self.root, check=True)

        self.assertNotIn("queue_wait:", result.stdout)
        self.assertNotIn("exec_duration:", result.stdout)

    def test_content_hash_ignores_started_timestamp(self):
        fm = {
            "id": "t-hash-started",
            "task": "Hash test",
            "status": "pending",
            "assigned": "codex",
            "created": "2026-05-16T00:00:00Z",
        }
        body = "## Plan\nplaceholder\n"

        before = COORD_MODULE["content_hash"](fm, body)
        fm["started"] = "2026-05-16T00:01:00Z"

        self.assertEqual(before, COORD_MODULE["content_hash"](fm, body))


if __name__ == "__main__":
    unittest.main()
