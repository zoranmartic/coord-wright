#!/usr/bin/env bash
# Per-project coord worker. Runs every 60s under launchd. Picks the first
# pending task in the project and runs the assigned agent; handles rate-limit sleep.
#
# Usage: worker.sh <project-abs-path>

set -euo pipefail

# launchd does not inherit the user PATH; add common Claude install locations.
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"

# Force Dublin time in child processes (codex's Rust router logs with a
# Z-suffix UTC timestamp by default; this makes the codex log lines align
# with our bracketed Dublin timestamps so the worker.log timeline is
# readable in one timezone).
export TZ=Europe/Dublin

mktemp_suffix() {
  local prefix="$1" suffix="$2" path
  path=$(mktemp -t "$prefix")
  mv "$path" "${path}.${suffix}"
  printf '%s.%s\n' "$path" "$suffix"
}

# Resolve GNU timeout command (macOS ships none; coreutils provides timeout or gtimeout).
if [[ "${COORD_FORCE_PY_TIMEOUT:-}" == "1" ]]; then
  TIMEOUT_CMD=""
else
  TIMEOUT_CMD=$(command -v timeout || command -v gtimeout || true)
fi

# Wrap a command in a wall-clock timeout when TIMEOUT_CMD and ROUND_TIMEOUT_SECONDS are set.
# Falls back to a Python process-group watchdog when GNU timeout is unavailable.
run_with_timeout() {
  if [[ -z "${ROUND_TIMEOUT_SECONDS:-}" ]]; then
    "$@"
  elif [[ -n "${TIMEOUT_CMD:-}" ]]; then
    "$TIMEOUT_CMD" --kill-after=30 "$ROUND_TIMEOUT_SECONDS" "$@"
  else
    python3 -c '
import os
import signal
import subprocess
import sys

try:
    timeout = int(sys.argv[1])
except Exception:
    timeout = 0
cmd = sys.argv[2:]
if timeout <= 0 or not cmd:
    sys.exit(127)

grace = int(os.environ.get("ROUND_TIMEOUT_GRACE_SECONDS", "30") or "30")
proc = subprocess.Popen(cmd, preexec_fn=os.setsid)
try:
    rc = proc.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=grace)
        sys.exit(124)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        sys.exit(137)

if rc < 0:
    sys.exit(128 + abs(rc))
sys.exit(rc)
' "$ROUND_TIMEOUT_SECONDS" "$@"
  fi
}

annotate_round_timeout_artifact() {
  local path="$1" agent="$2" task_id="$3" elapsed="$4" budget="$5"
  python3 - "$path" "$agent" "$task_id" "$elapsed" "$budget" <<'PYEOF'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
agent, task_id, elapsed, budget = sys.argv[2:6]
metadata = {
    "terminal_reason": "round_timeout",
    "agent": agent,
    "task_id": task_id,
    "elapsed_seconds": int(elapsed),
    "budget_seconds": int(budget),
}

try:
    raw = path.read_text(encoding="utf-8")
except Exception:
    raw = ""

if agent == "claude":
    try:
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {"raw_output": payload}
    except Exception:
        payload = {"raw_output": raw}
    payload["terminal_reason"] = "round_timeout"
    payload["coord_worker"] = metadata
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
else:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "coord.round_timeout", **metadata}, sort_keys=True) + "\n")
PYEOF
}

# Re-exec from an immutable tmp copy so concurrent edits to this file
# (e.g. a `git commit` in the CoordWright checkout landing while a 20-minute agent
# tick is mid-run) cannot truncate our open inode and crash bash with a
# parse error. The copy is removed in cleanup(). TOOLS is captured here
# before re-exec because $0 will point at the tmp copy afterwards.
if [[ "${COORD_WORKER_REEXEC:-}" != "1" ]]; then
  COORD_WORKER_TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
  COORD_WORKER_SELF_COPY=$(mktemp_suffix coord-worker sh)
  cp "$0" "$COORD_WORKER_SELF_COPY"
  export COORD_WORKER_REEXEC=1 COORD_WORKER_TOOLS COORD_WORKER_SELF_COPY
  exec /bin/bash "$COORD_WORKER_SELF_COPY" "$@"
fi

PROJ="${1:?usage: worker.sh <project-abs-path>}"
TOOLS="${COORD_WORKER_TOOLS:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PROJ"
mkdir -p .coord

LOG=.coord/worker.log
STATE=.coord/worker.state
ts() { TZ=Europe/Dublin date +%FT%T%z; }

load_project_config_env() {
  local cfg=".coord/config.env" raw key val
  [[ -f "$cfg" ]] || return 0
  while IFS= read -r raw || [[ -n "$raw" ]]; do
    [[ "$raw" =~ ^[[:space:]]*$ || "$raw" =~ ^[[:space:]]*# || "$raw" != *=* ]] && continue
    key=${raw%%=*}
    key=$(printf '%s' "$key" | tr -d '[:space:]')
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ -n "${!key+x}" ]]; then
      continue
    fi
    val=${raw#*=}
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    if [[ ${#val} -ge 2 ]]; then
      if [[ "${val:0:1}" == '"' && "${val: -1}" == '"' ]]; then
        val="${val:1:${#val}-2}"
      elif [[ "${val:0:1}" == "'" && "${val: -1}" == "'" ]]; then
        val="${val:1:${#val}-2}"
      fi
    fi
    export "$key=$val"
  done < "$cfg"
}

load_project_config_env

# Unattended autonomy gate. Worker rounds run Claude with
# --dangerously-skip-permissions and Codex with danger-full-access — those
# modes can edit, commit, and push in this repository with no prompt. That is
# an explicit operator decision, never a default: without the exact
# acknowledgement value the worker exits before reading the queue or touching
# the worktree. Set COORD_UNSAFE_AUTONOMOUS=1 in the launchd plist environment
# (install.sh writes it when set at install time) or in .coord/config.env.
# See README "Blast radius".
if [[ "${COORD_UNSAFE_AUTONOMOUS:-0}" != "1" ]]; then
  echo "[$(ts)] COORD_UNSAFE_AUTONOMOUS=1 not set; unattended worker rounds are disabled (see README 'Blast radius')" >> "$LOG"
  rm -f "${COORD_WORKER_SELF_COPY:-}"  # created pre-gate; cleanup trap is not installed yet
  exit 0
fi

coord_round_token_threshold() {
  local name="$1" default="$2"
  # Assign value on its own line: on bash 3.2 (macOS /bin/bash, what launchd
  # runs) the indirect expansion ${!name} does not see `name` when both are set
  # in one `local` statement, which would silently pin every threshold to its
  # default and ignore .coord/config.env / env overrides.
  local value="${!name:-}"
  if [[ "$value" =~ ^[0-9]+$ && "$value" -gt 0 ]]; then
    printf '%s\n' "$value"
  else
    printf '%s\n' "$default"
  fi
}

coord_round_token_budget_gate() {
  local effective="${1:-}"
  [[ "$effective" =~ ^[0-9]+$ ]] || return 0

  local warn escalate halt band threshold issue rc
  warn=$(coord_round_token_threshold COORD_ROUND_TOKEN_WARN 1000000)
  escalate=$(coord_round_token_threshold COORD_ROUND_TOKEN_ESCALATE 2000000)
  halt=$(coord_round_token_threshold COORD_ROUND_TOKEN_HALT 4000000)

  if (( effective >= halt )); then
    band="halt"
    threshold="$halt"
  elif (( effective >= escalate )); then
    band="escalate"
    threshold="$escalate"
  elif (( effective >= warn )); then
    band="warn"
    threshold="$warn"
  else
    return 0
  fi

  issue="round_token_${band} for ${ID}: effective=${effective} threshold=${threshold} warn=${warn} escalate=${escalate} halt=${halt}"
  if [[ "$band" == "warn" ]]; then
    echo "[$(ts)] round token budget warn for $ID: effective=${effective} warn=${warn} escalate=${escalate} halt=${halt}; continuing" >> "$LOG"
    rc=0
    python3 "$TOOLS/bin/coord" update "$ID" --add-issues "$issue; continuing" >> "$LOG" 2>&1 || rc=$?
    if (( rc != 0 )); then
      echo "[$(ts)] failed to record token budget warning for $ID (coord update rc=$rc)" >> "$LOG"
      return "$rc"
    fi
    return 0
  fi

  echo "[$(ts)] round token budget ${band} for $ID: effective=${effective} warn=${warn} escalate=${escalate} halt=${halt}; moving to needs-brainstorming" >> "$LOG"
  rc=0
  # The agent may already have advanced the task to done before the worker can
  # inspect token usage, so the circuit-breaker must be able to reopen it.
  python3 "$TOOLS/bin/coord" update "$ID" --force --status needs-brainstorming --add-issues "$issue; no auto-requeue" >> "$LOG" 2>&1 || rc=$?
  if (( rc != 0 )); then
    echo "[$(ts)] failed to apply token budget ${band} for $ID (coord update rc=$rc)" >> "$LOG"
    return "$rc"
  fi
  ROUND_TOKEN_BUDGET_GATE_ACTION="stop"
}

write_worker_state() {
  local phase="${1:-unknown}"
  local task_id="${2:-}"
  local agent="${3:-}"
  local tmp="${STATE}.$$"
  {
    printf 'pid=%s\n' "$$"
    printf 'phase=%s\n' "$phase"
    printf 'task_id=%s\n' "$task_id"
    printf 'agent=%s\n' "$agent"
    printf 'updated_at=%s\n' "$(date +%s)"
  } > "$tmp"
  mv "$tmp" "$STATE"
}

restore_rate_limited_task() {
  local compact current_status current_assigned rc
  compact=$(python3 "$TOOLS/bin/coord" show "$ID" --compact 2>/dev/null || true)
  current_status=$(printf '%s\n' "$compact" | awk '/^status:/ {print $2; exit}' || true)
  current_assigned=$(printf '%s\n' "$compact" | awk '/^assigned:/ {print $2; exit}' || true)

  case "$current_status" in
    "")
      echo "[$(ts)] rate-limit recovery failed for $ID: current status unreadable" >> "$LOG"
      return 1
      ;;
    pending|needs-review)
      echo "[$(ts)] rate-limited; preserving runnable status $current_status assigned=${current_assigned:-unknown}" >> "$LOG"
      return 0
      ;;
    done)
      echo "[$(ts)] rate-limited after task reached done; preserving done" >> "$LOG"
      return 0
      ;;
    claude-working|codex-working)
      if [[ -z "${ORIG_STATUS:-}" || -z "${ORIG_ASSIGNED:-}" ]]; then
        echo "[$(ts)] rate-limit recovery failed for $ID: missing original status/assignee" >> "$LOG"
        return 1
      fi
      rc=0
      python3 "$TOOLS/bin/coord" update "$ID" \
        --force \
        --status "$ORIG_STATUS" \
        --assigned "$ORIG_ASSIGNED" \
        >> "$LOG" 2>&1 || rc=$?
      if (( rc != 0 )); then
        echo "[$(ts)] rate-limit recovery failed for $ID (coord update rc=$rc)" >> "$LOG"
        return "$rc"
      fi
      echo "[$(ts)] rate-limited; restored $ID from $current_status to $ORIG_STATUS assigned=$ORIG_ASSIGNED" >> "$LOG"
      return 0
      ;;
    *)
      echo "[$(ts)] rate-limited; preserving current status ${current_status:-unknown}" >> "$LOG"
      return 0
      ;;
  esac
}

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

