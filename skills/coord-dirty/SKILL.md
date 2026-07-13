---
name: coord-dirty
description: "Inspect coord project worktrees for dirty files and likely unfinished agent or worker ownership. Use when the user says /coord-dirty, asks which worktrees are dirty, asks what agent left files behind, or asks for dirty coord state across a project or all registered projects."
---

Read-only diagnostic for dirty coord worktrees. Do not mutate files, task state,
commits, branches, or launchd services from this skill.

## Syntax

`/coord-dirty [--project <name-or-path>] [--all-projects] [--json]`

## Workflow

1. Run the helper from the current directory unless the user asks otherwise:
   - Current project: `"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-dirty"`
   - One project: `"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-dirty" --project <name-or-path>`
   - All registered projects: `"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-dirty" --all-projects`
   - Machine-readable output: add `--json`
2. Report the helper output plainly. Preserve the distinction between proven
   state and `likely_owner`; likely ownership is a heuristic from task status,
   worker locks, worker logs, branch names, and dirty status.
3. If the output is longer than 40 lines, summarize by project and include the
   dirty worktree rows plus worker hints. Do not hide helper errors.

## Interpretation

- `coord worker active` means the project worker lock PID is currently alive.
- `codex on <task>` or `claude on <task>` comes from a `*-working` task status.
- `latest worker run` comes from `.coord/worker.log`; it is a recent hint, not
  proof that the agent owns all current dirty files.
- `pre-existing before <agent>` means the worker logged that the checkout was
  already dirty before that agent started.
- `manual/task branch` and `manual task worktree` are branch/path heuristics.

## Rules

- Read-only only.
- Default scope is the current coord project. Use `--all-projects` only when the
  user explicitly asks for all repos/projects/worktrees.
- Prefer the helper output over ad hoc git commands unless the helper itself is
  missing or fails.
