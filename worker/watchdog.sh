#!/usr/bin/env bash
# watchdog.sh — Diagnoses and unblocks coord tasks stuck in needs-brainstorming.
# Runs every 20 minutes via launchd alongside the main coord worker.
#
# Usage: watchdog.sh <project-abs-path>

set -euo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

PROJ="${1:?Usage: watchdog.sh <project-abs-path>}"
TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ"
mkdir -p .coord

LOG=.coord/watchdog.log
ts() { TZ=Europe/Dublin date +%FT%T%z; }

# Unattended autonomy gate — same contract as worker.sh. The watchdog mutates
# task state and launches Claude without a human present, so it requires the
# same explicit acknowledgement. The watchdog reads only its process
# environment (launchd plist, written by /coord-unblocker when acknowledged);
# it does not read .coord/config.env.
if [[ "${COORD_UNSAFE_AUTONOMOUS:-0}" != "1" ]]; then
  echo "[$(ts)] COORD_UNSAFE_AUTONOMOUS=1 not set; watchdog triage is disabled (see README 'Blast radius')" >> "$LOG"
  exit 0
fi

codex_doctor_snapshot() {
  local reason="${1:-failure}" task_id="${2:-unknown}" project_name safe_task base path err rc
  project_name=$(basename "$PROJ" | LC_ALL=C tr -c '[:alnum:]._-' '_')
  safe_task=$(printf '%s' "${task_id:-unknown}" | LC_ALL=C tr -c '[:alnum:]._-' '_')
  base=$(mktemp "/tmp/coord-codex-doctor-${project_name}-${safe_task}-${reason}.XXXXXX") || {
    echo "[$(ts)] codex doctor snapshot failed ($reason): unable to allocate /tmp path" >> "$LOG"
    return 0
  }
  path="${base}.json"
  mv "$base" "$path"
  err="${path%.json}.err"
  if "$TOOLS/bin/agent-launch.sh" codex doctor --json --summary > "$path" 2> "$err"; then
    echo "[$(ts)] codex doctor snapshot ($reason): $path" >> "$LOG"
    if [[ -s "$err" ]]; then
      echo "[$(ts)] codex doctor snapshot stderr ($reason): $err" >> "$LOG"
    else
      rm -f "$err"
    fi
    return 0
  fi
  rc=$?
  echo "[$(ts)] codex doctor snapshot failed ($reason rc=$rc): $path stderr=$err" >> "$LOG"
  return 0
}

file_mtime() {
  stat -f %m "$1" 2>/dev/null || echo 0
}

restart_worker() {
  local holder="$1"
  local label="$2"
  local age="$3"
  local stale_after="$4"

  echo "[$(ts)] watchdog: worker stale (pid=$holder age=${age}s >= ${stale_after}s), restarting $label" >> "$LOG"
  if [[ -f "$WORKER_STATE" ]] && grep -q '^agent=codex$' "$WORKER_STATE"; then
    local task_id
    task_id=$(awk -F= '$1 == "task_id" { print $2; exit }' "$WORKER_STATE")
    codex_doctor_snapshot "stale-worker" "${task_id:-unknown}"
  fi
  if launchctl kickstart -k "gui/$(id -u)/$label" >> "$LOG" 2>&1; then
    echo "[$(ts)] watchdog: launchctl restart requested for $label; skipping needs-brainstorming triage this cycle" >> "$LOG"
    return 0
  fi

  echo "[$(ts)] watchdog: launchctl restart failed for $label; sending TERM to pid=$holder" >> "$LOG"
  if kill -TERM "$holder" >> "$LOG" 2>&1; then
    for _ in 1 2 3 4 5; do
      if ! kill -0 "$holder" 2>/dev/null; then
        if [[ "$(cat "$WORKER_LOCK" 2>/dev/null || true)" == "$holder" ]]; then
          rm -f "$WORKER_LOCK"
        fi
        echo "[$(ts)] watchdog: terminated stale worker pid=$holder; skipping needs-brainstorming triage this cycle" >> "$LOG"
        return 0
      fi
      sleep 1
    done
  fi

  echo "[$(ts)] watchdog: failed to restart or terminate stale worker pid=$holder; needs-brainstorming triage skipped" >> "$LOG"
  return 1
}

