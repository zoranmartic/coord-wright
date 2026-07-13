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


if __name__ == "__main__":
    unittest.main()
