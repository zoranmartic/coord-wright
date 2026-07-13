---
name: coord-audit
description: Run the CoordWright hardening audit — read-only check of codex sandbox config, auth file perms, worker.sh integrity, execpolicy allow-list, Claude Code hook installation, and per-project .gitignore + .env perms. Use when the user says "/coord-audit", "audit hardening", "check security posture", or wants a one-shot drift check.
---

Read-only inspection of the operational hardening landed across the CoordWright checkout, ~/.codex/, ~/.claude/, and each registered project. Does not modify anything. The same script can run nightly under launchd (e.g. `com.coord.audit.daily`, logging to `~/Library/Logs/coord-audit.log`); this skill exposes the same check on demand.

Source of truth:

- Script: `${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/audit-hardening.sh`
- Companion sweep across projects (advisory, not gate): `${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/audit-projects-secrets.sh`

## Syntax

`/coord-audit [--secrets]`

- No flag: run the hardening audit only (fast; exits 0 if all checks pass, 1 if any fail).
- `--secrets`: also run the project-wide secrets sweep (advisory; always exits 0; flags world-readable .env files, credential-pattern files, and tracked files matching secret-keyword regex).

## Workflow

1. **Run the hardening audit.**
   - `bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/audit-hardening.sh"`
   - Capture exit code. The script prints PASS/FAIL/SKIP per check and a `N passed, M failed` summary line.

2. **If `--secrets` was passed, also run the sweep.**
   - `bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/audit-projects-secrets.sh"`
   - This is advisory — exits 0 even when findings exist. The user should triage each flagged file.

3. **Present output.**
   - Stream each script's output verbatim. Do not summarise individual checks; the script's own table is the answer.
   - If the hardening audit exits non-zero, lead the response with the FAIL lines, then show the full output.
   - If the secrets sweep is run, present its output AFTER the hardening audit so a FAIL is not buried under advisory noise.

4. **Cross-reference for context.**
   - Mention that the same hardening audit runs nightly (`launchctl list | grep com.coord.audit.daily`) and logs to `~/Library/Logs/coord-audit.log` so the user can spot drift between manual runs.
   - If any FAIL is in scope, point at the relevant project docs or memory for context (e.g. the project's `AGENTS.md`, or a relevant note under `~/.claude/projects/<project>/memory/`).

## Rules

- Never mutate any file from this skill. For chmod fixes or sandbox changes, the user makes the call explicitly.
- Truncate per-script output over 60 lines to the first 30 + last 30 lines with `[... N lines truncated ...]`.
- Report results plainly; do not fabricate check names. The script defines what is checked.
- If `audit-hardening.sh` is missing at the expected path, print that the CoordWright install needs to be re-run (`bash "${COORD_TOOLS:-$HOME/Projects/coord-wright}/install.sh"`) and stop.