source "$TOOLS/bin/coord-commit-agent.sh"

sync_clean_checkout() {
  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi
  local upstream
  upstream=$(current_upstream)
  if [[ -z "$upstream" ]]; then
    return 0
  fi
  if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
    echo "[$(ts)] git sync skipped: worktree dirty before pickup" >> "$LOG"
    return 1
  fi
  git fetch --quiet "${upstream%%/*}" >> "$LOG" 2>&1
  if ! git merge --ff-only --quiet "$upstream" >> "$LOG" 2>&1; then
    echo "[$(ts)] git sync failed: cannot fast-forward to $upstream" >> "$LOG"
    return 1
  fi
}

structured_current_round_verdict() {
  # $1 = task file path (pass explicitly — after review-passed, coord update
  #      auto-archives the file, so the active TASK_PATH may already be stale)
  # $2 = agent (claude|codex) — selects which findings section to scan
  # $3 = verdict to test (approve|reject)
  # exit 0 when the current round's last finding block carries that verdict.
  python3 - "$1" "$2" "$3" <<'PYEOF'
import pathlib, re, sys

try:
    text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
except Exception:
    sys.exit(1)
agent = sys.argv[2].strip().lower()
mode = sys.argv[3].strip().lower()
section_title = "Codex findings" if agent == "codex" else "Claude findings"

frontmatter = re.match(r"\A---\n(.*?)\n---\n", text, re.S)
if not frontmatter:
    sys.exit(1)
round_match = re.search(r"(?m)^round:\s*([0-9]+)\s*$", frontmatter.group(1))
if not round_match:
    sys.exit(1)
round_n = int(round_match.group(1))

section_match = re.search(r"(?ms)^## " + re.escape(section_title) + r"\s*\n(.*?)(?=^## |\Z)", text)
if not section_match:
    sys.exit(1)
section = section_match.group(1)
blocks = [
    match.group(2).strip()
    for match in re.finditer(r"(?ms)^### Round\s+([0-9]+)\s*\n(.*?)(?=^### Round\s+[0-9]+\s*$|\Z)", section)
    if int(match.group(1)) == round_n
]
if not blocks:
    sys.exit(1)

approve = re.compile(r"\bAPPROVE\b|Outcome:.*APPROVE", re.I)
reject_line = re.compile(r"\bREJECT\b|review-failed", re.I)
# The demote trigger is stricter than the approve suppressor: only an explicit
# verdict line counts — "Outcome: ... REJECT", the documented reviewer format
# "REJECT: <reason>" (agents/reviewer.md), "REJECT.", or a standalone REJECT —
# so prose like "prior REJECTs are resolved" cannot false-trip the guard.
reject_verdict = re.compile(r"^\s*[-*]?\s*Outcome:.*\bREJECT\b|^\s*[-*]?\s*REJECT\s*([:.].*)?$", re.I)

approved = False
rejected = False
for line in blocks[-1].splitlines():
    if approve.search(line) and not reject_line.search(line):
        approved = True
    if reject_verdict.search(line):
        rejected = True

if mode == "approve":
    sys.exit(0 if approved and not rejected else 1)
if mode == "reject":
    # An explicit REJECT verdict line wins regardless of stray APPROVE mentions
    # in the same block ("Do not APPROVE until..." must not suppress demotion).
    sys.exit(0 if rejected else 1)
sys.exit(1)
PYEOF
}

structured_current_round_approve() {
  structured_current_round_verdict "$TASK_PATH" "${AGENT:-claude}" approve
}

# Mechanical verify gate. Re-runs the task's verify_commands from the project
# root after a reviewer round closes a task, so the final gate is proven by
# exit codes instead of the reviewer's claim (hollow-gate class, observed
# 2026-06-29 and 2026-07-04: green reviewer claims whose gate commands had
# never actually executed, and a REJECT-then-approve false close).
# $1 = task file path (may be the archived location).
# Returns 0 when every command exits 0 AND the verify left the worktree
# byte-identical; returns 1 otherwise with MECH_VERIFY_ISSUE set.
# Dirt handling: tracked state is snapshotted with `git stash create` (a
# content-true, restorable commit — porcelain text is not path-safe and cannot
# see a verify further mutating an already-dirty file); untracked paths are
# captured NUL-safe. Restore puts tracked files back to the exact pre-verify
# content (preserving uncommitted agent work) and removes only verify-created
# untracked paths. Accepted residual (YAGNI): a verify that DELETES or mutates
# a pre-existing UNTRACKED file is not detected — verify commands create
# artifacts, they do not edit agent files; revisit only if observed.
MECH_VERIFY_ISSUE=""
MECH_PRE_TRACKED_COMMIT=""
MECH_VERIFY_RESTORED=0

mech_verify_tree() {
  # Normalize a stash-create oid to a comparable tree. Empty oid = worktree
  # matches HEAD, so HEAD's tree is the canonical value.
  if [[ -n "$1" ]]; then
    git rev-parse "$1^{tree}" 2>/dev/null || true
  else
    git rev-parse "HEAD^{tree}" 2>/dev/null || true
  fi
}

