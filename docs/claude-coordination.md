# Claude Coordination

Claude-specific runtime details. The shared protocol (project-root commands, launchd env vars, cross-device sync, mobile policy, output noise reduction, review-round reasoning reduction, transient provider-limit detection, shared workflow infrastructure) lives in `coordination.md`. Task format, statuses, and read ladder live in `task-files.md`; frontmatter fields, shaping bar, routing, and lifecycle flows live in `task-files-reference.md`.

> **Read `coordination.md` and `task-files.md` first.** Read `task-files-reference.md` when authoring or transitioning a task. This file only covers what is unique to Claude's wrapper and runtime.

## Claude runtime policy

Claude coord rounds no longer rely on whatever default model the local Claude CLI happens to pick on one machine.

The wrapper resolves an explicit Claude model in this order:

1. architect round: `model_architect`, or reviewer round: `model_review`
2. coder rounds only: subtask `model_claude`
3. task-level `model_claude`
4. project-level `CLAUDE_MODEL`
5. shared coord default: `sonnet` (`claude-sonnet-5`)

Ordinary unattended review or design rounds stay on the shared Sonnet baseline unless a task or project opts into something cheaper (`haiku`) or stronger (`opus`).

Claude has no dedicated `--reasoning-effort` CLI flag, so the wrapper applies round-specific reasoning policy through a short prompt preamble:

- `low` -> explicitly keep extended thinking minimal
- `high` -> "think hard"
- `xhigh` -> `ultrathink`

Resolution order is `reasoning_effort_architect` or `reasoning_effort_review` for those rounds, then task-level `reasoning_effort`, then the project default. The pickup packet also includes `round_role` plus resolved model/reasoning source fields so the wrapper can log what it chose.

`CLAUDE_MODEL` is an optional plist-level override (e.g. `sonnet`, `haiku`, `opus`, or a full model ID). The worker consumes the resolved model from `coord pickup` and passes it as `--model <id>` to the Claude CLI. Task-level and role-specific frontmatter still take precedence.

## Claude flow

`/coord-check` accepts an optional mode argument: no arg or `one` runs a single round and stops; `all` loops through the queue (up to `COORD_CHECK_MAX_ROUNDS`, default 5) until pickup returns `skip` or `needs-brainstorming`; `<task-id>` resolves that id directly for one round. Wrapper-launched Claude rounds always run a single round; the mode arg is only relevant for interactive sessions.

1. Optionally run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" precheck` from the project root for a cheap "is there Claude work?" answer.
2. Resolve one `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" pickup --assigned=claude` packet, or start from the wrapper-resolved handoff packet when the trigger already provided it.
3. Use the embedded handoff packet or `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --handoff` as the default read path.
4. If that view is insufficient, escalate to `--compact`, then `show-signatures`, then targeted file or section reads. Use full `show` only when a specific missing detail still blocks the work.
5. Do the work in the project repo.
6. Write findings back with `update`.
7. Hand off to Codex with `--status=pending --assigned=codex`, or mark `done` when appropriate.

Each wrapper run executes only the currently assigned agent. Claude wrapper
runs must not invoke `/codex` internally. If an explicit `roles.architect`
round exists, Claude records the plan and hands off with `assigned: codex` so
the Codex wrapper records a separate `codex` token row. Do not add that role
for normal work; architecture usually happens before or during shaping.

## Task Architecture

When Claude creates or reshapes tasks, task architecture is the first job. Do not turn a broad user request into one broad runnable task by default; decompose it first, then create the smallest useful task chain.

