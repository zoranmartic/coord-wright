---
name: coord-split
description: Decompose an oversized or badly-shaped coord task into N dependent children. Interviews the user via grill-me to find the natural fault lines, creates child tasks chained with depends_on, then archives the parent. Use when the user says "/coord-split", "this task is too big", or "split <id>".
---

Break a too-broad coord task into properly-shaped children. Companion to `/coord-shape` (which shapes one task) — `/coord-split` is for when shaping reveals the task should have been multiple tasks.

Project-root preflight:

- Resolve the canonical project checkout before reading, creating, updating, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; split child tasks and parent updates belong to the main queue that the launchd worker reads.

## Syntax

`/coord-split <task-id>`

## Workflow

1. **Load the parent.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` → capture task body, current subtasks, scope, acceptance, depends_on, kind, complexity.
   - Refuse if status is `done`, `archived`, or already `needs-brainstorming` — those don't need splitting.

2. **Interview the user via grill-me.**
   - Invoke the `grill-me` skill with the parent's title, current scope, and current subtasks as context.
   - The interview must surface:
     - **Fault lines:** where does the task naturally divide? Each child should have one main outcome and one final verification path.
     - **Order and dependencies:** which child must finish before the next?
     - **Per-child agent and model:** default to Codex unless the user says otherwise.
     - **Per-child complexity, kind, reasoning_effort:** inherit from parent or downgrade if the child is genuinely smaller.
   - Stop the interview when the children are crisply defined (typically 2–5 children).

3. **Create each child task.**
   - For each child, write three files before running `coord new`:
     - `/tmp/coord-split-<parent-id>-<n>-subtasks.txt` — subtask block
     - `/tmp/coord-split-<parent-id>-<n>-acceptance.txt` — acceptance bullets
     - `/tmp/coord-split-<parent-id>-<n>-scope.txt` — scope paths (if needed)
   - Run `coord new` for each child with explicit `--complexity`, `--kind`, `--reasoning_effort`, `--model_claude`, `--model_codex`, optional `--agents`, optional `--assigned`, optional `--roles` for explicit review or an exceptional architect handoff, `--depends_on=<previous-child-ids>` to chain them, and:
     `--set-subtasks=@/tmp/coord-split-<parent-id>-<n>-subtasks.txt`
     `--acceptance=@/tmp/coord-split-<parent-id>-<n>-acceptance.txt`
     `--scope=@/tmp/coord-split-<parent-id>-<n>-scope.txt` (omit if no scope needed)
   - Capture each new child id from coord's stdout.
   - If any `coord new` exits non-zero, stop immediately. Do NOT archive the parent; report which child failed and why so the user can fix the inputs and retry.

4. **Promote ALL children to pending, not just the chain head.**
   - Run `coord promote <child-id>` for every child after `coord new`. The worker's `dependency_blockers` check in `cmd_pickup` already enforces ordering by skipping tasks with unmet deps; leaving siblings in `shaping` strands them until someone manually re-runs `/coord-promote`.
   - No coord code (worker.sh, cmd_promote, any launchd job) auto-flips `shaping → pending` when deps clear. The previous "children that depend on later siblings stay in shaping" pattern was misleading.

5. **Archive the parent — recipe for `needs-brainstorming` or incomplete-subtasks state.**
   - `coord update <parent-id> --status=done` will fail if the parent is in `needs-brainstorming` (no `needs-brainstorming → done` edge) or still has incomplete subtasks (subtasks were migrated to children, not finished). Use this 3-step recipe:
     1. `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <parent-id> --status=pending`
     2. `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <parent-id> --status=claude-working` (or `codex-working`)
     3. `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <parent-id> --status=done --force` — `--force` is the right authority here because the parent's subtasks are genuinely incomplete (migrated to children). The `Rules` section's general "no `--force`" applies to normal closes; this is the documented `/coord-discard` carve-out.
   - Append a discard note listing the child ids:
     `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <parent-id> --add-issues="Split into: <child-id-1>, <child-id-2>, ..."`
   - The launchd auto-archiver moves the parent on its next cycle.

   Bonus: every `coord update` and `coord new` auto-commits; the launchd worker auto-pushes. The explicit "stage + commit + push" steps below are usually no-ops by the time you reach them. Verify with `git rev-list --count main..origin/main` rather than running a manual `git push`.

6. **Stage and commit.**
   - Stage the parent and child paths returned by `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --path`.
   - Commit subject: `coord: split <parent-id> into <N> tasks`
   - Body lists each child id on its own line.
   - Append trailer: `Co-Authored-By: coord-bot <noreply@coord.local>`
   - Pass via heredoc.

7. **Push.**
   - `git push` (synchronous). Stop on non-zero.

8. **Report.**
   - `split: <parent-id> -> <child-id-1>, <child-id-2>, ...`
   - For each promoted child: `promoted: <child-id>`
   - For each child still in shaping (dependency-blocked): `shaping (waiting on <dep>): <child-id>`
   - Final line: commit sha (short) and push outcome.

## Rules

- Never use `--force`, `--no-verify`, or `--shape-override`.
- Never edit task files directly; always use `coord new` and `coord update`.
- Do not add `roles.architect` when splitting normal work. Use child tasks chained with `depends_on` as the decomposition mechanism; reserve architect roles for explicit in-loop design handoffs.
- Do NOT use the umbrella pattern (parent kept alive as a tracker). The children's `depends_on` chain encodes ordering; an umbrella duplicates state.
- If `coord new` rejects a child for shape warnings, treat it as the user's signal that the child is itself too broad — re-grill that child rather than bypassing the warning.
- Stage only the parent file and the new child files.
