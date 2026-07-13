---
name: coord-help
description: Show help for a coord skill (parameters, examples) or list all coord-* skills with one-line descriptions. Read-only. Use when the user says "/coord-help", "/coord-help <name>", "what params does <skill> take", or "list coord skills".
---

Display documentation for coord skills. Read-only — never mutates anything.

Project-root preflight:

- Resolve the canonical project checkout before showing command-specific coord help:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- Generic skill-file help can be shown without changing directories, but any `coord help <subcommand>` call should run from the main checkout.

## Syntax

- `/coord-help` → list all `coord-*` skills.
- `/coord-help <skill-name>` → show full help for one skill.

## Workflow

1. **Locate the skills root.**
   - Prefer `${COORD_TOOLS:-$HOME/Projects/coord-wright}/skills` (canonical source).
   - Fall back to `$HOME/.claude/skills` if the canonical path is unavailable.
   - Fall back to `$HOME/.agents/skills` if neither of the above exists (Codex runtime).

2. **No-arg form: list mode.**
   - Enumerate every directory under the skills root whose name starts with `coord-`.
   - For each, parse the `description:` line from `SKILL.md` frontmatter.
   - Print one line per skill: `/<name> — <description>`.
   - Sort alphabetically.
   - End with a hint: `Run /coord-help <name> for full help.`

3. **Single-arg form: detail mode.**
   - Accept the skill name with or without a leading `/` or `coord-` prefix; normalise to `coord-<name>`.
   - Print the full body of `SKILL.md` (skip the frontmatter block).
   - If the skill maps to a `coord` subcommand, append a section:
     ```
     ─── coord help ───
     <output of: python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" help <subcommand>>
     ```
   - Skill → `coord` subcommand mapping (use this when present, omit the section when the skill has no direct mapping):
     - `coord-promote` → `promote`
     - `coord-assign`, `coord-requeue`, `coord-discard` → `update`
     - `coord-status` → `status`
     - `coord-split` → `new`
     - `coord-shape` → `new`
     - `coord-tokens`, `coord-check`, `coord-init`, `coord-refine`, `coord-help` → no mapping

4. **Unknown skill.**
   - If the named skill does not exist under the skills root, print: `unknown skill: <name>` and run the no-arg list form so the user sees what's available.

## Rules

- Read-only; never call `coord update`, `git add`, `git commit`, or `git push`.
- Do not summarise or paraphrase SKILL.md content — print it verbatim so users see the canonical text.
- Surface helper errors (missing file, `coord` non-zero exit) verbatim.
