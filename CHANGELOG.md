# Changelog

Notable changes to CoordWright. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are annotated tags on `main`.

## [0.3.0] — 2026-09-30

### Added

- `coord show <id> --result`: read-only outcome view (handoff header, latest terminal review finding, final subtask handoff, token total).
- `bin/coord-log`: compact, rotation-safe viewer for `.coord/worker.log` — one line per round with agent, model, task, subtask, duration and verify result.
- `codex-coord-stats.js --round-summary`: one JSON record of usage, model and tool calls for a single Codex rollout.
- `coord-review` requires a recorded `Subtraction analysis` (four non-placeholder answers) and a numeric `scope_budget.net_loc_delta_target` band on shaped tasks; the example task shows both.
- `review_rounds_max` is enforced: a reviewer rejection (`review-failed` from `needs-review`) increments `review_round`, and reaching the cap parks the task in `needs-brainstorming` with `pickup_hold` and an Open issue instead of another coder round. Same-side loops and tasks without the field stay uncapped.
- `coord update --status=needs-review` without `--assigned` assigns `roles.reviewer` when it names `claude` or `codex`.
- `coord update --complexity=<trivial|simple|complex|xhigh>`: validated, and the model/effort baseline is checked against the new complexity together with any model/effort flags in the same call.

### Changed

- Provider rate limits cool down per agent (`.coord/sleep-until.<agent>`): a limited provider no longer pauses work already assigned to the other one. Capacity/overload errors (`at capacity`, `overloaded`) are detected and, without a reset time, back off 1, 5, 10, 20, then 30 minutes; reset times such as `resets 3pm` or `try again at 9:52` are parsed, and a reset in the current minute retries after 5 minutes.
- `scope_budget` is a warning target, not a stop: the coder finishes the subtask and records actual vs target net LOC; the reviewer decides whether an overshoot is bloat. A negative band on `code-cut`/`refactor` stays a hard review criterion.
- The watchdog skips tasks with `pickup_hold: true`, parks a task it judges human-required, and auto-holds a task after two consecutive watchdog verdicts with no state change, instead of re-triaging it on every cycle.
- Queue commits made by `coord new`/`update`/`promote`/`release` include only the task paths they wrote; git failures exit `4` (`<command>: git side effect failed`). A rejected push retries once after `git pull --rebase --autostash` and never leaves a rebase in progress.
- Worker commits of scoped rounds include only the declared scope paths, and commit/push failures propagate to the caller.
- `update`, `promote`, `release`, `next-subtask` and `depends_on` resolve exact task ids only; `show` reports ambiguous partial ids instead of picking the first match. `coord new` picks the next free `-N` suffix and never overwrites an existing file.
- `coord new --status`, `--assigned`, `promote --status`, `release --status` and runnable `roles` values are validated against the status routing and transition table.
- A forced demote out of `done` and `coord release` report model/effort baseline drift as a warning instead of refusing the transition.
- Closing a never-started `shaping`/`needs-brainstorming` draft to `done` (discard, split parent close) skips the model/effort baseline check, so an off-baseline draft can still be closed.
- Reviewer and architect token rows are labelled `review`/`arch`; `/coord-run` does not record its own token row when the worker records the round.
- `coord new --tags` keeps the supplied tags; `coord update --tags` replaces them.
- Interactive `agent-launch.sh` no longer injects a default `--effort`; `settings.json` owns interactive effort unless `CLAUDE_LAUNCH_EFFORT` is set.
- The round finding path is exported to agents as `COORD_AGENT_FINDING_FILE`.
- Timestamps no longer assume a fixed timezone: `coord`, the worker, the watchdog and rate-limit reset parsing use `COORD_TZ` (IANA name) when set, otherwise the system local timezone; human-readable timestamps keep a numeric `%z` offset.

### Fixed

- The false-approve guard and the mechanical verify gate now run whenever a round leaves a task `done` — after coder closes, non-zero exits and the max-turns path, not only after successful reviewer rounds. If the forced demote itself fails, the task is parked in `needs-brainstorming` with `pickup_hold`.
- Terminating the worker (TERM/INT/HUP) stops the agent's whole process group, including under the Python timeout fallback, so no orphaned agent keeps editing after the round is recorded as failed. `verify_commands` run with stdin closed.
- Interrupted task bookkeeping confined to the tasks directory is committed and pushed at the next tick instead of blocking pickup; the recovery is skipped while a rebase or merge is in progress.
- The global semaphore sweeps dead owners and acquires slots under one file lock.
- The pickup dedup hash ignores the generated token and runtime-warning sections, so a token-only update no longer makes a finished task runnable again. Re-appending an identical finding or token row is a no-op. Plain-integer token values and older token rows parse correctly.
- Frontmatter round-trip: column-0 list items, flow lists with commas, literal list items (`- true`, `- 17`, `- [ -f x ]`), invalid quoted scalars and nested integers survive a rewrite; existing task files render byte-identically. A `## ` heading inside an appended finding no longer splits the findings section, a non-integer `round` no longer crashes `coord update`, and `--set-subtasks` keeps scope notes that follow the checklist.
- `rebase-to-main.sh` prints the exact finish commands after a conflicted rebase (`git diff --check`, then a force-with-lease push pinned to the fetched upstream commit) instead of telling the user to re-run the script, whose preflight refuses a rebased branch.
- Scoped worker commits stage the configured coord task paths (`COORD_TASKS_DIR`, archive, findings and changes file, from the environment or `.coord/config.env`) instead of a literal `tasks/` directory.
- Skills and docs reference only CLI forms that exist and match current worker behaviour; the never-implemented `--shape-override` is gone.

