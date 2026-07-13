# Codex Coordination

Codex-specific runtime details. The shared protocol (project-root commands, launchd env vars, cross-device sync, mobile policy, output noise reduction, review-round reasoning reduction, transient provider-limit detection, shared workflow infrastructure) lives in `coordination.md`. Task format, statuses, and read ladder live in `task-files.md`; frontmatter fields, shaping bar, routing, and lifecycle flows live in `task-files-reference.md`.

> **Read `coordination.md` and `task-files.md` first.** Read `task-files-reference.md` when authoring or transitioning a task. This file only covers what is unique to Codex's wrapper and runtime.

## Codex-specific project-root commands

Held batch release:

```bash
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" new --hold --status=pending --task="Fix narrow parser bug" --complexity=simple --kind=code-fix --reasoning-effort=medium --set-subtasks=@/tmp/subtasks.txt --set-plan=@/tmp/plan.txt --acceptance="Parser handles the failing case"
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" release <id>
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" release --all-held
```

Normal tasks are Codex-first and usually Codex-only. `--solo` and `--overnight` are compatibility aliases only: they may set Codex/tag defaults, but they do not bypass shaping, subtask metadata, Plan, acceptance, or verifier validation. For unattended batches, create tasks with `pickup_hold: true` (`coord new --hold` or `coord update --pickup-hold=true`), finish all metadata updates, then release them with one `coord release` command. Add explicit `roles.reviewer` for independent review, and add `roles.architect` only when a design handoff must run inside the wrapper after shaping. When the operator's request names a reviewer in prose ("claude as reviewer"), that MUST land as `--roles=reviewer:claude` at shape time — omitting `roles` silently means no review round.

When the wrapper has already resolved the active task and subtask, start from that handoff packet instead of rediscovering with pickup helpers. The startup packet already carries the bounded handoff text, active subtask, and execution policy.

## Pickup model

When no Codex-runnable task exists, `pickup --assigned=codex` returns `skip` and Codex is not launched. The canonical queued state is `pending` with `assigned=codex`. `precheck` remains available for watchdogs and manual cheap queue checks.

Tasks can also stay queued but unrunnable when they declare `depends_on` predecessors that are not complete yet. In that case `precheck` and `pickup` skip them until the dependency chain is satisfied.

Tasks with `pickup_hold: true` are also skipped by `precheck` and `pickup` until `coord release` validates and clears the hold.

## Codex flow

1. `launchd` starts the shared `worker/worker.sh`.
2. The wrapper resolves one `pickup --assigned=codex` packet before launching Codex. If pickup returns `skip`, the run exits cheaply without starting Codex.
3. Immediately before launching Claude or Codex, the wrapper re-reads the same task. If the content hash, status, assignee, hold flag, resolved model, resolved reasoning effort, or round role changed since pickup, it logs `stale-pickup` and exits 0 so the next launchd tick uses fresh metadata.
4. The pickup packet already includes the handoff text, next subtask, and the Codex execution policy for plan gating and the required `coord update` path. Codex follows the normal read ladder from there: `--compact`, then `show-signatures`, then targeted file reads, and full `show` only if still blocked. For `simple` tasks, the prompt biases Codex toward the target file before broader repo docs, and tells it not to open coordination skill docs unless the task is actually coordination work or the handoff is missing a specific policy detail.
5. Codex launches are pinned with explicit non-interactive startup flags (`-a never`, `-s danger-full-access`) instead of inheriting interactive defaults. If the project sets `CODEX_SERVICE_TIER=fast`, the wrapper launches `codex exec` with `service_tier="fast"` and enables the Codex `fast_mode` feature, matching CLI `/fast`. The wrapper also passes the pickup packet's resolved reasoning effort as `model_reasoning_effort`.
6. Codex edits files in the project repo.
7. While Codex is running, the wrapper publishes a small state file so the watchdog can tell the difference between healthy work, stale locks, and a wedged run.
8. Codex writes findings back through `coord update`, including any round-local smoke checks. Final `verify_commands` stay reserved for the end-of-task acceptance gate.
9. The wrapper commits the round, records runtime warnings such as `closed-stdin`, records a Codex token row or token warning,
   and triggers Claude's side.

Manual `/coord-check` Codex rounds run outside the launchd wrapper, so they
self-report tokens through `coord-tokens.sh --agent=codex` when
`COORD_WRAPPER_TOKENS` is unset; wrapper-launched rounds set that guard and keep
token capture in the worker. The `/coord-check all` mode arg collapses to a
single round on Codex because the `codex exec` process exits after each round;
queue multiple `/coord-check` invocations externally to drain the queue.

