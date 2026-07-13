---
name: coord-discard
description: Abandon a coord task you no longer want. Marks it `done` with a discard note; the launchd auto-archiver moves it to the configured archive directory on its next cycle. Use when the user says "/coord-discard", "drop <id>", "kill <id>", or "abandon <id>".
---

Cancel an in-flight coord task without finishing it. The launchd `archive-done` step picks it up automatically on the next loop cycle.

Project-root preflight:

- Resolve the canonical project checkout before reading, updating, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; discard must update the main queue that the launchd worker reads.

## Syntax

`/coord-discard <task-id> [--reason="..."]`

## Workflow

1. **Read current state.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` → confirm task exists and is not already `done`.
   - If already `done`: report and stop. The auto-archiver will handle it; nothing to do.

2. **Compose the discard note.**
   - Reason: from `--reason="..."` if supplied, else `discarded by user`.
   - Note text: `Discarded <ISO-timestamp>: <reason>` (use `date -u +%Y-%m-%dT%H:%M:%SZ`).

3. **Append the note.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --add-issues=<note>`
   - Use the `--add-issues` flag so the discard note lands under `## Open issues` and is preserved in the archive.

4. **Mark done.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=done`
   - If coord refuses due to incomplete subtasks, stop and report — do not use `--force`. Subtasks represent real unfinished work; either complete them or ask the user to confirm a forced close explicitly before using `--force`.
   - Both `coord update` calls in steps 3 and 4 auto-commit-and-push via the CLI. Do not run any manual `git add`, `git commit`, or `git push` after this step.

5. **Report.**
   - `discarded: <id>` — the auto-archiver will move it to the configured archive directory on the next cycle.
   - Confirm with `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` that `status: done` is written.

## Rules

- Never edit task files directly; always go through `coord update`.
- Never run manual `git add`, `git commit`, or `git push` — `coord update` auto-commits-and-pushes each mutation.
- `--force` only with explicit user confirmation that incomplete subtasks are intentionally abandoned.
- Never use `--no-verify` or `--shape-override`.
- Mechanical archiving: `done` tasks are moved to the configured archive directory by the launchd worker on its next cycle.
