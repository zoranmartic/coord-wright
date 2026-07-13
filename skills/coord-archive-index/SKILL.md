---
name: coord-archive-index
description: Generate searchable indexes for coord task archives. Use when task history is large, old coord work needs to be queried, or the user asks what was done before without opening hundreds of Markdown files.
---

# Coord Archive Index

Use this skill to summarize task archives from canonical project roots. Avoid counting mirrored task worktrees unless the user specifically asks about them.

## Workflow

1. Resolve canonical project roots from `${COORD_TOOLS:-$HOME/Projects/coord-wright}/projects.txt`.
2. For one project, run `scripts/build_coord_archive_index.py --project-root <root> --output <path>`.
3. Prefer generated JSON for tooling and TSV for quick shell inspection.
4. Keep generated artifacts out of the repo unless the user explicitly wants them tracked.
5. Use the index to find candidate tasks, then open only the specific task files needed.

## Output

Report output path, task count, fields indexed, and any parse warnings.
