---
name: coord-check
description: "Check the configured coord task directory for tasks assigned to this agent and work on them. Use at the start of any coordinated work session."
---

Repo-local entry point for the shared coord loop. Keep this file identical across projects and across `.claude` / `.agents`.

**Runtime identity:** determine your agent role before any other step. If you are Claude, `AGENT_ROLE=claude`. If you are Codex, `AGENT_ROLE=codex`. All status, token, and queue commands below use `$AGENT_ROLE` as a placeholder — substitute it literally.

**Mode** (parse `$ARGUMENTS` before any other step):

- `` (empty) or `one` → `MODE=one`: execute exactly one round, then stop.
- `all` → `MODE=all`: loop rounds until pickup returns `skip` or `needs-brainstorming`, or `COORD_CHECK_MAX_ROUNDS` (default 5) is reached.
- `<task-id>` (e.g. `2026-05-17-my-task`) → `MODE=id`: skip discovery; use that id directly, one round.

Default is `one`. On Codex, `all` collapses to `one` because the `codex exec` process exits after each round; queue multiple `/coord-check` invocations externally for multi-round Codex work.

Source of truth:

- `AGENTS.md`
- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/architecture.md`
- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md`
- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/claude-coordination.md`
- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/codex-coordination.md`

Project-root preflight:

- Resolve the canonical project checkout before any pickup or update:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root")`
- If `pwd -P` is not exactly `$COORD_MAIN`, stop and report:
  `coord-check is main-checkout only; current directory is <cwd>, main checkout is <COORD_MAIN>. Use the launchd worker or start a main-checkout session for coord pickup.`
- Do not `cd "$COORD_MAIN"` and continue from a sibling task worktree. Slot sessions may create, inspect, or administer coord tasks through the other coord skills, but they must not pick up runnable work or mutate active task state through `/coord-check`.

Workflow:

**Loop control (`MODE=all` only):** initialise `ROUNDS_COMPLETED=0`. After step 4 completes, increment `ROUNDS_COMPLETED`. If pickup returned `skip` or `needs-brainstorming` during this round, exit and report `Completed $ROUNDS_COMPLETED round(s); queue empty or needs-brainstorming`. If `ROUNDS_COMPLETED` has reached `COORD_CHECK_MAX_ROUNDS` (default 5), exit and report `Stopped at round cap ($ROUNDS_COMPLETED rounds); re-run /coord-check all to continue`. Otherwise go back to step 1. For `MODE=one` or `MODE=id`, run steps 1–4 once and stop.

1. Prefer the resolved handoff packet.
   - If startup already includes `Active task id:` and `## Resolved handoff packet`, treat that as authoritative.
   - Context ladder: `show <id> --compact` -> `show-signatures <id>` -> targeted file or section reads -> full `show <id>` only when a specific missing detail still blocks progress.

2. Discovery path when no handoff packet was injected.
   - If `MODE=id`: use `$ARGUMENTS` as `<id>` directly; run `show <id> --handoff` and skip the precheck/pickup calls below.
   - Otherwise: run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" precheck --assigned=${AGENT_ROLE}`
   - Read `changes_file` from `coord paths --json`; if it exists, read it for recent diff context.
   - Resolve pickup: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" pickup --assigned=${AGENT_ROLE}`
   - On a returned task id, start with `show <id> --handoff`, then `show <id> --compact`, then full `show <id>` only if a specific missing detail still blocks the work.
   - If pickup reports no runnable task for ${AGENT_ROLE}, list blocked tasks with `--status=needs-brainstorming` and report them.

