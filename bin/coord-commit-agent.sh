#!/usr/bin/env bash

coord_commit_ts() {
  if [[ -n "${COORD_TZ:-}" ]]; then
    TZ="$COORD_TZ" date +%FT%T%z
  else
    date +%FT%T%z
  fi
}

coord_commit_log() {
  if [[ -n "${LOG:-}" ]]; then
    echo "[$(coord_commit_ts)] $*" >> "$LOG"
  else
    echo "[$(coord_commit_ts)] $*" >&2
  fi
}

coord_commit_run_logged() {
  if [[ -n "${LOG:-}" ]]; then
    "$@" >> "$LOG" 2>&1
  else
    "$@" >/dev/null 2>&1
  fi
}

coord_commit_status_logged() {
  if [[ -n "${LOG:-}" ]]; then
    git status --short >> "$LOG" 2>&1 || true
  else
    git status --short >&2 || true
  fi
}

coord_commit_require_env() {
  local missing=()
  local name
  for name in COORD_TASK_ID COORD_AGENT COORD_BASE_GIT_STATUS_FILE; do
    if [[ -z "${!name:-}" ]]; then
      missing+=("$name")
    fi
  done
  if (( ${#missing[@]} )); then
    coord_commit_log "git commit failed: missing required env ${missing[*]}"
    return 2
  fi
  if [[ ! -f "$COORD_BASE_GIT_STATUS_FILE" ]]; then
    coord_commit_log "git commit failed: base status file not found: $COORD_BASE_GIT_STATUS_FILE"
    return 2
  fi
}

current_upstream() {
  git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true
}

push_current_branch() {
  local upstream
  if [[ -z "$(git remote)" ]]; then
    coord_commit_log "no git remote; commit kept local, push skipped"
    return 0
  fi
  upstream=$(current_upstream)
  if [[ -n "$upstream" ]]; then
    coord_commit_run_logged git fetch --quiet "${upstream%%/*}"
    if ! coord_commit_run_logged git rebase --autostash "$upstream"; then
      coord_commit_log "git rebase before push failed against $upstream"
      return 1
    fi
  fi
  coord_commit_run_logged git push --quiet
}

coord_commit_scope_specs() {
  # Pathspecs for the work commit: coord-owned paths plus the task's scope
  # and scope_creates globs from COORD_SCOPE_FILE (one per line). No output
  # means no scope is available and the caller falls back to staging
  # everything.
  if [[ -z "${COORD_SCOPE_FILE:-}" || ! -s "$COORD_SCOPE_FILE" ]]; then
    return 0
  fi
  local spec
  # Configured task paths (COORD_TASKS_DIR etc. or .coord/config.env).
  # A failing coord must not empty the spec list (that would stage everything).
  { python3 "$(dirname "${BASH_SOURCE[0]}")/coord" paths | cut -f2; } || printf 'tasks\n'
  printf '.coord\n'
  while IFS= read -r spec; do
    if [[ -z "$spec" ]]; then
      continue
    fi
    if [[ "$spec" == *"*"* ]]; then
      printf ':(glob)%s\n' "$spec"
    else
      printf '%s\n' "$spec"
    fi
  done < "$COORD_SCOPE_FILE"
}

coord_commit_stage_changes() {
  # Stage agent changes for the work commit. With task scope available only
  # matching paths are staged, so files edited concurrently elsewhere in the
  # checkout are not swept into the coord commit; without scope keep the
  # historical stage-everything behavior.
  local spec
  local specs=()
  COORD_COMMIT_MATCHED_SPECS=()
  COORD_COMMIT_HAS_SCOPE=0
  while IFS= read -r spec; do
    if [[ -n "$spec" ]]; then
      specs+=("$spec")
    fi
  done < <(coord_commit_scope_specs)
  if (( ${#specs[@]} == 0 )); then
    git reset -q || return 1
    git add -A || return 1
    return 0
  fi
  COORD_COMMIT_HAS_SCOPE=1
  git reset -q || return 1
  for spec in "${specs[@]}"; do
    # git add errors on pathspecs that match nothing; only pass specs with
    # pending changes.
    if [[ -n $(git status --porcelain --untracked-files=all -- "$spec" 2>/dev/null) ]]; then
      COORD_COMMIT_MATCHED_SPECS+=("$spec")
    fi
  done
  if (( ${#COORD_COMMIT_MATCHED_SPECS[@]} > 0 )); then
    git add -A -- "${COORD_COMMIT_MATCHED_SPECS[@]}" || return 1
  fi
}

coord_commit_warn_leftovers() {
  # After a scoped stage, anything still dirty was outside the task scope.
  # Leave it in the worktree for a human instead of sweeping it into the
  # coord commit.
  local leftover
  leftover=$(git status --porcelain --untracked-files=all)
  if [[ -n "$leftover" ]]; then
    coord_commit_log "out-of-scope changes left uncommitted after $COORD_AGENT ran $COORD_TASK_ID"
    coord_commit_status_logged
  fi
}

commit_agent_changes() {
  coord_commit_require_env || return $?

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    coord_commit_log "git commit skipped: not inside a git worktree"
    return 0
  fi

  local after_status
  after_status=$(git status --porcelain --untracked-files=all)
  if [[ -z "$after_status" ]]; then
    return 0
  fi

  local base_status
  base_status=$(cat "$COORD_BASE_GIT_STATUS_FILE")
  if [[ -n "$base_status" ]]; then
    coord_commit_log "git commit skipped: worktree was dirty before $COORD_AGENT ran $COORD_TASK_ID"
    coord_commit_status_logged
    return 1
  fi

  coord_commit_stage_changes || return 1
  if git diff --cached --quiet; then
    coord_commit_warn_leftovers
    return 0
  fi
  if (( COORD_COMMIT_HAS_SCOPE )); then
    git commit --quiet -m "coord: work $COORD_TASK_ID" -- "${COORD_COMMIT_MATCHED_SPECS[@]}" || return 1
  else
    git commit --quiet -m "coord: work $COORD_TASK_ID" || return 1
  fi
  push_current_branch || return 1
  coord_commit_log "git commit pushed for $COORD_TASK_ID"
  coord_commit_warn_leftovers
}

commit_tentative_changes() {
  local rc="${1:?usage: commit_tentative_changes <rc>}"
  coord_commit_require_env || return $?

  if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    return 0
  fi

  local after_status
  after_status=$(git status --porcelain --untracked-files=all)
  if [[ -z "$after_status" ]]; then
    return 0
  fi

  local base_status
  base_status=$(cat "$COORD_BASE_GIT_STATUS_FILE")
  if [[ -n "$base_status" ]]; then
    coord_commit_log "tentative commit skipped: worktree was dirty before $COORD_AGENT ran $COORD_TASK_ID"
    return 1
  fi

  coord_commit_stage_changes || { echo 0; return 1; }
  if git diff --cached --quiet; then
    coord_commit_warn_leftovers
    return 0
  fi

  if (( COORD_COMMIT_HAS_SCOPE )); then
    coord_commit_run_logged git commit --quiet -m "coord: tentative $COORD_TASK_ID (rc=$rc, needs human review)" -- "${COORD_COMMIT_MATCHED_SPECS[@]}" || { echo 0; return 1; }
  else
    coord_commit_run_logged git commit --quiet -m "coord: tentative $COORD_TASK_ID (rc=$rc, needs human review)" || { echo 0; return 1; }
  fi
  push_current_branch || { echo 0; return 1; }
  coord_commit_log "tentative commit pushed for $COORD_TASK_ID"
  coord_commit_warn_leftovers
  echo 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  set -euo pipefail
  commit_agent_changes "$@"
fi
