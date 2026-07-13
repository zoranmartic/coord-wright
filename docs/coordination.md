# Coord — Shared Protocol

Shared concepts used by both Claude and Codex coordination loops. Tool-specific runtime details (trigger wrappers, pickup specifics, flow) live in `claude-coordination.md` and `codex-coordination.md`. Task format, statuses, and read ladder live in `task-files.md`; frontmatter fields, shaping bar, routing, and lifecycle flows live in `task-files-reference.md`. Cross-agent workflow policy (loop bias mitigation, YAGNI/KISS, decomposition preferences, subtask handoff convention) lives in `agent-workflow-policy.md`.

> When working on coord: read this file, then the tool-specific file for your runtime, then `task-files.md` for the task contract. Read `task-files-reference.md` when authoring or transitioning a task. Read `agent-workflow-policy.md` for YAGNI / loop-bias / handoff rules that apply to every task. The docs are authoritative — do not rely on remembered defaults.

## What coord owns

The shared `coord/` repo owns:

- the shared coordination CLI: `coord`
- shared worker scripts: `worker/worker.sh`, `worker/watchdog.sh`, `worker/rate-limit.sh`, `worker/semaphore.sh`
- shared helpers: `coord-tokens.sh`
- shared docs under `docs/`

Each project repo contributes only:

- `.coord/config.env`
- `tasks/`
- project-specific launchd plists under `tools/`

Task storage paths are configurable through `.coord/config.env` or the environment:

- `COORD_TASKS_DIR` (default `tasks`)
- `COORD_ARCHIVE_DIR` (default `tasks/archive`)
- `COORD_FINDINGS_DIR` (default `tasks/findings`)
- `COORD_CHANGES_FILE` (default `tasks/CHANGES.md`)

Use `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" paths --json` from a project root to inspect the resolved paths. The CLI can still read legacy `tasks/coord` during migration, but new writes use the configured paths.

## Running from a project root

The shared CLI auto-loads `.coord/config.env` from `process.cwd()` when `COORD_*` env vars are not already set. Common commands from any project root:

```bash
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" precheck [--assigned=claude|codex]
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" pickup --assigned=claude|codex
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --handoff
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --compact
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show-signatures <id>
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> ...
```

Tool-specific commands appear in the tool-specific docs.

When a wrapper has already resolved the active task and handoff packet, start from that packet instead of rediscovering with queue helpers.

### Smoke-testing `coord new` and other coord-creating subcommands

`coord new`, `coord promote`, and most `coord update` paths auto-commit and auto-push the task file (`commit_and_push(path, ...)` in `bin/coord`). Smoke-testing them inside `~/Projects/coord-wright` lands the smoke task on the CoordWright repo's `origin/main` before you can intercept it.

Recipes:

- Pytest: `tempfile.TemporaryDirectory()` → `git init` → `(root/"tasks").mkdir()` → run coord with `cwd=root` (see `tests/test_coord_complexity_baseline.py` and `tests/test_coord_subtask_lifecycle.py`).
- Ad-hoc CLI: `export COORD_TASKS_DIR=$(mktemp -d)/tasks; mkdir -p "$COORD_TASKS_DIR"` before invoking, or `cd` into a throwaway repo first.

The auto-push is intentional for real coord work — it's the queue's distribution mechanism — but it makes the CoordWright checkout itself a hazardous scratch space.

## Unattended-autonomy acknowledgement

Unattended worker and watchdog rounds require the exact environment value `COORD_UNSAFE_AUTONOMOUS=1` (README "Blast radius"). Without it, installed workers and the watchdog exit idle at entry — every interactive flow in this document (shaping, promoting, status, foreground `/coord-run`, reviews from your own sessions) works regardless. `install.sh` writes the key into generated worker plists when set at install time; `/coord-unblocker` does the same for the watchdog plist; per-project `.coord/config.env` reaches the worker only.

## Agent workspaces and sibling worktrees

Projects in `projects.txt` use a single main checkout — the canonical coord queue checkout, because the launchd worker reads and writes it. There are no persistent `-task-a`/`-task-b` worktrees; isolated manual work that would otherwise dirty the worker-polled main checkout uses an on-demand session worktree off `origin/main`, removed when idle: `git fetch origin main && git worktree add -b task/session-<slug> ../<project>-session-<slug> origin/main`. `install.sh` updates the workspace file and per-checkout settings when they already exist, but does not create them.

Tracked `<project>-agents.code-workspace` files must use absolute paths for the
main checkout and sibling task worktrees. The same workspace file is copied
through Git into every worktree branch, so relative paths can point at the wrong
checkout after a rebase or merge.

