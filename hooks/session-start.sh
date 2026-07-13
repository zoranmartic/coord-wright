#!/usr/bin/env bash
# SessionStart hook: probe codex and claude auth/version at session open.
# Prints status; non-zero exit signals auth failure (informational only —
# Claude Code may still proceed, but the error is visible in the session banner).

set -euo pipefail

ok=0

if claude_ver=$(claude --version 2>&1); then
  echo "coord: claude ok — $claude_ver"
else
  echo "coord: claude not found or errored" >&2
  ok=1
fi

if codex_ver=$(codex whoami 2>&1); then
  echo "coord: codex ok — $codex_ver"
else
  echo "coord: codex auth may be stale: $codex_ver" >&2
fi

exit $ok