# Skip if the main worker is actively running a task.
WORKER_LOCK=.coord/worker.lock
WORKER_STATE=.coord/worker.state
if [[ -f "$WORKER_LOCK" ]]; then
  HOLDER=$(cat "$WORKER_LOCK" 2>/dev/null || echo "")
  if [[ -n "$HOLDER" ]] && kill -0 "$HOLDER" 2>/dev/null; then
    STALE_AFTER="${COORD_WATCHDOG_WORKER_STALE_AFTER:-7200}"
    AGE_FILE="$WORKER_LOCK"
    if [[ -f "$WORKER_STATE" ]]; then
      AGE_FILE="$WORKER_STATE"
    fi
    LOCK_MTIME=$(file_mtime "$AGE_FILE")
    NOW=$(date +%s)
    AGE=$((NOW - LOCK_MTIME))
    if [[ "$STALE_AFTER" =~ ^[0-9]+$ ]] && (( STALE_AFTER > 0 && AGE >= STALE_AFTER )); then
      NAME=$(basename "$PROJ")
      LABEL="com.coord.worker.$NAME"
      restart_worker "$HOLDER" "$LABEL" "$AGE" "$STALE_AFTER" || exit 1
    else
      echo "[$(ts)] watchdog: worker running (pid=$HOLDER age=${AGE}s source=$AGE_FILE), skipping cycle" >> "$LOG"
    fi
    exit 0
  fi
fi

# Per-watchdog lock — prevents overlapping cycles.
LOCK=.coord/watchdog.lock
if ! ( set -C; echo "$$" > "$LOCK" ) 2>/dev/null; then
  HOLDER=$(cat "$LOCK" 2>/dev/null || echo "")
  if [[ -n "$HOLDER" ]] && kill -0 "$HOLDER" 2>/dev/null; then
    exit 0
  fi
  rm -f "$LOCK"
  ( set -C; echo "$$" > "$LOCK" ) 2>/dev/null || exit 0
fi

TMPOUT=""
cleanup() {
  [[ -n "$TMPOUT" ]] && rm -f "$TMPOUT"
  rm -f "$LOCK"
}
trap cleanup EXIT

# Sync from remote so we see the latest task state.
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  UPSTREAM=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)
  if [[ -n "$UPSTREAM" ]] && [[ -z "$(git status --porcelain)" ]]; then
    git fetch --quiet "${UPSTREAM%%/*}" >> "$LOG" 2>&1 || true
    git merge --ff-only --quiet "$UPSTREAM" >> "$LOG" 2>&1 || true
  fi
fi

# Reset stale working-state tasks: no active worker lock means no agent is
# actively running, so any *-working task is abandoned. The only valid source
# for *-working is pending, so reset to pending; the worker will re-pick-up and
# this time with the execution policy injected it will finish the transition.
for WORKING_STATUS in codex-working claude-working; do
  STALE_IDS=$(python3 "$TOOLS/bin/coord" list --status="$WORKING_STATUS" --format=ids 2>/dev/null || true)
  for STALE_ID in $STALE_IDS; do
    echo "[$(ts)] watchdog: stale $WORKING_STATUS on $STALE_ID (no active worker); resetting to pending" >> "$LOG"
    python3 "$TOOLS/bin/coord" update "$STALE_ID" --status pending >> "$LOG" 2>&1 || true
  done
done

# Find tasks queued for agent triage (needs-brainstorming set by worker on failure).
# Also scan archive in case a task was mis-archived before the state machine fix.
STUCK_IDS=$(python3 "$TOOLS/bin/coord" list --status=needs-brainstorming --format=ids 2>/dev/null || true)
ARCHIVE_DIR=$(python3 "$TOOLS/bin/coord" paths --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('archive_dir',''))" 2>/dev/null || true)
if [[ -n "$ARCHIVE_DIR" ]] && [[ -d "$ARCHIVE_DIR" ]]; then
  ARCHIVE_STUCK=$(grep -rl "^status: needs-brainstorming" "$ARCHIVE_DIR" 2>/dev/null | xargs -I{} basename {} .md 2>/dev/null || true)
  if [[ -n "$ARCHIVE_STUCK" ]]; then
    STUCK_IDS=$(printf '%s\n%s' "$STUCK_IDS" "$ARCHIVE_STUCK" | grep . | sort -u)
  fi
fi

if [[ -z "$STUCK_IDS" ]]; then
  echo "[$(ts)] watchdog: no stuck tasks" >> "$LOG"
  exit 0
fi

COUNT=$(echo "$STUCK_IDS" | wc -l | tr -d ' ')
echo "[$(ts)] watchdog: $COUNT task(s) to unblock: $(echo "$STUCK_IDS" | tr '\n' ' ')" >> "$LOG"