## [0.2.0] — 2026-07-14

### Security

- **Unattended worker rounds are disabled by default.** Installed workers and the watchdog exit idle until the operator sets the exact acknowledgement `COORD_UNSAFE_AUTONOMOUS=1`. `install.sh` writes the key into generated launchd worker environments when it is set at install time; re-running install without it removes the key again (revocation is the same command). With the acknowledgement, worker-launched Claude runs with `--dangerously-skip-permissions` and Codex with `--sandbox danger-full-access` — spelled out in the new README "Blast radius" section.
- Interactive (non-worker) Claude launches without an explicit permission flag default to `--permission-mode acceptEdits` instead of bypassing permissions.
- The manual `/codex` debugging command runs sandboxed (`--sandbox workspace-write`) instead of the retired `--full-auto`.

### Fixed

- Installer aborts before any side effects when `jq` is missing (previously it printed a note and could still load launchd workers without the merged settings and hooks).
- Installer settings merge preserves existing `permissions.allow`, `permissions.additionalDirectories`, and hook arrays, and backs up `~/.claude/settings.json` before writing (previously user arrays were silently replaced).
- Installer placeholder resolution parses the settings JSON and substitutes inside parsed string values; raw text substitution could corrupt the file when a checkout path contains `\`, `"`, `&`, or the sed delimiter.
- Watchdog: a macOS `mktemp` template bug killed every triage cycle after the first — a suffix after the `X`s is not expanded, so the first run created the literal template file and every later run failed on it.
- Watchdog: stuck-task triage honors only the latest review round's verdict; an APPROVE from an older round no longer counts after a later REJECT.
- Worker: reviewer rounds receive an explicit failure command, so a REJECT verdict has an instructed path and can never end in the success update. A false-approve guard demotes tasks that were closed as done while the same round's review finding says REJECT, and a mechanical verify gate re-runs the task's `verify_commands` after every reviewer close — demoting the task when they fail and restoring any worktree changes the verify created.
- Worker: `.coord/work-scope-*` temporary files are removed on exit (previously one leaked per pickup).
- Worker: warns when `scope`/`scope_creates` is present but not a YAML list — a scalar silently disabled scoped-commit protection.
- `coord` CLI: failed `git add`, `git commit`, or `git push` now exits non-zero with the error instead of reporting success while nothing was committed; repositories without a remote remain supported as a local-only state.
- `coord` CLI advisories point to `docs/task-files-reference.md` instead of a documentation path that does not ship.
- `audit-hardening.sh` reports `SKIP` instead of `FAIL` when `projects.txt` does not exist yet (a supported fresh-install state).
- The example task uses the list form of `scope:` (the worker only honors lists) and a relative documentation link that resolves on GitHub.
- Skills resolve the checkout via `${COORD_TOOLS:-$HOME/Projects/coord-wright}` instead of hard-coding the default clone path.

### Changed

- Codex model default is `gpt-5.6-sol` across docs, skills, and the validator allowlist; `gpt-5.5` remains accepted.
- Claude alias resolution pins the current models: `sonnet` → `claude-sonnet-5`, `opus` → `claude-opus-4-8` (`haiku` unchanged). The superseded IDs remain valid in existing task files. The watchdog's model fallback follows the new Sonnet pin.
- README states the real requirements (Python 3.9+) and a clone path that works on a fresh machine.

### Removed

- The `coord-cadence` skill — it invoked components that have never shipped in this repository.

## [0.1.0] — 2026-06-10

- Initial public release: file-backed task queue with a typed contract, launchd workers, cross-model (Claude ⇄ Codex) review loop, `coord` CLI, skills, hooks, agents, and docs.

[0.3.0]: https://github.com/zoranmartic/coord-wright/releases/tag/v0.3.0
[0.2.0]: https://github.com/zoranmartic/coord-wright/releases/tag/v0.2.0
