---
name: coord-assign
description: Assign a coord task's agent and/or model. Narrow — only writes `assigned` and `model_*`, never touches `status`. Use when the user says "/coord-assign", "assign <id> to <agent>", or wants to change the model for a task or specific subtasks.
---

Write `assigned` (agent) and/or `model_*` (per-task or per-subtask) on a coord task. Atomic: edit → commit → push. **Never touches `status`** — use `/coord-requeue` for that.

Project-root preflight:

- Resolve the canonical project checkout before reading, updating, patching, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; assignment must update the main queue that the launchd worker reads.

## Syntax

`/coord-assign <task-id> [S1,S2,...] [--agent=claude|codex] [--model=<name>]`

- `<task-id>`: required.
- `[S1,S2,...]`: optional subtask list. Only meaningful with `--model`.
- `--agent=X`: set task `assigned: X`. Subtask list (if any) is ignored when only `--agent` is given (agent is task-scoped).
- `--model=Y`: model override. Without subtask list → task-default `model_<agent>`. With subtask list → per-subtask `model_<agent>` on each named subtask.

## Workflow

1. **Parse args.**
   - Extract `<task-id>`, optional `S<n>` list, `--agent`, `--model`.
   - Reject if neither `--agent` nor `--model` is supplied — there is nothing to do.

2. **Resolve the agent for `--model`.**
   - Infer from model name: `opus|sonnet|haiku|*claude*` → `claude`; `gpt-*|*codex*` → `codex`.
   - If `--agent` is also supplied, the inferred agent must match it. Reject mismatches.
   - If `--agent` is not supplied, read current task `assigned` via `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id>` and require the inferred agent to match. Reject mismatches with a message pointing to `/coord-split` if the user wants per-subtask agent splits (not supported here).

3. **Apply the agent change** (if `--agent` supplied).
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --assigned=<agent> --agents=<agent>`
   - `coord update --agents` sets the `agents:` frontmatter field through the CLI; no direct file edits needed.
   - For `roles.coder`: read the current roles map from `coord show <id>`, build a merged spec preserving all existing keys (e.g. `reviewer:claude`), then apply: `coord update <id> --roles=coder:<agent>,reviewer:<existing-reviewer>`. Only include keys that were already present. Skip `--roles` entirely if the task has no `roles:` block.
   - Also remove any stale `shape_override: route back to <old-agent>` text via `coord update` if present.
   - `roles.reviewer` is intentionally left as-is (often stays `claude` for review quality even on codex-coder tasks).
   - Each `coord update` call auto-commits-and-pushes. Do not run manual `git add`, `git commit`, or `git push`.

4. **Apply the model change** (if `--model` supplied).
   - **Task-level (no subtask list):**
     `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --model_<agent>=<value>`
   - **Per-subtask:**
     - Read current subtasks block from the task path returned by `coord show <id> --path` (the `### Subtasks` checklist under `## Scope notes`).
     - For each named `S<n>`, replace its `model_<agent>:` line with the new value (or insert one if missing).
     - Write the modified block to `/tmp/coord-assign-subtasks-<id>.txt`.
     - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --set-subtasks=@/tmp/coord-assign-subtasks-<id>.txt`
     - If any named `S<n>` does not exist in the current subtask list, stop without committing and report which ids were missing.

5. **Report.**
   - One line summarising the change (agent, model, or both).
   - Confirm with `coord show <id>` that `assigned`, `agents`, and `roles` reflect the new values.

## Rules

- Never touch `status`. If the user wants to kick a stuck loop, that is `/coord-requeue`.
- Never use `--force`, `--no-verify`, or `--shape-override`.
- Cross-agent subtask routing (S3 on a different agent than the task) is intentionally not supported — recommend `/coord-split` instead.
- Stage only the task path returned by `coord show <id> --path`.