mechanical_verify_gate() {
  local task_file="$1" cmds rc out_file cmd pre_tree pre_untracked
  cmds=$(python3 - "$TOOLS" "$task_file" 2>>"$LOG" <<'PYEOF'
import runpy, sys
tools, path = sys.argv[1], sys.argv[2]
mod = runpy.run_path(f"{tools}/bin/coord", run_name="coord_worker_mech_verify")
fm, _body = mod["parse_task"](path)
for item in (fm.get("verify_commands") or []):
    text = str(item).strip()
    if text:
        print(text)
PYEOF
  ) || true
  if [[ -z "$cmds" ]]; then
    return 0
  fi
  # Normalize the index before snapshotting: file CONTENT is never touched,
  # but staged-vs-worktree divergence is dropped so (a) a pre-staged agent
  # file lands in the untracked pre-list (protected from cleanup below) and
  # (b) nothing a verify later stages can hide from the dirt scan. Step-6
  # commit staging is redone by the commit helper anyway.
  git reset -q >> "$LOG" 2>&1 || true
  MECH_PRE_TRACKED_COMMIT=$(git stash create 2>/dev/null || true)
  pre_tree=$(mech_verify_tree "$MECH_PRE_TRACKED_COMMIT")
  pre_untracked=$(mktemp /tmp/coord-mech-pre-XXXXXX)
  git ls-files -o --exclude-standard -z > "$pre_untracked" 2>/dev/null || true
  out_file=$(mktemp_suffix coord-mech-verify out)
  while IFS= read -r cmd; do
    [[ -z "$cmd" ]] && continue
    rc=0
    run_with_timeout bash -c "$cmd" > "$out_file" 2>&1 || rc=$?
    if (( rc != 0 )); then
      echo "[$(ts)] mechanical verify gate: '$cmd' exited rc=$rc for $ID" >> "$LOG"
      tail -20 "$out_file" >> "$LOG" 2>&1 || true
      MECH_VERIFY_ISSUE="mechanical verify gate: '$cmd' exited rc=$rc after reviewer close; see .coord/worker.log"
      mech_verify_restore_dirt "$pre_tree" "$pre_untracked"
      rm -f "$out_file" "$pre_untracked"
      return 1
    fi
  done <<< "$cmds"
  rm -f "$out_file"
  mech_verify_restore_dirt "$pre_tree" "$pre_untracked"
  rm -f "$pre_untracked"
  if [[ "$MECH_VERIFY_RESTORED" == "1" ]]; then
    MECH_VERIFY_ISSUE="mechanical verify gate: verify_commands passed but created or mutated worktree content (restored; leftover artifacts violate the gate contract); see .coord/worker.log"
    return 1
  fi
  echo "[$(ts)] mechanical verify gate: all verify_commands passed for $ID" >> "$LOG"
  return 0
}

# Restore the worktree to the pre-verify snapshot and set MECH_VERIFY_RESTORED=1
# when anything had to be restored. Tracked files return to their exact
# pre-verify CONTENT via the stash-create commit (agent's uncommitted work
# preserved byte-for-byte); untracked paths created by the verify are removed
# via a NUL-safe pathspec (space-safe), nothing pre-existing is touched.
mech_verify_restore_dirt() {
  local pre_tree="$1" pre_untracked="$2"
  local post_commit post_tree post_untracked new_untracked new_count
  MECH_VERIFY_RESTORED=0
  # Drop anything the verify staged (git add in a verify command) so it shows
  # as untracked below and gets removed; agent content is unaffected.
  git reset -q >> "$LOG" 2>&1 || true
  post_commit=$(git stash create 2>/dev/null || true)
  post_tree=$(mech_verify_tree "$post_commit")
  if [[ "$post_tree" != "$pre_tree" ]]; then
    MECH_VERIFY_RESTORED=1
    if [[ -n "$MECH_PRE_TRACKED_COMMIT" ]]; then
      git checkout -q "$MECH_PRE_TRACKED_COMMIT" -- . >> "$LOG" 2>&1 \
        || echo "[$(ts)] mechanical verify gate: tracked restore from snapshot failed" >> "$LOG"
    else
      git checkout -q HEAD -- . >> "$LOG" 2>&1 \
        || echo "[$(ts)] mechanical verify gate: tracked restore from HEAD failed" >> "$LOG"
    fi
    echo "[$(ts)] mechanical verify gate: restored tracked files mutated by verify" >> "$LOG"
  fi
  post_untracked=$(mktemp /tmp/coord-mech-post-XXXXXX)
  git ls-files -o --exclude-standard -z > "$post_untracked" 2>/dev/null || true
  new_untracked=$(mktemp /tmp/coord-mech-new-XXXXXX)
  new_count=$(python3 - "$pre_untracked" "$post_untracked" "$new_untracked" <<'PYEOF'
import sys
pre = set(open(sys.argv[1], "rb").read().split(b"\0")) - {b""}
post = set(open(sys.argv[2], "rb").read().split(b"\0")) - {b""}
new = sorted(post - pre)
with open(sys.argv[3], "wb") as f:
    f.write(b"\0".join(new))
print(len(new))
PYEOF
  ) || new_count=0
  if [[ "$new_count" =~ ^[0-9]+$ ]] && (( new_count > 0 )); then
    MECH_VERIFY_RESTORED=1
    # git clean has no --pathspec-from-file; feed each NUL-delimited path
    # explicitly (space-safe, exact set only).
    local vpath
    while IFS= read -r -d '' vpath || [[ -n "$vpath" ]]; do
      [[ -z "$vpath" ]] && continue
      git clean -fdq -- "$vpath" >> "$LOG" 2>&1 \
        || echo "[$(ts)] mechanical verify gate: untracked cleanup failed for '$vpath'" >> "$LOG"
    done < "$new_untracked"
    echo "[$(ts)] mechanical verify gate: removed $new_count verify-created untracked path(s)" >> "$LOG"
  fi
  rm -f "$post_untracked" "$new_untracked"
}

# 1. Skip if rate-limit sleep marker is in the future.
if [[ -f .coord/sleep-until ]]; then
  NOW=$(date +%s)
  UNTIL=$(cat .coord/sleep-until 2>/dev/null || echo 0)
  if (( NOW < UNTIL )); then exit 0; fi
  rm -f .coord/sleep-until
fi

# 2. Per-project lock — prevents overlapping ticks on the same project.
# Uses noclobber instead of flock (flock is not available on macOS).
LOCK=.coord/worker.lock
if ! ( set -C; echo "$$" > "$LOCK" ) 2>/dev/null; then
  HOLDER=$(cat "$LOCK" 2>/dev/null || echo)
  if [[ -z "$HOLDER" ]] || ! kill -0 "$HOLDER" 2>/dev/null; then
    rm -f "$LOCK"
    ( set -C; echo "$$" > "$LOCK" ) 2>/dev/null || exit 0
  else
    exit 0
  fi
fi
write_worker_state "locked"
TMPOUT=""
PROMPT=""
BASE_GIT_STATUS_FILE=""
SCOPE_SPEC_FILE=""
HAVE_SEMAPHORE=0
cleanup() {
  if [[ "$HAVE_SEMAPHORE" == "1" ]]; then
    "$TOOLS/worker/semaphore.sh" release || true
  fi
  if [[ -n "$TMPOUT" ]]; then rm -f "$TMPOUT"; fi
  if [[ -n "$PROMPT" ]]; then rm -f "$PROMPT"; fi
  if [[ -n "$BASE_GIT_STATUS_FILE" ]]; then rm -f "$BASE_GIT_STATUS_FILE"; fi
  if [[ -n "$SCOPE_SPEC_FILE" ]]; then rm -f "$SCOPE_SPEC_FILE"; fi
  rm -f "$STATE"
  rm -f "$LOCK"
  rm -f "${COORD_WORKER_SELF_COPY:-}"
}
trap cleanup EXIT

# 3. Find the first runnable task through the shared path resolver.
sync_clean_checkout || exit 0
AGENT=claude
PICKUP=$(python3 "$TOOLS/bin/coord" pickup --assigned="$AGENT" 2>> "$LOG" || true)
ID=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
if payload.get("decision") == "run":
    print(payload.get("pickup", {}).get("id") or payload.get("task", {}).get("id") or "")
