---
name: coord-promote
description: Promote one or more shaped coord tasks to pending, then commit and push. Zero args promotes every task in status:shaping. Use when the user says "/coord-promote", "promote <id>", or "promote all shaping tasks".
---

Flip shaped tasks to `pending` and publish atomically. The launchd coord loop reads local files, so promote → commit → push must run as a tight sequence with no pauses.

Project-root preflight:

- Resolve the canonical project checkout before listing tasks, promoting, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; promotion must update the main queue that the launchd worker reads.

## Workflow

1. **Resolve target ids.**
   - If `$ARGUMENTS` is non-empty: split on whitespace/commas to get the id list.
   - If `$ARGUMENTS` is empty: run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list --status=shaping --format=ids` and use the output as the list. If output is empty, report "no shaping tasks found" and stop — do not commit.

2. **Pre-check for unrelated dirty coord files.**
   - Run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" paths --json` to get `tasks_dir`, then `git status --porcelain "$tasks_dir"` and collect any modified coord task files whose base name (without `.md`) is NOT in the promote set.
   - If any exist, print a warning listing each filename, then continue — do not abort.

3. **Promote each id.**
   - For each id in the list, run:
     `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" promote <id>`
   - `coord promote` auto-commits-and-pushes each task individually. Do not run manual `git add`, `git commit`, or `git push`.
   - If any invocation exits non-zero: print the failing id and its stderr, then **stop immediately**. Do not retry. Do not use `--shape-override` or any bypass.

4. **Report.**
   - One line per promoted id: `promoted: <id>`.
   - Note: each promotion is its own commit; multi-id batching into a single commit requires a CLI-level change that does not yet exist.

## Rules

- Never use `--no-verify`, `--force`, or `--shape-override`.
- Stage only the exact files for the promoted ids.
- If `coord promote` rejects an id (shaping warning, missing plan, etc.), surface the error as-is — the task is not ready.
- Keep output terse; no extra commentary beyond the per-id lines and the commit/push result.
