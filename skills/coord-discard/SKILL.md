---
name: coord-discard
description: Abandon a coord task you no longer want. Marks it `done` with a discard note; `coord update` archives it in the same call. Use when the user says "/coord-discard", "drop <id>", "kill <id>", or "abandon <id>".
---

Cancel a coord task without finishing it. `coord update --status=done` moves the file to the configured archive directory in the same call.

Project-root preflight:

- Resolve the canonical project checkout before reading, updating, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; discard must update the main queue that the launchd worker reads.

## Syntax

`/coord-discard <task-id> [--reason="..."]`

## Workflow

1. **Read current state.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` → confirm task exists and is not already `done`.
   - If already `done`: report and stop; it is already archived.

2. **Compose the discard note.**
   - Reason: from `--reason="..."` if supplied, else `discarded by user`.
   - Note text: `Discarded <ISO-timestamp>: <reason>` (use `date +%Y-%m-%dT%H:%M:%S%z`, local time with explicit offset).

3. **Append the note and mark done in one call** (no partial state if the status change is refused).
   - From `claude-working`, `codex-working`, or `needs-review`:
     `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=done --add-issues="<note>"`
   - From `shaping`, `pending`, or `needs-brainstorming`: the transition table has no edge to `done`, so the same command needs `--force`. The `/coord-discard` invocation is the user's explicit request to abandon the task; add `--force` to the command above.
   - Quote the note (it contains spaces). `--add-issues` puts it under `## Open issues`, preserved in the archive.
   - If a non-forced close is refused for incomplete subtasks, stop and report; use `--force` only after the user confirms the subtasks are intentionally abandoned.
   - `coord update` auto-commits-and-pushes. Do not run any manual `git add`, `git commit`, or `git push`.

4. **Report.**
   - `discarded: <id>` — already moved to the configured archive directory.
   - Confirm with `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` that `status: done` is written.

## Rules

- Never edit task files directly; always go through `coord update`.
- Never run manual `git add`, `git commit`, or `git push` — `coord update` auto-commits-and-pushes each mutation.
- `--force` only for the no-edge sources above or with explicit user confirmation that incomplete subtasks are intentionally abandoned.
- Never use `--no-verify`.
- Archiving is part of `coord update --status=done`; there is no separate archive step.
