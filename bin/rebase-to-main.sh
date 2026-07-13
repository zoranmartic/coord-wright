#!/usr/bin/env bash
# rebase-to-main.sh — rebase a task worktree branch onto origin/main and force-push
#
# Exit codes:
#   0  success — rebase and push complete; run merge-to-main.sh next
#   1  conflicts — resolve manually, run git rebase --continue, then re-run this script
#   2  preflight failure — wrong state, dirty tree, branch out of sync, etc.
#
# Environment:
#   COORD_TOOLS    override the CoordWright checkout root (default: auto-detected from script location)

set -euo pipefail

COORD_TOOLS="${COORD_TOOLS:-$(cd "$(dirname "$0")/.." && pwd)}"

die()  { printf 'rebase-to-main: %s\n' "$*" >&2; exit 2; }
note() { printf 'rebase-to-main: %s\n' "$*"; }

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

# ── 3. In-progress rebase check ───────────────────────────────────────────────
REBASE_MERGE=$(git -C "$TASK_ROOT" rev-parse --git-path rebase-merge 2>/dev/null || true)
REBASE_APPLY=$(git -C "$TASK_ROOT" rev-parse --git-path rebase-apply 2>/dev/null || true)
if [[ -d "${REBASE_MERGE:-/dev/null/no}" || -d "${REBASE_APPLY:-/dev/null/no}" ]]; then
  git -C "$TASK_ROOT" status --short >&2
  die "rebase already in progress — resolve conflicts, then: git rebase --continue  (or: git rebase --abort)"
fi

# ── 4. Dirty check ────────────────────────────────────────────────────────────
[[ -z "$(git -C "$TASK_ROOT" status --porcelain)" ]] \
  || die "task worktree is dirty; commit or clean it before rebasing"
[[ -z "$(git -C "$MAIN_ROOT" status --porcelain)" ]] \
  || die "main checkout is dirty; commit or clean it before rebasing"

# ── 5. Upstream check ─────────────────────────────────────────────────────────
TASK_UPSTREAM=$(git -C "$TASK_ROOT" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null) \
  || die "task branch has no upstream; push it first (git push -u origin HEAD)"

case "$TASK_UPSTREAM" in
  origin/*) ;;
  *) die "task upstream must be on origin, got: $TASK_UPSTREAM" ;;
esac
TASK_UPSTREAM_BRANCH="${TASK_UPSTREAM#origin/}"

TASK_LOCAL_COMMIT=$(git -C "$TASK_ROOT" rev-parse HEAD)
note "fetching origin..."
git -C "$TASK_ROOT" fetch origin
TASK_UPSTREAM_COMMIT=$(git -C "$TASK_ROOT" rev-parse "$TASK_UPSTREAM")

[[ "$TASK_LOCAL_COMMIT" == "$TASK_UPSTREAM_COMMIT" ]] \
  || die "task branch ($TASK_LOCAL_COMMIT) differs from upstream ($TASK_UPSTREAM_COMMIT); push or reconcile first"

# ── 6. Rebase ─────────────────────────────────────────────────────────────────
OLD_TASK=$(git -C "$TASK_ROOT" rev-parse --short HEAD)
note "rebasing $TASK_BRANCH onto origin/main..."

if ! git -C "$TASK_ROOT" rebase origin/main; then
  printf '\n' >&2
  git -C "$TASK_ROOT" status --short >&2
  printf '\nrebase-to-main: rebase stopped with conflicts.\n' >&2
  printf 'Resolve each conflict, then:\n' >&2
  printf '  git add <resolved-path>\n' >&2
  printf '  git rebase --continue\n' >&2
  printf 'Then re-run this script to verify and push.\n' >&2
  printf 'To abandon: git rebase --abort\n' >&2
  exit 1
fi

# ── 7. Post-rebase checks ─────────────────────────────────────────────────────
git -C "$TASK_ROOT" diff --check origin/main..HEAD \
  || die "whitespace errors in rebased branch; fix and re-run"

# ── 8. Force-push ─────────────────────────────────────────────────────────────
note "pushing $TASK_UPSTREAM_BRANCH with --force-with-lease..."
git -C "$TASK_ROOT" push --force-with-lease origin "HEAD:$TASK_UPSTREAM_BRANCH" \
  || die "force-push failed; check if remote was updated by another push"

NEW_TASK=$(git -C "$TASK_ROOT" rev-parse --short HEAD)
printf 'rebased %s onto origin/main: %s -> %s\nrun /merge-to-main next\n' \
  "$TASK_UPSTREAM" "$OLD_TASK" "$NEW_TASK"
