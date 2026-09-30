import json
import os
import time
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


TEST_TZ = "Europe/Dublin"
ZONE = ZoneInfo(TEST_TZ)

ROOT = Path(__file__).resolve().parents[1]
RATE_LIMIT = ROOT / "worker" / "rate-limit.sh"
KNOBS = (
    "CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX",
    "CODEX_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX",
    "COORD_TRANSIENT_LIMIT_REGEX",
)


def run_check(tmp_path, agent, artifact_text, env_extra=None):
    artifact = tmp_path / "agent-output.json"
    artifact.write_text(artifact_text, encoding="utf-8")
    (tmp_path / ".coord").mkdir(exist_ok=True)

    env = os.environ.copy()
    for knob in KNOBS:
        env.pop(knob, None)
    env.pop("TZ", None)
    env["COORD_TZ"] = TEST_TZ
    if env_extra:
        env.update(env_extra)

    result = subprocess.run(
        ["bash", str(RATE_LIMIT), "check", agent, str(artifact)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
    )
    marker = tmp_path / ".coord" / f"sleep-until.{agent}"
    target = int(marker.read_text(encoding="utf-8")) if marker.exists() else None
    return result, target


# Clock-reset tests pin "now" away from the parsed reset times; with the real
# clock they flake in the 5 minutes after each reset (retry-in-5-minutes path).
FIXED_NOW = {
    "RATE_LIMIT_NOW": str(int(datetime(2026, 9, 19, 12, 0, tzinfo=ZONE).timestamp()))
}


def assert_local_time(target, hour, minute):
    dt = datetime.fromtimestamp(target, ZONE)
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
        FIXED_NOW,
    )

    assert result.returncode == 0, result.stderr
    assert_local_time(target, 0, 50)
    assert not (tmp_path / ".coord" / "sleep-until").exists()
    assert not (tmp_path / ".coord" / "sleep-until.codex").exists()


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
        FIXED_NOW,
    )

    assert result.returncode == 0, result.stderr
    assert_local_time(target, 3, 5)
    assert not (tmp_path / ".coord" / "sleep-until").exists()
    assert not (tmp_path / ".coord" / "sleep-until.claude").exists()


def test_codex_usage_limit_matches_turn_failed_error_message(tmp_path):
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"turn.failed","error":{"message":"You have hit your usage limit. try again at 3:05 AM."}}\n',
        FIXED_NOW,
    )

    assert result.returncode == 0, result.stderr
    assert_local_time(target, 3, 5)


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


def test_unknown_agent_is_rejected_without_writing_marker(tmp_path):
    result, target = run_check(
        tmp_path,
        "other",
        '{"type":"error","message":"rate limit"}\n',
    )

    assert result.returncode == 2
    assert target is None
    assert not list((tmp_path / ".coord").glob("sleep-until*"))


@pytest.mark.parametrize("message", [
    "Selected model is at capacity. Please try a different model.",
    "Model temporarily overloaded",
])
@pytest.mark.parametrize("agent,event", [
    ("codex", "error"),
    ("codex", "turn.failed"),
    ("claude", "result"),
])
def test_provider_capacity_creates_only_affected_agent_cooldown(tmp_path, message, agent, event):
    if agent == "claude":
        artifact = {"type": event, "is_error": True, "result": message}
    elif event == "turn.failed":
        artifact = {"type": event, "error": {"message": message}}
    else:
        artifact = {"type": event, "message": message}
    before = int(time.time())
    result, target = run_check(tmp_path, agent, json.dumps(artifact))
    after = int(time.time())

    assert result.returncode == 0, result.stderr
    assert before + 60 <= target <= after + 60
    assert list((tmp_path / ".coord").glob("sleep-until*")) == [
        tmp_path / ".coord" / f"sleep-until.{agent}"
    ]


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_capacity_in_ordinary_output_does_not_trigger_cooldown(tmp_path, agent):
    message = "Selected model is at capacity. Model temporarily overloaded."
    if agent == "claude":
        artifact = {"type": "result", "is_error": False, "result": message}
    else:
        artifact = {"type": "item.completed", "item": {"type": "agent_message", "text": message}}
    result, target = run_check(tmp_path, agent, json.dumps(artifact))

    assert result.returncode == 1
    assert target is None


