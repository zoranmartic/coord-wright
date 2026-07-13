---
description: Run a pre-resolved coord task in the foreground. Usage: /coord-run <task-id>
---

You are running the already-resolved coord task `$ARGUMENTS`.

Delegate to `skills/coord-check/SKILL.md` as the authoritative protocol for
task reads, token accounting, findings, status transitions, round-role handling,
and finish-or-handoff updates.

Differences from `/coord-check`:

1. Use `AGENT_ROLE=claude`.
2. Do not run `precheck` or `pickup`; the task id is `$ARGUMENTS`.
3. Start the read ladder at `coord show "$ARGUMENTS" --handoff`, then
   `--compact`, `show-signatures`, targeted reads, and full `show` only if
   still blocked.
4. Capture `BASELINE` with `coord-tokens.sh --count` before marking the task
   `claude-working`.
5. Mark in progress with `coord update "$ARGUMENTS" --status=claude-working`,
   then run `coord next-subtask "$ARGUMENTS"` and work only the returned
   subtask when present.
6. Write the round finding to `/tmp/claude-finding-$ARGUMENTS.txt`.
7. Before the final update of the round (the status-changing call — never the
   finding-only call in the reviewer 2-step pattern, since `--since=$BASELINE`
   is cumulative and would double-count), capture `TOKENS` with
   `coord-tokens.sh --since="$BASELINE"` and include
   `--add-tokens-claude="$TOKENS"`. Label the row's Stage column via
   `--subtask`: `S<n>` for a subtask coder round, `review` for a reviewer
   round, `arch` for an architect round, omit for a coder round with no
   subtask.
8. Finish or hand off exactly as the `coord-check` `AGENT_ROLE=claude` section
   requires for `round_role` values `coder`, `reviewer`, and `architect`.
   Append the finding before any reviewer transition. Use the documented
   `coord update` aliases instead of hand-editing task status.

Stop after this one task. Never edit task files directly.
