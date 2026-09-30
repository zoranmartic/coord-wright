---
name: coord-status
description: "Show coord queue status, list tasks, display a specific task, or summarize a task result/outcome. Use when the user asks about coord state (\"what's pending\", \"show task X\", \"show result for X\", \"coord status\", \"any tasks waiting\")."
---

Read-only view onto the shared coord queue. Does not modify task state.

Source of truth:

- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/architecture.md`
- `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md`

Project-root preflight:

- Resolve the canonical project checkout before any `coord` command:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; status must reflect the main queue that the launchd worker reads.

Dispatch (pick the narrowest that matches the user's ask):

1. Specific task result / outcome (e.g. "show result for <id>", "what happened in <id>", "finished evidence for <id>", "outcome of <id>"):
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --result`
   - Use this for operator review of a completed or near-completed task. It is a compact read-only view over persisted task state: handoff header, latest terminal finding, final handoff content when present, and token total when available.
   - Do not use it as a worker startup packet; active rounds still use `show <id> --handoff`.

2. Specific task id (e.g. "show 2026-05-02-foo", "what's in <id>"):
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --compact`
   - Escalate to `show <id> --handoff` or full `show <id>` only if the user wants more detail.

3. Filtered list (e.g. "what's pending for claude", "show codex tasks", "anything blocked"):
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list --status=<csv> --assigned=<csv>`
   - Common filters:
     - Pending Claude work: `--status=pending,needs-review --assigned=claude`
     - Pending Codex work: `--status=pending,needs-review --assigned=codex`
     - Stuck / needs triage: `--status=needs-brainstorming`

4. Operator overview (default for "coord status", "what's the state of the loop"):
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" status`
   - Follow up with a `list` if the user wants the full table.
   - The output appends a soft warning when the last 3 completed tasks were all additive (no `kind: code-cut`, no negative `scope_budget` band). This is a sprint-level nudge toward the subtraction-as-opening-move policy in `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md`. Surface the warning to the user — do not strip it. It is advisory, not a block; the shaper still decides.

Rules:

- Never mutate state from this skill. For pickup/work, defer to `coord-check`. For new tasks, defer to `coord-shape`.
- If output is long, show the head and tail with a `[... N lines truncated ...]` marker and always keep FAIL/WARN lines.
- Report results plainly; do not fabricate task ids or statuses if the CLI returns nothing.