@pytest.mark.parametrize("agent", ["claude", "codex"])
def test_capacity_backoff_caps_and_success_resets_only_that_agent(tmp_path, agent):
    other = "claude" if agent == "codex" else "codex"
    (tmp_path / ".coord").mkdir()
    other_backoff = tmp_path / ".coord" / f"capacity-backoff.{other}"
    other_backoff.write_text("240\n")
    artifact = json.dumps(
        {"is_error": True, "result": "Model is at capacity"}
        if agent == "claude" else {"type": "error", "message": "Model is at capacity"}
    )
    for delay in (60, 300, 600, 1200, 1800, 1800):
        before = int(time.time())
        result, target = run_check(tmp_path, agent, artifact)
        assert result.returncode == 0, result.stderr
        assert before + delay <= target <= int(time.time()) + delay
    reset = subprocess.run(["bash", str(RATE_LIMIT), "reset", agent], cwd=tmp_path)
    assert reset.returncode == 0
    assert not (tmp_path / ".coord" / f"capacity-backoff.{agent}").exists()
    assert other_backoff.read_text() == "240\n"
    before = int(time.time())
    result, target = run_check(tmp_path, agent, artifact)
    assert result.returncode == 0
    assert before + 60 <= target <= int(time.time()) + 60


@pytest.mark.parametrize("message", [
    "You have hit your usage limit.",
    "Model at capacity; quota exhausted.",
])
def test_quota_without_reset_keeps_hour_fallback(tmp_path, message):
    before = int(time.time())
    result, target = run_check(tmp_path, "codex", json.dumps({"type": "error", "message": message}))
    assert result.returncode == 0
    assert before + 3600 <= target <= int(time.time()) + 3600
    assert not (tmp_path / ".coord" / "capacity-backoff.codex").exists()


def test_capacity_explicit_reset_takes_precedence(tmp_path):
    result, target = run_check(tmp_path, "codex", json.dumps({
        "type": "error", "message": "Model at capacity; try again at 3:05 AM."
    }), FIXED_NOW)
    assert result.returncode == 0
    assert_local_time(target, 3, 5)
    assert not (tmp_path / ".coord" / "capacity-backoff.codex").exists()


def test_reset_time_in_current_minute_retries_in_five_minutes(tmp_path):
    now = int(datetime(2026, 9, 19, 9, 52, 8, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"error","message":"You have hit your usage limit. try again at 9:52 AM."}\n',
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )

    assert result.returncode == 0, result.stderr
    assert target == now + 300


def test_reset_time_well_in_the_past_rolls_to_next_day(tmp_path):
    now = int(datetime(2026, 9, 19, 10, 30, 0, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path,
        "codex",
        '{"type":"error","message":"You have hit your usage limit. try again at 9:52 AM."}\n',
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )

    assert result.returncode == 0, result.stderr
    assert_local_time(target, 9, 52)
    assert target > now


def test_hit_your_limit_matches_and_parses_hour_only_reset(tmp_path):
    now = int(datetime(2026, 9, 19, 14, 0, 0, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path,
        "codex",
        json.dumps({"type": "error", "message": "You've hit your limit · resets 3pm"}),
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )

    assert result.returncode == 0, result.stderr
    assert_local_time(target, 15, 0)


def test_hour_limit_reached_matches_builtin_fallback(tmp_path):
    now = int(datetime(2026, 9, 19, 14, 0, 0, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path,
        "codex",
        json.dumps({"type": "error", "message": "5-hour limit reached"}),
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )

    assert result.returncode == 0, result.stderr
    assert target == now + 3600


@pytest.mark.parametrize("reset", ["resets in 5 hours", "resets Oct 3", "resets 5"])
def test_non_clock_reset_uses_hour_fallback(tmp_path, reset):
    now = int(datetime(2026, 9, 19, 14, 0, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path, "codex",
        json.dumps({"type": "error", "message": f"You've hit your limit; {reset}"}),
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )
    assert result.returncode == 0, result.stderr
    assert target == now + 3600


@pytest.mark.parametrize("reset", ["resets at 3pm", "resets 15:05", "resets at 15:05"])
def test_explicit_clock_reset_is_parsed(tmp_path, reset):
    now = int(datetime(2026, 9, 19, 14, 0, tzinfo=ZONE).timestamp())
    result, target = run_check(
        tmp_path, "codex",
        json.dumps({"type": "error", "message": f"You've hit your limit; {reset}"}),
        env_extra={"RATE_LIMIT_NOW": str(now)},
    )
    assert result.returncode == 0, result.stderr
    assert_local_time(target, 15, 0 if "3pm" in reset else 5)
