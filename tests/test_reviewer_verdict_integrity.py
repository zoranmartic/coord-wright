"""Regression tests for the reviewer verdict-integrity chain and the
unattended-autonomy gate.

Locks in:
- False-approve guard: a reviewer round that writes an explicit REJECT finding
  but still runs the success update (closing the task as done) is demoted back
  to review-failed — including when the same finding block contains stray
  APPROVE mentions ("Do not APPROVE until ..."), which must not suppress the
  demotion.
- Mechanical verify gate: after a reviewer closes a task as done, the task's
  verify_commands are re-run mechanically; a failing command demotes the task.
- Mechanical verify gate dirt restoration: a verify run that mutates tracked
  files or creates untracked artifacts is restored byte-for-byte (agent work
  preserved, verify artifacts removed, pre-existing untracked files kept) and
  the task is demoted for violating the gate contract.
- COORD_UNSAFE_AUTONOMOUS gate: without the exact acknowledgement value the
  worker and the watchdog exit idle before touching queue or worktree; with it
  the watchdog launches Claude with the bypass permission flag and the pinned
  fallback model.
"""

import os
import shlex
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORD = ROOT / "bin" / "coord"
WORKER = ROOT / "worker" / "worker.sh"
WATCHDOG = ROOT / "worker" / "watchdog.sh"


