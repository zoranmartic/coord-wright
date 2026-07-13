#!/usr/bin/env bash
# PostToolUse hook for Edit / Write: when Claude touches a Python file,
# run mypy on just that file using the project's own venv-installed mypy.
# Errors are printed to stdout (Claude reads them as hook output) so the
# model can fix them in the next turn instead of waiting for the reviewer
# round to bounce. Silent on success or when mypy is unavailable.
#
# Input: JSON on stdin with tool_input.file_path.
# Output: mypy error lines on stdout when present; exit 0 always.
#
# Performance: per-file mypy is usually 2-5s. When timeout/gtimeout is
# available, a 15s timeout caps the worst case so the hook never wedges a
# Claude session.

set -euo pipefail

input=$(cat)
path=$(python3 -c "
import sys, json
try:
    d = json.loads(sys.argv[1])
    print((d.get('tool_input', {}) or {}).get('file_path', ''))
except Exception:
    pass
" "$input" 2>/dev/null || echo "")

# Bail fast on non-Python files.
[[ "$path" == *.py ]] || exit 0
[[ -f "$path" ]] || exit 0

# Need a git repo to locate the project venv.
repo_root=$(git -C "$(dirname "$path")" rev-parse --show-toplevel 2>/dev/null || true)
[[ -z "$repo_root" ]] && exit 0

# Find a venv-installed mypy. Stop at the first hit.
mypy_bin=""
for cand in \
  "$repo_root/.venv/bin/mypy" \
  "$repo_root/backend/.venv/bin/mypy" \
  "$repo_root/venv/bin/mypy" \
  "$repo_root/backend/venv/bin/mypy"; do
  if [[ -x "$cand" ]]; then
    mypy_bin="$cand"
    break
  fi
done
[[ -z "$mypy_bin" ]] && exit 0

# Run mypy from the directory that holds [tool.mypy] so config is picked up.
config_root="$repo_root"
for cand in "$repo_root/backend" "$repo_root"; do
  if [[ -f "$cand/pyproject.toml" ]] && grep -q '^\[tool\.mypy\]' "$cand/pyproject.toml" 2>/dev/null; then
    config_root="$cand"
    break
  fi
  if [[ -f "$cand/mypy.ini" ]] || [[ -f "$cand/setup.cfg" ]]; then
    config_root="$cand"
    break
  fi
done

rel_path=$(python3 -c "import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))" "$path" "$config_root")

rc=0
timeout_bin=$(command -v timeout 2>/dev/null || command -v gtimeout 2>/dev/null || true)
if [[ -n "$timeout_bin" ]]; then
  output=$(cd "$config_root" && "$timeout_bin" 15 "$mypy_bin" --no-error-summary --no-pretty --no-color-output "$rel_path" 2>&1) || rc=$?
else
  printf 'posttooluse-py-typecheck: timeout/gtimeout unavailable; running mypy without watchdog\n' >&2
  output=$(cd "$config_root" && "$mypy_bin" --no-error-summary --no-pretty --no-color-output "$rel_path" 2>&1) || rc=$?
fi

# Timeout (124) or no config (1 with no findings) — stay silent.
if [[ $rc -eq 124 ]]; then
  exit 0
fi

if [[ $rc -ne 0 ]]; then
  errors=$(printf '%s\n' "$output" | grep -E ':[0-9]+: (error|note):' | head -20 || true)
  if [[ -n "$errors" ]]; then
    echo "mypy ($rel_path):"
    printf '%s\n' "$errors"
  fi
fi

exit 0
