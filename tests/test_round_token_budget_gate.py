"""Regression tests for the worker success-path round token-budget gate.

Covers the four bands (under-warn / warn / escalate / halt) of
`coord_round_token_budget_gate` in `worker/worker.sh`, plus `.coord/config.env`
overriding the built-in default thresholds (1M/2M/4M), and the docs knob
assertions.

The gate functions live inside `worker/worker.sh`, a top-to-bottom launchd
script (`set -euo pipefail`, requires `$1`) that cannot be sourced. We extract
the contiguous helper block (`load_project_config_env` ->
`coord_round_token_budget_gate`) by function-name markers, stub `ts`, and run it
against a real coord repo so the warn/escalate/halt side effects exercise the
real `bin/coord update` (commit + push to the fixture's origin).
"""

import os
import runpy
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker" / "worker.sh"
COORD = ROOT / "bin" / "coord"
DOCS = ROOT / "docs" / "coordination.md"

COORD_MODULE = runpy.run_path(str(COORD), run_name="coord_cli")
parse_task = COORD_MODULE["parse_task"]
get_section = COORD_MODULE["get_section"]

THRESHOLD_KNOBS = (
    "COORD_ROUND_TOKEN_WARN",
    "COORD_ROUND_TOKEN_ESCALATE",
    "COORD_ROUND_TOKEN_HALT",
)


def _gate_helpers():
    """Extract the contiguous gate-helper block from worker.sh by name markers.

    Spans `load_project_config_env() {` through the line before
    `write_worker_state() {`, which captures load_project_config_env, its bare
    invocation, coord_round_token_threshold, and coord_round_token_budget_gate.
    """
    lines = WORKER.read_text(encoding="utf-8").splitlines(keepends=True)
    start = end = None
    for i, line in enumerate(lines):
        if start is None and line.startswith("load_project_config_env() {"):
            start = i
        elif start is not None and line.startswith("write_worker_state() {"):
            end = i
            break
    assert start is not None and end is not None, "gate helpers not found in worker.sh"
    block = "".join(lines[start:end])
    assert "coord_round_token_threshold() {" in block
    assert "coord_round_token_budget_gate() {" in block
    return block


def _run_gate(repo, effective, *, log_path, env_extra=None):
    """Drive `coord_round_token_budget_gate` against a real repo.

    Returns (rc, action) parsed from the driver's stdout. The gate's own log
    lines and any `coord update` output go to ``log_path``.
    """
    driver = (
        "ts() { echo TS; }\n"
        "LOG=" + shlex.quote(str(log_path)) + "\n"
        "ID=" + shlex.quote("sample-pending") + "\n"
        "TOOLS=" + shlex.quote(str(ROOT)) + "\n"
        'ROUND_TOKEN_BUDGET_GATE_ACTION="continue"\n'
        + _gate_helpers()
        + '\ncoord_round_token_budget_gate "$1"\n'
        "rc=$?\n"
        'printf "GATE_RC=%s\\n" "$rc"\n'
        'printf "GATE_ACTION=%s\\n" "$ROUND_TOKEN_BUDGET_GATE_ACTION"\n'
    )

    env = os.environ.copy()
    env.update({
        "COORD_TASKS_DIR": "tasks",
        "COORD_ARCHIVE_DIR": "tasks/archive",
        "COORD_FINDINGS_DIR": "tasks/findings",
        "COORD_CHANGES_FILE": "tasks/CHANGES.md",
    })
    # Default-threshold tests must not inherit knobs from the ambient env, and
    # config.env-driven tests rely on them being unset so the file wins (the
    # loader skips any key already present in the environment).
    for knob in THRESHOLD_KNOBS:
        env.pop(knob, None)
    if env_extra:
        env.update(env_extra)

    proc = subprocess.run(
        ["bash", "-c", driver, "gate", str(effective)],
        cwd=repo.root,
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, f"driver failed: {proc.stderr}\n{proc.stdout}"
    parsed = dict(
        line.split("=", 1)
        for line in proc.stdout.splitlines()
        if line.startswith(("GATE_RC=", "GATE_ACTION="))
    )
    return int(parsed["GATE_RC"]), parsed["GATE_ACTION"]


def _status_and_issues(repo):
    fm, body = parse_task(repo.tasks["pending"])
    return fm.get("status"), (get_section(body, "Open issues") or "")


def _write_config(repo, **knobs):
    (repo.root / ".coord").mkdir(exist_ok=True)
    body = "".join(f"{key}={value}\n" for key, value in knobs.items())
    (repo.root / ".coord" / "config.env").write_text(body, encoding="utf-8")


def test_under_warn_proceeds_unchanged(coord_repo, tmp_path):
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 500_000, log_path=log)
    assert rc == 0
    assert action == "continue"
    status, issues = _status_and_issues(coord_repo)
    assert status == "pending"
    assert "round_token" not in issues
    # No action means the gate returned before writing anything.
    assert not log.exists() or log.read_text(encoding="utf-8") == ""


def test_warn_records_issue_and_continues(coord_repo, tmp_path):
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 1_500_000, log_path=log)
    assert rc == 0
    assert action == "continue"
    status, issues = _status_and_issues(coord_repo)
    assert status == "pending"  # warn never changes status
    assert "round_token_warn" in issues
    assert "continuing" in issues


def test_escalate_flips_to_needs_brainstorming(coord_repo, tmp_path):
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 2_500_000, log_path=log)
    assert rc == 0
    assert action == "stop"
    status, issues = _status_and_issues(coord_repo)
    assert status == "needs-brainstorming"
    assert "round_token_escalate" in issues
    assert "no auto-requeue" in issues


def test_halt_flips_to_needs_brainstorming(coord_repo, tmp_path):
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 4_500_000, log_path=log)
    assert rc == 0
    assert action == "stop"
    status, issues = _status_and_issues(coord_repo)
    assert status == "needs-brainstorming"
    assert "round_token_halt" in issues
    assert "no auto-requeue" in issues


def test_default_thresholds_apply_without_config(coord_repo, tmp_path):
    # No .coord/config.env -> built-in defaults 1M/2M/4M, so 250 is under warn.
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 250, log_path=log)
    assert rc == 0
    assert action == "continue"
    status, _ = _status_and_issues(coord_repo)
    assert status == "pending"


def test_config_env_overrides_default_thresholds(coord_repo, tmp_path):
    # Same effective (250) that is under-warn at defaults lands in the escalate
    # band once config.env lowers the thresholds — proving config beats default.
    _write_config(
        coord_repo,
        COORD_ROUND_TOKEN_WARN=100,
        COORD_ROUND_TOKEN_ESCALATE=200,
        COORD_ROUND_TOKEN_HALT=300,
    )
    log = tmp_path / "gate.log"
    rc, action = _run_gate(coord_repo, 250, log_path=log)
    assert rc == 0
    assert action == "stop"
    status, issues = _status_and_issues(coord_repo)
    assert status == "needs-brainstorming"
    assert "round_token_escalate" in issues


def test_docs_document_all_three_knobs():
    text = DOCS.read_text(encoding="utf-8")
    for knob in THRESHOLD_KNOBS:
        assert knob in text, f"{knob} missing from docs/coordination.md"