PYEOF
)
if [[ -z "$ID" ]]; then
  AGENT=codex
  PICKUP=$(python3 "$TOOLS/bin/coord" pickup --assigned="$AGENT" 2>> "$LOG" || true)
  ID=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    sys.exit(0)
if payload.get("decision") == "run":
    print(payload.get("pickup", {}).get("id") or payload.get("task", {}).get("id") or "")
PYEOF
)
fi
if [[ -z "$ID" ]]; then exit 0; fi
write_worker_state "picked-up" "$ID" "$AGENT"
ROUND_ROLE=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("round_role", ""))
except Exception:
    pass
PYEOF
)
RESOLVED_MODEL=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("resolved_model", ""))
except Exception:
    pass
PYEOF
)
RESOLVED_MODEL_SOURCE=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("resolved_model_source", ""))
except Exception:
    pass
PYEOF
)
RESOLVED_REASONING=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("resolved_reasoning_effort", ""))
except Exception:
    pass
PYEOF
)
RESOLVED_REASONING_SOURCE=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("resolved_reasoning_effort_source", ""))
except Exception:
    pass
PYEOF
)
CODEX_WORK_MODE=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("codex_execution_policy", {}).get("work_mode", ""))
except Exception:
    pass
PYEOF
)
CODEX_SUCCESS_CMD=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("codex_execution_policy", {}).get("success_update", {}).get("command", ""))
except Exception:
    pass
PYEOF
)
CURRENT_SUBTASK=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("current_subtask", {}).get("id", ""))
except Exception:
    pass
PYEOF
)
ORIG_STATUS=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("task", {}).get("status", ""))
except Exception:
    pass
PYEOF
)
ORIG_ASSIGNED=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("task", {}).get("assigned", ""))
except Exception:
    pass
PYEOF
)
TASK_PATH=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("source", ""))
except Exception:
    pass
PYEOF
)
VERIFY_PROFILE=$(python3 - "$PICKUP" <<'PYEOF'
import json, sys
try:
    print(json.loads(sys.argv[1]).get("task", {}).get("verify_profile", ""))
except Exception:
    pass
PYEOF
)

# 4. Acquire global semaphore slot.
if ! "$TOOLS/worker/semaphore.sh" acquire; then exit 0; fi
HAVE_SEMAPHORE=1

if [[ -n "${COORD_TEST_STALE_PICKUP_HOOK:-}" ]]; then
  bash -c "$COORD_TEST_STALE_PICKUP_HOOK" >> "$LOG" 2>&1 || true
fi

