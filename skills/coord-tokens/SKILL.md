---
name: coord-tokens
description: Show current token spend per agent across coord tasks. Read-only — no commits. Use when the user says "/coord-tokens", "show tokens", "how many tokens left", or before deciding which agent to assign.
---

Display token usage for Claude and Codex coord runs. Read-only; never mutates anything.

Project-root preflight:

- Resolve the canonical project checkout before running token helpers:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; token reporting should reflect the main queue and worker state.

## Syntax

`/coord-tokens [--since=<duration>]`

## Workflow

1. **Run the helpers.**
   - Claude side: `bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-tokens.sh"`
   - Codex side: `node "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/codex-coord-stats.js"`
   - Pass `--since=<duration>` through to whichever helper accepts it; if neither does, print the duration in the header and run them unfiltered.
   - If a helper exits non-zero, print its stderr and continue with whatever output is available — partial data is still useful.

2. **Present output.**
   - Print a short header: `Token spend (Claude / Codex)` plus the `--since` value when supplied.
   - Stream each helper's output with a one-line label per section.
   - Do not summarise, do not interpret — show the raw output so the user sees what the helpers actually report.

3. **No commits, no pushes, no file edits.** This skill is observational.

## Rules

- Read-only; never call `coord update`, `git add`, `git commit`, or `git push`.
- Surface helper errors verbatim; do not retry or work around them.
