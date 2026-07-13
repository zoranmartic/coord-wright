---
name: coord-review
description: Validate a shaped coord task against shaping quality checks (plan, acceptance, subtask metadata, model allowlist, high-risk keywords). Use after shaping a task or before promoting it to pending. Accepts an optional task id; infers the latest shaped task if omitted.
---

Goal: catch shaping defects before a task enters the runnable queue. Run `bin/coord-review` on the task file and present any objections to the user with an inline fix offer. Print LGTM on a clean pass.

## Input

Optional: task id (e.g. `2026-05-13-some-task-id`). If omitted, infer the most recently updated task in `shaping` status.

## Workflow

1. **Resolve the task file.**
   - If a task id was provided, find it in the project task directory.
   - If not, run:
     ```bash
     python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list --status=shaping --format=ids
     ```
     Pick the first result (most recently updated).
   - Resolve the full path to the task file using the project task directory.

2. **Run the validator.**
   ```bash
   python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-review" <task-file-path>
   ```

3. **Interpret results.**
   - Exit 0: print `LGTM — no shaping objections found for <task-id>.`
   - Exit 1: present each numbered objection from stdout and ask:
     > "I can fix these inline — want me to apply the fixes and re-run the check?"
     If yes, apply targeted fixes via `coord update` commands or direct SKILL file edits, then re-run `coord-review` and confirm exit 0 before reporting done.

4. **xhigh task extra prompt.**
   - If `reasoning_effort: xhigh` is on the task, also ask:
     > "This task is `xhigh` — do you want to run a Codex loop pass before promoting?"
   - Relay the user's answer; do not run Codex automatically.

5. **Report.**
   - State the final check result (LGTM or remaining objections).
   - If LGTM, offer: "Ready to promote — run `coord promote <id>` to move to `pending`."

## Notes

- Never mutate the task to bypass a check. Only fix real shaping gaps.
- Do not run `coord-review` on tasks in `pending`, `claude-working`, or terminal statuses — those have already entered the work queue.
- If the task file is not found (wrong id or task in a different project), report the error and ask the user to confirm the task id.
