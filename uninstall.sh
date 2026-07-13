#!/usr/bin/env bash
# Unload launchd workers and remove symlinks pointing into this repo.
# Files in this repo are untouched. ~/.claude/settings.json is left as-is
# (it was merged, not symlinked) — review by hand if you want to revert.

set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

if [[ -f "$TOOLS/projects.txt" ]]; then
  while IFS= read -r PROJ || [[ -n "$PROJ" ]]; do
    [[ -z "$PROJ" || "$PROJ" =~ ^[[:space:]]*# ]] && continue
    PROJ="${PROJ%/}"
    NAME=$(basename "$PROJ")
    SAFE_NAME=$(printf '%s' "$NAME" | LC_ALL=C tr -c '[:alnum:]._-' '_')
    PLIST="$LAUNCHD_DIR/com.coord.worker.${SAFE_NAME}.plist"
    if [[ -f "$PLIST" ]]; then
      launchctl unload "$PLIST" 2>/dev/null || true
      rm -f "$PLIST"
      echo "removed $PLIST"
    fi
  done < "$TOOLS/projects.txt"
fi

for d in "$CLAUDE_DIR/agents" "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills" "$HOME/.agents/skills"; do
  [[ -d "$d" ]] || continue
  for f in "$d"/*; do
    [[ -L "$f" ]] || continue
    target=$(readlink "$f")
    case "$target" in
      "$TOOLS"/*) rm "$f"; echo "removed symlink $f" ;;
    esac
  done
done

echo "uninstall done. settings.json untouched; review manually."