# Re-read the pickup immediately before launch. Metadata can change between
# the initial pickup and semaphore acquisition; stale launches should yield to
# the next tick rather than run with old model or reasoning details.
STALE_PICKUP_REASON=$(python3 - "$PICKUP" "$AGENT" "$TOOLS" <<'PYEOF'
import json
import os
import subprocess
import sys

try:
    original = json.loads(sys.argv[1])
except Exception as exc:
    print(f"original pickup JSON invalid: {exc}")
    sys.exit(0)
agent = sys.argv[2]
tools = sys.argv[3]
task_id = (original.get("pickup") or {}).get("id") or (original.get("task") or {}).get("id")
if not task_id:
    print("original pickup had no task id")
    sys.exit(0)

try:
    result = subprocess.run(
        ["python3", os.path.join(tools, "bin/coord"), "pickup", f"--assigned={agent}", f"--task-id={task_id}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
except subprocess.TimeoutExpired:
    print("pickup-recheck timed out after 15s")
    sys.exit(0)
try:
    fresh = json.loads(result.stdout)
except Exception as exc:
    print(f"fresh pickup JSON invalid: {exc}; stderr={result.stderr.strip()}")
    sys.exit(0)
if fresh.get("decision") != "run":
    print(f"fresh pickup decision is {fresh.get('decision')}: {fresh.get('reason', '')}")
    sys.exit(0)

checks = [
    ("hash", original.get("current_hash"), fresh.get("current_hash")),
    ("status", (original.get("task") or {}).get("status"), (fresh.get("task") or {}).get("status")),
    ("assigned", (original.get("task") or {}).get("assigned"), (fresh.get("task") or {}).get("assigned")),
    ("pickup_hold", bool((original.get("task") or {}).get("pickup_hold")), bool((fresh.get("task") or {}).get("pickup_hold"))),
    ("resolved_model", original.get("resolved_model"), fresh.get("resolved_model")),
    ("resolved_reasoning_effort", original.get("resolved_reasoning_effort"), fresh.get("resolved_reasoning_effort")),
    ("round_role", original.get("round_role"), fresh.get("round_role")),
]
for name, old, new in checks:
    if old != new:
        print(f"{name} changed: {old!r} -> {new!r}")
        sys.exit(0)
print("ok")
PYEOF
)
if [[ "$STALE_PICKUP_REASON" != "ok" ]]; then
  echo "[$(ts)] stale-pickup: $ID with $AGENT skipped before launch ($STALE_PICKUP_REASON)" >> "$LOG"
  exit 0
fi

if [[ -n "${VERIFY_PROFILE:-}" ]]; then
  "$TOOLS/bin/coord-verify-artifacts" "$ID" --capture-baseline >> "$LOG" 2>&1 || \
    echo "[$(ts)] verifier baseline capture warning for $ID profile=$VERIFY_PROFILE" >> "$LOG"
fi

# 5. Run.
echo "[$(ts)] tick: running $ID with $AGENT" >> "$LOG"
write_worker_state "running" "$ID" "$AGENT"
echo "[$(ts)] pickup: role=${ROUND_ROLE:-unknown} model=${RESOLVED_MODEL:-default} model_source=${RESOLVED_MODEL_SOURCE:-unknown} reasoning=${RESOLVED_REASONING:-default} reasoning_source=${RESOLVED_REASONING_SOURCE:-unknown}" >> "$LOG"
BASE_GIT_STATUS=""
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  BASE_GIT_STATUS=$(git status --porcelain --untracked-files=all)
  if [[ -n "$BASE_GIT_STATUS" ]]; then
    echo "[$(ts)] warning: worktree dirty before $AGENT runs $ID" >> "$LOG"
    git status --short >> "$LOG" 2>&1 || true
  fi
fi
BASE_GIT_STATUS_FILE=$(mktemp ".coord/work-base-${ID}-XXXXXX")
printf '%s' "$BASE_GIT_STATUS" > "$BASE_GIT_STATUS_FILE"
export COORD_TASK_ID="$ID"
export COORD_AGENT="$AGENT"
export COORD_BASE_GIT_STATUS_FILE="$BASE_GIT_STATUS_FILE"
# Extract the task's scope and scope_creates globs so the end-of-round work
# commit stages only task paths; files edited concurrently elsewhere in the
# checkout stay uncommitted. With no usable scope the commit helper falls
# back to staging everything (historical behavior).
SCOPE_SPEC_FILE=$(mktemp ".coord/work-scope-${ID}-XXXXXX")
python3 - "$TOOLS" "$ID" > "$SCOPE_SPEC_FILE" 2>>"$LOG" <<'PYEOF' || true
import runpy
import sys

tools, task_id = sys.argv[1], sys.argv[2]
mod = runpy.run_path(f"{tools}/bin/coord", run_name="coord_worker_scope")
path = mod["find_task"](task_id)
if not path:
    raise SystemExit
fm, _body = mod["parse_task"](path)
specs = []
for key in ("scope", "scope_creates"):
    value = fm.get(key)
    if isinstance(value, list):
        specs.extend(str(item).strip() for item in value if str(item).strip())
    elif value is not None and str(value).strip():
        # Contract is list-only; a scalar here silently loses scoped-commit
        # protection, so say it out loud (worker falls back to full staging).
        print(f"warning: {key} in {task_id} is not a YAML list; "
              f"scoped-commit protection is disabled for this round", file=sys.stderr)
for spec in dict.fromkeys(specs):
    print(spec)
PYEOF
if [[ -s "$SCOPE_SPEC_FILE" ]]; then
  export COORD_SCOPE_FILE="$SCOPE_SPEC_FILE"
else
  unset COORD_SCOPE_FILE
fi
TICK_START=$(date +%s)
TMPOUT=$(mktemp_suffix coord-worker-out json)
TASK_MAX_TURNS=$(python3 "$TOOLS/bin/coord" show "$ID" --compact 2>/dev/null | awk '/^max_turns:/ {print $2; exit}' || true)
TASK_MAX_SECONDS=$(python3 "$TOOLS/bin/coord" show "$ID" --compact 2>/dev/null | awk '/^max_seconds:/ {print $2; exit}' || true)
CLAUDE_MAX_TURNS_FLOOR=60
if [[ "$TASK_MAX_TURNS" =~ ^[0-9]+$ ]] && (( TASK_MAX_TURNS > CLAUDE_MAX_TURNS_FLOOR )); then
  CLAUDE_MAX_TURNS=$TASK_MAX_TURNS
else
  CLAUDE_MAX_TURNS=$CLAUDE_MAX_TURNS_FLOOR
fi
# Resolve wall-clock round budget: frontmatter max_seconds -> role default -> hard fallback.
if [[ "$TASK_MAX_SECONDS" =~ ^[0-9]+$ ]]; then
  ROUND_TIMEOUT_SECONDS=$TASK_MAX_SECONDS
elif [[ "$ROUND_ROLE" == "reviewer" || "$ROUND_ROLE" == "architect" ]]; then
  ROUND_TIMEOUT_SECONDS=1800
else
  ROUND_TIMEOUT_SECONDS=1200
fi
echo "[$(ts)] round budget: max_turns=$CLAUDE_MAX_TURNS timeout=${ROUND_TIMEOUT_SECONDS}s" >> "$LOG"
RC=0
# Permission mode is intentionally not pinned here. The non-interactive launchd
# worker context turns "ask before shell" (acceptEdits) into silent auto-denials
# of Skill / Bash / etc., burning the turn budget on bootstrap denials before
# the agent reaches real work. The COORD_UNSAFE_AUTONOMOUS entry gate has
# already passed by this point, so COORD_UNSAFE_AUTONOMOUS=1 is in the
# environment and bin/agent-launch.sh resolves the omitted flag to
# --dangerously-skip-permissions for non-management claude calls. Codex rounds
# below pass their own explicit sandbox flags.
if [[ "$AGENT" == "claude" ]]; then
  CLAUDE_ARGS=(-p "/coord-run $ID" \
    --max-turns "$CLAUDE_MAX_TURNS" \
    --output-format json)
  if [[ -n "${RESOLVED_MODEL:-}" ]]; then
    CLAUDE_ARGS=(--model "$RESOLVED_MODEL" "${CLAUDE_ARGS[@]}")
  fi
  export COORD_WRAPPER_TOKENS=1
  run_with_timeout \
    "$TOOLS/bin/agent-launch.sh" claude "${CLAUDE_ARGS[@]}" > "$TMPOUT" 2>> "$LOG" || RC=$?
else
  PROMPT=$(mktemp_suffix coord-worker-prompt txt)
  # Resolve the finding file path and materialise the success command.
  CODEX_FINDING_FILE="/tmp/codex-finding-${ID}.txt"
  CODEX_SUCCESS_CMD_RESOLVED="${CODEX_SUCCESS_CMD//@<file>/@$CODEX_FINDING_FILE}"
  # Reviewer rounds also get an explicit failure command: with only
  # success_update named, a REJECT verdict has no instructed path — observed
  # 2026-07-04: a reviewer wrote "Outcome: REJECT" then ran success_update,
  # closing the task unverified.
  VERDICT_RULE="When you are done, run the success_update command above exactly as written."
  if [[ "${CODEX_WORK_MODE:-}" == "reviewer" ]]; then
    CODEX_FAILURE_CMD_RESOLVED="${CODEX_SUCCESS_CMD_RESOLVED/--status=review-passed/--status=review-failed}"
    if [[ "$CODEX_FAILURE_CMD_RESOLVED" != "$CODEX_SUCCESS_CMD_RESOLVED" ]]; then
      VERDICT_RULE="Verdict rule: if your review verdict is APPROVE, run the success_update
command exactly as written. If your verdict is REJECT, run this failure command
exactly as written instead — NEVER run success_update after a REJECT:
  failure_update.command: ${CODEX_FAILURE_CMD_RESOLVED}"
    fi
  fi
  cat > "$PROMPT" <<EOF
You are Codex running coord task $ID in $PROJ.

Use the coord-check workflow with AGENT_ROLE=codex. Start from:

python3 "$TOOLS/bin/coord" show "$ID" --handoff

Then follow the smallest necessary read ladder, update status to codex-working,
work only the current subtask or scoped task, and write findings to:
  $CODEX_FINDING_FILE

Execution policy (authoritative — do not guess or skip):
  work_mode: ${CODEX_WORK_MODE:-coder}
  success_update.command: ${CODEX_SUCCESS_CMD_RESOLVED}

$VERDICT_RULE
Do not add --add-tokens-codex, --subtask, or call coord-tokens.sh: the worker
captures real token usage from your stdout JSON after you exit and labels the
row with the current subtask itself. Self-reporting only adds a duplicate
zero row plus an all-zero warning. Never edit task files directly.

Tool reliability (these failures triple round wall time when they happen):
- Before apply_patch on a file, re-read the live file contents in the same
  round (cat or the read tool). apply_patch verifies expected context lines
  against the on-disk file; a stale read causes "apply_patch verification
  failed: Failed to find expected lines" and forces a retry that re-runs the
  full diff. If a verification failure occurs once, re-read the whole target
  range before retrying — do not re-issue the same patch.
- For shell sessions that need follow-on input (write_stdin, REPL-style
  exec_command, interactive prompts), open exec_command with tty=true.
  Without a TTY the kernel closes stdin after the first command and the next
  write_stdin fails with "stdin is closed for this session; rerun
  exec_command with tty=true to keep stdin open".
EOF
  CODEX_ARGS=(-a never -s danger-full-access)
  if [[ -n "${CODEX_SERVICE_TIER:-}" ]]; then
    CODEX_ARGS+=(-c "service_tier=\"$CODEX_SERVICE_TIER\"")
    if [[ "$CODEX_SERVICE_TIER" == "fast" ]]; then
      CODEX_ARGS+=(--enable fast_mode)
    fi
  fi
  if [[ -n "${RESOLVED_REASONING:-}" ]]; then
    CODEX_ARGS+=(-c "model_reasoning_effort=\"$RESOLVED_REASONING\"")
  fi
  if [[ -n "${RESOLVED_MODEL:-}" ]]; then
    CODEX_ARGS+=(--model "$RESOLVED_MODEL")
  fi
  CODEX_ARGS+=(exec --json --cd "$PROJ" -)
  export COORD_WRAPPER_TOKENS=1
  run_with_timeout \
    "$TOOLS/bin/agent-launch.sh" codex "${CODEX_ARGS[@]}" \
    < "$PROMPT" \
    > "$TMPOUT" 2>> "$LOG" || RC=$?
fi

# Append text result to log regardless of exit code.
python3 - "$TMPOUT" "$AGENT" >> "$LOG" 2>/dev/null <<'PYEOF'
import sys, json
path, agent = sys.argv[1], sys.argv[2]
try:
    if agent == "claude":
        d = json.load(open(path))
        lines = len((d.get("result") or "").splitlines())
        print(f"agent output: {lines} line(s) in result")
    else:
        msgs = 0
        last_lines = 0
        for raw in open(path):
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    msgs += 1
                    last_lines = len((item.get("text") or "").splitlines())
        print(f"agent output: {msgs} message(s), last wrap-up {last_lines} line(s)")
except Exception:
    pass
PYEOF

ROUND_TIMEOUT_TERMINAL=0
ELAPSED_SECONDS=$(( $(date +%s) - TICK_START ))
if (( RC == 124 || RC == 137 )); then
  ROUND_TIMEOUT_TERMINAL=1
  echo "[$(ts)] round timeout (rc=$RC, budget=${ROUND_TIMEOUT_SECONDS}s, elapsed=${ELAPSED_SECONDS}s) for $ID" >> "$LOG"
  # Preserve any agent finding written before the timeout.
  AGENT_FINDING_SRC="/tmp/${AGENT}-finding-${ID}.txt"
  if [[ -f "$AGENT_FINDING_SRC" && -s "$AGENT_FINDING_SRC" ]]; then
    FINDING_DEST=".coord/finding-${ID}-$(date +%Y%m%dT%H%M%S).txt"
    cp "$AGENT_FINDING_SRC" "$FINDING_DEST" 2>/dev/null || true
    echo "[$(ts)] preserved agent finding to $FINDING_DEST" >> "$LOG"
  fi
fi

if (( RC != 0 )); then
  write_worker_state "failed" "$ID" "$AGENT"
  if "$TOOLS/worker/rate-limit.sh" check "$AGENT" "$TMPOUT"; then
    if restore_rate_limited_task; then
      echo "[$(ts)] rate-limited; sleep-until set" >> "$LOG"
      exit 0
    fi
    rm -f .coord/sleep-until
    echo "[$(ts)] rate-limit detected but recovery failed; surfacing for human review" >> "$LOG"
  fi
  if [[ "$AGENT" == "codex" ]]; then
    codex_doctor_snapshot "agent-failure" "$ID"
  fi
  echo "[$(ts)] tick failed rc=$RC for $ID; surfacing for human review" >> "$LOG"

  # Preserve agent output for post-mortem debugging.
  RUNS_DIR="$PROJ/.coord/agent-runs"
  mkdir -p "$RUNS_DIR"
  ROUND_NUM=$(python3 "$TOOLS/bin/coord" show "$ID" --compact 2>/dev/null | grep '^round:' | awk '{print $2}')
  DEBUG_COPY="$RUNS_DIR/${ID}-r${ROUND_NUM:-0}-$(date +%Y%m%dT%H%M%S).json"
  cp "$TMPOUT" "$DEBUG_COPY" 2>/dev/null || true
  if [[ "${ROUND_TIMEOUT_TERMINAL:-0}" == "1" ]]; then
    annotate_round_timeout_artifact "$DEBUG_COPY" "$AGENT" "$ID" "$ELAPSED_SECONDS" "$ROUND_TIMEOUT_SECONDS" || true
  fi
  echo "[$(ts)] agent output saved to $DEBUG_COPY" >> "$LOG"

  # Detect max-turns terminal reason. Claude exposes it as a top-level JSON field;
  # Codex emits a `turn.failed` JSONL event whose payload may name the cause
  # (max_turns / turn_limit / turn_budget / turn_exhausted / turn_exceeded).
  # Codex's exact field names are not documented, so the scan walks every leaf
  # string while requiring `turn` proximity for exceeded/exhausted alternates so
  # generic provider or quota errors do not trigger max-turns recovery.
  MAX_TURNS_TERMINAL=$(python3 - "$DEBUG_COPY" "$AGENT" 2>/dev/null <<'PYEOF'
import sys, json, re
path, agent = sys.argv[1], sys.argv[2]
try:
    if agent == "claude":
        d = json.load(open(path))
        if d.get("terminal_reason") == "max_turns" or d.get("subtype") == "error_max_turns":
            print("max_turns")
    else:
        pattern = re.compile(r"max[_\s-]?turn|turn[_\s-]?(limit|budget|cap|exceeded|exhausted)", re.I)
        def walk(node):
            if isinstance(node, str):
                return bool(pattern.search(node))
            if isinstance(node, dict):
                return any(walk(v) for v in node.values())
            if isinstance(node, list):
                return any(walk(v) for v in node)
            return False
        for raw in open(path):
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if event.get("type") != "turn.failed":
                continue
            if walk(event):
                print("max_turns")
                break
except Exception:
    pass
PYEOF
  )

  # Save any work the agent produced before exiting.
  TENTATIVE_COMMITTED=$(commit_tentative_changes "$RC") || true

  # Capture the agent output tail for the finding.
  TAIL=$(python3 - "$TMPOUT" "$AGENT" 2>/dev/null <<'PYEOF'
import sys, json
path, agent = sys.argv[1], sys.argv[2]
out = ""
try:
    if agent == "claude":
        d = json.load(open(path))
        # Prefer result text; fall back to structured error fields
        out = d.get("result") or ""
        if not out:
            parts = []
            if d.get("subtype"):
                parts.append(f"subtype: {d['subtype']}")
            if d.get("is_error"):
                parts.append("is_error: true")
            if d.get("num_turns") is not None:
                parts.append(f"num_turns: {d['num_turns']}")
            if d.get("error"):
                parts.append(f"error: {d['error']}")
            # Last assistant message if available
            msgs = d.get("messages") or []
            for m in reversed(msgs):
                if m.get("role") == "assistant":
                    for blk in (m.get("content") or []):
                        if isinstance(blk, dict) and blk.get("type") == "text":
                            parts.append(blk["text"])
                            break
                    break
            out = "\n".join(parts)
    else:
        msgs = []
        for raw in open(path):
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message":
                    msgs.append(item.get("text", "") or "")
        out = "\n".join(msgs)
except Exception as e:
    out = f"(parse error: {e})"
lines = out.splitlines()
print("\n".join(lines[-40:]))
PYEOF
)
  # Reviewer auto-recovery: if the reviewer already wrote an APPROVE finding
  # (via --append-claude-finding) for the current round before hitting the turn
  # cap, promote instead of sending to triage. A bare APPROVE in the output tail
  # is not enough; the same-line REJECT guard prevents promoting an
  # "APPROVE after fixes, but currently REJECT" finding line.
  # Must run before the max-turns auto-requeue block so an approved reviewer
  # round is promoted rather than requeued.
  if [[ "$ROUND_ROLE" == "reviewer" ]]; then
    if structured_current_round_approve; then
      # This early-exit path bypasses the post-close 5b/5c guards, so the
      # mechanical verify gate must be proven HERE before the promote — an
      # APPROVE finding with failing verify_commands must not archive as done.
      if ! mechanical_verify_gate "$TASK_PATH"; then
        echo "[$(ts)] reviewer approve recovery blocked by mechanical verify gate for $ID" >> "$LOG"
      else
        echo "[$(ts)] reviewer approved despite rc=$RC; auto-promoting $ID to review-passed" >> "$LOG"
        APPROVE_UPDATE_RC=0
        python3 "$TOOLS/bin/coord" update "$ID" --status review-passed >> "$LOG" 2>&1 || APPROVE_UPDATE_RC=$?
        if (( APPROVE_UPDATE_RC == 0 )); then
          commit_agent_changes || true
          exit 0
        fi
        echo "[$(ts)] reviewer approve recovery failed for $ID (coord update rc=$APPROVE_UPDATE_RC)" >> "$LOG"
      fi
    fi
  fi

  # Auto-requeue once on max-turns if progress was made (Claude or Codex).
  # Wall-clock timeouts are never auto-requeued — a stuck round means shaping is wrong.
  if [[ "$MAX_TURNS_TERMINAL" == "max_turns" && "${ROUND_TIMEOUT_TERMINAL:-0}" != "1" && -n "$ORIG_STATUS" && -n "$ORIG_ASSIGNED" ]]; then
    TASK_COMPACT=$(python3 "$TOOLS/bin/coord" show "$ID" --compact 2>/dev/null || true)
    CURRENT_STATUS=$(printf '%s\n' "$TASK_COMPACT" | awk '/^status:/ {print $2; exit}' || true)
    CURRENT_ASSIGNED=$(printf '%s\n' "$TASK_COMPACT" | awk '/^assigned:/ {print $2; exit}' || true)
    RETRIES_USED=$(printf '%s\n' "$TASK_COMPACT" | awk '/^max_turns_retries_used:/ {print $2; exit}' || true)
    RETRIES_USED=${RETRIES_USED:-0}
    if (( RETRIES_USED >= 1 )); then
      echo "[$(ts)] auto-requeue exhausted for $ID (retries_used=$RETRIES_USED); surfacing for human review" >> "$LOG"
    elif [[ "$CURRENT_STATUS" == "done" ]]; then
      echo "[$(ts)] auto-requeue skipped for $ID: task already done" >> "$LOG"
      exit 0
    else
      PROGRESS=$(python3 - "$PROJ" "$TASK_PATH" "/tmp/${AGENT}-finding-${ID}.txt" "$TICK_START" "${TENTATIVE_COMMITTED:-0}" "$AGENT" 2>/dev/null <<'PYEOF'
import os, subprocess, sys
proj, task_path, tmp_finding, tick_start_str, committed, agent = sys.argv[1:7]
try:
    tick_start = int(tick_start_str)
except Exception:
    tick_start = 0

if committed.strip() == "1":
    print(1)
    sys.exit(0)

if os.path.exists(tmp_finding) and os.path.getsize(tmp_finding) > 0:
    if int(os.path.getmtime(tmp_finding)) >= tick_start:
        print(1)
        sys.exit(0)

if task_path:
    result = subprocess.run(
        ["git", "log", "--format=%ct %s", "--", task_path],
        cwd=proj, text=True, capture_output=True, check=False,
    )
    needle = f"{agent}-finding"
    for raw in result.stdout.splitlines():
        ts, _, subject = raw.partition(" ")
        try:
            if int(ts) >= tick_start and (needle in subject or "complete-subtask=" in subject):
                print(1)
                sys.exit(0)
        except Exception:
            pass
PYEOF
      )
      if [[ "${PROGRESS:-0}" != "1" ]]; then
        echo "[$(ts)] auto-requeue skipped for $ID: no progress signal; surfacing for human review" >> "$LOG"
      else
        NEW_TURNS=$(( CLAUDE_MAX_TURNS * 3 ))
        REQUEUE_STATUS="$ORIG_STATUS"
        REQUEUE_ASSIGNED="$ORIG_ASSIGNED"
        if [[ "$CURRENT_STATUS" == "pending" || "$CURRENT_STATUS" == "needs-review" ]]; then
          REQUEUE_STATUS="$CURRENT_STATUS"
          REQUEUE_ASSIGNED="${CURRENT_ASSIGNED:-$ORIG_ASSIGNED}"
        fi
        UPDATE_RC=0
        python3 "$TOOLS/bin/coord" update "$ID" \
          --force \
          --max-turns "$NEW_TURNS" \
          --max-turns-retries-used 1 \
          --status "$REQUEUE_STATUS" \
          --assigned "$REQUEUE_ASSIGNED" \
          >> "$LOG" 2>&1 || UPDATE_RC=$?
        if (( UPDATE_RC == 0 )); then
          echo "[$(ts)] auto-requeued $ID: max_turns $CLAUDE_MAX_TURNS -> $NEW_TURNS (retry 1/1), status restored to $REQUEUE_STATUS assigned=$REQUEUE_ASSIGNED" >> "$LOG"
          exit 0
        else
          echo "[$(ts)] auto-requeue failed for $ID (coord update rc=$UPDATE_RC); surfacing for human review" >> "$LOG"
        fi
      fi
    fi
  fi

  FINDING_FLAG="--append-${AGENT}-finding"
  NEEDS_BRAINSTORMING_RC=0
  if [[ "${ROUND_TIMEOUT_TERMINAL:-0}" == "1" ]]; then
    FINDING="terminal_reason=round_timeout
Agent: $AGENT elapsed=${ELAPSED_SECONDS}s budget=${ROUND_TIMEOUT_SECONDS}s
Output tail (partial):
${TAIL:-(no output captured)}"
    TIMEOUT_ISSUE="terminal_reason=round_timeout for $ID: elapsed ${ELAPSED_SECONDS}s exceeded budget ${ROUND_TIMEOUT_SECONDS}s. Re-shape with a larger max_seconds value, or check external dependencies first (DB/host reachability) — a hung dependency produces this same signal (observed 2026-07-04)."
    python3 "$TOOLS/bin/coord" update "$ID" \
      --status needs-brainstorming \
      "$FINDING_FLAG" "$FINDING" \
      --add-issues "$TIMEOUT_ISSUE" \
      >> "$LOG" 2>&1 || NEEDS_BRAINSTORMING_RC=$?
  else
    FINDING="Worker failure (rc=$RC) — queued for agent triage.
Agent: $AGENT
Output tail:
${TAIL:-(no output captured)}"
    python3 "$TOOLS/bin/coord" update "$ID" \
      --status needs-brainstorming \
      "$FINDING_FLAG" "$FINDING" \
      >> "$LOG" 2>&1 || NEEDS_BRAINSTORMING_RC=$?
  fi

  if (( NEEDS_BRAINSTORMING_RC != 0 )); then
    echo "[$(ts)] failed to surface $ID as needs-brainstorming (coord update rc=$NEEDS_BRAINSTORMING_RC)" >> "$LOG"
    exit "$NEEDS_BRAINSTORMING_RC"
  fi

  exit 0
fi

# 5b. Reviewer false-approve guard. A reviewer agent (codex especially — the
# structured scan above only runs on non-zero exits) can write a REJECT finding
# yet still execute the success_update, closing the task unverified (observed
# 2026-07-04: a reviewer wrote "Outcome: REJECT" yet ran success_update while
# the verify target was unreachable, closing the task as done). If this was a
# reviewer round, the task ended closed, and the current round's finding
# carries an explicit REJECT verdict, demote back to the coder instead of
# letting the false close stand.
if [[ "$ROUND_ROLE" == "reviewer" ]]; then
  # coord update auto-archives on the done transition INSIDE the same update
  # call, so a falsely-closed task is usually already in the archive dir by
  # the time this guard runs — resolve the live location first.
  GUARD_TASK_PATH="$TASK_PATH"
  if [[ ! -f "$GUARD_TASK_PATH" ]]; then
    ARCH_CAND="$(dirname "$TASK_PATH")/archive/$(basename "$TASK_PATH")"
    if [[ -f "$ARCH_CAND" ]]; then
      GUARD_TASK_PATH="$ARCH_CAND"
    elif [[ -n "${COORD_ARCHIVE_DIR:-}" && -f "$COORD_ARCHIVE_DIR/$(basename "$TASK_PATH")" ]]; then
      GUARD_TASK_PATH="$COORD_ARCHIVE_DIR/$(basename "$TASK_PATH")"
    fi
  fi
  CLOSED_STATUS=$(awk '/^status:/{print $2; exit}' "$GUARD_TASK_PATH" 2>/dev/null || true)
  if [[ "$CLOSED_STATUS" == "done" ]] \
     && structured_current_round_verdict "$GUARD_TASK_PATH" "$AGENT" reject; then
    echo "[$(ts)] reviewer false-approve guard: $AGENT finding says REJECT but $ID closed as done; demoting to review-failed" >> "$LOG"
    python3 "$TOOLS/bin/coord" update "$ID" --status=review-failed --force \
      --add-issues="worker false-approve guard: reviewer finding for this round says REJECT but the round closed the task as done; demoted back to the coder" >> "$LOG" 2>&1 \
      || echo "[$(ts)] false-approve guard demote failed for $ID" >> "$LOG"
  elif [[ "$CLOSED_STATUS" == "done" ]]; then
    # 5c. Mechanical verify gate: the reviewer closed the task — prove the
    # final gate with exit codes before letting done stand.
    if ! mechanical_verify_gate "$GUARD_TASK_PATH"; then
      echo "[$(ts)] mechanical verify gate failed after reviewer close; demoting $ID to review-failed" >> "$LOG"
      python3 "$TOOLS/bin/coord" update "$ID" --status=review-failed --force \
        --add-issues="${MECH_VERIFY_ISSUE:-mechanical verify gate failed after reviewer close}" >> "$LOG" 2>&1 \
        || echo "[$(ts)] mechanical verify demote failed for $ID" >> "$LOG"
    fi
  fi
fi

# 6. Commit successful agent work before recording wrapper token usage.
if ! commit_agent_changes; then
  echo "[$(ts)] tick failed: uncommitted work remains after $ID" >> "$LOG"
  exit 1
fi

STAGE_LABEL="${CURRENT_SUBTASK:-}"
if [[ -z "$STAGE_LABEL" ]]; then
  case "${ORIG_STATUS:-}" in
    needs-review) STAGE_LABEL="fix" ;;
    pending) STAGE_LABEL="code" ;;
  esac
