#!/bin/sh
set -eu

if [ "$#" -lt 1 ]; then
  echo "Usage: $(basename "$0") <claude|codex> [args...]" >&2
  exit 64
fi

is_claude_management_command() {
  case "${1:-}" in
    config|mcp|plugin|plugins|update|doctor|help|-h|--help|version|--version)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

has_claude_permission_flag() {
  for arg do
    case "$arg" in
      --dangerously-skip-permissions|--permission-mode|--permission-mode=*)
        return 0
        ;;
    esac
  done
  return 1
}

# Headless coord callers (worker.sh, watchdog.sh) run claude with -p/--print;
# the VS Code task buttons launch a bare interactive `claude`. This is the
# signal used to apply the interactive effort default below.
has_claude_print_flag() {
  for arg do
    case "$arg" in
      -p|--print)
        return 0
        ;;
    esac
  done
  return 1
}

has_claude_effort_flag() {
  for arg do
    case "$arg" in
      --effort|--effort=*)
        return 0
        ;;
    esac
  done
  return 1
}

agent_name=$1
shift

case "$agent_name" in
  claude)
    agent_bin=${CLAUDE_BIN:-}
    candidates="
/opt/homebrew/bin/claude
/usr/local/bin/claude
$HOME/.npm-global/bin/claude
$HOME/.local/bin/claude
"
    ;;
  codex)
    agent_bin=${CODEX_BIN:-}
    candidates="
/opt/homebrew/bin/codex
/usr/local/bin/codex
$HOME/.npm-global/bin/codex
$HOME/.local/bin/codex
"
    ;;
  *)
    echo "Unknown agent: $agent_name" >&2
    exit 64
    ;;
esac

# Interactive Claude launches (the VS Code task buttons run `agent-launch.sh
# claude` with no -p/--print) default to the highest reasoning effort. Headless
# coord callers — worker.sh and watchdog.sh — pass -p and are deliberately left
# alone so each task honours its own reasoning_effort and stays token-frugal.
# Override per launch with an explicit --effort flag or CLAUDE_LAUNCH_EFFORT=<level>;
# set CLAUDE_LAUNCH_EFFORT= to disable. An unrecognised value is ignored (with a
# warning) rather than failing the launch.
claude_effort=${CLAUDE_LAUNCH_EFFORT-max}
case "$claude_effort" in
  low|medium|high|xhigh|max|"")
    ;;
  *)
    echo "agent-launch: ignoring invalid CLAUDE_LAUNCH_EFFORT='$claude_effort' (use low|medium|high|xhigh|max)" >&2
    claude_effort=
    ;;
esac
if [ "$agent_name" = "claude" ] && \
   [ -n "$claude_effort" ] && \
   ! is_claude_management_command "${1:-}" && \
   ! has_claude_print_flag "$@" && \
   ! has_claude_effort_flag "$@"; then
  set -- --effort "$claude_effort" "$@"
fi

# Non-management Claude launches default to acceptEdits unless the operator
# has explicitly opted into unsafe autonomous execution. COORD_UNSAFE_AUTONOMOUS=1
# is the documented global acknowledgement (README "Blast radius");
# CLAUDE_LAUNCH_BYPASS_PERMISSIONS=1 remains a Claude-specific escape hatch for
# this fallback only and does not satisfy the worker/watchdog entry gates.
if [ "$agent_name" = "claude" ] && \
   ! is_claude_management_command "${1:-}" && \
   ! has_claude_permission_flag "$@"; then
  if [ "${COORD_UNSAFE_AUTONOMOUS:-0}" = "1" ] || \
     [ "${CLAUDE_LAUNCH_BYPASS_PERMISSIONS:-0}" = "1" ]; then
    set -- --dangerously-skip-permissions "$@"
  else
    set -- --permission-mode acceptEdits "$@"
  fi
fi

if [ -n "$agent_bin" ] && [ -x "$agent_bin" ]; then
  exec "$agent_bin" "$@"
fi

resolved_bin=$(command -v "$agent_name" 2>/dev/null || true)
if [ -n "$resolved_bin" ] && [ -x "$resolved_bin" ]; then
  exec "$resolved_bin" "$@"
fi

for candidate in $candidates; do
  if [ -x "$candidate" ]; then
    exec "$candidate" "$@"
  fi
done

echo "$agent_name not found on PATH or standard install dirs" >&2
exit 127
