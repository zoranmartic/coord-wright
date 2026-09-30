import os
import signal
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"


def function_source(name):
    lines = WORKER.read_text(encoding="utf-8").splitlines()
    start = None
    collected = []
    for line in lines:
        if start is None and line.startswith(f"{name}() {{"):
            start = True
        if start:
            collected.append(line)
            if line == "}":
                break
    assert collected and collected[-1] == "}", f"{name} not found"
    return "\n".join(collected) + "\n"


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


@pytest.mark.parametrize("round_timeout", ["600", "''"])
def test_background_wrapper_preserves_stdin_and_exit_status(round_timeout):
    driver = (
        "set -uo pipefail\n" + function_source("run_with_timeout")
        + f"TIMEOUT_CMD=''\nROUND_TIMEOUT_SECONDS={round_timeout}\n"
        + "run_with_timeout bash -c 'read -r line; echo \"$line\"; exit 7'\n"
    )
    proc = subprocess.run(
        ["/bin/bash", "-c", driver], input="agent prompt\n",
        capture_output=True, text=True, timeout=10,
    )
    assert proc.stdout == "agent prompt\n"
    assert proc.returncode == 7, proc.stderr


def test_external_sigterm_takes_agent_group_down(tmp_path):
    """SIGTERM to the Python fallback wrapper must not leave the agent process
    group running as an orphan that keeps editing the checkout after the worker
    has recorded the round as failed: termination is forwarded to the group."""
    child_pid_file = tmp_path / "child.pid"
    driver = (
        "set -uo pipefail\n"
        f"{function_source('run_with_timeout')}"
        "TIMEOUT_CMD=''\n"
        "ROUND_TIMEOUT_SECONDS=600\n"
        "ROUND_TIMEOUT_GRACE_SECONDS=5\n"
        f"run_with_timeout bash -c 'echo $$ > \"{child_pid_file}\"; sleep 600'\n"
        "echo \"rc=$?\"\n"
    )
    proc = subprocess.Popen(
        ["bash", "-c", driver],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert wait_for(lambda: child_pid_file.exists() and child_pid_file.read_text().strip())
    child_pid = int(child_pid_file.read_text().strip())
    assert pid_alive(child_pid)

    wrapper_pids = subprocess.run(
        ["pgrep", "-P", str(proc.pid)], capture_output=True, text=True
    ).stdout.split()
    assert wrapper_pids, "python wrapper not found under the driver shell"
    for pid in wrapper_pids:
        os.kill(int(pid), signal.SIGTERM)

    out, _ = proc.communicate(timeout=30)
    assert "rc=143" in out, out
    assert wait_for(lambda: not pid_alive(child_pid)), (
        f"agent child {child_pid} survived wrapper SIGTERM"
    )


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
@pytest.mark.parametrize("backend", ["python", "unlimited", "gnu"])
@pytest.mark.parametrize("resistance", ["normal", "group", "child"])
def test_worker_signal_stops_group_before_cleanup(tmp_path, signum, backend, resistance):
    timeout_cmd = shutil.which("timeout") or shutil.which("gtimeout")
    if backend == "gnu" and not timeout_cmd:
        pytest.skip("GNU timeout unavailable")
    child_pids = tmp_path / "children.pid"
    agent = tmp_path / "agent.py"
    agent.write_text(
        "import os, signal, subprocess, time\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_IGN)\n" if resistance != "normal" else "")
        + "child = subprocess.Popen(['sleep', '600'])\n"
        + ("signal.signal(signal.SIGTERM, signal.SIG_DFL)\n" if resistance == "child" else "")
        + f"open({str(child_pids)!r}, 'w').write(f'{{os.getpid()}} {{child.pid}}')\n"
        + "time.sleep(600)\n"
    )
    worker_dir = tmp_path / "worker"
    worker_dir.mkdir()
    slot = tmp_path / "slot"
    slot.touch()
    release = worker_dir / "semaphore.sh"
    release.write_text(
        "#!/bin/bash\n"
        f"for pid in $(cat {shlex.quote(str(child_pids))}); do\n"
        f"  if kill -0 \"$pid\" 2>/dev/null; then touch {tmp_path / 'released-too-early'}; fi\n"
        "done\n"
        f"rm -f {shlex.quote(str(slot))}\n"
    )
    release.chmod(0o755)
    lock = tmp_path / "lock"
    state = tmp_path / "state"
    lock.touch()
    state.touch()
    traps = "\n".join(
        line for line in WORKER.read_text().splitlines()
        if line == "trap cleanup EXIT" or line.startswith("trap 'terminate_round ")
    )
    round_timeout = "''" if backend == "unlimited" else "600"
    driver = (
        "set -euo pipefail\n"
        + function_source("run_with_timeout")
        + function_source("terminate_round")
        + function_source("cleanup")
        + f"TOOLS={shlex.quote(str(tmp_path))}\n"
        + f"LOCK={shlex.quote(str(lock))}\nSTATE={shlex.quote(str(state))}\n"
        + "HAVE_SEMAPHORE=1\nTMPOUT=''\nPROMPT=''\nBASE_GIT_STATUS_FILE=''\nSCOPE_SPEC_FILE=''\n"
        + f"TIMEOUT_CMD={shlex.quote(timeout_cmd if backend == 'gnu' else '')}\n"
        + f"ROUND_TIMEOUT_SECONDS={round_timeout}\n"
        + "export ROUND_TIMEOUT_GRACE_SECONDS=1\n"
        + traps + "\n"
        + f"run_with_timeout python3 {shlex.quote(str(agent))}\n"
    )
    proc = subprocess.Popen(
        ["/bin/bash", "-c", driver], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, preexec_fn=lambda: signal.signal(signal.SIGHUP, signal.SIG_DFL),
    )
    pids = []
    try:
        assert wait_for(lambda: child_pids.exists() and child_pids.read_text().strip())
        pids = [int(pid) for pid in child_pids.read_text().split()]
        assert all(pid_alive(pid) for pid in pids)
        os.kill(proc.pid, signum)
        if resistance == "group":
            time.sleep(0.2)
            assert lock.exists() and slot.exists(), "cleanup preceded group shutdown"
        out, _ = proc.communicate(timeout=15)
        assert proc.returncode == 128 + signum, out
        assert wait_for(lambda: all(not pid_alive(pid) for pid in pids))
        assert not (tmp_path / "released-too-early").exists()
        assert not lock.exists() and not slot.exists() and not state.exists()
    finally:
        for pid in pids:
            if pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_python_wrapper_keeps_signal_status_when_zombie_group_denies_kill(tmp_path, signum):
    (tmp_path / "sitecustomize.py").write_text(
        "import os, signal\n"
        "original_killpg = os.killpg\n"
        "def killpg(pid, sig):\n"
        "    if sig == signal.SIGKILL:\n"
        "        raise PermissionError('zombie-only process group')\n"
        "    return original_killpg(pid, sig)\n"
        "os.killpg = killpg\n"
    )
    ready = tmp_path / "ready"
    driver = (
        "set -uo pipefail\n" + function_source("run_with_timeout")
        + "TIMEOUT_CMD=''\nROUND_TIMEOUT_SECONDS=600\n"
        + f"run_with_timeout bash -c 'touch {shlex.quote(str(ready))}; exec sleep 600'\n"
    )
    proc = subprocess.Popen(
        ["/bin/bash", "-c", driver], env=os.environ | {"PYTHONPATH": str(tmp_path)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert wait_for(ready.exists)
        wrapper = subprocess.check_output(["pgrep", "-P", str(proc.pid)], text=True).split()
        assert len(wrapper) == 1
        os.kill(int(wrapper[0]), signum)
        out, err = proc.communicate(timeout=10)
        assert proc.returncode == 128 + signum, (out, err)
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.communicate(timeout=5)


def test_stale_lock_race_loss_removes_worker_self_copy(tmp_path):
    lock = tmp_path / "worker.lock"
    self_copy = tmp_path / "worker-copy.sh"
    lock.write_text("99999999\n")
    self_copy.touch()
    source = WORKER.read_text()
    lock_block = source[source.index('if ! ( set -C; echo "$$" > "$LOCK" )'):
                        source.index('write_worker_state "locked"')]
    driver = (
        "set -euo pipefail\n"
        + f"LOCK={shlex.quote(str(lock))}\n"
        + f"COORD_WORKER_SELF_COPY={shlex.quote(str(self_copy))}\n"
        + 'rm() { command rm "$@"; if [[ "$*" == "-f $LOCK" ]]; then '
        + f'echo {os.getpid()} > "$LOCK"; fi; }}\n'
        + lock_block
        + "exit 9\n"
    )
    result = subprocess.run(["/bin/bash", "-c", driver], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not self_copy.exists()
    assert lock.read_text().strip() == str(os.getpid())