- Create a brainstorm task when scope or acceptance is unclear instead of queueing a broad runnable task.
- Create multiple narrow tasks with `depends_on` when the work has distinct backend, worker, frontend, docs, operations, or final-verification outcomes.
- Split backend, worker, frontend, docs, and final verification work into separate subtasks or `depends_on` tasks when they are distinct outcomes.
- Keep each subtask to one major surface and one final outcome. A title that bundles "implement and document and verify" is usually too broad unless it proves one tiny change.
- Keep `scope` narrow enough for the next round. Prefer specific files or directories over broad roots once the target surface is known.
- Keep findings compact after discovery: changed files, verification result, blockers, and handoff notes. Avoid repeating large inventories in every round.
- Reserve `verify_commands` for the final acceptance gate. Put interim smoke checks in the active subtask body or the current round finding.
- If token telemetry shows high cache/input or repeated oversized effective context, finish the current narrow step and create a follow-on task with a compact handoff instead of continuing to extend the same task.
- Shaping warnings from `coord new` or `coord update --set-subtasks` are fatal for runnable tasks by default. Use `--brainstorm` for unclear work, and use `--shape-override=<reason>` only for a human-approved exception.
- Do not stop after creating `status: shaping` task files. A shaped task must be handoff-ready in `show --handoff`: actionable current focus, concrete Plan, concrete Acceptance test, parseable subtasks with model/complexity metadata, correct dependencies, and only intentional warnings.
- Add explicit `roles.reviewer` when independent review is required. Add
  explicit `roles.architect` only when a design handoff must run after
  queueing; the architect round must persist executable subtasks with
  `coord update --set-subtasks` before re-queueing the coder.
- High-risk migration, cutover, destructive cleanup, auth/security, money,
  trading, or live-operations tasks should be split into narrow dependent
  tasks and use explicit review. Use an architect role only when shaping cannot
  settle the design safely.

### Task creation: populate Plan before Codex polls

When creating a codex-first task with `coord new`, populate the **Plan** section before Codex's polling loop picks it up. If the task exists but Plan is empty when Codex polls, Codex will refuse to implement and bounce the task to Claude — the intended Codex-first flow is lost.

Safe approaches:
- Create the task with `--hold` (`pickup_hold: true`), fill Plan + subtasks + acceptance, then `coord release <id>`.
- Use inline `--set-plan=@file` / `--set-subtasks=@file` flags in the single `new` call.
- Batch the `new` and all `update` calls into a single shell invocation so Codex's poll interval cannot fall between them.

Claude-first tasks are not sensitive to this race — Claude won't start until `/coord-check` is explicitly invoked.

## Trigger flow

Claude no longer has a separate project trigger script or per-agent sentinel path. The normal path is the shared per-project launchd worker:

1. The project launchd job starts `worker/worker.sh <project>` at load and on each `StartInterval` tick. The shared template uses a 60 second interval.
2. The worker exits before pickup when `.coord/sleep-until` exists and still points to a future timestamp. When the timestamp has expired, it removes the marker and continues.
3. The worker synchronizes a clean checkout, then runs `python3 "$COORD_TOOLS/bin/coord" pickup --assigned=claude`. If no Claude-runnable task exists, the same tick tries `pickup --assigned=codex`.
4. A run starts only when pickup returns `decision=run`; the pickup packet is the authoritative task id, round role, resolved model, and resolved reasoning source.
5. Before launching Claude, the worker records `.coord/worker.state` and acquires the shared global semaphore through `worker/semaphore.sh`, so concurrent project ticks do not overrun the configured slot limit.
6. Claude is launched through `bin/agent-launch.sh claude` with `/coord-run <id>`. On success, the worker commits and pushes worktree changes as `coord: work <id>` before recording wrapper token usage on the task. When the task declares `scope:`/`scope_creates:` globs, only those paths plus `tasks/` and `.coord/` are staged; anything else dirty (for example a concurrent edit by another actor) is left uncommitted with an `out-of-scope changes left uncommitted` warning in `worker.log`. Tasks without scope keep the historical stage-everything behavior.

This polling model is the retry path for both normal queue progress and prior provider-limit sleeps. Cross-agent handoff is represented by task state written through `bin/coord`; the next launchd tick picks up whichever agent is currently assigned.

## Claude-side transient provider-limit handling

The shared concept and generic regex override are documented in `coordination.md`. Claude-specific override precedence:

- Claude-specific override: `CLAUDE_COORD_TRANSIENT_PROVIDER_LIMIT_REGEX`
- preferred generic override: `COORD_TRANSIENT_LIMIT_REGEX`

Precedence is Claude-specific override -> generic override -> built-in default.

When `worker/rate-limit.sh` matches a rate-limit signature in the Claude output artifact, it writes the parsed reset time to `.coord/sleep-until`. If Claude already marked the task `claude-working`, the worker restores the pre-pickup runnable status and assignee before exiting. Subsequent `worker/worker.sh` ticks short-circuit while that timestamp is in the future and delete the marker after it expires; normal pickup resumes on the next tick. The current wrapper does **not** escalate rate-limited Claude tasks to `needs-brainstorming` and does **not** write a per-task rate-limit flag — `.coord/sleep-until` is the only persistent rate-limit state.

