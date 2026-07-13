#!/usr/bin/env bash
# coord-tokens.sh — read current agent session token usage from local JSONL logs
#
# Usage:
#   coord-tokens.sh                 Print cumulative totals for the current session
#   coord-tokens.sh --since=N       Print totals only for JSONL lines N and later (1-based)
#   coord-tokens.sh --count         Print baseline: "<line-count>:<jsonl-path>"
#   coord-tokens.sh --agent=codex   Read Codex rollout token_count events
#   coord-tokens.sh --help          Show this help
#
# Output (default / --since):
#   JSON: {"input":N,"output":N,"cache_read":N,"cache_create":N,"effective":N,"lines":N}
#   lines = total lines in file (useful to pass as --since on the next call)
#
#   effective is an API-parity proxy for "what your subscription likely meters."
#   The exact rule used by Claude Max / Codex Pro for their usage gauges is not
#   publicly documented; the formula below matches each provider's published
#   API pricing discounts as of 2026-05 — closest thing to ground truth.
#
#     claude: input + 5*output + cache_read/10 + cache_create*5/4
#             (Anthropic: out=5x, cache_read=0.1x, cache_create=1.25x — uniform
#              across Haiku/Sonnet/Opus pricing tables)
#
#     codex:  input + 6*output + cache_read/10
#             (OpenAI Codex GPT-5.5 rate card as of 2026-05:
#                input        125  credits / 1M  (baseline 1x)
#                cached input  12.5 credits / 1M  = 0.1x
#                output       750  credits / 1M  = 6x
#              Sources:
#                https://help.openai.com/en/articles/20001106-codex-rate-card
#                https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan.pdf
#              Codex does not report a separate cache_create stream.)
#
# Output (--count):
#   "<line-count>:<jsonl-path>"  — pass verbatim to --since to handle session rotation
#
# --since accepts either:
#   --since=N              Plain integer (legacy): uses most recently modified JSONL
#   --since=N:<path>       Baseline from --count: uses <path> if still most recent,
#                          otherwise falls back to --since=0 on the new JSONL so a
#                          session rotation (fresh claude -p invocation) is captured.
#
# Env knobs:
#   COORD_PROJ_DIR   path to the ~/.claude/projects/<slug> dir for this repo
#                    Required — set in .coord/config.env or as an environment variable
#   AGENT_ROLE       default agent when --agent is omitted (claude or codex)
#
# Notes:
# - For Claude, picks the most recently modified *.jsonl in COORD_PROJ_DIR
# - Claude may emit multiple JSONL rows for the same API call (thinking/text/tool_use
#   chunks can repeat the same message.usage block). Deduplicate by request/message id
#   so per-call usage is only counted once.
# - For Codex, picks the newest rollout-*.jsonl in ~/.codex/sessions/YYYY/MM/DD,
#   checking today first and walking back up to 2 days.
# - Cache reads are reported separately AND counted toward 'effective' at the
#   provider's published API discount rate (0.1x for both Anthropic and OpenAI
#   Codex GPT-5.5). Prior versions excluded cache_read from effective entirely;
#   on cache-heavy sessions that under-reported real burn by up to ~50x.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

zero_json() {
  echo '{"input":0,"output":0,"cache_read":0,"cache_create":0,"effective":0,"lines":0}'
  exit 0
}

AGENT="${AGENT_ROLE:-claude}"
SINCE=0
COUNT_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --agent=*) AGENT="${arg#--agent=}" ;;
    --since=*) SINCE="${arg#--since=}" ;;
    --count)   COUNT_ONLY=true ;;
    --help|-h)
      grep '^#' "$0" | grep -v '^#!/' | sed 's/^# \{0,1\}//'
      exit 0
      ;;
  esac
done

case "$AGENT" in
  claude|codex) ;;
  *)
    echo "unsupported agent for coord-tokens.sh: $AGENT" >&2
    exit 2
    ;;
esac

