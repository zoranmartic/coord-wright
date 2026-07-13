#!/usr/bin/env bash
# audit-hardening.sh — read-only sanity check of the coord/codex/claude
# hardening landed on 2026-05-16. Verifies sandbox configs, FS perms,
# hook installation, per-project .gitignore, and worker.sh integrity.
#
# Usage: bash ~/Projects/coord-wright/bin/audit-hardening.sh
# Exits 0 if all checks pass, 1 if any fail. Safe to wire into launchd.
#
# Read-only — never modifies files, prints, or chmods.

set -uo pipefail

TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
PROJECTS_TXT="$TOOLS/projects.txt"

PASS=0
FAIL=0

ok()   { printf "  %-55s OK\n"   "$1"; PASS=$((PASS+1)); }
fail() { printf "  %-55s FAIL  (%s)\n" "$1" "$2"; FAIL=$((FAIL+1)); }
skip() { printf "  %-55s SKIP  (%s)\n" "$1" "$2"; }

section() { printf "\n=== %s ===\n" "$1"; }

# ---------------------------------------------------------------------------
section "Codex hardening"

CODEX_CONFIG="$HOME/.codex/config.toml"
if [[ -f "$CODEX_CONFIG" ]]; then
  # Both danger-full-access and workspace-write are acceptable here. The
  # 2026-05-17 experiment showed workspace-write breaks real workflows
  # (manual /coord-promote can't write .git or push), so the practical
  # default is danger-full-access. The real defenses are chmod 400 on
  # ~/.codex/auth.json + .env files plus the Claude PreToolUse hooks.
  mode=$(grep -E '^sandbox_mode' "$CODEX_CONFIG" | head -1)
  case "$mode" in
    *danger-full-access*)     ok "config.toml sandbox_mode = danger-full-access" ;;
    *workspace-write*)        ok "config.toml sandbox_mode = workspace-write (note: breaks git ops in manual codex)" ;;
    *read-only*)              ok "config.toml sandbox_mode = read-only (more strict)" ;;
    *)                        fail "config.toml sandbox_mode" "unrecognized: $mode" ;;
  esac
else
  fail "~/.codex/config.toml" "missing"
fi

AUTH="$HOME/.codex/auth.json"
if [[ -f "$AUTH" ]]; then
  m=$(stat -f %Sp "$AUTH")
  case "$m" in
    -r--------)               ok "~/.codex/auth.json mode = 400 (read-only)" ;;
    -rw-------)               ok "~/.codex/auth.json mode = 600 (acceptable)" ;;
    *)                        fail "~/.codex/auth.json mode" "$m (too permissive)" ;;
  esac
else
  fail "~/.codex/auth.json" "missing"
fi

# ---------------------------------------------------------------------------
section "Worker.sh integrity (anti-mid-edit re-exec + mktemp fix)"

WORKER="$TOOLS/worker/worker.sh"
if [[ -f "$WORKER" ]]; then
  if grep -q "COORD_WORKER_REEXEC" "$WORKER"; then
    ok "worker.sh has self-copy re-exec preamble"
  else
    fail "worker.sh self-copy" "missing COORD_WORKER_REEXEC guard"
  fi

  helper_count=$(grep -c '^mktemp_suffix()' "$WORKER" || true)
  call_count=$(grep -c 'mktemp_suffix coord-worker' "$WORKER" || true)
  if [[ "$helper_count" == "1" && "$call_count" == "3" ]]; then
    ok "worker.sh mktemp_suffix helper + call sites"
  elif grep -q 'mktemp -t coord-worker' "$WORKER"; then
    fail "worker.sh mktemp" "old inline mktemp pattern still present; expected mktemp_suffix helper"
  else
    fail "worker.sh mktemp" "missing mktemp_suffix helper or expected call sites"
  fi

  # Workspace-write was tried (2026-05-17) and rolled back — codex's
  # internal command-policy under workspace-write rejects rm-rf even with
  # prefix_rule entries (rules use full-argv match, not per-element prefix,
  # so every command variant needs its own rule), AND macOS launchd-spawn
  # codex cannot bind TCP ports or launch Chromium regardless of sandbox
  # mode (listen EPERM, MachPort denied) which breaks a project's Playwright
  # workflow. Defense-in-depth: chmod 400 on auth.json + .env, Claude
  # PreToolUse Edit/Write hook, and separate user-level Codex config auditing.
  if grep -Eq -- '(^|[[:space:]])(--sandbox|-s)[[:space:]]+danger-full-access' "$WORKER"; then
    ok "worker.sh Codex sandbox = danger-full-access (workspace-write incompatible with Playwright)"
  elif grep -Eq -- '(^|[[:space:]])(--sandbox|-s)[[:space:]]+workspace-write' "$WORKER"; then
    fail "worker.sh Codex sandbox" "workspace-write blocks Playwright; revert to danger-full-access"
  else
    fail "worker.sh Codex sandbox" "danger-full-access flag not found"
  fi
