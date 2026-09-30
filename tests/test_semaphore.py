import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def semaphore(tmp_path):
    worker = tmp_path / "worker"
    worker.mkdir()
    script = worker / "semaphore.sh"
    shutil.copy(ROOT / "worker" / "semaphore.sh", script)
    script.chmod(0o755)
    return script


def run(script, action, owner):
    env = os.environ | {"COORD_SEMAPHORE_N": "1", "COORD_SEMAPHORE_OWNER": str(owner)}
    return subprocess.run(
        ["bash", str(script), action],
        cwd=script.parent.parent,
        env=env,
        text=True,
        capture_output=True,
    )


def test_acquire_reclaims_slot_owned_by_dead_process(tmp_path):
    script = semaphore(tmp_path)
    slots = tmp_path / ".semaphore"
    slots.mkdir()
    (slots / "slot-1").write_text("99999999\n", encoding="utf-8")

    result = run(script, "acquire", os.getpid())

    assert result.returncode == 0, result.stderr
    assert (slots / "slot-1").read_text(encoding="utf-8") == f"{os.getpid()}\n"


def test_acquire_keeps_slot_owned_by_live_process(tmp_path):
    script = semaphore(tmp_path)
    slots = tmp_path / ".semaphore"
    slots.mkdir()
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        (slots / "slot-1").write_text(f"{sleeper.pid}\n", encoding="utf-8")

        result = run(script, "acquire", os.getpid())

        assert result.returncode == 1
        assert (slots / "slot-1").read_text(encoding="utf-8") == f"{sleeper.pid}\n"
    finally:
        sleeper.terminate()
        sleeper.wait()


def test_concurrent_acquires_never_overgrant_dead_owner_slot(tmp_path):
    script = semaphore(tmp_path)
    slots = tmp_path / ".semaphore"
    slots.mkdir()
    owners = [subprocess.Popen(["sleep", "30"]) for _ in range(8)]
    try:
        for _ in range(10):
            (slots / "slot-1").write_text("99999999\n")
            contenders = [
                subprocess.Popen(
                    ["bash", "-c", 'read -r start; exec bash "$1" acquire', "bash", str(script)],
                    env=os.environ | {
                        "COORD_SEMAPHORE_N": "1", "COORD_SEMAPHORE_OWNER": str(owner.pid)
                    },
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True,
                )
                for owner in owners
            ]
            for contender in contenders:
                contender.stdin.write("start\n")
                contender.stdin.flush()
            results = [contender.communicate(timeout=10) for contender in contenders]
            winners = [owner.pid for owner, contender in zip(owners, contenders)
                       if contender.returncode == 0]
            assert len(winners) == 1, results
            assert all(contender.returncode in (0, 1) for contender in contenders), results
            assert (slots / "slot-1").read_text().strip() == str(winners[0])
            assert run(script, "release", winners[0]).returncode == 0
            assert not (slots / "slot-1").exists()
    finally:
        for owner in owners:
            owner.terminate()
            owner.wait()