fi

RUNTIME_WARNING_CODES=$(python3 - "$TMPOUT" 2>/dev/null <<'PYEOF'
import json
import re
import sys

path = sys.argv[1]
needle = re.compile(r"write_stdin.*stdin is closed|stdin is closed.*write_stdin", re.I | re.S)

def walk(node):
    if isinstance(node, str):
        return bool(needle.search(node))
    if isinstance(node, dict):
        return any(walk(v) for v in node.values())
    if isinstance(node, list):
        return any(walk(v) for v in node)
    return False

found = False
try:
    for raw in open(path, encoding="utf-8", errors="ignore"):
        if needle.search(raw):
            found = True
            break
        try:
            event = json.loads(raw)
        except Exception:
            continue
        if walk(event):
            found = True
            break
except Exception:
    pass
if found:
    print("closed-stdin")
PYEOF
)
if [[ "$RUNTIME_WARNING_CODES" == *"closed-stdin"* ]]; then
  RUNTIME_WARNING_ARGS=("--add-runtime-warning=closed-stdin" "--add-runtime-warning-agent=$AGENT")
  if [[ -n "${STAGE_LABEL:-}" ]]; then
    RUNTIME_WARNING_ARGS+=("--subtask=$STAGE_LABEL")
  fi
  python3 "$TOOLS/bin/coord" update "$ID" "${RUNTIME_WARNING_ARGS[@]}" >> "$LOG" 2>&1 || \
    echo "[$(ts)] runtime warning recording skipped for $ID" >> "$LOG"