else
  fail "worker.sh" "missing at $WORKER"
fi

# ---------------------------------------------------------------------------
section "Codex execpolicy allow-list"

CODEX_RULES="$HOME/.codex/rules/default.rules"

check_codex_prefix_rule() {
  local label="$1"
  local rule="$2"

  if [[ -f "$CODEX_RULES" ]]; then
    if grep -Fq -- "$rule" "$CODEX_RULES"; then
      ok "$label"
    else
      fail "$label" "missing: $rule"
    fi
  else
    fail "$label" "rules file missing at $CODEX_RULES; expected: $rule"
  fi
}

check_codex_prefix_rule \
  "execpolicy allows /bin/zsh rm -rf prefix" \
  'prefix_rule(pattern=["/bin/zsh", "-lc", "rm -rf "], decision="allow")'
check_codex_prefix_rule \
  "execpolicy allows bash rm -rf prefix" \
  'prefix_rule(pattern=["bash", "-lc", "rm -rf "], decision="allow")'

# ---------------------------------------------------------------------------
section "Claude Code hooks"

CLAUDE_SETTINGS="$HOME/.claude/settings.json"
HOOKS_DIR="$TOOLS/hooks"

if [[ -f "$CLAUDE_SETTINGS" ]]; then
  ok "~/.claude/settings.json exists"
else
  fail "~/.claude/settings.json" "missing — hooks not active"
fi

for h in pretooluse-bash.sh pretooluse-edit-write.sh posttooluse-py-typecheck.sh session-start.sh; do
  f="$HOOKS_DIR/$h"
  if [[ -x "$f" ]]; then
    ok "hook installed + executable: $h"
  elif [[ -f "$f" ]]; then
    fail "hook $h" "exists but not executable"
  else
    fail "hook $h" "missing at $f"
  fi
done

# Verify settings.json actually references the hooks (not just files present)
if [[ -f "$CLAUDE_SETTINGS" ]] && command -v python3 >/dev/null; then
  for event in PreToolUse PostToolUse SessionStart; do
    if python3 -c "
import json, sys
d = json.load(open('$CLAUDE_SETTINGS'))
entries = d.get('hooks', {}).get('$event', [])
print(len(entries) > 0)
" | grep -q True; then
      ok "settings.json has $event hooks wired"
    else
      fail "settings.json $event" "no entries wired"
    fi
  done
fi

# Keychain entry for Claude
if security find-generic-password -s "Claude Code-credentials" -a "$USER" >/dev/null 2>&1; then
  ok "Claude keychain entry exists"
else
  fail "Claude keychain entry" "not found — run claude login"
fi

# ---------------------------------------------------------------------------
section "Per-project: .gitignore + .env perms"

if [[ ! -f "$PROJECTS_TXT" ]]; then
  # A fresh install legitimately has no projects.txt yet (install.sh skips
  # launchd setup in that state), so its absence is not a hardening failure.
  skip "projects.txt" "no registered projects"
else
  while IFS= read -r proj; do
    [[ -z "$proj" || "$proj" =~ ^# ]] && continue
    name=$(basename "$proj")

    if [[ ! -d "$proj/.git" ]] && ! git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
      skip "$name" "not a git repo"
      continue
    fi

    # Coord runtime files in .coord/ must be ignored so worker.lock/state/logs
    # do not make the checkout dirty before pickup. Accept any equivalent
    # .gitignore pattern, including projects that keep .coord/config.env tracked.
    if git -C "$proj" check-ignore -q .coord/worker.state 2>/dev/null; then
      ok "$name: .coord runtime ignored"
    else
      fail "$name: .coord runtime ignored" "missing in .gitignore"
    fi

    # .env perms (if any .env files exist)
    env_files=$(find "$proj" -maxdepth 5 -name '.env' \
      ! -path '*/node_modules/*' ! -path '*/.venv/*' ! -path '*/venv/*' 2>/dev/null)
    if [[ -z "$env_files" ]]; then
      skip "$name: .env perms" "no .env files"
    else
      while IFS= read -r ef; do
        [[ -z "$ef" ]] && continue
        m=$(stat -f %Sp "$ef")
        rel=${ef#$proj/}
        case "$m" in
          -r--------|-rw-------)  ok "$name/$rel mode = ${m: -9}" ;;
          *)                      fail "$name/$rel mode" "$m (world/group readable)" ;;
        esac
      done <<< "$env_files"
    fi
  done < "$PROJECTS_TXT"
fi

# ---------------------------------------------------------------------------
section "Summary"
printf "  %d passed, %d failed\n" "$PASS" "$FAIL"

if (( FAIL > 0 )); then
  exit 1
fi
exit 0
