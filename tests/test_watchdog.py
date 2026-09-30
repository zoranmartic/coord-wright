import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = ROOT / "worker" / "watchdog.sh"


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "project"
        self.home = self.root / "home"
        self.project.mkdir()
        (self.project / ".coord").mkdir()
        (self.home / ".local" / "bin").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_fake_launchctl(self, rc=0):
        path = self.home / ".local" / "bin" / "launchctl"
        path.write_text(f"#!/usr/bin/env bash\nexit {rc}\n", encoding="utf-8")
        path.chmod(0o755)

    def write_fake_codex(self):
        path = self.home / ".local" / "bin" / "codex"
        path.write_text(
            "#!/usr/bin/env bash\n"
            "if [[ \"${1:-}\" == \"doctor\" ]]; then\n"
            "  printf '{\"overallStatus\":\"ok\",\"codexVersion\":\"test\"}\\n'\n"
            "  exit 0\n"
            "fi\n"
            "exit 64\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def run_watchdog(self, stale_after):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["COORD_WATCHDOG_WORKER_STALE_AFTER"] = str(stale_after)
        return subprocess.run(
            ["bash", str(WATCHDOG), str(self.project)],
            text=True,
            capture_output=True,
            env=env,
        )

    def write_worker_files(self, mtime=None, agent="", task_id=""):
        coord = self.project / ".coord"
        (coord / "worker.lock").write_text(str(os.getpid()), encoding="utf-8")
        state = coord / "worker.state"
        state.write_text(f"phase=running\ntask_id={task_id}\nagent={agent}\n", encoding="utf-8")
        if mtime is not None:
            os.utime(state, (mtime, mtime))
        return state

    def test_running_worker_skips_cycle_without_restart(self):
        self.write_worker_files()

        result = self.run_watchdog(stale_after=3600)

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("worker running", log)
        self.assertIn("source=.coord/worker.state", log)

    def test_stale_worker_restart_logs_triage_skip(self):
        self.write_fake_launchctl(rc=0)
        self.write_worker_files(mtime=time.time() - 10)

        result = self.run_watchdog(stale_after=1)

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("worker stale", log)
        self.assertIn("launchctl restart requested", log)
        self.assertIn("skipping needs-brainstorming triage this cycle", log)

    def test_stale_codex_worker_captures_doctor_snapshot_before_restart(self):
        self.write_fake_launchctl(rc=0)
        self.write_fake_codex()
        self.write_worker_files(mtime=time.time() - 10, agent="codex", task_id="t-stale-codex")

        result = self.run_watchdog(stale_after=1)

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("codex doctor snapshot (stale-worker): /tmp/coord-codex-doctor-", log)
        self.assertIn("t-stale-codex", log)


    # ── needs-brainstorming triage gate ─────────────────────────────────────

    def write_fake_claude(self):
        marker = self.root / "claude-invoked"
        path = self.home / ".local" / "bin" / "claude"
        path.write_text(
            "#!/usr/bin/env bash\n"
            f"echo invoked >> '{marker}'\n"
            "printf '{\"result\":\"fake watchdog run\"}\\n'\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return marker

    def write_stuck_task(self, task_id, *, pickup_hold=False, claude_rounds=()):
        tasks = self.project / "tasks"
        tasks.mkdir(exist_ok=True)
        hold = "pickup_hold: true\n" if pickup_hold else ""
        findings = "".join(
            f"### Round {n}\n\n{text}\n\n" for n, text in enumerate(claude_rounds, start=1)
        ) or "_No findings yet._\n"
        (tasks / f"{task_id}.md").write_text(
            "---\n"
            f"id: {task_id}\n"
            f"task: {task_id}\n"
            "status: needs-brainstorming\n"
            "assigned: codex\n"
            "complexity: simple\n"
            "kind: code-fix\n"
            "roles:\n  coder: codex\n  reviewer: claude\n"
            "round: 3\n"
            "attempts: 0\n"
            "created: 2026-09-06T09:00:00+0100\n"
            "updated: 2026-09-06T09:00:00+0100\n"
            f"{hold}"
            "---\n\n"
            "## Plan\n\nfixture\n\n"
            "## Claude findings\n\n"
            f"{findings}"
            "## Codex findings\n\n_No findings yet._\n",
            encoding="utf-8",
        )

    def run_triage_watchdog(self):
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["CLAUDE_BIN"] = str(self.home / ".local" / "bin" / "claude")
        env["COORD_TASKS_DIR"] = "tasks"
        env["COORD_ARCHIVE_DIR"] = "tasks/archive"
        env["COORD_FINDINGS_DIR"] = "tasks/findings"
        env["COORD_CHANGES_FILE"] = "tasks/CHANGES.md"
        return subprocess.run(
            ["bash", str(WATCHDOG), str(self.project)],
            text=True,
            capture_output=True,
            env=env,
        )

    def test_held_task_is_skipped_without_launching_the_diagnostician(self):
        marker = self.write_fake_claude()
        self.write_stuck_task("t-held", pickup_hold=True)

        result = self.run_triage_watchdog()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("skipping t-held (pickup_hold=true", log)
        self.assertIn("no triageable tasks (all held)", log)
        self.assertFalse(marker.exists(), "claude must not run for a held task")

    def test_two_consecutive_watchdog_verdicts_auto_hold_the_task(self):
        marker = self.write_fake_claude()
        self.write_stuck_task(
            "t-loop",
            claude_rounds=(
                "Worker failure (rc=1) — queued for agent triage.",
                "Watchdog: blocked. Root cause: needs a human. Unblocked by: decision.",
                "Watchdog: blocked. Root cause: needs a human. Unblocked by: decision.",
            ),
        )

        result = self.run_triage_watchdog()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("two consecutive watchdog verdicts", log)
        self.assertFalse(marker.exists(), "claude must not run once the task is auto-held")
        task = (self.project / "tasks" / "t-loop.md").read_text(encoding="utf-8")
        self.assertRegex(task, r"(?m)^pickup_hold: true$")
        self.assertIn("watchdog auto-hold", task)

    def test_fresh_failure_still_reaches_the_diagnostician(self):
        marker = self.write_fake_claude()
        self.write_stuck_task(
            "t-fresh",
            claude_rounds=("Worker failure (rc=1) — queued for agent triage.",),
        )

        result = self.run_triage_watchdog()

        self.assertEqual(result.returncode, 0, result.stderr)
        log = (self.project / ".coord" / "watchdog.log").read_text(encoding="utf-8")
        self.assertIn("diagnosing t-fresh", log)
        self.assertTrue(marker.exists(), "claude must run for a task that is not held")


if __name__ == "__main__":
    unittest.main()
