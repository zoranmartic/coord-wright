---
description: Run a pre-resolved coord task in the foreground. Usage: /coord-run <task-id>
---

You are running the already-resolved coord task `$ARGUMENTS`.

`coord` below is shorthand for `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord"`;
it is not on PATH.

Delegate to the `coord-check` skill
(`${COORD_TOOLS:-$HOME/Projects/coord-wright}/skills/coord-check/SKILL.md`) as the authoritative protocol for
task reads, token accounting, findings, status transitions, round-role handling,
and finish-or-handoff updates.

Differences from `/coord-check`:

1. Use `AGENT_ROLE=claude`.
2. Do not run `precheck` or `pickup`; the task id is `$ARGUMENTS`.
3. Start the read ladder at `coord show "$ARGUMENTS" --handoff`, then
   `--compact`, targeted reads, and full `show` only if
   still blocked. The worker passes no packet, so read `round_role` from the
   read-only `coord pickup --task-id="$ARGUMENTS" --assigned=claude` JSON; if
   it returns `skip`, treat `status: needs-review` as `reviewer` and anything
   else as `coder`.
4. When `COORD_WRAPPER_TOKENS` is set, skip token capture entirely: the worker
   records the complete run after exit. Otherwise capture `BASELINE` with
   `coord-tokens.sh --count` before marking the task `claude-working`.
5. Coder/architect rounds only: mark in progress with
   `coord update "$ARGUMENTS" --status=claude-working`. Skip this for reviewer
   rounds (`needs-review -> claude-working` is not an allowed transition and
   exits 3). Then run `coord next-subtask "$ARGUMENTS"` and work only the
   returned subtask when present.
6. Write the round finding to `"${COORD_AGENT_FINDING_FILE:-/tmp/claude-finding-$ARGUMENTS.txt}"`.
7. For manual runs only (`COORD_WRAPPER_TOKENS` unset), before the final
   update of the round (the status-changing call — never the
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