3. Work the active task.
   - Read the handoff packet, task Rules, prior findings, open issues, and Lessons learned.
   - Read repo-local guidance in `AGENTS.md`. Use `CLAUDE.md` as supplementary context when present.
   - If `COORD_WRAPPER_TOKENS` is unset, capture token baseline before any other coord work: `BASELINE=$(bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-tokens.sh" --agent=${AGENT_ROLE} --count 2>/dev/null || echo 0)`. Save it for step 4. If `COORD_WRAPPER_TOKENS` is set, skip this; the wrapper owns token capture.
   - Mark in progress (coder / architect rounds only): `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=${AGENT_ROLE}-working`. Skip this for reviewer rounds — `needs-review → ${AGENT_ROLE}-working` is not in `VALID_TRANSITIONS` and will exit 3. Reviewer rounds stay at `needs-review` until the final `review-passed` / `review-failed` / `pending` transition in step 4.
   - Capture the pre-agent git status immediately (after marking in progress for coder/architect, or at this point for reviewer rounds that skipped the mark). If the wrapper already provided `COORD_BASE_GIT_STATUS_FILE`, reuse it; otherwise create the manual sidecar and save `BASE_GIT_STATUS_FILE` for step 4: `BASE_GIT_STATUS_FILE="${COORD_BASE_GIT_STATUS_FILE:-.coord/work-base-<id>.txt}"; mkdir -p "$(dirname "$BASE_GIT_STATUS_FILE")"; if [[ -z "${COORD_BASE_GIT_STATUS_FILE:-}" ]] && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then git status --porcelain --untracked-files=all > "$BASE_GIT_STATUS_FILE"; elif [[ -z "${COORD_BASE_GIT_STATUS_FILE:-}" ]]; then : > "$BASE_GIT_STATUS_FILE"; fi`
   - Check subtask routing: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" next-subtask <id>`
   - If a current `S<n>` subtask is returned, work only that subtask in this round and remember the label for the token-log entry.
   - Use `show-signatures <id>` before opening full files when you only need structure.
   - Do the scoped work, write findings to `/tmp/${AGENT_ROLE}-finding-<id>.txt`, then update the task via `coord update`.