Coord skills follow this global policy:

- `coord-shape`, `coord-status`, `coord-tokens`, and coord admin
  skills resolve the canonical main checkout before running `coord` or `git`
  operations. This keeps task creation, queue inspection, and queue
  administration pointed at the launchd-owned queue even when the skill is
  invoked from a sibling task worktree.
- `coord-check` is main-checkout only. It must refuse to run from a sibling
  task worktree instead of silently changing directory, because pickup marks
  tasks working and may lead to code edits. Use the launchd worker or a
  main-checkout session for active coord pickup.
- Manual task worktree sessions are for code work and review. They must not run
  separate coord workers.
- Before manual code or docs edits, agents must confirm `pwd` and
  `git branch --show-current`. If they are on the canonical main checkout for
  non-coord implementation, they must stop and create (or reuse) an on-demand
  session worktree off `origin/main` rather than dirtying main. A freshly
  created session worktree is current by construction; if reusing one that is
  behind `origin/main`, rebase before starting unless local changes would be at
  risk.
- Non-coord skills that explicitly operate on the current repo, such as
  `commit-and-push`, keep their current-repo/current-branch semantics. From a
  task worktree, they commit and push that task branch.

Default work routing:

- Codex owns normal implementation work by default.
- Use `depends_on` task chains to scale work across surfaces or phases.
- Claude review, Claude implementation, or an in-loop architect round must be
  explicit through `--assigned` or `roles`; architecture normally happens
  before or during task shaping.

Degraded mode:

- If one agent in a slot is unavailable for one or two days, the surviving agent
  may take both roles.
- Keep commits smaller in degraded mode: one logical change per commit.
- Do not merge the branch until the recovered agent or the human operator
  reviews the accumulated diff.

Runtime isolation:

- Parallel-safe across slots: type checks, frontend lint/build/unit targets, and
  fixture/unit tests that do not touch shared services.
- Serialized until per-slot ports and databases exist: E2E runs, dev servers,
  database migrations, tests that mutate shared databases, worker loops, and
  live external-service flows.

Main checkout synchronization:

- Before pickup, the launchd worker fast-forwards a clean canonical checkout to
  its upstream branch. If main is dirty or cannot fast-forward, the worker exits
  without starting an agent.
- After committing agent work, the worker fetches and rebases its new commit on
  the upstream branch before pushing. This lets session-worktree merges and other
  out-of-band pushes advance `origin/main` while the worker is running; real
  rebase conflicts still stop the worker for human recovery.

Break-glass recovery:

- Normal mode: task worktrees do not mutate coord task state; the main checkout
  and launchd worker own queue transitions.
- If coord is broken, stop the project worker with
  `launchctl bootout gui/$(id -u)/<project-worker-label>` or mark the affected
  task blocked from the main checkout, nominate exactly one worktree as recovery
  owner, finish and verify the code change there, push the branch for review,
  then restart the worker with
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<project-worker-label>.plist`
  when it is safe to resume.

Shared helper:

```bash
"${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root"
```

The helper resolves the canonical main checkout from `.coord/config.env`
(`COORD_REPO_ROOT`) when present, otherwise from `git worktree list --porcelain`
by selecting the `main` worktree. Skills should fail closed if this is
ambiguous.

## VS Code rendering settings

VS Code's WebGL/canvas terminal renderer can produce blurred text and
mis-aligned glyphs on retina displays, especially in Codex CLI and Claude
Code CLI terminal panes that re-render high-frequency status output. The
fix is two user-level settings — apply once per machine, not per-project,
so every VS Code window (workspace files, folder-only opens, and any new
project) inherits the correct rendering path.

```jsonc
// ~/Library/Application Support/Code/User/settings.json   (macOS)
// %APPDATA%/Code/User/settings.json                       (Windows)
// ~/.config/Code/User/settings.json                       (Linux)
{
  "terminal.integrated.gpuAcceleration": "off",
  "terminal.integrated.customGlyphs": false
}
```

Effect: terminal text is drawn via DOM instead of WebGL; box-drawing
glyphs come from the monospace font instead of VS Code's custom glyphs.
Slightly higher CPU on heavy scroll; imperceptible on M-series Macs.
Reversible by removing either key. No effect on shell processes, file
I/O, network, builds, or tests — only on how the terminal pixels are
drawn.

**One-shot install** for any new machine:

```bash
node -e '
  const fs = require("node:fs"), path = require("node:path"), os = require("node:os");
  const p = path.join(os.homedir(),
    "Library/Application Support/Code/User/settings.json");
  const j = JSON.parse(fs.readFileSync(p, "utf8"));
  j["terminal.integrated.gpuAcceleration"] = "off";
  j["terminal.integrated.customGlyphs"] = false;
  fs.writeFileSync(p, JSON.stringify(j, null, 4) + "\n");