fi

# 7. Report token usage to the task file.
ROUND_TOKEN_USAGE_FILE=$(mktemp_suffix coord-round-tokens json)
ROUND_EFFECTIVE_TOKENS=""
python3 - "$TMPOUT" "$ID" "$TOOLS" "$PROJ" "$AGENT" "${STAGE_LABEL:-}" "${ROUND_ROLE:-}" "$ROUND_TOKEN_USAGE_FILE" >> "$LOG" 2>&1 <<'PYEOF'
import sys, json, subprocess, os
tmpout, task_id, tools, proj, agent = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
subtask = sys.argv[6] if len(sys.argv) > 6 else ""
round_role = sys.argv[7] if len(sys.argv) > 7 else ""
usage_file = sys.argv[8] if len(sys.argv) > 8 else ""
sys.path.insert(0, os.path.join(tools, "bin"))
from coord_token_effective import effective_tokens
# Fall back to a role tag (review/arch) when there is no subtask label, so the
# token row's Stage column shows what the round was instead of being blank.
if not subtask:
    if round_role == "reviewer":
        subtask = "review"
    elif round_role == "architect":
        subtask = "arch"
try:
    visible_work = False
    cache_create = 0
    if agent == "claude":
        d = json.load(open(tmpout))
        visible_work = bool((d.get("result") or "").strip())
        u = d.get("usage")
        missing_usage = not isinstance(u, dict)
        if missing_usage:
            u = {}
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        cache = u.get("cache_read_input_tokens", 0)
        cache_create = u.get("cache_creation_input_tokens", 0)
        effective = effective_tokens("claude", inp, out, cache, cache_create)
    else:
        u = None
        for raw in open(tmpout):
            try:
                event = json.loads(raw)
            except Exception:
                continue
            if event.get("type") == "item.completed":
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and (item.get("text") or "").strip():
                    visible_work = True
            if event.get("type") == "turn.completed":
                u = event.get("usage")
        missing_usage = not isinstance(u, dict)
        if missing_usage:
            u = {}
        inp = u.get("input_tokens", 0)
        out = u.get("output_tokens", 0)
        cache = u.get("cached_input_tokens", 0)
        inp = max(inp - cache, 0)
        effective = effective_tokens("codex", inp, out, cache, cache_create)
    warnings = []
    if missing_usage:
        warnings.append("missing-usage")
    if inp == 0 and out == 0 and cache == 0:
        warnings.append("all-zero")
    if inp == 0 and out == 0 and cache > 0:
        warnings.append("cache-only")
    if out == 0 and visible_work:
        warnings.append("output-zero-with-work")
    payload = json.dumps({
        "input":       inp,
        "output":      out,
        "cache_read":  cache,
        "effective":   effective,
        "warnings":    warnings,
        "missing_usage": missing_usage,
        "agent_visible_work": visible_work,
    })
    if usage_file:
        with open(usage_file, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
    update_args = [
        "python3", os.path.join(tools, "bin/coord"), "update", task_id,
        f"--add-tokens-{agent}={payload}",
    ]
    if subtask:
        update_args.append(f"--subtask={subtask}")
    subprocess.run(update_args, cwd=proj, check=True, capture_output=True)
    print(f"tokens reported for {task_id} ({agent}{f' {subtask}' if subtask else ''})")
    if warnings:
        print(f"token warnings for {task_id} ({agent}): {', '.join(warnings)}")
except Exception as e:
    print(f"token reporting skipped: {e}")
PYEOF
if [[ -s "$ROUND_TOKEN_USAGE_FILE" ]]; then
  ROUND_EFFECTIVE_TOKENS=$(python3 - "$ROUND_TOKEN_USAGE_FILE" <<'PYEOF'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        print(int((json.load(f) or {}).get("effective", 0) or 0))
except Exception:
    print("")
PYEOF
)
fi
ROUND_TOKEN_BUDGET_GATE_ACTION="continue"
if [[ -n "${ROUND_EFFECTIVE_TOKENS:-}" ]]; then
  if ! coord_round_token_budget_gate "$ROUND_EFFECTIVE_TOKENS"; then
    echo "[$(ts)] token budget gate failed for $ID" >> "$LOG"
    exit 1
  fi
  if [[ "$ROUND_TOKEN_BUDGET_GATE_ACTION" == "stop" ]]; then
    write_worker_state "token-budget" "$ID" "$AGENT"
    exit 0
  fi
fi

if [[ -n "${VERIFY_PROFILE:-}" ]]; then
  VERIFY_OUT=$(mktemp_suffix coord-verify out)
  if ! "$TOOLS/bin/coord-verify-artifacts" "$ID" > "$VERIFY_OUT" 2>&1; then
    echo "[$(ts)] artifact verifier failed for $ID profile=$VERIFY_PROFILE" >> "$LOG"
    tail -40 "$VERIFY_OUT" >> "$LOG" 2>&1 || true
    ROUTE=$(python3 - "$TOOLS" "$ID" <<'PYEOF'
import runpy
import sys

tools, task_id = sys.argv[1], sys.argv[2]
mod = runpy.run_path(f"{tools}/bin/coord", run_name="coord_worker_verify_route")
path = mod["find_task"](task_id)
if not path:
    print("needs-brainstorming:")
    raise SystemExit
fm, _body = mod["parse_task"](path)
roles = fm.get("roles") or {}
reviewer = roles.get("reviewer") if isinstance(roles, dict) else None
if reviewer in ("claude", "codex"):
    print(f"needs-review:{reviewer}")
else:
    print("needs-brainstorming:")
PYEOF
)
    ROUTE_STATUS="${ROUTE%%:*}"
    ROUTE_ASSIGNED="${ROUTE#*:}"
    VERIFY_TAIL=$(tail -40 "$VERIFY_OUT" 2>/dev/null || true)
    FINDING="Artifact verifier failure (profile=${VERIFY_PROFILE}).
${VERIFY_TAIL:-no verifier output captured}"
    ISSUE="artifact verifier failed for $ID (profile=${VERIFY_PROFILE}); see ${LOG}"
    UPDATE_ARGS=("$ID" "--force" "--status=$ROUTE_STATUS" "--append-${AGENT}-finding" "$FINDING" "--add-issues" "$ISSUE")
    if [[ "$ROUTE_STATUS" == "needs-review" && -n "$ROUTE_ASSIGNED" ]]; then
      UPDATE_ARGS+=("--assigned=$ROUTE_ASSIGNED")
    fi
    VERIFY_ROUTE_RC=0
    python3 "$TOOLS/bin/coord" update "${UPDATE_ARGS[@]}" >> "$LOG" 2>&1 || VERIFY_ROUTE_RC=$?
    rm -f "$VERIFY_OUT"
    if (( VERIFY_ROUTE_RC != 0 )); then
      echo "[$(ts)] failed to route verifier failure for $ID (coord update rc=$VERIFY_ROUTE_RC)" >> "$LOG"
      exit "$VERIFY_ROUTE_RC"
    fi
    write_worker_state "verifier-failed" "$ID" "$AGENT"
    exit 0
  fi
  cat "$VERIFY_OUT" >> "$LOG" 2>&1 || true
  rm -f "$VERIFY_OUT"
fi

echo "[$(ts)] tick: done $ID with $AGENT" >> "$LOG"
write_worker_state "done" "$ID" "$AGENT"
