---
name: coord-loop-doctor
description: Diagnose stuck, quiet, token-heavy, or repeatedly requeued coord loops. Use when coord-loop seems unreliable, tasks sit in needs-brainstorming or *-working too long, wrapper state looks stale, or the user asks why coord is not moving.
---

# Coord Loop Doctor

Use this skill before starting another expensive loop. The goal is one diagnosis and the smallest safe recovery action.

## Required Reading

When diagnosing coord behavior, read these first:

1. `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/coordination.md`
2. `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/codex-coordination.md` or `claude-coordination.md`, depending on the stuck agent
3. `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md`

Read `task-files-reference.md` only when authoring or transitioning tasks.

## Workflow

1. Resolve the canonical project root. Do not mutate queue state from sibling task worktrees.
2. Inspect the handoff or task with the smallest useful coord view: `show --handoff`, then `show --compact`, then scoped files only if needed.
3. Check wrapper state files such as `/tmp/codex-coord-check-<label>.state`.
4. Check launchd service state, recent logs, and provider retry markers.
5. Check whether the task is genuinely runnable or blocked by `depends_on`.
6. Check whether main checkout dirt or fast-forward failure prevented pickup.
7. Use `coord-status`, `coord-requeue`, `coord-unblocker`, and `coord-tokens` only when they match the diagnosis.

## Classification

Return exactly one primary classification:

- `healthy`
- `queue-starved`
- `dependency-blocked`
- `provider-limited`
- `stale-wrapper`
- `stuck-task`
- `dirty-main`
- `needs-human`

## Use Grill-Me

Invoke `grill-me` when recovery would mutate task state, when multiple worktrees could own recovery, or when the fix is a wrapper change rather than a one-task requeue.

## Output

Report classification, evidence, smallest recovery action, and whether a follow-up task should be shaped.