'
```

Per-project workspace files (`<project>-agents.code-workspace`) MAY also
set these keys as belt-and-suspenders fallback, but the user-level
settings are the canonical source. New projects added to the rotation
inherit the fix automatically with no per-project work.

If terminal blur persists after this fix, the stronger Electron-level
fallback is `"disable-hardware-acceleration": true` in user settings,
which disables editor GPU acceleration as well — only use if the
terminal-only fix does not resolve.

## Launchd mode

When a wrapper is launched by `launchd`, the project plist provides the project
path and the worker loads `.coord/config.env` from that checkout without
executing it as shell code. That file usually provides:

- `COORD_PROJECT_LABEL`
- `COORD_REPO_ROOT`
- `COORD_PROJ_DIR`
- `COORD_TOOLS`

Environment variables already present in the launchd environment win over
values from `.coord/config.env`. Tool-specific overrides (`CLAUDE_MODEL`,
`CODEX_MODEL`, `CODEX_SERVICE_TIER`, reasoning effort overrides, model
validator details) live in the tool-specific files.

## Mobile session policy

Mobile sandboxes (the Claude or Codex phone apps) have no git remote configured — `git push` will fail. They are **review-only**.

- Do not commit or push from phone sessions.
- Do not ask phone Codex to make code changes. It spins up a sandbox, edits files, then cannot push — work is lost when the session ends, burning quota for zero result.
- On the phone, use **Claude** instead — for review/analysis (it runs server-side and can read the repo), or to shape a coord task (`/coord-shape <description>`); the Mac's Codex launchd loop will apply the change.

Optimal session split:

| iPhone Claude (web)        | MacBook (automated)                     |
|----------------------------|------------------------------------------|
| Discuss, plan, design      | Codex launchd applies changes & pushes   |
| Create coord tasks         | Claude launchd reviews & pushes          |
| Check status, decide       | Fresh sessions, low token cost           |

iPhone Claude sessions accumulate conversation history (50–100K+ tokens). MacBook trigger sessions start fresh at ~6–10K tokens. Use iPhone Claude to think and decide; let the MacBook execute.

## Output noise reduction

Verbose command output is bounded before reaching either agent through `coord`'s shared `truncateOutput()`:

- `verify_commands` failure output is truncated to the first 20 + last 20 lines with a `[... N lines truncated ...]` marker before the validation error is raised.
- Handoff `Rules`, `Claude latest`, `Codex latest`, `Open issues`, and `Lessons learned` sections are capped before being embedded in pickup packets or `show --handoff` output.

The same 20+20 policy applies manually when an agent runs shell commands or tests during a session (output exceeding 40 lines should be truncated to first 20 + last 20 before pasting into a finding). This is the fallback for live tool output that does not pass through `coord`.

## Review-round reasoning reduction

Reviewer rounds re-read accumulated task context but perform less new reasoning. The pickup packet's resolved reasoning depth is preferred over blindly reusing task-level `reasoning_effort`:

- reviewer rounds prefer `reasoning_effort_review`
- architect rounds prefer `reasoning_effort_architect`
- other rounds fall back to task-level `reasoning_effort`, then the project default

A `high` reasoning round on a large accumulated context consumes the same input tokens as `low`, but `low` generates shorter output and completes faster — typically 20–40% cheaper for review-only work. Wrapper-side mechanics (round-role detection, `work_mode`, model logging) live in the tool-specific files.

## Transient provider-limit detection

When either agent hits a temporary provider limit, the wrapper classifies the agent output artifact, records a retry-after marker, restores any `*-working` task back to its runnable pre-pickup state, and exits without escalating to `needs-brainstorming`. The next trigger after the window expires resumes normally.

Detection is regex-based and extensible per project. Preferred generic override:

```bash
COORD_TRANSIENT_LIMIT_REGEX='hit your limit|provider quota exhausted for now'
```

Set in the project's `.coord/config.env` to apply to both interactive runs and the launchd wrapper. Setting any override variable to the empty string does **not** disable detection — the shell treats empty as unset and falls through to the built-in default. Tool-specific override variables (`CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX`, `CODEX_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX`) and tool-specific behaviour are documented in the tool files.

## Shared workflow infrastructure

Every project using coord has these files. Treat them as shared workflow infrastructure — do not break them casually:

- `.coord/config.env` — project identification, model defaults, regex overrides
- `.vscode/tasks.json` — coord helper tasks (where present)
- `tools/*.plist` — project-specific launchd plists

These are intentionally machine-local on single-user setups. Template them before sharing the repo or using a second machine.

## Task routing

Coord tasks default to Codex. Plain `coord new` creates a Codex-assigned
shaping draft, and runnable tasks stay Codex-owned unless the creator supplies
`--assigned`, `--agents`, `roles.reviewer`, or `roles.architect`.

Use `depends_on` task chains as the main scale-out mechanism. Add
`roles.reviewer` for explicit independent review. Add `roles.architect` only
when a design handoff must run after shaping; do not use an architect role for
normal decomposition work.

## Operational Diagnostics

### Shaping bar
`coord show <id> --handoff` is the real shaping bar. A task remaining in `status: shaping` is not meaningful unless the handoff packet is actually executable. Use `show --handoff` (not `precheck`) to review shaping tasks.

### Stall triage
- Check `<project>/.coord/worker.state` when a coord run looks quiet — it shows the active phase, task id, agent, and update time while the worker is running.
- `exceeded max run age` plus advancing rounds usually means a looping task under watchdog restarts, not a dead runner. Reroute the looping task rather than waiting.

### Archive failure
`archived 0/1` from `archive-done` means `archiveTask()` found a duplicate active task that collided with the already-archived file. The trigger retries every 180 seconds until the duplicate is removed.

### Launchd diagnostics
`launchctl print gui/$(id -u)/<label>` is the canonical launchd diagnostic — pair it with a live check (`lsof`, `ps`, `jps -l`, or logs) to confirm the service state.

### Shell environment caveats
- Do not trust inherited `XPC_SERVICE_NAME` as a coord service-label fallback in VS Code terminals.
- `$CODEX_HOME` may be unset in some shells; do not assume it resolves under `$HOME/.codex` without checking.

### Token attribution
When reporting token usage, `effective` is an API-parity proxy weighted per provider's published rate card (since neither Anthropic Max nor OpenAI Codex Pro documents the exact subscription-gauge formula):

- **Claude** (Anthropic API discounts as of 2026-05, uniform across Haiku/Sonnet/Opus):
  `effective = input + 5*output + cache_read/10 + cache_create*5/4`
  (output 5×, cache_read 0.1×, cache_create 1.25×)
- **Codex** (OpenAI GPT-5.5 rate card as of 2026-05):
  `effective = input + 6*output + cache_read/10`
  (output 6×, cache_read 0.1×; cache_create not reported by Codex)
  Sources: https://help.openai.com/en/articles/20001106-codex-rate-card and https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan.pdf

Prior versions used `effective = input + output` (cache excluded, output unweighted), which under-reported real burn on cache-heavy or output-heavy sessions by 1.4-50×. Token_log entries written before the 2026-05-24 cutover still hold their old-formula `effective` values; cross-boundary comparisons are meaningless. Show cache reads separately; cached input is discounted but not free. Missing or suspicious telemetry is warn-only by default and can be audited with `coord token-audit --include-archive`.

### Round token budget

On the worker success path — after the round's agent work is committed and the per-round `effective` value (see [Token attribution](#token-attribution)) is recorded — the worker compares that round's effective spend against three thresholds and reacts by band:

- under warn — proceed unchanged.
- at or above warn — log it, append a `round_token_warn` issue, and continue.
- at or above escalate or halt — flip the task to `needs-brainstorming` with a `round_token_escalate`/`round_token_halt` issue and **no auto-requeue**, so a human reroutes it instead of the loop burning another round.

Thresholds resolve from `.coord/config.env` (or the environment) and fall back to built-in defaults:

```bash
COORD_ROUND_TOKEN_WARN=1000000      # default 1M — log + record issue, continue
COORD_ROUND_TOKEN_ESCALATE=2000000  # default 2M — needs-brainstorming, no auto-requeue
COORD_ROUND_TOKEN_HALT=4000000      # default 4M — needs-brainstorming, no auto-requeue
```

A value that is not a positive integer falls back to its default. This is a **round-boundary** circuit-breaker: it gates the next round, it does not abort an in-flight one — the wall-clock `ROUND_TIMEOUT_SECONDS` remains the only mid-round kill. The failure and timeout paths are unaffected; the gate runs on the success path only.

## Related docs

- `task-files.md` — task contract: format, statuses, read ladder (authoritative, always loaded)
- `task-files-reference.md` — frontmatter fields, shaping bar, routing, lifecycle flows (on-demand)
- `claude-coordination.md` — Claude runtime, trigger wrapper, flow specifics
- `codex-coordination.md` — Codex pickup model, wrapper, observability
- `architecture.md` — repo layout, plist injection, project discovery
