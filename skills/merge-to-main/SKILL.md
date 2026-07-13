---
name: merge-to-main
description: "Fast-forward a registered coord session worktree branch into its canonical main checkout. Use when the user says $merge-to-main, \"merge this task branch to main\", or \"promote this worktree branch\"."
---

Fast-forward the current session worktree branch into canonical main.
Run from the session worktree (not the main checkout).

## Run

```bash
"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/merge-to-main.sh"
```

## Exit codes

**Exit 0** — merge and push complete. Report the output line to the user.

**Exit 1** — security finding. The script printed matches from the candidate diff.
Evaluate each match against the placeholder allowlist: `your-password`, `<password>`,
`example`, `changeme`, `REPLACE_ME`, `xxx`, `***`, empty values, `${ENV_VAR}`,
environment lookups. If all matches are safe:
```bash
SKIP_SECURITY=1 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/merge-to-main.sh"
```
If any match is a real credential, wallet, private key, or DSN: stop, fix on the
task branch, push the fix, then re-run without `SKIP_SECURITY=1`.

**Exit 2** — preflight failure (dirty tree, wrong worktree, branch out of sync,
push failed). Report the error message and stop.

## Source of truth

- `${COORD_TOOLS}/docs/coordination.md`
- `${COORD_TOOLS}/projects.txt`

## Rules

- Only run from a registered session worktree (`<project>-session-*`), never from main.
- Never push main until exit 0.
- Never print secret values in the chat response or terminal summary.
- Do not delete or rename the task branch.
- After a successful merge the session worktree remains on its branch, untouched.
