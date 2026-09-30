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
   - For each child, write four files before running `coord new`:
     - `/tmp/coord-split-<parent-id>-<n>-plan.txt` — concrete Plan (lead with prose; use `###` for any sub-heading such as `### Subtraction analysis`, never `## `). Without it `coord new` seeds a placeholder Plan and step 4 `promote` exits 3.
     - `/tmp/coord-split-<parent-id>-<n>-subtasks.txt` — subtask block
     - `/tmp/coord-split-<parent-id>-<n>-acceptance.txt` — acceptance bullets
     - `/tmp/coord-split-<parent-id>-<n>-scope.txt` — scope paths (if needed)
   - Run `coord new` for each child with explicit `--complexity`, `--kind`, `--reasoning_effort`, `--model_claude`, `--model_codex`, optional `--agents`, optional `--assigned`, optional `--roles` for explicit review or an exceptional architect handoff, `--depends_on=<previous-child-ids>` to chain them, and:
     `--set-plan=@/tmp/coord-split-<parent-id>-<n>-plan.txt`
     `--set-subtasks=@/tmp/coord-split-<parent-id>-<n>-subtasks.txt`
     `--acceptance=@/tmp/coord-split-<parent-id>-<n>-acceptance.txt`
     `--scope=@/tmp/coord-split-<parent-id>-<n>-scope.txt` (omit if no scope needed)
   - Capture each new child id from coord's stdout, then set `coord update <child-id> --scope-budget-loc="<band>"` and run the `coord-review` skill on the child before promoting it.
   - If any `coord new` exits non-zero, stop immediately. Do NOT archive the parent; report which child failed and why so the user can fix the inputs and retry.

4. **Promote ALL children to pending, not just the chain head.**
   - Run `coord promote <child-id>` for every child after `coord new`. The worker's `dependency_blockers` check in `cmd_pickup` already enforces ordering by skipping tasks with unmet deps; leaving siblings in `shaping` strands them until someone manually re-runs `/coord-promote`.
   - No coord code (worker.sh, cmd_promote, any launchd job) auto-flips `shaping → pending` when deps clear.

5. **Archive the parent — recipe for `needs-brainstorming` or incomplete-subtasks state.**
   - A plain `--status=done` fails from `shaping`, `pending`, or `needs-brainstorming` (no edge to `done`) and while subtasks are incomplete (they were migrated to children, not finished). Close the parent in one forced call, which also records the child ids:
     `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <parent-id> --status=done --force --add-issues="Split into: <child-id-1>, <child-id-2>, ..."`
   - `--force` is the right authority here because the parent's subtasks are genuinely incomplete (migrated to children). The `Rules` section's general "no `--force`" applies to normal closes; this is the documented `/coord-discard` carve-out. Do not route the parent through `pending` first: that makes it runnable (a live worker can pick it up) and runs the runnable-shape gate.
   - `coord update --status=done` archives the parent in the same call. Closing a never-started `shaping`/`needs-brainstorming` parent skips the model/effort baseline check, so an off-baseline draft still closes.

   `coord new`, `coord update`, and `coord promote` each commit and push their own change. Do not run manual `git add`, `git commit`, or `git push`; if a push failed, `git rev-list --count origin/main..main` shows the unpushed commits.

6. **Report.**
   - `split: <parent-id> -> <child-id-1>, <child-id-2>, ...`
   - For each promoted child: `promoted: <child-id>`
   - Final line: push outcome (any `git push failed` output from `coord`).

## Rules

- Never use `--force` or `--no-verify`, except the step 5 parent-close `--force`.
- Never edit task files directly; always use `coord new` and `coord update`.
- Do not add `roles.architect` when splitting normal work. Use child tasks chained with `depends_on` as the decomposition mechanism; reserve architect roles for explicit in-loop design handoffs.
- Do NOT use the umbrella pattern (parent kept alive as a tracker). The children's `depends_on` chain encodes ordering; an umbrella duplicates state.
- If `coord new` rejects a child for shape warnings, treat it as the user's signal that the child is itself too broad — re-grill that child rather than bypassing the warning.
- Do not stage anything by hand; `coord` commits the parent and child files itself.
