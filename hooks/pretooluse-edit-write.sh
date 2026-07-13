#!/usr/bin/env bash
# PreToolUse hook for Edit / Write / NotebookEdit: block writes to known
# secret-bearing files and coord worker runtime files. Mirrors the
# pretooluse-bash safety hook for the file-write tools.
#
# Input: JSON on stdin with tool_input.file_path (Edit/Write) or
#        tool_input.notebook_path (NotebookEdit).
# Output: JSON decision to stdout. Exit 0 always.

set -euo pipefail

input=$(cat)
path=$(python3 -c "
import sys, json
try:
    d = json.loads(sys.argv[1])
    ti = d.get('tool_input', {}) or {}
    print(ti.get('file_path') or ti.get('notebook_path') or '')
except Exception:
    pass
" "$input" 2>/dev/null || echo "")

[[ -z "$path" ]] && exit 0

block() {
  # Match the format used by pretooluse-bash.sh so Claude Code surfaces
  # the reason verbatim. python3 handles JSON escaping of $1.
  python3 -c "
import json, sys
print(json.dumps({'decision': 'block', 'reason': sys.argv[1]}))
" "$1"
  exit 0
}

base=$(basename "$path")

# .env files — but allow examples / samples that are typically committed.
case "$base" in
  .env|.env.local|.env.production|.env.prod|.env.staging|.env.dev|.env.development|.env.test)
    block "coord safety hook: refusing to Edit/Write '$base' (path: $path). Suspected secrets file. Ask the user to edit it manually if intentional."
    ;;
esac

# Secret-bearing file names.
case "$base" in
  auth.json|credentials.json|credentials.yml|credentials.yaml|.netrc|.pgpass)
    block "coord safety hook: refusing to Edit/Write '$base' (path: $path). Suspected credentials file."
    ;;
  wallet.dat|wallet.json|keystore.json)
    block "coord safety hook: refusing to Edit/Write '$base' (path: $path). Suspected wallet/keystore."
    ;;
  id_rsa|id_dsa|id_ecdsa|id_ed25519)
    block "coord safety hook: refusing to Edit/Write SSH private key '$base' (path: $path)."
    ;;
esac

# Private key / cert extensions.
if [[ "$base" =~ \.(pem|key|p12|pfx)$ ]]; then
  block "coord safety hook: refusing to Edit/Write '$base' (path: $path). Suspected private key/cert file."
fi

# Sensitive directories anywhere in the path.
case "$path" in
  */.ssh/*|*/.gnupg/*|*/.aws/credentials|*/.aws/credentials.*|*/.codex/auth.json|*/.claude/auth.json)
    block "coord safety hook: refusing to Edit/Write under a sensitive directory (path: $path)."
    ;;
esac

# Coord worker runtime files — owned by the launchd worker, not Claude.
case "$path" in
  */.coord/worker.lock|*/.coord/worker.state|*/.coord/sleep-until|*/.coord/config.env)
    block "coord safety hook: '$path' is owned by the coord launchd worker; editing it from Claude can break the worker. Manual shell edits only."
    ;;
esac

exit 0