if [[ "$AGENT" == "claude" ]]; then
  if [ -z "${COORD_PROJ_DIR:-}" ]; then
    # Load COORD_PROJ_DIR from the project's .coord/config.env if it exists.
    _cfg="$(pwd)/.coord/config.env"
    if [ -f "$_cfg" ]; then
      _v=$(awk -F= '/^COORD_PROJ_DIR=/ {print $2; exit}' "$_cfg")
      [ -n "$_v" ] && export COORD_PROJ_DIR="$_v"
    fi
    unset _cfg _v
  fi
  PROJ_DIR="${COORD_PROJ_DIR:-}"
  if [ -z "$PROJ_DIR" ]; then
    # Claude Code stores per-project session JSONLs at ~/.claude/projects/<slug>/
    # where <slug> is the canonical cwd with '/' replaced by '-'.
    _derived="${HOME}/.claude/projects/$(pwd -P | sed 's|/|-|g')"
    if [ -d "$_derived" ]; then
      PROJ_DIR="$_derived"
    fi
    unset _derived
  fi
  if [ -z "$PROJ_DIR" ]; then
    zero_json
  fi

  # Find most recently modified JSONL. `ls | head -1` triggers SIGPIPE on ls
  # when the directory has many files, which kills the script under pipefail;
  # disable pipefail just for this assignment.
  JSONL=$(set +o pipefail; ls -t "${PROJ_DIR}"/*.jsonl 2>/dev/null | head -1)
else
  JSONL=$(python3 - <<'PYEOF'
from datetime import datetime, timedelta
from pathlib import Path

root = Path.home() / ".codex" / "sessions"
today = datetime.now()
for offset in range(3):
    day = today - timedelta(days=offset)
    day_dir = root / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"
    if not day_dir.is_dir():
        continue
    rollouts = list(day_dir.glob("rollout-*.jsonl"))
    if rollouts:
        print(max(rollouts, key=lambda path: path.stat().st_mtime))
        break
PYEOF
)
fi
if [[ -z "${JSONL}" ]]; then
  zero_json
fi

if $COUNT_ONLY; then
  LINE_COUNT=$(wc -l < "$JSONL" | tr -d ' ')
  printf '%s:%s\n' "$LINE_COUNT" "$JSONL"
  exit 0
fi

# Parse --since: supports both legacy "N" and new "N:<path>" formats.
# If the baseline JSONL path differs from the current most-recent JSONL
# (session rotated between baseline and delta call), reset SINCE to 0
# so all tokens in the new session file are captured.
BASELINE_PATH=""
if [[ "$SINCE" == *:/* ]]; then
  BASELINE_PATH="${SINCE#*:}"
  SINCE="${SINCE%%:*}"
  if [[ "$BASELINE_PATH" != "$JSONL" ]]; then
    # Session rotated — fresh JSONL, capture everything from line 1
    SINCE=0
  fi
fi

if [[ "$AGENT" == "codex" ]]; then
  python3 - "$JSONL" "$SINCE" "$SCRIPT_DIR" <<'PYEOF'
import json
import sys

jsonl_path = sys.argv[1]
since = int(sys.argv[2])
sys.path.insert(0, sys.argv[3])
from coord_token_effective import effective_tokens

zero = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_create': 0}
baseline = dict(zero)
current = dict(zero)
total_lines = 0

def usage_totals(payload):
    if not isinstance(payload, dict):
        return None
    if payload.get('type') != 'token_count':
        return None
    info = payload.get('info') or {}
    if not isinstance(info, dict):
        return None
    usage = info.get('total_token_usage') or {}
    if not isinstance(usage, dict):
        return None

    input_total = int(usage.get('input_tokens', 0) or 0)
    cache_read = int(usage.get('cached_input_tokens', 0) or 0)
    output = int(usage.get('output_tokens', 0) or 0)
    input_uncached = max(input_total - cache_read, 0)
    return {
        'input': input_uncached,
        'output': output,
        'cache_read': cache_read,
        'cache_create': int(usage.get('cache_creation_input_tokens', 0) or 0),
    }

with open(jsonl_path) as f:
    for i, line in enumerate(f, 1):
        total_lines = i
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        if d.get('type') != 'event_msg':
            continue
        totals = usage_totals(d.get('payload', {}))
        if totals is None:
            continue
        if i <= since:
            baseline = totals
        else:
            current = totals

delta = {key: max(current[key] - baseline[key], 0) for key in zero}
effective = effective_tokens('codex', delta['input'], delta['output'], delta['cache_read'])
print(json.dumps({
    'input':        delta['input'],
    'output':       delta['output'],
    'cache_read':   delta['cache_read'],
    'cache_create': delta['cache_create'],
    'effective':    effective,
    'lines':        total_lines,
}, separators=(',', ':')))
PYEOF
  exit 0
fi

python3 - "$JSONL" "$SINCE" "$SCRIPT_DIR" <<'PYEOF'
import json, sys

jsonl_path = sys.argv[1]
since      = int(sys.argv[2])
sys.path.insert(0, sys.argv[3])
from coord_token_effective import effective_tokens

totals = {'input': 0, 'output': 0, 'cache_read': 0, 'cache_create': 0}
total_lines = 0
seen_usage_keys = set()

with open(jsonl_path) as f:
    for i, line in enumerate(f, 1):
        total_lines = i
        if i < since:
            continue
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except Exception:
            continue
        msg = d.get('message', {})
        if not isinstance(msg, dict):
            continue
        usage = msg.get('usage', {})
        if not usage:
            continue
        request_id = d.get('requestId')
        message_id = msg.get('id')
        if request_id:
            usage_key = ('requestId', request_id)
        elif message_id:
            usage_key = ('messageId', message_id)
        else:
            usage_key = (
                'usage',
                usage.get('input_tokens', 0),
                usage.get('output_tokens', 0),
                usage.get('cache_read_input_tokens', 0),
                usage.get('cache_creation_input_tokens', 0),
            )
        if usage_key in seen_usage_keys:
            continue
        seen_usage_keys.add(usage_key)
        totals['input']        += usage.get('input_tokens', 0)
        totals['output']       += usage.get('output_tokens', 0)
        totals['cache_read']   += usage.get('cache_read_input_tokens', 0)
        totals['cache_create'] += usage.get('cache_creation_input_tokens', 0)

effective = effective_tokens(
    'claude',
    totals['input'],
    totals['output'],
    totals['cache_read'],
    totals['cache_create'],
)
print(json.dumps({
    'input':        totals['input'],
    'output':       totals['output'],
    'cache_read':   totals['cache_read'],
    'cache_create': totals['cache_create'],
    'effective':    effective,
    'lines':        total_lines,
}, separators=(',', ':')))
PYEOF
