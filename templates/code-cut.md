# Template — `kind: code-cut` subtraction-discipline non-negotiables

This is the canonical non-negotiables block for `kind: code-cut` coord tasks.
The `coord-shape` skill copies this verbatim into the task body's
`## Non-negotiables` section when shaping a `code-cut` task, then substitutes
the `{target_low}` and `{target_high_added}` placeholders against the task's
`scope_budget.net_loc_delta_target` band.

Source of truth: this file. Do not paraphrase or compress in individual task
files — the literal text is the contract the worker reads. If a project needs
to add task-specific exclusions, append them as new bullets below the block;
do not rewrite the existing bullets.

The discipline below is the same that produced a real C1–C5 chain
(2026-05-25, -10,349 LOC net, 47 files, +988 / -11,337). C3 in that chain is
the empty-cut control — Codex correctly detected scope had already been
absorbed and shipped a 29-LOC cleanup with an explicit handoff note, proving
the worker follows the discipline when given it.

---

## Non-negotiables — SUBTRACTION DISCIPLINE

- **Net LOC delta is the contract.** If your final commit's `git diff --stat`
  shows fewer than {target_low} lines deleted, you missed scope. If it shows
  more than {target_high_added} lines ADDED, you scope-crept.
- **Do not add helpers, abstractions, or "while I'm here" refactors.** Touch
  only lines that change because of the cut.
- **Test files for deleted modules: DELETE them.** Do not skip them, comment
  them out, or move them to legacy/.
- **Do not add feature flags or backward-compat shims.** Reversibility comes
  from git, not from code.
- **If you find something else broken or worth cutting**, write it at the
  bottom of THIS task file under `## Findings for follow-up`. DO NOT FIX IT.
- **Do not preserve env vars, types, constants, or routes "for backward
  compat".** They are gone.
- **Do not refactor adjacent code in the files you edit.** Renames, helper
  extractions, import reorganisations beyond the minimal change are out of
  scope.
