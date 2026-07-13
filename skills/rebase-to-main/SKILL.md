---
name: rebase-to-main
description: "Rebase a registered coord session worktree branch onto origin/main and push it with --force-with-lease. Use when the user says $rebase-to-main, \"rebase this task branch onto main\", or needs to make a task branch fast-forwardable before $merge-to-main."
---

Rebase the current session worktree branch onto `origin/main` so `/merge-to-main`
can fast-forward afterward. Rewrites task branch history.
Run from the session worktree (not the main checkout).

## Run

```bash
"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/rebase-to-main.sh"
```

## Exit codes

**Exit 0** — rebase and force-push complete. Run `/merge-to-main` next.

**Exit 1** — rebase stopped with conflicts. The script printed the conflicted paths.
Resolve:
1. `git status --short` — see which files conflict.
2. `git diff --cc -- <path>` — inspect conflict hunks.
3. Resolve only when the correct resolution is clear from local context.
   If unclear, stop and ask the user.
4. `git add <resolved-path>` for each resolved file.
5. `git rebase --continue`.
6. Repeat if more conflicts remain.
7. Re-run this skill after a successful continue — it will run `diff --check`
   and force-push.

To abandon a conflicted rebase: `git rebase --abort`, confirm `git status --short`
is clean, then re-run this skill from scratch.

**Exit 2** — preflight failure (dirty tree, no upstream, branch out of sync,
not a registered session worktree). Report the error and stop.

## Source of truth

- `${COORD_TOOLS}/docs/coordination.md`
- `${COORD_TOOLS}/projects.txt`

## Rules

- Only run from a registered session worktree (`<project>-session-*`), never from main.
- Never use plain `--force`; the script uses `--force-with-lease`.
- Do not merge main into the task branch — rebase only.
- Do not delete or rename the task branch.
- If conflicts occur, stop and surface them. Do not guess resolutions.