for ID in $STUCK_IDS; do
  echo "[$(ts)] watchdog: diagnosing $ID" >> "$LOG"

  # macOS mktemp does not expand templates with a suffix after the X's — the
  # first call created a LITERAL coord-watchdog-out-XXXXXX.json and every later
  # call failed "File exists", killing the cycle under set -e (observed
  # 2026-07-03..05: triage silently dead on all projects). mktemp-then-mv,
  # same pattern as codex_doctor_snapshot above.
  TMPOUT=$(mktemp /tmp/coord-watchdog-out-XXXXXX)
  mv "$TMPOUT" "$TMPOUT.json"
  TMPOUT="$TMPOUT.json"

  # Find the most recent agent-run dump for this task (extra context for Claude).
  RUNS_DIR="$PROJ/.coord/agent-runs"
  LAST_RUN=$(ls -t "$RUNS_DIR/${ID}"-*.json 2>/dev/null | head -1 || true)
  LAST_RUN_NOTE=""
  if [[ -n "$LAST_RUN" ]]; then
    LAST_RUN_NOTE="The raw agent output from the last failed run is at: $LAST_RUN"
  fi

  RC=0
  # The COORD_UNSAFE_AUTONOMOUS entry gate has passed by this point. acceptEdits
  # in this headless context silently auto-denies Bash/Skill calls and burns the
  # turn budget, so the acknowledged watchdog uses the same bypass as worker rounds.
  "$TOOLS/bin/agent-launch.sh" claude \
    --dangerously-skip-permissions \
    --max-turns 12 \
    --output-format json \
    --model "${COORD_WATCHDOG_MODEL:-${CLAUDE_MODEL:-claude-sonnet-5}}" \
    -p "You are the coord watchdog. A task is in needs-brainstorming status — the worker queued it here after a failure. Triage it: fix if you can, reset scope if the approach is wrong, leave in needs-brainstorming only if a human is genuinely required (physical device, live credentials, unresolvable design ambiguity).

Project: $PROJ
Coord tools: $TOOLS
Task: $ID
$LAST_RUN_NOTE

STEP 1 — Read the task:
  python3 $TOOLS/bin/coord show $ID --handoff
Read the findings carefully — especially the 'Worker failure' entry and output tail.

STEP 2 — Check for an existing APPROVE signal FIRST (before doing any other work):
Look ONLY at the LATEST round's finding (the highest '### Round N' block in Claude findings and in Codex findings). It must contain APPROVE and no REJECT verdict — an APPROVE in an OLDER round does NOT count; a later REJECT supersedes any earlier APPROVE.
Also run the verify_commands from the task frontmatter to confirm they pass.

If BOTH are true — an APPROVE finding exists AND verify_commands pass — the task is already complete.
Mark it done immediately, do not re-queue:
  python3 $TOOLS/bin/coord update $ID --status review-passed --force --append-claude-finding 'Watchdog: task already approved and verified. Marking done.'
  git add -A && git commit -m 'watchdog: mark $ID done (already approved)' && git push
Then STOP. Do not continue to Step 3.

STEP 3 — If no APPROVE signal or verify_commands fail, reproduce the failure and classify:

FIXABLE (compilation error, import missing, wrong path, assertion failure, schema mismatch, linting, test testing the wrong thing):
  - Fix the root cause in the source files.
  - Re-run verify_commands to confirm green.
  - python3 $TOOLS/bin/coord update $ID --status pending --append-claude-finding 'Watchdog fixed: <root cause>. Verified: <result>. Reset to pending.'
  - git add -A && git commit -m 'watchdog: fix $ID' && git push

WRONG APPROACH / SCOPE MISMATCH (the task is asking for something that conflicts with existing code, the subtask decomposition is wrong, or the acceptance criteria are ambiguous):
  - python3 $TOOLS/bin/coord update $ID --status needs-brainstorming --append-claude-finding 'Watchdog triage: approach needs redesign. Issue: <specific problem>. Suggested fix: <what needs to change in the task or plan>.'
  - Leave in needs-brainstorming. A human will review the finding and adjust the task.

CANNOT AUTO-FIX (physical device, live broker credentials, APNs provisioning, Apple Developer account, unavailable local server, unresolvable design ambiguity):
  - Leave status as needs-brainstorming. Do NOT change the status.
  - python3 $TOOLS/bin/coord update $ID --append-claude-finding 'Watchdog: blocked. Root cause: <reason>. Unblocked by: <specific human action or external dependency>.'
  - The human will see this in needs-brainstorming when they next check in.

Be decisive. Do not ask for clarification." \
    > "$TMPOUT" 2>> "$LOG" || RC=$?

  # Append Claude's result summary to the log.
  python3 - "$TMPOUT" >> "$LOG" 2>&1 <<'PYEOF'
import sys, json
try:
    d = json.load(open(sys.argv[1]))
    result = (d.get("result") or "").strip()
    if result:
        lines = result.splitlines()
        print("\n".join(lines[-30:]))
except Exception as e:
    print(f"watchdog: unable to parse claude result summary: {e}")
PYEOF

  if (( RC != 0 )); then
    echo "[$(ts)] watchdog: claude exited rc=$RC for $ID" >> "$LOG"
  fi

  echo "[$(ts)] watchdog: done $ID" >> "$LOG"
done

echo "[$(ts)] watchdog: cycle complete" >> "$LOG"