Each wrapper run executes only the currently assigned agent. Claude must not
run `/codex` internally for wrapper-managed tasks. Explicit Claude design or
review rounds hand off Codex implementation by setting `assigned: codex`, and
the Codex wrapper then runs Codex directly.

## Codex launchd overrides

In addition to the shared `COORD_*` env vars documented in `coordination.md`, the Codex launchd environment or project `.coord/config.env` may set:

- `CODEX_REASONING_EFFORT`
- `CODEX_MODEL`
- `CODEX_SERVICE_TIER=fast`

When both are set, task-level `model_codex` frontmatter overrides project-level `CODEX_MODEL` for that pickup. `model_codex` is passed straight to `codex exec --model`, so use the same model string your local Codex CLI already accepts in `CODEX_MODEL`. Prefer `gpt-5.6-sol`; do not use unsupported aliases such as `codex-latest` or `codex-mini-latest` (the Codex CLI rejects `codex-latest` under a ChatGPT account, and `codex-mini-latest` is a retired legacy alias). `coord` rejects both at write time.

`gpt-5.3-codex-spark` is available as an explicit low-risk override, but it is not a project default and not a fallback when `gpt-5.6-sol` is low. The validator only accepts Spark for fully shaped trivial/simple Codex-only tasks with small scope, low/medium reasoning, no architect/reviewer role flow, and concrete acceptance or verification. High-risk, complex, design/review, security, database, live-operations, destructive, or multi-surface work must stay on `gpt-5.6-sol` or another standard Codex model.

## Codex task architecture

When Codex creates or reshapes tasks, treat "create a task" as a design request. Decompose first, then create one narrow task or a chain of narrow tasks with `depends_on`.

- Prefer several small tasks chained with `depends_on` over one long-running task that spans backend, worker, frontend, docs, and final verification.
- Keep each subtask to one major surface and one concrete outcome. Split implementation, documentation, and final verification unless they all prove the same tiny change.
- Keep `scope` as narrow as the next round allows. Use specific files or focused directories once the implementation surface is known.
- Keep findings short after discovery: changed files, verification result, blockers, and handoff notes.
- If token telemetry shows high cache/input or repeated oversized effective context, finish the current narrow step and create a follow-on task from a compact handoff rather than growing the same task.
- Task-shaping warnings are fatal by default for runnable task creation and `update --set-subtasks` unless a human records `--shape-override=<reason>`. Use `--brainstorm` when the work is not narrow enough to queue.
- Do not stop after creating `status: shaping` task files. A shaped task must be handoff-ready in `show --handoff`.
- Do not add an architect role by default. Architecture and decomposition should happen before or during shaping, then be encoded as subtasks and `depends_on` chains.
- For explicit Codex architect rounds, persist a narrow executable subtask checklist with `coord update --set-subtasks` before handing off to the coder queue.
- For high-risk migration, cutover, destructive cleanup, auth/security, money, trading, or live-operations work, prefer narrow dependent tasks plus explicit review. Add `roles.architect` only when there is still a real in-loop design step after shaping.

## Review-round reasoning (Codex-side)

The shared concept lives in `coordination.md`. Codex-side wrapper specifics:

The pickup packet's `codex_execution_policy` is round-role aware. Normal coder and subtask rounds complete directly unless `roles.reviewer` is explicitly configured. Multi-subtask tasks mark the current subtask complete and stay `pending/assigned=codex`; the last subtask or non-subtask coder work completes through the existing terminal path. Explicit architect rounds expose `work_mode: architect` with a design-only scope and a success update that hands off to the configured `roles.coder` queue. Reviewer rounds expose `work_mode: reviewer`, skip the plan gate, and close the task on a successful review. Wrapper token logging follows the same contract: only `work_mode: subtask` runs attach `--subtask=S<n>` usage rows, while architect and reviewer rounds stay task-level even if pickup already knows the next coder subtask.

The wrapper logs `round_role`, resolved model source, and resolved reasoning source for each run, so review-only re-entries stay cheaper without rewriting task-level settings mid-flight.

## Codex diagnostics

When a Codex wrapper run exits non-zero for a non-rate-limit failure, the worker captures a redacted `codex doctor --json --summary` snapshot under `/tmp/coord-codex-doctor-*.json` and logs the path in `.coord/worker.log`. The watchdog captures the same snapshot before restarting a stale worker whose state file says the running agent was Codex. These snapshots are failure-only diagnostics; the worker does not run `codex doctor` on every tick.

## Codex-side transient provider-limit handling

The shared concept and generic regex override are documented in `coordination.md`. Codex-specific override precedence:

- Codex-specific override: `CODEX_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX`
- preferred generic override: `COORD_TRANSIENT_LIMIT_REGEX`

Precedence is Codex-specific override -> generic override -> built-in default.

