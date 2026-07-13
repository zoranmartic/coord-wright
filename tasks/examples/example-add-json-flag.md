---
id: example-add-json-flag
task: "Add a --json flag to the `status` subcommand so its output can be piped to jq"
status: pending
complexity: simple
kind: code-fix
assigned: codex
priority: 5
scope:
  - src/cli/status
tags: [example]

# Models — override if defaults aren't right
model_claude: sonnet
model_codex: gpt-5.6-sol

# Reasoning effort
reasoning_effort: medium

# Dependencies — task ids that must be `status: done` first
depends_on: []

# Verification — reviewer runs verify_commands and gates on exit code 0
acceptance:
  - "`mycli status --json` prints a single valid JSON object to stdout and nothing else."
  - "`mycli status` with no flag prints the existing human-readable output, unchanged."
  - "Exit code is 0 on success and non-zero on error, in both modes."
verify_commands:
  - "mycli status --json | jq -e . >/dev/null"
  - "mycli status | grep -q 'Status:'"
---

## Plan

`status` currently prints only human-readable text, so scripts have to scrape it.
Add an opt-in `--json` flag that emits one JSON object carrying the same fields,
reusing the existing status struct. The default (text) output must not change —
that would break existing users. No output-format registry, no YAML, no
pretty/compact toggle (see Subtraction analysis).

## Scope notes

- [ ] **S1: Add the `--json` flag and JSON serialization**
  complexity: simple
  model_claude: sonnet
  model_codex: gpt-5.6-sol
  Add a `--json` boolean to the `status` subcommand parser. When set, serialize
  the existing status struct to JSON and print it; otherwise leave the text path
  untouched. Do NOT change the default output.
  Writes handoff: `.coord/handoffs/example-add-json-flag/S1.md`

- [ ] **S2: Test both modes and document the flag**
  complexity: simple
  model_claude: sonnet
  model_codex: gpt-5.6-sol
  Add a test asserting `status --json` is valid JSON with the expected keys and
  that `status` (no flag) is unchanged. Add one line to the CLI reference. No new
  test harness.
  Reads handoff: `.coord/handoffs/example-add-json-flag/S1.md`
  Writes handoff: `.coord/handoffs/example-add-json-flag/S2.md`

## Subtraction analysis

- **Smallest version that delivers the value?** One `--json` flag on `status`,
  reusing the existing status struct. No new abstraction.
- **What are we consciously NOT building?** No `--format=<x>` plugin system, no
  YAML, no pretty/compact toggle — those serve hypothetical second consumers.
- **Net LOC band:** small positive (~+15–30). Not a `code-cut`.

## Notes

This is a worked **example** of the task contract, not a real task. It shows what
a shaped task carries: a crisp one-line `task`, machine-checkable `acceptance` +
`verify_commands`, a `## Plan`, `## Scope notes` with per-subtask `complexity` /
model metadata and deterministic **handoff files** (the compression layer between
cold-start subtask workers), and a `Subtraction analysis` block (the additive-bias
guardrail). Larger tasks add a `roles:` block (architect / coder / reviewer) and
`depends_on` chains — see [`../../docs/task-files-reference.md`](../../docs/task-files-reference.md).
