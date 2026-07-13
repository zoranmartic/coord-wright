#!/usr/bin/env bash
# Detect transient provider-limit signatures in an agent output artifact. The
# match is anchored to the structured terminal-error locus, NOT the whole
# artifact, so a failed run whose ordinary output merely mentions limit
# vocabulary (e.g. a task that edits this very file) is not misclassified as a
# provider limit. If a limit is found, write .coord/sleep-until with a unix
# timestamp and exit 0. Otherwise exit 1.
#
# Usage: rate-limit.sh check <agent> <agent-output-file>
#
# Relative paths in this script (e.g. .coord/sleep-until) are resolved
# against the worker's current working directory, which is the project root.

set -euo pipefail

ACTION="${1:?usage: rate-limit.sh check <agent> <agent-output-file>}"
AGENT="${2:?usage: rate-limit.sh check <agent> <agent-output-file>}"
OUTPUT="${3:?usage: rate-limit.sh check <agent> <agent-output-file>}"

if [[ "$ACTION" != "check" ]]; then
  echo "unknown action: $ACTION" >&2
  exit 2
fi

BUILTIN_REGEX='rate.?limit|usage limit|session limit|quota.*exhaust|too many requests'
AGENT_REGEX=""
case "$AGENT" in
  claude) AGENT_REGEX="${CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX:-}" ;;
  codex) AGENT_REGEX="${CODEX_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX:-}" ;;
esac
REGEX="${AGENT_REGEX:-${COORD_TRANSIENT_LIMIT_REGEX:-$BUILTIN_REGEX}}"

# Extract only the terminal-error text from the structured artifact.
#   Claude: a single JSON object. Expose result/error only for an API-level
#     error (api_error_status 429, or is_error true that is NOT a max-turns
#     termination — max-turns has its own recovery path in worker.sh and must
#     not be intercepted here).
#   Codex: JSONL. Expose only `error` events and `turn.failed` error messages,
#     never `agent_message` prose.
# Empty output (no terminal error, or the artifact is missing/empty/unparseable)
# yields no text, so the vocabulary match below fails closed to exit 1.
ERROR_TEXT=$(RATE_LIMIT_AGENT="$AGENT" python3 - "$OUTPUT" <<'PYEOF'
import json
import os
import sys

agent = os.environ.get("RATE_LIMIT_AGENT", "")
path = sys.argv[1]
chunks = []


def add(value):
    if isinstance(value, str) and value:
        chunks.append(value)
    elif isinstance(value, dict):
        for nested in value.values():
            add(nested)


try:
    if agent == "claude":
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if isinstance(doc, dict):
            max_turns = (
                doc.get("terminal_reason") == "max_turns"
                or doc.get("subtype") == "error_max_turns"
            )
            is_api_error = doc.get("api_error_status") == 429 or (
                doc.get("is_error") is True and not max_turns
            )
            if is_api_error:
                add(doc.get("result"))
                add(doc.get("error"))
    else:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    event = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(event, dict):
                    continue
                event_type = event.get("type")
                if event_type == "error":
                    add(event.get("message"))
                elif event_type == "turn.failed":
                    add(event.get("error"))
                    add(event.get("message"))
except Exception:
    pass

print("\n".join(chunks))
PYEOF
)

if ! printf '%s\n' "$ERROR_TEXT" | grep -qiE "$REGEX"; then
  exit 1
fi

NOW=$(date +%s)
TARGET=$(RATE_LIMIT_TEXT="$ERROR_TEXT" python3 - "$NOW" <<'PYEOF'
import datetime
import os
import re
import sys

now = int(sys.argv[1])
text = os.environ.get("RATE_LIMIT_TEXT", "")
patterns = [
    r"\breset(?:s)?[^0-9]*(\d{1,2}:\d{2})\s*([ap]\.?m\.?)?",
    r"\btry again at[^0-9]*(\d{1,2}:\d{2})\s*([ap]\.?m\.?)?",
]

for pattern in patterns:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        continue
    clock = match.group(1)
    meridiem = (match.group(2) or "").replace(".", "").upper()
    try:
        if meridiem:
            parsed = datetime.datetime.strptime(clock + meridiem, "%I:%M%p").time()
        else:
            parsed = datetime.datetime.strptime(clock, "%H:%M").time()
    except ValueError:
        continue

    base = datetime.datetime.fromtimestamp(now)
    target = base.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    ts = int(target.timestamp())
    if ts <= now:
        ts += 86400
    print(ts)
    break
PYEOF
)
if [[ -z "$TARGET" ]]; then
  TARGET=$((NOW + 3600))   # default: 1h
fi

mkdir -p .coord
echo "$TARGET" > .coord/sleep-until
exit 0
