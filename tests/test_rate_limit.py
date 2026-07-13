import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
RATE_LIMIT = ROOT / "worker" / "rate-limit.sh"
KNOBS = (
    "CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX",
    "CODEX_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX",
    "COORD_TRANSIENT_LIMIT_REGEX",
    "COORD_TRANSIENT_PROVIDER_LIMIT_REGEX",
)


def run_check(tmp_path, agent, artifact_text, env_extra=None):
    artifact = tmp_path / "agent-output.json"
    artifact.write_text(artifact_text, encoding="utf-8")
    (tmp_path / ".coord").mkdir(exist_ok=True)

    env = os.environ.copy()
    for knob in KNOBS:
        env.pop(knob, None)
    env["TZ"] = "Europe/Dublin"
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        ["bash", str(RATE_LIMIT), "check", agent, str(artifact)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    marker = tmp_path / ".coord" / "sleep-until"
    target = int(marker.read_text(encoding="utf-8")) if marker.exists() else None
    return result, target


def assert_dublin_time(target, hour, minute):
    dt = datetime.fromtimestamp(target, ZoneInfo("Europe/Dublin"))
    assert (dt.hour, dt.minute) == (hour, minute)


# ── Claude: true cap matches only at the structured terminal-error locus ──────

def test_claude_session_limit_matches_and_parses_am_reset(tmp_path):
    # Real incident shape: subtype "success" but is_error/api_error_status flag
    # the API-level cap, with the message in `result`.
    result, target = run_check(
        tmp_path,
        "claude",
        '{"type":"result","subtype":"success","is_error":true,"api_error_status":429,'
        '"result":"You have hit your session limit. resets 12:50am (Europe/Dublin)"}\n',
    )

    assert result.returncode == 0, result.stderr
    assert_dublin_time(target, 0, 50)


def test_claude_limit_vocab_in_normal_prose_does_not_match(tmp_path):
    # Load-bearing false-positive guard: a task that fails for an unrelated
    # reason and merely mentions limit vocabulary (e.g. one editing this file)
    # is NOT a provider limit — no is_error / api_error_status.
    result, target = run_check(
        tmp_path,
        "claude",
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"Updated rate-limit.sh to detect session limit and usage limit strings"}\n',
    )

    assert result.returncode == 1
    assert target is None


def test_claude_max_turns_with_limit_vocab_is_not_treated_as_limit(tmp_path):
    # max-turns has its own recovery path in worker.sh and runs after the
    # rate-limit check; detection must not intercept it even when the last
    # message mentions limit vocabulary.
    result, target = run_check(
        tmp_path,
        "claude",
        '{"type":"result","subtype":"error_max_turns","is_error":true,'
        '"result":"I was explaining the usage limit handling when the turn budget ran out"}\n',
    )

    assert result.returncode == 1
    assert target is None


# ── Codex: true cap matches error / turn.failed events, not agent prose ───────

def test_codex_usage_limit_matches_error_event_and_parses_try_again(tmp_path):
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"error","message":"You have hit your usage limit. try again at 3:05 AM."}\n',
    )

    assert result.returncode == 0, result.stderr
    assert_dublin_time(target, 3, 5)


def test_codex_usage_limit_matches_turn_failed_error_message(tmp_path):
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"turn.failed","error":{"message":"You have hit your usage limit. try again at 3:05 AM."}}\n',
    )

    assert result.returncode == 0, result.stderr
    assert_dublin_time(target, 3, 5)


def test_codex_limit_vocab_in_agent_message_does_not_match(tmp_path):
    # Load-bearing false-positive guard: vocabulary in agent_message prose with
    # no error / turn.failed event must not trigger a sleep.
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"item.completed","item":{"type":"agent_message","text":"I updated the usage limit and rate limit regex"}}\n'
        '{"type":"turn.completed","usage":{"input_tokens":10}}\n',
    )

    assert result.returncode == 1
    assert target is None


# ── Override precedence ───────────────────────────────────────────────────────

def test_agent_specific_override_replaces_generic(tmp_path):
    result, target = run_check(
        tmp_path,
        "claude",
        '{"is_error":true,"api_error_status":429,"result":"generic-only provider cap"}\n',
        {
            "CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX": "agent-only",
            "COORD_TRANSIENT_LIMIT_REGEX": "generic-only",
        },
    )

    assert result.returncode == 1
    assert target is None

    result, target = run_check(
        tmp_path,
        "claude",
        '{"is_error":true,"api_error_status":429,"result":"agent-only provider cap"}\n',
        {
            "CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX": "agent-only",
            "COORD_TRANSIENT_LIMIT_REGEX": "generic-only",
        },
    )

    assert result.returncode == 0, result.stderr
    assert target is not None


def test_empty_agent_override_falls_through_to_generic(tmp_path):
    result, target = run_check(
        tmp_path,
        "claude",
        '{"is_error":true,"api_error_status":429,"result":"generic-only provider cap"}\n',
        {
            "CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX": "",
            "COORD_TRANSIENT_LIMIT_REGEX": "generic-only",
        },
    )

    assert result.returncode == 0, result.stderr
    assert target is not None


def test_no_match_returns_one_and_does_not_write_marker(tmp_path):
    result, target = run_check(tmp_path, "codex", '{"message":"ordinary failure"}\n')

    assert result.returncode == 1
    assert target is None
