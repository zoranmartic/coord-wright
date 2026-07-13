# Changelog

Notable changes to CoordWright. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions are annotated tags on `main`.

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

[0.2.0]: https://github.com/zoranmartic/coord-wright/releases/tag/v0.2.0