## Output noise reduction (Claude-side)

The shared 20+20 truncation policy is documented in `coordination.md`. When Claude runs shell commands, build steps, or tests during an interactive session, apply the same 20+20 rule manually before pasting output into a finding. The `truncateOutput` helper in `coord` is the canonical implementation; this is the live-tool fallback for output that does not pass through `coord`.

## Micro-loop review inside a coord task: `/codex-loop`

Explicit role flow is available for shaped tasks that truly need separate design or review rounds across sessions. For hardening a single artifact *inside* one working session — a design memo, a migration plan, a recommendation doc, or any markdown the task will commit — use the `/codex-loop` Claude skill (`~/.claude/skills/codex-loop/SKILL.md`).

It is a bounded, file-anchored Claude↔Codex review subroutine with a mechanical `CONVERGED` sentinel and a round cap. It logs every Codex exec to the project-local `.coord/codex-runs/` directory (separate from the wrapper's own logs under `.coord/worker.log`) and never auto-commits, so the resulting transcript is reviewable diff that a reviewer round can later validate.

Use explicit role flow for the task itself when needed; use the micro loop to harden the artifacts the task produces. Do **not** invoke `/codex-loop` from any wrapper-managed coord round — Claude architect, Claude coder, or Claude reviewer alike — since the wrapper already manages Codex budget and turn ordering and a nested loop would recurse on both. `/codex-loop` is intended for an interactive Claude session that is not itself running under the coord wrapper.

## Recovery from agent failures

When an agent run fails (max-turns hit, rc!=0, syntax error in worker.sh edited mid-tick), the worker's "restore original status" logic must NOT blindly restore the pre-pickup status. An agent may complete its handoff (e.g. `coord update --status review-failed` which aliases to `pending + reassign-to-codex`) and then hit max-turns on the closing log message. Restoring `ORIG_STATUS=pending, ORIG_ASSIGNED=claude` would clobber the completed handoff.

Recipe:

1. After the agent failure, call `coord show --compact` to get `CURRENT_STATUS` / `CURRENT_ASSIGNED`.
2. If the current status is already a valid runnable state (`pending`, `needs-review`), preserve it.
3. Only fall back to the pre-pickup original if the current status is still an in-progress state (`claude-working`, `codex-working`).
4. Guard for `done` — if the agent reached done before rc!=0, exit clean without requeue.

## Worker "dirty tick" stalls

When a launchd coord worker logs `git sync skipped: worktree dirty before pickup` every minute, it has two distinct root causes that look identical from the log line alone.

**Cause 1 — `.gitignore` missing a coord runtime rule.** The worker writes `.coord/worker.lock` and `.coord/worker.state` before the dirty check (see `worker/worker.sh` step ordering). If `.gitignore` doesn't ignore `.coord/worker.state` (for example through `.coord/` or `.coord/*`), `worker.state` shows as untracked → worker exits as "dirty" → never picks up tasks. Diagnose with `git check-ignore -v .coord/worker.state`. Fix: add `.coord/` or re-run `~/Projects/coord-wright/install.sh` for a registered project.

**Cause 2 — `worker.sh` edited mid-tick.** If a separate coord task commits a new `worker/worker.sh` while another project's worker is mid-execution (codex/Claude tick can run 20+ min), the running bash re-reads the mutated file and bombs at runtime with `syntax error near unexpected token`. The crash exits before `commit_agent_changes`, so any agent code edits stay dirty. Critically, if the agent had already called `coord update --complete-subtask=Sn` before the crash, the task file is committed (advancing `current_subtask`) but the code edits aren't — task state and code desync. Recovery: `git add` the dirty files and `git commit -m "coord: recover S<n> ..."` — do NOT `git restore`, because the task file already says S<n> is done.

Diagnosis order: run `git check-ignore -v .coord/worker.state` first (cheap). If ignored properly, scan the log for `syntax error|tick failed|rc=` to find a crash. `tail -30 worker.log` not just the latest dirty line.

## Related docs

- `coordination.md` — shared protocol (read first)
- `task-files.md` — task contract: format, statuses, read ladder (authoritative, always loaded)
- `task-files-reference.md` — frontmatter fields, shaping bar, routing, lifecycle flows (on-demand)
- `codex-coordination.md` — Codex side