4. Finish or hand off.
   - **Commit agent code edits before the final status update.** After scoped work and the finding file are ready, but before the status-changing `coord update`, run: `COORD_TASK_ID=<id> COORD_AGENT=${AGENT_ROLE} COORD_BASE_GIT_STATUS_FILE="${COORD_BASE_GIT_STATUS_FILE:-${BASE_GIT_STATUS_FILE:?missing base status file}}" bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-commit-agent.sh"`. If the helper exits non-zero, stop before the final status update and report that uncommitted work remains for human recovery.
   - **Token capture.** If `COORD_WRAPPER_TOKENS` is set, do not call `coord-tokens.sh` and do not pass `--add-tokens-*`; the launchd wrapper owns token capture and avoids duplicate rows. If `COORD_WRAPPER_TOKENS` is unset, capture and report tokens **on the final `coord update` of the round only** — the call that changes status. For the reviewer 2-step pattern (append finding, then set status), the status call is the final one; do NOT attach token flags to the finding-only call. `coord-tokens.sh --since="$BASELINE"` returns cumulative usage since the baseline, so attaching it to both calls double-counts.
     - **If `AGENT_ROLE=claude` and `COORD_WRAPPER_TOKENS` is unset:** before the final status update, run: `TOKENS=$(bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-tokens.sh" --agent=claude --since="$BASELINE" 2>/dev/null || echo 0)`. Pass `--add-tokens-claude="$TOKENS"` to the final update, and label the row's Stage column via `--subtask`: pass `--subtask=S<n>` for a subtask coder round, `--subtask=review` for a reviewer round, `--subtask=arch` for an architect round, and omit `--subtask` for a coder round with no subtask.
     - **If `AGENT_ROLE=codex` and `COORD_WRAPPER_TOKENS` is unset:** before the final status update, run: `TOKENS=$(bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-tokens.sh" --agent=codex --since="$BASELINE" 2>/dev/null || echo 0)`. Pass `--add-tokens-codex="$TOKENS"` to the final update, and label the row's Stage column via `--subtask`: pass `--subtask=S<n>` for a subtask coder round, `--subtask=review` for a reviewer round, `--subtask=arch` for an architect round, and omit `--subtask` for a coder round with no subtask.
   - **If `AGENT_ROLE=claude`:**
     - Check the `round_role` field in the pickup payload first (values: `coder`, `reviewer`, `architect`).
     - For every Claude role below, invoke `coord-commit-agent.sh` before the final status update. Reviewer rounds still append the finding first; the helper runs between that finding append and the status update.
     - **`round_role=reviewer`** (Claude is the explicit designated reviewer):
       - **Always append your finding first, then set status — two separate `coord update` calls.** Write the finding with `--append-claude-finding` before running the status update. If the turn cap hits between the two steps, the worker can auto-recover from an approved finding; it cannot recover from a missing one.
       - **Before the status update, check remaining subtasks**: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" next-subtask <id>`.
       - Review passes:
         - If `next-subtask` returns an `S<n>` (subtasks remain — rare under review-once-at-end, but defensive): `coord update <id> --status=pending --assigned=<coder>` to advance the chain instead of closing.
         - If `next-subtask` returns no remaining work: `coord update <id> --status=review-passed` (no `--force`; the close gate verifies every subtask is `[x]`).
       - Review fails → first `coord update <id> --append-claude-finding "Outcome: REJECT. Root cause: ..."`, then `coord update <id> --status=review-failed`. Include a `Root cause:` line in the finding.
       - **Do not pass `--force`** on `--status=review-passed`. `--force` is a human escape hatch (cancel a stuck task), not a normal review handoff. The CLI refuses to close while any `[ ]` subtask remains — that refusal is the safety net.
     - **`round_role=architect`**: this should only occur for explicit architect roles. Persist executable subtasks or a concrete plan, then hand to Codex with `--status=pending --assigned=codex`.
     - **`round_role=coder`**:
       - If the round had a resolved `S<n>` subtask, always pass `--complete-subtask=S<n>` on the success update so the `[ ]` flips to `[x]`.
       - Subtasks remain after this one: `--status=pending --assigned=<self>` (advance to the next subtask). Skip review until the chain ends.
       - Last subtask done and `roles.reviewer` is set: `--status=needs-review --assigned=<reviewer>`.
       - Last subtask done and no reviewer: `--status=review-passed` (no `--force`).
   - **If `AGENT_ROLE=codex`:**
     - Before running the resolved success command, invoke `coord-commit-agent.sh` as described above so code edits are committed before the task-file status update.
     - Follow the resolved `codex_execution_policy.success_update.command` for every Codex round. It is authoritative for coder, reviewer, architect, subtask, and full-task transitions.
     - Replace `@<file>` in that command with `/tmp/codex-finding-<id>.txt`.
     - Under launchd (`COORD_WRAPPER_TOKENS` set), do not add `--add-tokens-codex` or `--subtask` for the token row. Token capture for wrapper-run Codex rounds is the worker's job (it parses real numbers from stdout and labels them with the current subtask). In a manual `/coord-check` session (`COORD_WRAPPER_TOKENS` unset), add the `--add-tokens-codex="$TOKENS"` and token-stage `--subtask=...` flags described above to the final status update. The `--complete-subtask=S<n>` argument already in the resolved success command is unrelated to token rows — keep it as written.
     - If the resolved handoff packet does not include `codex_execution_policy.success_update`, stop and report the missing policy instead of guessing a handoff.
   - **Never use `status=review`, `status=review-passed`, or `status=review-failed` directly.** These are internal coord transient states — `review-passed` and `review-failed` are command aliases (run via `coord update --status=review-passed`), not status values you write. `review` is not a valid status at all.

Rules:

- Never edit coord task files directly; use `coord update`.
- Follow the shared status and review-loop rules in `task-files.md`; use `needs-brainstorming` when appropriate.
- Do not force round caps manually. If `coord` escalates to `needs-brainstorming`, stop there and report it.
- Do not invent reviewer or architect handoffs. Follow explicit `roles` and the resolved pickup policy.
- Truncate tool output over 40 lines to the first 20 + last 20 lines with `[... N lines truncated ...]`.
- Do not run raw `git commit`; call `bin/coord-commit-agent.sh` as described above so agent code edits are committed before the final `coord update`, and let `coord update` own task-file commits.
