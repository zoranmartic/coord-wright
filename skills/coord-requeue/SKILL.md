---
name: coord-requeue
description: Kick a stuck coord task. Flips `*-working` → `pending` and resets the runnable content hash so launchd treats it as fresh work. Optional `--model=<name>` for intra-agent model swap (token-out recovery). Use when the user says "/coord-requeue", "kick <id>", "the loop is stuck on <id>", or "<id> ran out of tokens".
---

Recover stuck coord tasks. Status flip + hash reset, optionally with a model swap in the same atomic commit.

Project-root preflight:

- Resolve the canonical project checkout before reading, updating, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; requeue must update the main queue that the launchd worker reads.

## Syntax

`/coord-requeue <task-id> [--model=<name>]`

## Workflow

1. **Read current state.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` → capture `status` and `assigned`.

2. **Validate source status.**
   - Accepted: `pending`, `claude-working`, `codex-working`.
   - Refuse `needs-review`, `review-passed`, `review-failed`, `needs-brainstorming`, `done`, `shaping`. Print the current status and which skill to use instead:
     - `needs-brainstorming` → `/coord-promote` after shaping
     - `done` → `/coord-discard` (already finished) or audit
     - review queue → diagnose, do not silently rescue
     - `shaping` → `/coord-promote`

3. **Validate `--model` (if supplied).**
   - Infer agent from model name: `opus|sonnet|haiku|*claude*` → `claude`; `gpt-*|*codex*` → `codex`.
   - Inferred agent must equal task `assigned`. Reject cross-agent model swaps with a clear message:
     `cross-agent model swap requires explicit re-assignment first: run /coord-assign <id> --agent=<other> --model=<m>, then /coord-requeue <id>`

4. **Apply changes.**
   - If `--model`: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --model_<agent>=<value>`
   - If status was `*-working`: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=pending`
   - If status was already `pending` and no `--model`: the coord CLI only clears the content hash on a non-runnable → runnable transition. A `pending` → `pending` write does NOT clear it. In this case, also run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=pending` to force a write, but warn the user that the hash may not be cleared and the task may not be picked up as fresh work. True hash-clearing for an already-pending task requires a pending→shaping→pending round-trip or a direct CLI flag if one is added.
   - Each `coord update` auto-commits-and-pushes. Do not run manual `git add`, `git commit`, or `git push`.

5. **Verify hash was cleared.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` and check that `content_hash_<assigned>` is absent from the output. If still present on an already-pending task, warn the user about the limitation above.

6. **Report.**
   - `requeued: <id> (was <prev-status>, now pending)` — include `model_<agent>=<value>` if changed.
   - Note the commit sha from coord update's output.

## Rules

- Never use `--force`, `--no-verify`, or `--shape-override`.
- Never cross agents via `--model` — reject and point at `/coord-assign`.
- Never touch review-queue states (`needs-review`, etc.) — those need a human look, not a kick.
- Stage only the task path returned by `coord show <id> --path`.

## Token-out recovery flows

- **Same agent, cheaper model:** one command — `/coord-requeue <id> --model=<cheaper>`.
- **Switch agent entirely:** `/coord-assign <id> --agent=<other> --model=<m>` then `/coord-requeue <id>`. The agent switch is a deliberate decision, not bundled into recovery.