def _init_repo(root):
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Coord Test"], cwd=root, check=True)
    origin = root / ".coord-test-origin.git"
    subprocess.run(["git", "init", "--bare", str(origin)], cwd=root, check=True, capture_output=True)
    (root / ".gitignore").write_text(
        ".coord-test-origin.git/\n.coord/\nfake-claude\nfake-codex\nclaude-args.txt\n",
        encoding="utf-8",
    )
    (root / "tasks").mkdir()
    (root / "tasks" / "archive").mkdir()
    (root / "tasks" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
    (root / "tracked.txt").write_text("original line\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitignore", "tasks/.gitkeep", "tasks/archive/.gitkeep", "tracked.txt"],
        cwd=root, check=True,
    )
    subprocess.run(["git", "commit", "-m", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=root, check=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=root, check=True, capture_output=True)


class VerdictIntegrityTests(unittest.TestCase):
    TASK_ID = "verdict-integrity-fixture"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def write_reviewer_task(self, verify_commands=()):
        verify_block = ""
        if verify_commands:
            verify_block = "verify_commands:\n" + "".join(
                f"  - {cmd}\n" for cmd in verify_commands
            )
        header = (
            "---\n"
            f"id: {self.TASK_ID}\n"
            "task: Verdict integrity fixture\n"
            "status: needs-review\n"
            "assigned: codex\n"
            "complexity: simple\n"
            "kind: code-fix\n"
            "reasoning_effort: medium\n"
            "round: 1\n"
            "roles:\n"
            "  coder: codex\n"
            "  reviewer: codex\n"
            f"{verify_block}"
            "created: 2026-05-16T00:00:00Z\n"
            "updated: 2026-05-16T00:00:00Z\n"
            "---\n"
        )
        body = (
            "## Task parameters\n\n"
            "## Scope notes\n\n"
            "- [x] **S1: Done subtask**\n"
            "  complexity: simple\n"
            "  model_claude: sonnet\n"
            "  model_codex: gpt-5.6-sol\n"
            "  One-line body for S1.\n"
            "  Writes handoff: `.coord/handoffs/<task-id>/S1.md`.\n\n"
            "## Plan\nReviewer fixture.\n\n"
            "## Acceptance test\nReviewer fixture reaches the expected terminal state.\n"
        )
        path = self.root / "tasks" / f"{self.TASK_ID}.md"
        path.write_text(header + body, encoding="utf-8")
        subprocess.run(["git", "add", "tasks"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "seed reviewer task"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=self.root, check=True, capture_output=True)
        return path

    def fake_codex(self, review_script):
        """A stub codex reviewer: runs `review_script` shell lines (the round's
        behavior), then prints the token JSONL tail the worker expects."""
        path = self.root / "fake-codex"
        path.write_text(
            "#!/bin/sh\nset -eu\n"
            'if [ "${1:-}" = "doctor" ]; then\n'
            '  printf \'{"overallStatus":"ok","codexVersion":"test"}\\n\'\n'
            "  exit 0\n"
            "fi\n"
            f"{review_script}\n"
            "cat <<'JSONL'\n"
            '{"type":"item.completed","item":{"type":"agent_message","text":"review recorded"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":5,"cached_input_tokens":0}}\n'
            "JSONL\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def run_worker(self, fake):
        env = os.environ.copy()
        env["CODEX_BIN"] = str(fake)
        env["COORD_UNSAFE_AUTONOMOUS"] = "1"
        return subprocess.run(
            ["bash", str(WORKER), str(self.root)],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def task_text(self):
        for candidate in (
            self.root / "tasks" / f"{self.TASK_ID}.md",
            self.root / "tasks" / "archive" / f"{self.TASK_ID}.md",
        ):
            if candidate.exists():
                return candidate.read_text(encoding="utf-8")
        self.fail("task file disappeared from tasks/ and tasks/archive/")

    def frontmatter_status(self):
        for line in self.task_text().splitlines():
            if line.startswith("status: "):
                return line.split(": ", 1)[1]
        return None

    def test_false_approve_close_is_demoted_despite_stray_approve_mention(self):
        self.write_reviewer_task()
        # The observed incident shape: an explicit REJECT verdict (plus a stray
        # APPROVE mention in the same block) followed by the success update.
        fake = self.fake_codex(textwrap.dedent(f"""\
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" \
              --append-codex-finding 'Outcome: REJECT. Gate not proven. Do not APPROVE until the verify runs.' >/dev/null
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" --status=review-passed >/dev/null
        """))
        result = self.run_worker(fake)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("reviewer false-approve guard", log)
        # review-failed is immediately routed back to the coder as pending —
        # the demotion evidence lives in the issues text.
        self.assertEqual(self.frontmatter_status(), "pending")
        self.assertIn("false-approve guard", self.task_text())

    def test_mechanical_verify_gate_demotes_when_verify_command_fails(self):
        self.write_reviewer_task(verify_commands=["false"])
        fake = self.fake_codex(textwrap.dedent(f"""\
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" \
              --append-codex-finding 'Outcome: APPROVE. Looks good.' >/dev/null
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" --status=review-passed >/dev/null
        """))
        result = self.run_worker(fake)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("mechanical verify gate: 'false' exited rc=1", log)
        self.assertEqual(self.frontmatter_status(), "pending")
        self.assertIn("mechanical verify gate", self.task_text())

    def test_mechanical_verify_gate_restores_dirt_and_demotes(self):
        self.write_reviewer_task(verify_commands=[
            "echo artifact > verify-artifact.txt",
            "echo verify-mutation >> tracked.txt",
        ])
        # The agent leaves real work in the worktree before the close: a dirty
        # tracked file and an untracked note. Both must survive the verify
        # byte-for-byte; the verify's own artifact must not.
        fake = self.fake_codex(textwrap.dedent(f"""\
            printf 'agent work\\n' >> tracked.txt
            printf 'agent note\\n' > agent-note.txt
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" \
              --append-codex-finding 'Outcome: APPROVE. Looks good.' >/dev/null
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" --status=review-passed >/dev/null
        """))
        result = self.run_worker(fake)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("restored tracked files mutated by verify", log)
        self.assertIn("removed 1 verify-created untracked path(s)", log)
        self.assertEqual(self.frontmatter_status(), "pending")
        self.assertIn("created or mutated worktree content", self.task_text())
        self.assertEqual(
            (self.root / "tracked.txt").read_text(encoding="utf-8"),
            "original line\nagent work\n",
            msg="agent's uncommitted tracked work must survive the verify restore",
        )
        self.assertFalse((self.root / "verify-artifact.txt").exists(),
                         msg="verify-created artifact must be removed")
        self.assertEqual((self.root / "agent-note.txt").read_text(encoding="utf-8"),
                         "agent note\n",
                         msg="pre-existing untracked agent file must be kept")


    def test_reject_colon_reason_format_triggers_demotion(self):
        self.write_reviewer_task()
        # agents/reviewer.md's documented verdict format is `REJECT: <reason>`.
        fake = self.fake_codex(textwrap.dedent(f"""\
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" \
              --append-codex-finding 'REJECT: verify_commands were never executed.' >/dev/null
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" --status=review-passed >/dev/null
        """))
        result = self.run_worker(fake)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("reviewer false-approve guard",
                      (self.root / ".coord" / "worker.log").read_text(encoding="utf-8"))
        self.assertEqual(self.frontmatter_status(), "pending")

    def test_approve_recovery_after_nonzero_exit_is_blocked_by_failing_verify(self):
        self.write_reviewer_task(verify_commands=["false"])
        # The reviewer appends a structured APPROVE but exits non-zero (turn
        # cap). The auto-recovery path must prove the mechanical gate before
        # promoting — a failing verify must leave the task un-closed.
        fake = self.fake_codex(textwrap.dedent(f"""\
            python3 {shlex.quote(str(COORD))} update "$COORD_TASK_ID" \
              --append-codex-finding 'Outcome: APPROVE. Looks good.' >/dev/null
            exit 2
        """))
        result = self.run_worker(fake)
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("approve recovery blocked by mechanical verify gate", log)
        self.assertNotIn("auto-promoting", log)
        text = self.task_text()
        self.assertNotIn("status: done", text)



class UnsafeAutonomousGateTests(unittest.TestCase):
    TASK_ID = "gate-fixture"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def _env_without_ack(self):
        env = os.environ.copy()
        env.pop("COORD_UNSAFE_AUTONOMOUS", None)
        return env

    def _seed_task(self, status):
        path = self.root / "tasks" / f"{self.TASK_ID}.md"
        path.write_text(
            "---\n"
            f"id: {self.TASK_ID}\n"
            "task: Gate fixture\n"
            f"status: {status}\n"
            "assigned: codex\n"
            "complexity: simple\n"
            "kind: code-fix\n"
            "reasoning_effort: medium\n"
            "round: 1\n"
            "created: 2026-05-16T00:00:00Z\n"
            "updated: 2026-05-16T00:00:00Z\n"
            "---\n\n"
            "## Task parameters\n\n## Plan\nGate fixture.\n\n"
            "## Acceptance test\nNot picked up without acknowledgement.\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "tasks"], cwd=self.root, check=True)
        subprocess.run(["git", "commit", "-m", "seed gate task"], cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "push"], cwd=self.root, check=True, capture_output=True)
        return path

    def test_worker_exits_idle_without_acknowledgement(self):
        task = self._seed_task("pending")
        result = subprocess.run(
            ["bash", str(WORKER), str(self.root)],
            cwd=self.root, env=self._env_without_ack(),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("COORD_UNSAFE_AUTONOMOUS=1 not set", log)
        self.assertIn("status: pending", task.read_text(encoding="utf-8"))
        self.assertFalse((self.root / ".coord" / "worker.lock").exists(),
                         msg="gate must fire before any lock/queue mutation")

    def test_worker_gate_requires_exact_value(self):
        self._seed_task("pending")
        env = self._env_without_ack()
        env["COORD_UNSAFE_AUTONOMOUS"] = "0"
        result = subprocess.run(
            ["bash", str(WORKER), str(self.root)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "worker.log").read_text(encoding="utf-8")
        self.assertIn("COORD_UNSAFE_AUTONOMOUS=1 not set", log)

    def test_watchdog_exits_idle_without_acknowledgement(self):
        self._seed_task("needs-brainstorming")
        result = subprocess.run(
            ["bash", str(WATCHDOG), str(self.root)],
            cwd=self.root, env=self._env_without_ack(),
            capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        log = (self.root / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("COORD_UNSAFE_AUTONOMOUS=1 not set", log)
        self.assertIn("status: needs-brainstorming",
                      (self.root / "tasks" / f"{self.TASK_ID}.md").read_text(encoding="utf-8"))

    def test_acknowledged_watchdog_launches_claude_with_bypass_and_pinned_fallback(self):
        self._seed_task("needs-brainstorming")
        args_file = self.root / "claude-args.txt"
        fake_claude = self.root / "fake-claude"
        fake_claude.write_text(
            "#!/bin/sh\nset -eu\n"
            f"printf '%s\\n' \"$@\" > {shlex.quote(str(args_file))}\n"
            'printf \'{"result":"triage ok"}\\n\'\n',
            encoding="utf-8",
        )
        fake_claude.chmod(0o755)
        env = self._env_without_ack()
        env["COORD_UNSAFE_AUTONOMOUS"] = "1"
        env["CLAUDE_BIN"] = str(fake_claude)
        env.pop("COORD_WATCHDOG_MODEL", None)
        env.pop("CLAUDE_MODEL", None)
        result = subprocess.run(
            ["bash", str(WATCHDOG), str(self.root)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        args = args_file.read_text(encoding="utf-8").splitlines()
        self.assertIn("--dangerously-skip-permissions", args,
                      msg="acknowledged watchdog rounds must use bypass, not acceptEdits")
        self.assertNotIn("acceptEdits", " ".join(args))
        model_index = args.index("--model")
        self.assertEqual(args[model_index + 1], "claude-sonnet-5",
                         msg="watchdog model fallback must be the current pinned Sonnet")


if __name__ == "__main__":
    unittest.main()