When Codex hits a transient limit, the wrapper matches the Codex output artifact, restores any `codex-working` task to the pre-pickup runnable status and assignee, records a retry-after marker, and exits. The worker honors that marker and resumes normal pickup after the retry window expires.

## Prompt observability

Every Codex wrapper run logs a prompt-size summary to the debug log before launching `codex exec`. The summary includes per-section character/line counts plus a rough `chars / 4` token estimate for the wrapper boilerplate, handoff packet, next-subtask block, execution policy block, and AGENTS path reminder. This makes it possible to tell whether a "large input" round was already expensive before Codex opened any files.

For deeper debugging, set:

- `CODEX_COORD_DEBUG_PROMPT_MODE=full` to append the full rendered prompt to the debug log
- `CODEX_COORD_DEBUG_PROMPT_FILE=/tmp/some-path.txt` to preserve a copy of the rendered prompt on disk

## Context escalation visibility

The wrapper flags rounds where input tokens exceed the measured wrapper-prompt floor plus 3× a configurable baseline. When a round's input exceeds the threshold, the token log entry gets a trailing `:e` flag and the rate-flag column shows `<rate> esc` (e.g., `high esc`, `ok esc`).

The adjustable part is controlled by `CODEX_COORD_ESCALATION_INPUT_BASELINE` (default: `1500` tokens):

`estimated prompt tokens + (CODEX_COORD_ESCALATION_INPUT_BASELINE * 3)`

This keeps large injected handoff/policy prompts from tripping `esc` by themselves, while still marking rounds that grew well beyond the wrapper-provided startup context.

To raise the threshold for naturally large tasks, set `CODEX_COORD_ESCALATION_INPUT_BASELINE=<N>` in the project's `.coord/config.env` or the launchd plist EnvironmentVariables. The flag is informational — it does not stop or slow the round, only marks it for operator review.

## Sandbox: keep coord worker on `danger-full-access`

`worker/worker.sh` invokes codex with `--sandbox danger-full-access`. Do not switch to `--sandbox workspace-write` for the coord worker without first solving the `rm -rf` issue documented here.

Attempted 2026-05-16 (reverted same day, commit b2509e0): switched coord worker's codex invocation to `workspace-write`. Looked clean on paper — writes confined to project root, escalation still available via `-c sandbox_mode=danger-full-access`. In practice it broke a project's Playwright workflow:

```
ERROR codex_core::tools::router: error=exec_command failed for
`/bin/zsh -lc 'rm -rf test-results playwright-report && npm run test:e2e'`:
CreateProcess { message: "Rejected(...rejected: blocked by policy")"
```

Under `workspace-write`, codex has an internal command-policy layer (separate from the OS sandbox) that flags `rm -rf` as destructive regardless of target path. Even relative paths inside the workspace get rejected. The block fires at codex's tool router before reaching the OS sandbox. One project's `AGENTS.md` requires `rm -rf frontend/test-results frontend/playwright-report` before every Playwright run, so e2e tests literally cannot run end-to-end via coord under `workspace-write`.

A subsequent attempt to set `sandbox_mode = "workspace-write"` in `~/.codex/config.toml` (as a "safer manual default") also broke manual workflows: `.git/index.lock: Operation not permitted` (workspace-write protects `.git`) and DNS resolution failures (workspace-write blocks network egress). Both `~/.codex/config.toml` and `worker/worker.sh` remain on `danger-full-access`.

Defense-in-depth retained without the sandbox restriction:

- `chmod 400 ~/.codex/auth.json` blocks writes at the FS layer (with the documented `chmod 600 → login → chmod 400` recovery flow).
- `chmod 400` on `.env` files in projects that need it.
- Claude PreToolUse Edit/Write hook blocks the Claude side from the symmetric class of writes.
- `bin/audit-hardening.sh` records and verifies the trade-off; mention any FAIL in security reviews.

Future workspace-write retry candidates (none verified yet): (a) per-task sandbox override read from task frontmatter; (b) codex `--ask-for-approval` modes paired with a non-interactive auto-approve script; (c) replacing `rm -rf` with codex's native file-deletion tools in AGENTS.md cleanup steps.

The codex execpolicy `~/.codex/rules/default.rules` allow-list (see commit 5d9cb0c context) is a partial workaround for specific `rm -rf` shapes; widening it to cover every Playwright/Frontend cleanup permutation is not a substitute for the sandbox decision.

## Related docs

- `coordination.md` — shared protocol (read first)
- `task-files.md` — task contract: format, statuses, read ladder (authoritative, always loaded)
- `task-files-reference.md` — frontmatter fields, shaping bar, routing, lifecycle flows (on-demand)
- `claude-coordination.md` — Claude side
