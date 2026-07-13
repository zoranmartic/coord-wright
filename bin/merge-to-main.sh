#!/usr/bin/env bash
# merge-to-main.sh — fast-forward a task worktree branch into canonical main
#
# Exit codes:
#   0  success — merge and push complete
#   1  security finding — review the printed matches, then re-run with SKIP_SECURITY=1
#   2  preflight failure — wrong state, dirty tree, branch out of sync, etc.
#
# Environment:
#   COORD_TOOLS        override the CoordWright checkout root (default: auto-detected from script location)
#   SKIP_SECURITY=1    skip the secret-scan gate after manual review

set -euo pipefail

COORD_TOOLS="${COORD_TOOLS:-$(cd "$(dirname "$0")/.." && pwd)}"

die()  { printf 'merge-to-main: %s\n' "$*" >&2; exit 2; }
note() { printf 'merge-to-main: %s\n' "$*"; }

# ── 1. Resolve paths ──────────────────────────────────────────────────────────
TASK_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) \
  || die "not inside a Git worktree"
TASK_ROOT=$(cd "$TASK_ROOT" && pwd -P)

MAIN_ROOT=$("$COORD_TOOLS/bin/coord-project-root" 2>/dev/null) \
  || die "coord-project-root failed — is this project registered?"
MAIN_ROOT=$(cd "$MAIN_ROOT" && pwd -P)

TASK_BRANCH=$(git -C "$TASK_ROOT" symbolic-ref --quiet --short HEAD 2>/dev/null) \
  || die "current worktree is detached; run this from a task branch"

# ── 2. Guard: registered task worktree, not main ─────────────────────────────
[[ "$TASK_ROOT" != "$MAIN_ROOT" && "$TASK_BRANCH" != "main" ]] \
  || die "run this from a task worktree, not the main checkout"

grep -qFx -- "$MAIN_ROOT" "$COORD_TOOLS/projects.txt" 2>/dev/null \
  || die "main checkout is not registered in $COORD_TOOLS/projects.txt: $MAIN_ROOT"

case "$TASK_ROOT" in
  "$MAIN_ROOT"-session-*) ;;
  *) die "current path ($TASK_ROOT) is not a registered session worktree for $MAIN_ROOT" ;;
esac

# ── 3. Dirty check ────────────────────────────────────────────────────────────
[[ -z "$(git -C "$TASK_ROOT" status --porcelain)" ]] \
  || die "task worktree is dirty; commit or clean it before merging"
[[ -z "$(git -C "$MAIN_ROOT" status --porcelain)" ]] \
  || die "main checkout is dirty; commit or clean it before merging"

# ── 4. Upstream sync ──────────────────────────────────────────────────────────
TASK_UPSTREAM=$(git -C "$TASK_ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) \
  || die "task branch has no upstream; push it first (git push -u origin HEAD)"

TASK_LOCAL_COMMIT=$(git -C "$TASK_ROOT" rev-parse HEAD)
note "fetching origin..."
git -C "$TASK_ROOT" fetch origin
TASK_UPSTREAM_COMMIT=$(git -C "$TASK_ROOT" rev-parse "$TASK_UPSTREAM")

[[ "$TASK_LOCAL_COMMIT" == "$TASK_UPSTREAM_COMMIT" ]] \
  || die "task branch ($TASK_LOCAL_COMMIT) differs from upstream ($TASK_UPSTREAM_COMMIT); push or reconcile first"

# ── 5. Update main ────────────────────────────────────────────────────────────
note "updating main checkout..."
git -C "$MAIN_ROOT" fetch origin
git -C "$MAIN_ROOT" pull --ff-only origin main \
  || die "main could not fast-forward from origin/main; investigate before merging"
OLD_MAIN=$(git -C "$MAIN_ROOT" rev-parse HEAD)

# ── 6. Security gate ─────────────────────────────────────────────────────────
if [[ "${SKIP_SECURITY:-0}" != "1" ]]; then
  SECURITY_FINDINGS=0

  # 6a. Sensitive file paths in candidate range
  SENSITIVE_PATHS=$(
    git -C "$MAIN_ROOT" diff --name-only "$OLD_MAIN..$TASK_UPSTREAM" \
      | grep -Ei \
          '(^|/)(\.env($|[._-].*)|[^/]*(credential|wallet|dsn|secret|private[_ -]?key|api[_-]?key)[^/]*|cwallet\.sso|ewallet\.p12|tnsnames\.ora|sqlnet\.ora|[^/]*\.(pem|key|p12|pfx|jks|keystore))$' \
      || true
  )
  if [[ -n "$SENSITIVE_PATHS" ]]; then
    printf '\n=== SECURITY: sensitive file paths in candidate range ===\n' >&2
    printf '%s\n' "$SENSITIVE_PATHS" >&2
    SECURITY_FINDINGS=1
  fi

  # 6b. Secret-like assignments in diff
  SECRET_LINES=$(
    git -C "$MAIN_ROOT" diff --unified=0 --no-ext-diff "$OLD_MAIN..$TASK_UPSTREAM" \
      | grep -E '^\+[^+]' \
      | grep -Ei \
          '(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|dsn|connection[_-]?string|conn[_-]?string|credential)' \
      || true
  )
  if [[ -n "$SECRET_LINES" ]]; then
    printf '\n=== SECURITY: secret-like assignments in diff ===\n' >&2
    printf '%s\n' "$SECRET_LINES" >&2
    SECURITY_FINDINGS=1
  fi

  # 6c. gitleaks (if configured)
  if [[ -f "$MAIN_ROOT/.gitleaks.toml" ]]; then
    if command -v gitleaks >/dev/null 2>&1; then
      if ! gitleaks git \
            --log-opts="$OLD_MAIN..$TASK_UPSTREAM" \
            --config "$MAIN_ROOT/.gitleaks.toml" \
            --no-banner --no-color 2>&1; then
        printf '\n=== SECURITY: gitleaks reported findings ===\n' >&2
        SECURITY_FINDINGS=1
      fi
    else
      printf 'merge-to-main: gitleaks not found; skipping scan\n' >&2
    fi
  fi

  if [[ "$SECURITY_FINDINGS" -eq 1 ]]; then
    printf '\nReview the findings above. If all are placeholders or false positives,\n' >&2
    printf 're-run with: SKIP_SECURITY=1 %s\n' "$0" >&2
    exit 1
  fi
fi

# ── 7. Fast-forward merge ─────────────────────────────────────────────────────
note "merging $TASK_UPSTREAM into main..."
git -C "$MAIN_ROOT" merge --ff-only "$TASK_UPSTREAM" \
  || die "main cannot fast-forward to $TASK_UPSTREAM; run rebase-to-main first"

git -C "$MAIN_ROOT" diff --check "$OLD_MAIN"..HEAD \
  || die "whitespace errors detected; fix on task branch and re-run"

# ── 8. Push ───────────────────────────────────────────────────────────────────
git -C "$MAIN_ROOT" push origin main \
  || die "push failed; investigate and push manually from $MAIN_ROOT"

MAIN_COMMIT=$(git -C "$MAIN_ROOT" rev-parse --short HEAD)
printf 'merged %s into main at %s; task worktree remains on %s\n' \
  "$TASK_UPSTREAM" "$MAIN_COMMIT" "$TASK_BRANCH"
