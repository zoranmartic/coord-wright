# Coordination Task Files — Reference

Authoring and shaping reference for `task-files.md`. Read this when creating, shaping, or transitioning a task. Always-loaded contract (format, statuses, read ladder) lives in [task-files.md](task-files.md).

## Creation defaults by task shape

Use this as the practical creation template rather than inventing ad hoc task
shapes:

- Runnable Codex-first task:
  - write explicit `complexity`, `kind`, and `reasoning_effort`
  - omit `roles` unless the task deliberately needs explicit review or an
    exceptional architect handoff
  - fill `acceptance`
  - add a short `Plan`
  - put executable subtasks under `## Scope notes`
  - keep `verify_commands` narrow and final
- Held batch task:
  - create with `coord new --hold --status=pending` after supplying the same
    strict shape as any runnable task, or create a held draft and finish it
    with `coord update` before release
  - `precheck` and `pickup` skip `pickup_hold: true`
  - release with `coord release <id>` or `coord release --all-held`; release
    validates every selected task first, then clears the hold and writes one
    commit/push
- Compatibility aliases:
  - `--solo` and `--overnight` are temporary aliases only
  - they may set Codex/tag defaults, but they do not skip shaping,
    subtask metadata, Plan, acceptance, verifier, or release validation
- Brainstorm task:
  - create with `--brainstorm` (exempts the subtask requirement and seeds a
    placeholder Plan); it still lands in `shaping` unless you also pass
    `--status=needs-brainstorming`
  - resolve ambiguity before writing a runnable `Plan`
- Codex-default task:
  - `Plan` is seeded with the same placeholder as every task and must be
    replaced before promote (`[n/a — codex-only task]` also counts as a placeholder)
  - Codex completes directly unless `roles.reviewer` is explicitly configured
- Claude-only task:
  - keep the same overall body shape, but Codex findings are skipped

If you are creating tasks through the repo-local skill, follow the same shape:
create the task with `--set-subtasks=@...` already supplied (required before a
task enters any runnable queue; brainstorm drafts remain off-queue), then use
`coord update --set-plan=...` and
`coord update --set-acceptance-test=...` to fill the remaining body
deliberately.

`coord new --tags=...` preserves supplied tags alongside the default
`coordination` tag and the compatibility `overnight` tag when applicable, with
duplicates removed. `coord update --tags=...` replaces the complete tag list;
include `coordination` explicitly when it should remain.

Task-shape checks are strict: any runnable `coord new` or
`coord update --set-subtasks` whose shape validation fails is rejected. Use
`--brainstorm` to capture unclear work off-queue; there is no bypass flag.

**Subtasks are mandatory before a task enters a runnable queue.** Plain `coord new` defaults to `status: shaping`, so it may create an off-queue draft without `--set-subtasks`. Runnable creation with `--status=pending` or `--status=needs-review` requires `--set-subtasks=<str>` unless the task is still held with `pickup_hold: true`. Promotion from `shaping` or `needs-brainstorming`, hold release, and hold clearing all validate that the task has at least one parseable subtask carrying `complexity`, `model_claude`, and `model_codex` metadata, plus task-level `complexity`, `kind`, `reasoning_effort`, a concrete `Plan`, and acceptance or verifier intent. `--solo` and `--overnight` do not bypass runnable subtask validation.

**Verifier profiles are explicit finish-line metadata.** `verify_profile` accepts `html5`, `pptx-html`, or `lab-brief`. The worker captures PPTX text baselines before a `pptx-html` round under ignored `.coord/artifact-baselines/`, then runs `coord-verify-artifacts` after the agent exits. HTML validation uses Nu Html Checker `vnu` (not auto-installed: `html5` fails with install advice when it is missing, `lab-brief` skips the HTML check); Apple `/usr/bin/tidy` is not accepted for HTML5. Verifier failures route to `needs-review` when `roles.reviewer` is set, otherwise to `needs-brainstorming`. Tasks that modify `.pptx`, `.docx`, or `.xlsx` artifacts must use `verify_profile: pptx-html` and an explicit reviewer unless they are read-only review tasks.

**Token usage should be recorded for every wrapper-managed round.** Token telemetry is informational and non-blocking by default: wrappers log warnings for missing or suspicious usage, update `token_warnings` when possible, and keep task throughput moving. `coord token-audit --include-archive` reports incomplete telemetry for active and archived tasks. Do not backfill historical rows with guessed counts.

`completed` is written when a task transitions to `done`. When a task has token data, the rendered `## Token usage` section shows per-round rows and warning lines. `effective` is an API-parity proxy weighted per provider's published rate card — Claude: `input + 5*output + cache_read/10 + cache_create*5/4`; Codex GPT-5.5: `input + 6*output + cache_read/10`. See coordination.md § "Token attribution" for full formula text and rationale. Cache reads are tracked separately AND counted toward `effective` at the documented discount rate (0.1× for both providers). Suspicious rows include missing usage blobs, all-zero rows, cache-only rows, and `output=0` when agent-visible work was produced. Wrapper-managed Codex rounds should produce a `codex` token row only when the Codex wrapper actually ran; a missing Codex row usually means Claude handed work to Codex internally or telemetry failed.

Completed subtasks keep their checkbox entry in `## Scope notes`; `--complete-subtask` only flips `[ ]` to `[x]` (no completion stamp).

Existing tasks can be reshaped through `coord update`, including `--depends_on=...`, `--review_rounds_max=<n>`, `--complexity=<trivial|simple|complex|xhigh>` (validated; the baseline check runs against the new complexity together with any model/effort flags in the same call, e.g. `--complexity=simple --model_claude=sonnet`), and `--max_turns=<n>` when a queued task needs a larger per-round CLI-turn budget. The worker enforces a floor of 60 turns, so the task value only raises that budget; a round that hits it is handled by the worker's max-turns path (see `max_turns`), not by `coord update`. The runnable content hash now reflects execution-shaping frontmatter and current dependency blockers, so queue-shape changes and dependency unblocks are treated as fresh work instead of being suppressed as "unchanged."

## Role-specific execution overrides

These frontmatter fields are additive. Older task files that omit them continue
to work unchanged.

- `model_architect`: optional Claude-only model override for the architect round. Priority chain for Claude architect pickups is `model_architect` -> `model_claude` -> project `CLAUDE_MODEL` -> shared `sonnet` baseline.
- `model_review`: optional Claude-only model override for the reviewer round. Priority chain for Claude reviewer pickups is `model_review` -> `model_claude` -> project `CLAUDE_MODEL` -> shared `sonnet` baseline.
- `reasoning_effort_architect`: optional architect-round reasoning override. Priority chain is `reasoning_effort_architect` -> `reasoning_effort` -> project default.
- `reasoning_effort_review`: optional reviewer-round reasoning override. Priority chain is `reasoning_effort_review` -> `reasoning_effort` -> project default.

`coord pickup` exposes a small task summary (id, status, assigned, task,
pickup_hold, verify_profile, handoff) and the resolved
round-specific execution fields (`round_role`, `resolved_model_*`,
`resolved_reasoning_effort`, and their `_source` companions) so wrappers can
launch the right model/depth without reproducing queue logic.
For Codex pickups, the paired `codex_execution_policy` mirrors the resolved
round role. Normal coder/subtask rounds complete directly: multi-subtask work
marks the current subtask complete and stays `pending/assigned=codex`; the last
subtask or non-subtask coder work completes through `review-passed` (no `--force`).
Only tasks with explicit `roles.reviewer` enter `needs-review`. Explicit
architect rounds still emit `work_mode: architect` and hand off to
`roles.coder`, but that role is an opt-in escape hatch rather than a normal
task-shaping step. Reviewer rounds emit `work_mode: reviewer`, skip the plan
gate, and close the task on successful review.

There are intentionally no `model_codex_architect` or `model_codex_review`
fields today. Codex uses a single model chain for every round: subtask
`model_codex` (coder rounds) -> task `model_codex` -> project `CODEX_MODEL` ->
CLI default. Role-specific Codex tuning is handled through
`reasoning_effort_architect` and `reasoning_effort_review` instead of widening
unattended wrapper model selection.

The handoff render used by `show --handoff` and the pickup payload's
`task.handoff` is a short header only: id, task, status/assigned/round, queue
and execution timing, `acceptance`, `verify_commands`, `verify_profile`, and
`scope_budget`. It does not include Plan, subtasks, findings, issues, or
lessons; read those with `show <id> --compact` (frontmatter plus the first 50
body lines), `coord next-subtask <id>`, or full `show <id>`.

`coord new` writes a static `## Task parameters` section containing
`_See frontmatter above._`; it is never updated. The frontmatter is the source
of truth.

## Task shaping and granularity

These rules apply when Claude or Codex creates a new coord task or rewrites the `### Subtasks` block for an existing one.

Task creation is an architecture step. An agent asked to "create a task" should first decompose the request, decide whether it is one task or a chain of dependent tasks, and only then write runnable task files. The default should be a small task chain when the work spans multiple outcomes, surfaces, or verification paths. If the decomposition is still unclear, create a `--brainstorm` task and keep it off the runnable queue until the ambiguity is resolved.

**Interview the user before shaping non-trivial tasks.** Before calling `coord new` for any task that is not a clearly trivial code-fix, drive a short structured interview to surface the main outcome, the final verification path, the 2–5 subtasks (each one major surface), dependencies on existing active tasks, whether explicit review or Claude routing is needed, `complexity`, and `kind`. This avoids broad runnable tasks and `[no scoped focus yet]` shaping stubs that the next agent has to repair.

- **Claude** should invoke the `grill-me` skill (or the project-local `coord-shape` skill, which wraps `grill-me` plus this shaping flow). Do not skip when the user says "just create it" if the scope is not crisp; instead ask one round of grilling and proceed.
- **Codex** should ask the user 3–5 targeted clarifying questions covering the same fields before calling `coord new`. Do not invent answers from context alone for non-trivial work.
- Skip the interview only for trivial code-fix/docs/smoke-test tasks where the user's request already maps cleanly to a single subtask and verification. Even these trivial tasks must still supply `--set-subtasks` to `coord new`.

Shaping is not complete when the Markdown file merely exists. A `status:
shaping` task is handoff-ready only when the next agent can start from
`coord show <id>` without rediscovering intent, boundaries, or the finish
line. The mechanical bar is `coord promote` validation
(`validate_runnable_shape`) plus the `coord-review` skill; `show --handoff`
does not render the Plan or subtasks. Before promoting or leaving shaped tasks
for another agent, ensure the task has:

- a concrete `## Plan` that states what to change and what not to change;
- a concrete `## Acceptance test` with the final command or observable end
  state;
- parseable subtasks persisted with `coord update --set-subtasks=@...`,
  using `- [ ] **S1: Title**` plus `complexity`, `model_claude`, and
  `model_codex` metadata lines;
- dependencies for serialized follow-on work and shared-scope handoffs;
- only intentional shaping warnings left unresolved.

Use `coord update --set-plan=...`, `--set-acceptance-test=...`,
`--set-subtasks=@...`, and `--depends_on=...` to finish shaping. Do not edit
task files directly. Preserve `status: shaping` while improving task metadata
unless the user explicitly asks to queue, start, or complete the task.

`coord new` and `coord update --set-subtasks=...` emit shaping warnings when they detect broad scopes, too many acceptance items, high-risk work that skips architect/reviewer-grade metadata, or subtasks that mix multiple surfaces such as backend + docs + verification in one step. Those warnings are fatal for runnable tasks unless the task is kept off-queue with `--brainstorm`. Treat any warning as a prompt to split the task or raise the task architecture before another expensive round.

Task creation checklist for new runnable work:

1. Decompose first: list the distinct outcomes, affected surfaces, dependencies, and final gates.
2. Decide whether the work is actually executable. If scope, acceptance, ownership, or task split is still fuzzy, create it with `--brainstorm` instead of queueing a guess.
3. Prefer multiple narrow tasks with `depends_on` when the decomposition has independent backend, worker, frontend, docs, operations, or final-verification outcomes.
4. When creating several related tasks in one batch (for example, the user asks for "a set of review tasks" or "design tasks for X, Y, Z"), explicitly think about dependencies between the new tasks before queueing them flat. Ask: does any task synthesise the others (it should `depends_on` the contributors so it runs after, not in parallel)? Does any task need a recommendation, interface, or artefact produced by another (the consumer should `depends_on` the producer)? Sibling tasks that genuinely cover independent surfaces stay independent. Wiring the dependency graph at creation time avoids re-doing work or contradicting outputs across parallel runs.
5. Set `complexity` explicitly. Use `simple` for normal implementation work. Use `complex` only to signal high ambiguity or risk; it does not imply an architect role by itself.
6. Set `kind` explicitly so the initial assignee is intentional.
7. Set `reasoning_effort` explicitly for any task that is not trivial. Do not rely on the project default to communicate intended depth.
8. Add `roles.reviewer` only when independent review is required. Add `roles.architect` only for an exceptional in-loop design handoff; normal architecture happens before or during shaping.
9. Keep `acceptance` concrete and keep `verify_commands` narrow enough to represent one final gate rather than a whole test plan.

For high-risk migration, database cutover, destructive cleanup, auth/security, money, trading, live-operations, or serious RCA work, prefer a shaped `depends_on` task chain plus explicit review. Add `roles.architect` only when the design step must run as its own wrapper-managed round after queueing. If that feels too large for one task, split the work into dependent tasks before queueing implementation.

Most decomposition belongs before queueing, in the human discussion or
`coord-shape`. If the design is still too unclear after shaping, create a
separate design/analysis task or keep the task in `needs-brainstorming` rather
than adding an architect round by default. Use `model_architect` and
`reasoning_effort_architect` only for explicit `roles.architect` tasks.

**Canonical decomposition rules** (one source of truth): `agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rules 4 (one task vs chain) and 6 (subtask sizing + handoff convention + natural boundaries). Do not restate those rules here; the bullets below are the *task-files-specific* corollaries that don't fit in the policy doc.

- Keep task `scope` narrow. Prefer the specific files or directories needed for the next round over broad roots such as an entire backend plus worker plus frontend tree.
- Keep findings compact after the discovery round: changed files, verification result, blockers, and handoff notes. Long inventories become repeated cached context in later rounds.
- Use round-local smoke checks in subtask bodies or findings. Reserve `verify_commands` for the final `review-passed` gate so every pickup does not inherit a broad test plan.
- When token telemetry shows high cache/input, large effective context, or repeated oversized rounds, finish the current narrow step and create a follow-on task with a compact handoff instead of continuing to grow the same task.
- For explicit `roles.architect` tasks, the architect round must persist a narrow executable subtask checklist with `coord update --set-subtasks` before re-queueing the coder. A findings-only architecture pass is not enough under strict enforcement.
- A task should have one main outcome and one final verification path.
- Keep docs/runbook work separate when it is material. Preserve the dedicated final review/verification round at task end, and put interim smoke checks in the active subtask body or round findings instead of creating a broad verification subtask.
- Treat `verify_commands` as the single final acceptance gate for the task. If a task naturally needs several unrelated end-to-end gates, split it into ordered tasks or narrower subtasks instead of growing one oversized verify list.
- Split a task or subtask when its title or body naturally bundles several independent verbs with `and`, especially when it mixes implementation with docs, review, or operational work.
- The CLI rejects newly written subtasks that combine broad review modes in one executable unit. In particular, split these into dependent tasks instead of one subtask: all-archive inventory, source audit, backend/iOS/frontend verification, simulator/manual smoke, fix-task creation, and final handoff.

Warning signs that a task is too broad:

- one subtask touches multiple major surfaces and has no single obvious verification step
- the acceptance criteria describe several independent deliverables
- the natural completion note would read like a mini changelog instead of one focused outcome
- phrases such as "read every completed task", "run the full verification suite", "audit ios/ and backend/", "exercise all tabs", or "create fix tasks for every gap"

### Shaping checks for refactor and architecture tasks

For `kind: refactor`, `kind: design`, or `complexity: complex` tasks that
restructure modules or interfaces, the shaping interview should also surface:

- **Deletion test.** For each module being merged, split, or extracted, ask:
  if you deleted it, would complexity vanish (it was a pass-through and the
  refactor is justified) or reappear scattered across callers (it was
  earning its keep — leave it)? Record the answer in `Plan` so the coder
  round does not re-litigate it.
- **Seam reality check.** Do not introduce a port or interface for a single
  implementation. One adapter is a hypothetical seam; two adapters
  (typically production + test) is a real one. If only one adapter is
  planned, drop the seam from scope or split a follow-on task that adds the
  second adapter.
- **Interface as test surface.** Acceptance tests should assert through the
  module's public interface, not its internals. If the acceptance test has
  to reach past the interface to read internal state, the interface is the
  wrong shape and the task should be reshaped before queueing.
- **Dependency category at the seam.** When the refactor crosses I/O,
  classify the dependency as in-process, local-substitutable (e.g. PGLite,
  in-memory FS), remote-owned (own service, ports & adapters), or true
  external (third-party). The category determines whether the acceptance
  test uses a stand-in, an in-memory adapter, or a mock; record the choice
  in `Plan` so the coder does not pick a different strategy mid-round.

For high-stakes interface design (a real-seam refactor that also hits one of
the warning signs above), consider a brief **design-it-twice** architect
round: have the architect produce 2–3 radically different interface
sketches — minimal, flexible, common-case-optimised — and recommend one
before queueing the coder. Worth `reasoning_effort_architect: high` for
non-trivial seams.

**Findings sections:** `coord new` always writes both `Claude findings` and `Codex findings` with `_No findings yet._`; nothing prunes them.

### Subtask handoff files

Per `~/Projects/coord-wright/docs/agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rule 6, multi-subtask tasks use deterministic handoff files (NOT an in-task-file section) to pass state between cold-start subtask workers. Each subtask round spawns a fresh agent that re-reads the task file and codebase from scratch; the handoff file is the canonical record of what the prior subtask produced.

**Deterministic path** (worktree-relative): `.coord/handoffs/<task-id>/S<N>.md`

The `.coord/handoffs/<task-id>/` directory is created on first use and committed alongside the subtask's code changes (the handoff file is part of the audit trail). Workers do not need to scan the task file to find handoffs — the path is uniquely determined by task-id and subtask number.

**File content shape** (5-15 lines):

```markdown
# S<N> handoff — <task-id>
Completed: YYYY-MM-DD HH:MM<offset>

## Files committed
- path/to/file.ts: <one-line description>

## Exports / types / functions added
- <name>: <signature or shape> — <next subtask uses this for what>

## Decisions made (non-obvious only)
- <decision>: <why>

## Gotchas
- <thing the next worker should know>

## Acceptance items closed
- <which subtask bullets are now satisfied>
```

The subtask body in `## Scope notes` MUST carry:
- For every subtask (S1 and the final subtask included, no exemptions): a `Writes handoff:` line naming the exact write path. The handoff file is mandatory — the final subtask still writes one because downstream `depends_on` tasks and the audit trail read it.
- For subtasks after S1: a `Reads handoff:` line naming the exact read path (the prior subtask's handoff).
- For every subtask except the last: a `Handoff to S<N+1>:` line — one sentence the shaper writes at shape time, naming the specific artifact (signature, file, decision, partial output, invariant) the next subtask needs to start. The S<N> worker treats this as the spec for the `## Exports / types / functions added` section of its handoff file, so it does not have to guess what the next subtask needs.

This removes worker-side improvisation about location, naming, and handoff content. Two CLI gates enforce it:

- Shape time: `coord new`, `--set-subtasks`, `promote`, and `release` reject a subtask block missing `Writes handoff:`, `Reads handoff:` (after S1), or `Handoff to S<N+1>:` (all but the last).
- Runtime: `coord update --complete-subtask=S<n>` exits 3 unless `.coord/handoffs/<task-id>/S<n>.md` exists on disk (only `--force` bypasses). Write the handoff file before the completing update.

Handoff files do not participate in task-file serialization.

**Brainstorm tasks:** `coord new --brainstorm` exempts the subtask requirement and writes the Plan placeholder `_Brainstorm task — ambiguity checklist drives first session._`; the task lands in `shaping` unless `--status=needs-brainstorming` is also passed. The watchdog triages only `needs-brainstorming`. Promotion into a runnable queue clears the queued side's content hash so precheck treats the activation as fresh work.

## Role-based frontmatter fields

These fields are all **optional**. `coord` stores only the values you explicitly pass. When absent, tasks fall back to legacy ping-pong behavior.

### `complexity`

Controls which role-based lifecycle rules are active when present.

| Value      | Description                                      |
|------------|--------------------------------------------------|
| `trivial`  | Coder only; no architect, no reviewer            |
| `simple`   | Codex-first implementation; review only if explicit |
| `complex`  | Higher-risk or more ambiguous work; roles still explicit |

Default when absent: no `complexity` field is written. `coord` does not backfill `complexity: simple`.

### `kind`

Classifies the type of work. Used by the router to prefer the best-fit agent side.

Valid values: `code-fix`, `code-cut`, `feature`, `refactor`, `review`, `design`, `docs`, `sql-diagnostic`, `smoke-test`.

Default when absent: `coord new` assigns Codex unless `--assigned`, `--agents`,
or explicit `roles.architect` routes elsewhere.

`code-cut` is the explicit shape for net-negative subtractive work — deletions,
deprecations, dead-code removal, surface retirement. When a task is shaped with
`kind: code-cut`, the coord-shape skill auto-injects the subtraction-discipline
non-negotiables (from `${COORD_TOOLS}/templates/code-cut.md`) into the task
body so the worker inherits the constraints that produced a real
C1–C5 chain (-10,349 LOC net across 5 chained tasks). Do not auto-assign
`code-cut` from heuristics on legacy tasks — the kind must be set explicitly
by the shaper, and is the contract that flips a task from "default additive"
to "default subtractive."

### `roles`

Maps each coordination role to an agent side. Each key is a role (`architect`, `coder`, `reviewer`); each value is `claude`, `codex`, or `skip`.

```yaml
roles:
  architect: claude
  coder: codex
  reviewer: claude
```

Default when absent: no `roles` map is stored. `coord` does not infer or persist role assignments from `complexity`; a task creator or wrapper must materialize them explicitly.

Use colon pairs such as `--roles=coder:codex,reviewer:claude`; bare names like `--roles=reviewer` do not create a reviewer role in the current CLI.

### `reasoning_effort`

Optional in the schema, but recommended for all new runnable tasks that are not trivial.

Valid values: `low`, `medium`, `high`, `xhigh`.

```yaml
reasoning_effort: xhigh
```

Current behavior:

- Codex automation honors this field when present and passes it to the Codex CLI for that task.
- When absent, the loop uses the project default reasoning level from the launchd env or `.coord/config.env`.
- Some Claude launch paths may still inherit the operator's local Claude settings, so this field should be treated as explicit task intent even when a specific launcher does not yet enforce it.
- Projects can keep a lower default, such as `medium`, and reserve `high` or `xhigh` for the tasks that actually need deeper reasoning.

Recommended creation defaults:

| task shape | default `reasoning_effort` |
|------------|----------------------------|
| `trivial` task with no review | `low` |
| `simple` implementation-heavy task | `medium` |
| `simple` design or review task | `high` |
| explicit role-flow work | `high` |
| high-stakes money/auth/security/destructive/RCA task | `xhigh` |

Default when absent: project loop default.

### `model_claude` and `model_codex`

Optional. Override the model used by each agent for this specific task.

`model_claude` accepts `haiku`, `sonnet`, `opus`, or a full Claude model ID string.
`model_codex` accepts the exact model string you would otherwise set in `CODEX_MODEL`.
Prefer `gpt-5.6-sol`; `gpt-5.5` remains accepted for existing task files.
Do not use unsupported aliases such as `codex-latest` or `codex-mini-latest`;
`coord` rejects both at write time. The Codex CLI itself rejects
`codex-latest` under a ChatGPT account, which would otherwise fail every
launchd run that picks up such a task.
When unsure, omit the task-level override and let the project `CODEX_MODEL` decide.

`gpt-5.3-codex-spark` is accepted only as an explicit low-risk override. It is
for fully shaped trivial/simple Codex-only work such as small docs, smoke-test,
code-fix, or refactor tasks. `coord` rejects Spark when the task or subtask is
complex, high-reasoning, role-based, high-risk, broad in scope, or missing a
concrete acceptance/verification finish line.

```yaml
model_claude: sonnet
model_codex: gpt-5.6-sol
```

Priority chain per agent:
1. Subtask-level execution metadata (`complexity:`, `model_claude:`, `model_codex:`; see [Subtask execution metadata](#subtask-execution-metadata) below)
2. Task-level `model_claude` / `model_codex` frontmatter field
3. Project-level env var: `CLAUDE_MODEL` (Claude) or `CODEX_MODEL` (Codex), set in the launchd plist
4. System default — no `--model` flag passed

Claude alias mapping:

| alias | canonical ID |
|-------|-------------|
| `haiku` | `claude-haiku-4-5-20251001` |
| `sonnet` | `claude-sonnet-5` |
| `opus` | `claude-opus-4-8` |

Codex does not apply a shared alias table. `model_codex` is passed through to
`codex exec --model` unchanged, so use the same value your local Codex CLI
already accepts in `CODEX_MODEL`. Prefer `gpt-5.6-sol` over `codex-*` aliases such
as `codex-latest` and `codex-mini-latest`, which `coord` rejects.
Use `gpt-5.3-codex-spark` only for explicitly low-risk trivial/simple work
that still has a fully shaped task.

Recommended defaults by task shape:

| task shape | `model_claude` | `model_codex` |
|------------|---------------|--------------|
| `trivial` | `haiku` | `gpt-5.6-sol` |
| `simple` code-fix / refactor | `sonnet` | `gpt-5.6-sol` |
| explicit low-risk Spark task | `haiku` or `sonnet` | `gpt-5.3-codex-spark` |
| `simple` design or review | `sonnet` | standard Codex model such as `gpt-5.6-sol` |
| explicit role-flow work | `sonnet` | standard Codex model such as `gpt-5.6-sol` |
| high-stakes (`xhigh`) | `opus` | standard or stronger Codex model for the local project |

Default when absent: project env var or system default.

#### Subtask execution metadata

For new or reshaped runnable tasks, every subtask must declare its execution metadata directly below the checkbox: `complexity:`, `model_claude:`, and `model_codex:`. The CLI now enforces this documented S-checkbox format for `coord new --set-subtasks`, `coord update --set-subtasks`, `coord promote`, and `coord release`. Each subtask body also has a hard size ceiling: ~900 characters compact (title + body, whitespace-collapsed, excluding the mandated handoff lines) — shaping validation rejects larger bodies, so split or trim past it.

```markdown
- [ ] **S1: Cheap mechanical pass**
  complexity: trivial
  model_claude: haiku
  model_codex: gpt-5.6-sol
  Reformat the generated output files.

- [ ] **S2: Reasoning-heavy review**
  complexity: complex
  model_claude: opus
  model_codex: gpt-5.6-sol
  Evaluate the architectural trade-offs and write the design doc.
```

- Do not write YAML-style subtask blocks such as `- title: ...`; `coord` rejects them.
- IDs must be contiguous from `S1` with no gaps or duplicates.
- Metadata lines are stripped from `next_subtask.body` — they are execution metadata, not instructions.
- `coord update --set-subtasks=...` validates new subtask blocks, rejects unparseable checklist syntax, and rejects any subtask that omits `complexity`, `model_claude`, or `model_codex`.
- The subtask-level model hint takes priority over the task-level frontmatter field and env vars (see priority chain above).
- Existing older tasks without these lines remain readable for backward compatibility, but newly created or rewritten subtask blocks must include them.
- `complexity` accepts the same values as task-level complexity: `trivial`, `simple`, `complex`.
- `model_claude` accepts the same aliases as the task-level field (`haiku`, `sonnet`, `opus`, or a full model ID).
- `model_codex` is passed through unchanged to `codex exec --model`, so use `gpt-5.6-sol`, not unsupported aliases like `codex-latest` or `codex-mini-latest` (`coord` rejects both).
- `model_codex: gpt-5.3-codex-spark` is valid only for trivial/simple low-risk subtasks. `coord update --set-subtasks=...` rejects Spark subtasks that are complex, high-risk, bundled, or broad across multiple surfaces.

### `acceptance`

A YAML list of concrete, verifiable criteria the reviewer checks against.

```yaml
acceptance:
  - All new fields documented with valid values
  - Backward-compat fallback explicitly stated
```

Default when absent: the reviewer falls back to general-purpose review — checking the diff against the task description and open issues, same as legacy ping-pong.

### `verify_commands`

A YAML list of shell commands forming the final acceptance gate. The reviewer role executes them from the repo root and outputs `APPROVE` only when every command exits 0 (see the reviewer round in `skills/coord-check/SKILL.md`); the watchdog re-runs them when diagnosing a stuck task. The `coord` CLI itself does not execute them, but the worker does: after any round that leaves the task `done` (coder-only close, reviewer close, or failure path), it re-runs every line via `bash -c` from the project root with the round timeout. Each command must exit 0 and leave the worktree unchanged (no new or modified files); otherwise the worker restores the verify-created changes and demotes the task with `--status=review-failed --force` back to the coder. Commands that build artifacts (`dist/`, coverage, unignored caches) or are not idempotent therefore loop the task. The same close guard demotes a done task whose current-round reviewer finding says `REJECT`. `verify_profile` (`bin/coord-verify-artifacts`) is a separate artifact gate.

Reserve this list for the narrow final acceptance gate. Keep the list short and task-final. Do not put every smoke test or exploratory check you might run during implementation here; those local checks belong in the active subtask text or the relevant round finding. If a task needs multiple unrelated final gates, split it before the verify list turns into a second task plan.

`verify_commands` run on the host's stock tools; assume macOS system versions (system ruby 2.6 with no `tally`, bash 3.2) unless the project guarantees otherwise.

```yaml
verify_commands:
  - node test-coord.js
  - npm run lint
```

When present, the worker re-runs these commands from the project root (stdin closed) whenever a round leaves the task `done` — coder or reviewer — and demotes the task back to its coder if any command fails.

Default when absent: no mechanical verify gate on close.

### `depends_on`

YAML list of task ids that must be complete before this task becomes runnable.

```yaml
depends_on:
  - 2026-04-09-phase-4-scheduling-and-guarded-automation
```

Current behavior:

- Tasks with unmet dependencies remain in their queue status, but `precheck` and pickup helpers skip them until every dependency is either `done` in `tasks/` or already archived under `tasks/archive/`.
- Missing dependency ids are treated as blocked, not as satisfied.
- Ordering inside one task still comes from subtasks; `depends_on` is for cross-task sequencing only.
- Among runnable tasks, pickup orders by `priority` ascending (default 5), then by id.
- Nothing carries predecessor context forward automatically; read the predecessor's findings or handoff files directly.

Default when absent: task has no cross-task dependency gate.

### `review_rounds_max`

Integer. Maximum review rounds in a cross-side review loop before escalation
to `needs-brainstorming`.

`coord update --status=review-failed` from `needs-review` (a reviewer
rejection) increments `review_round`. When that count reaches the cap, the
same call parks the task in `needs-brainstorming` with `pickup_hold: true`,
`assigned` set to the coder, and an Open issue naming the cap, instead of
returning it to `pending`. So `1` allows one review and no fix loop, `2`
allows one fix loop. A `--review-rounds-max` in the same update call applies
to that rejection. To continue a parked task, raise `review_rounds_max` (or
rescope), then release it.

The cap applies only to cross-side loops: when `roles.coder` and
`roles.reviewer` name the same agent, no cap applies (same-side loops stay
bounded by `max_seconds`, the round token gate, and watchdog triage). Forced
demotes from `done` (the worker's false-approve and mechanical verify guards)
do not count.

`coord-review` also reads it: tasks whose title or tags match
`money|auth|security|destructive|trading|rca|migration` must set
`review_rounds_max >= 2` (and `complexity` of at least `complex`).

Default when absent: no cap — the reject/fix loop continues until the
reviewer approves or a human steps in. Set it to bound a cross-side loop.

### `review_round`

Integer, written by `coord update`: the number of reviewer rejections
(`review-failed` from `needs-review`) so far. Never written by agents; the
review cap compares it with `review_rounds_max`.

Default when absent: `0`.

### `scope_budget`

Optional in the runtime task schema; required by `coord-review` when reviewing
a shaped task. Per-task subtraction/addition envelope, surfaced to the worker via the
pickup handoff payload. It is a **warning target, not a stop**: the
implementer finishes the subtask, records actual vs target net LOC with a
one-line reason in its finding, and the reviewer decides whether the overshoot
is bloat. The CLI does not block on it. Stopping the coder at the threshold
would halt a healthy implementation on an honest estimation miss, while a
bloated change under the band would still pass untouched.

```yaml
scope_budget:
  net_loc_delta_target: "-800 to -1200"   # or "+50 to +200" for a feature
  abort_if_exceeded_by_pct: 50            # warning threshold; name kept for compatibility
```

Write the field via `coord update <id> --scope-budget-loc='-800 to -1200'`
(optionally with `--scope-budget-abort-pct=50`). The shaper derives the band
from the third grill question (net LOC delta target) in
`${COORD_TOOLS:-$HOME/Projects/coord-wright}/skills/coord-shape/SKILL.md`
§ "Mandatory subtraction questions."

`coord-review` requires a numeric band (`+50 to +200`, `0 to 0`, or
`-800 to -1200`) and four non-placeholder list answers in `## Subtraction
analysis` (or a `###` subsection inside the plan). The reviewing agent checks
that the answers are concrete, the prose and frontmatter budgets agree, and
the plan and acceptance cover promised removals. Justified growth with no
retirement is valid. The status warning about three additive tasks is only a
metadata heuristic, not a deletion quota. These shaping-review checks add no
worker pickup or direct CLI promotion gate for existing queued tasks.

How the worker uses it:

- The pickup handoff payload includes a `scope_budget:` block listing the
  target band, the warning percentage, and a one-line policy reminder.
- The coder finishes the subtask regardless of the number. When the final
  diff exceeds the band's upper bound by more than `abort_if_exceeded_by_pct`%,
  the finding must carry `scope: actual +N vs target <band>` plus a one-line
  reason. The only stop condition is overshoot caused by work outside the
  declared `scope`/`scope_creates`.
- The reviewer owns the verdict (see `skills/coord-check/SKILL.md`, reviewer
  round): APPROVE with a note when the overshoot is explained and the code is
  clean; REJECT on YAGNI bloat per `agent-workflow-policy.md`. A **negative**
  band (`code-cut`, `refactor`) stays a hard criterion: net LOC above the band
  is REJECT unless the finding names the cut that proved impossible.
- Positive bands for feature work are estimates and tend to run low. Estimate
  per file from `scope`/`scope_creates` rather than guessing a task total.

Default when absent: no budget surfaces in the handoff; the worker proceeds
under standard YAGNI/KISS implementation policy without a numeric ceiling.
Old tasks without the field continue to run unchanged — `scope_budget` is
purely additive.

## Round budget

### `max_seconds`

Integer. Wall-clock budget per round in seconds. The worker resolves the effective timeout as: frontmatter `max_seconds` → role default (coder=1200, reviewer/architect=1800) → hard fallback 1200.

On timeout (exit code 124 SIGTERM or 137 SIGKILL after a 30-second grace window):
- `terminal_reason=round_timeout` is logged to the worker log and agent-runs row.
- The worker exports `COORD_AGENT_FINDING_FILE=/tmp/<agent>-finding-<project>-<id>.txt` and clears it before launch. Any finding written there before the timeout is preserved to `.coord/finding-<id>-<ts>.txt`.
- The task routes to `needs-brainstorming` with an Open Issues note recording elapsed seconds and the timeout cap.
- **No auto-requeue**. A wall-clock timeout means shaping is wrong; increase `max_seconds` and re-promote.

Recommended values (full table in the "Round-budget table" subsection below):
- simple + code-fix single subtask: 600–900
- simple + code-fix multi-subtask: 1200
- simple + design audit: 1500
- complex per round: 1800–2400

### `max_turns`

Integer. **Runaway-loop fuse.** The worker enforces a floor of 60 turns regardless of what is set in frontmatter — this absorbs the ~14-call bootstrap overhead plus a generous implementation margin. Frontmatter `max_turns` is override-only above 60. Shape tasks with `max_seconds`; only set `max_turns` when a specific turn count above 60 is needed to cap a known runaway pattern.

Current behavior:

- `coord update --round=...` only sets `round` and bumps `attempts`; `coord update` never checks `max_turns` (the review cap is `review_rounds_max`, checked on reviewer rejection).
- If the agent exits non-zero for any non-rate-limit reason (verify failed, max-turns hit, OOM, API error), the worker commits any pending agent diff as `coord: tentative <id>`. For max-turns exits specifically (Claude `error_max_turns` or a Codex `turn.failed` turn-limit event), the worker checks for progress (tentative commit or finding file written during the tick) and auto-requeues once at 3× the effective budget rather than immediately escalating; see `max_turns_retries_used` below. All other non-zero exits go to `needs-brainstorming` immediately. The watchdog diagnoses and resets fixable tasks; discard with `/coord-discard` if the work is irredeemable.

Default when absent: worker floor is 60; `bin/coord new` writes `4` or `12` for the task file value (now only meaningful as override-above-floor).

### `max_turns_retries_used`

Integer. Number of automatic max-turns retries already consumed for this task. Written by the worker on auto-requeue; never written by agents.

- Valid values: absent (equivalent to 0) or 1. The worker caps auto-requeue at 1 attempt; a second max-turns exit on the same task always goes to `needs-brainstorming`.
- The raised `max_turns` and this counter are intentionally not reset on task completion — they are audit state, not operational state, and the higher ceiling is usually appropriate if the task needed it once.
- Both Claude and Codex max-turns exits can trigger the auto-requeue.

Default when absent: `0` (no retry used).

### Creator-owned defaults by complexity

| task shape | reviewer | architect | starting `reasoning_effort` |
|------------|----------|-----------|-----------------------------|
| trivial    | skip     | skip      | `low`                       |
| simple     | optional | skip      | `medium`                    |
| complex    | explicit when needed | explicit only | `high`       |

This table is a creator guideline. `coord` does not auto-populate `roles`,
`review_rounds_max`, or `reasoning_effort` from it. Treat the reasoning column
as a baseline; raise to `high` for important `design` or `review` work even
when it remains `simple`, and raise to `xhigh` for explicitly high-stakes
tasks. Review is opt-in through `roles.reviewer`; architect is opt-in through
`roles.architect`.

## Routing

### Kind-based initial assignment

When creating a task with `coord new` and no explicit `--assigned`, the `kind` field determines which side gets the task first:

| kind                                     | initial assignee |
|------------------------------------------|------------------|
| any supported kind                       | codex            |
| absent                                   | codex            |

Explicit `--assigned` always takes precedence over kind-based routing. Single-agent tasks (`--agents=codex` or `--agents=claude`) auto-derive the assignee from the agent and ignore kind routing. Explicit `roles.architect` starts on the named architect.

### Reviewer assignment

`coord update --status=needs-review` without `--assigned` assigns
`roles.reviewer` when it is `claude` or `codex`; otherwise `assigned` is left
unchanged. An explicit `--assigned` always wins; the worker's resolved success
commands pass it.

## Lifecycle flows

Default flows:

- Canonical queue: `pending` is the normal runnable state. By default it is `assigned=codex`.
- Codex-first no-review: `pending/codex -> codex-working -> pending/codex` for additional subtasks, then `done`.
- Explicit review: `pending/codex -> codex-working -> needs-review/<reviewer> -> review-passed (transient) -> done`; a rejection at the `review_rounds_max` cap parks in `needs-brainstorming` with `pickup_hold`.
- Triage gate: `{agent failure} -> needs-brainstorming -> watchdog diagnoses -> pending` (or stays for human when not fixable)
- Brainstorm gate: `{new task --brainstorm --status=needs-brainstorming} -> needs-brainstorming -> pending after clarification`
- Transition table (`VALID_TRANSITIONS` in `bin/coord`): `done` is reachable only from `claude-working`, `codex-working`, or `needs-review`; `shaping`/`pending`/`needs-brainstorming -> done` and anything out of `done` need `--force`. Closing a never-started `shaping`/`needs-brainstorming` task to `done` skips the model/effort baseline check unless the same call sets a model, effort, complexity, or subtask field. `--status=done` is also refused while subtasks are incomplete unless `--force`. `--force` on an archived task with a non-done status moves it back to the tasks dir.
- `coord promote` clears `pickup_hold`; `coord release <id>` releases a held task to `release_status` or its current status unless `--status=<status>` is given.
- Shaping gate (default for plain `coord new`): `{new task} -> shaping -> pending via coord promote <id>`. Use shaping when scope is fine but you want a review window before launchd picks it up; use `--brainstorm` when scope is still unclear. `--solo` and `--overnight` do not skip shaping.

### needs-brainstorming recovery paths

A task in `needs-brainstorming` is off-queue and will not be picked up by a worker until something explicitly transitions it. Three recovery paths are supported:

1. **Watchdog auto-reset** — the `coord-unblocker` launchd agent (see `/coord-unblocker`) periodically diagnoses fixable escalations and moves them back to `pending` automatically. This is the default path for transient failures (rate limits, single max-turns trip, recoverable agent crashes). The watchdog writes a human-required verdict **once**: it skips any task with `pickup_hold: true`, its diagnostician sets that hold when it concludes WRONG APPROACH or CANNOT AUTO-FIX, and two consecutive watchdog findings with no state change auto-hold the task. Release with `coord update <id> --pickup-hold=false --status=pending --force` after deciding.
2. **Manual return to the runnable queue** — when the operator has read the escalation context and the task is ready to run as-is:
   ```bash
   python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=pending
   ```
   Use this when the underlying blocker has been addressed externally (dependency landed, secret rotated, watchdog policy hand-tuned) and no scope change is needed.
3. **Demote for reshaping** — when the task itself needs scope work before it should run again:
   ```bash
   python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=shaping
   ```
   This drops the task back into `shaping` so the operator (or a shaping skill like `/coord-shape` or `/coord-split`) can rewrite the plan/subtasks before re-promoting via `coord promote`.

If none of these apply, abandon the task with `/coord-discard` instead of letting it sit in `needs-brainstorming` indefinitely.

Cross-task dependency gate:

- `{pending|needs-review} + depends_on with unfinished predecessors -> stays queued but unrunnable until dependencies are complete`

Explicit role flows:

- **Reviewer**:
  `pending -> {claude,codex}-working -> needs-review -> review-passed (transient) -> done`
  On failure: `needs-review -> review-failed (transient) -> pending -> {claude,codex}-working -> needs-review -> ...`

- **Architect**:
  Architect work starts in the normal assignee queue (`pending` with the architect named in `assigned`). After decomposition, hand off to the coder by keeping `status=pending` and switching `assigned` to the coder, then follow the same `working -> needs-review -> review-passed (transient) -> done` path as simple tasks.

### Local-only completion

Completed tasks should normally land as committed and pushed wrapper output with
no extra note. If the final completion path stays local-only instead — for
example because wrapper-safe staging had to skip overlapping edits or the final
`git push origin HEAD` failed — record that with
`coord update <id> --add-issues="..."` instead of leaving the task silently
local-only. There is no dedicated completion-handoff command.

## Usage

From a project root, use the shared CLI:

```bash
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" new --task="Clarify task" --assigned=claude --brainstorm
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" new --task="Narrow backend fix" --assigned=codex --complexity=simple --kind=code-fix --reasoning_effort=medium --set-subtasks=@/tmp/coord-subtasks.txt
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" new --task="Independent review" --assigned=codex --complexity=simple --kind=review --roles=coder:codex,reviewer:claude --review_rounds_max=1 --reasoning_effort=high --set-subtasks=@/tmp/coord-subtasks.txt
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" new --task="High-stakes review" --assigned=codex --reasoning_effort=xhigh --set-subtasks=@/tmp/coord-subtasks.txt
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" status
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --handoff
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --compact
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" update <id> --status=pending --assigned=codex
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" precheck
```

## Shaping defaults and pitfalls

(Merged from the former `shaping-guide.md`. Cross-references: cross-agent workflow policy lives in `agent-workflow-policy.md` — that doc owns the canonical YAGNI / loop-bias / decomposition rules. This section adds the CLI-validation matrix, telemetry-derived ceilings, naming rules, and known CLI pitfalls.)

### Shaping recommendations and CLI validation

Recommendations guide effort selection; the validator admits a wider set. Complexity describes the work, while effort describes the reasoning needed for its remaining decisions. Do not relabel a complex task to obtain a lower effort setting.

| Complexity | Allowed coder Claude family | Allowed reasoning effort |
| --- | --- | --- |
| `trivial` | `haiku` | `low` |
| `simple` | `sonnet` | `low`, `medium`, `high` |
| `complex` | `sonnet`, `opus` | `medium`, `high`, `xhigh` |
| `xhigh` | `opus` | `xhigh` |

`coord new` and `coord update` reject task-level combinations outside this table. `coord promote` re-validates subtask complexity/model pairs, but does not recheck task-level effort against this table. Role fields (`model_architect`, `model_review`, `reasoning_effort_architect`, `reasoning_effort_review`) additionally admit `opus` on `simple` tasks.

- Prefer `medium` for simple implementation with settled acceptance and affected callers/tests identified.
- Prefer `high` for design/review or complex work with unresolved decisions. Complex implementation with a settled contract may use `medium`; validate any broader change with paired quality and consumption evidence first.
- Retain `high` or `xhigh` for unresolved concurrency, identity or security decisions; high-stakes money, auth, destructive work and serious RCA generally warrant `xhigh`.
- Prefer `sonnet` for normal Claude work and `gpt-5.6-sol` for normal Codex work. High-stakes independent reviews can set `model_review: opus`, usually with `reasoning_effort_review: high`, without changing the coder model.

The worker resolves effort from the current role override, then task-level `reasoning_effort`, then `CODEX_REASONING_EFFORT` or `CLAUDE_REASONING_EFFORT`, falling back to `medium`. It does not consume a subtask-level reasoning field. Keep active tasks unchanged during experiments.

`coord new` and `coord update` emit a **non-fatal advisory** for simple/high combinations on `code-fix`, `code-cut`, `refactor`, `docs`, and `smoke-test` kinds. The advisory originated in local telemetry reporting about 30% longer runs with little quality gain; it is not a controlled benchmark for every current model or task class. Design/audit and high-stakes kinds are excluded.

### Measuring an isolated Codex round

The existing text and `--json` reports retain their output contracts. For a single explicit CLI rollout, use:

```bash
node bin/codex-coord-stats.js --round-summary --expect-cwd /tmp/exact-trial-checkout /absolute/path/to/rollout.jsonl
```

This opt-in JSON report includes session identity, exact cwd, model, effort, CLI version, first/last event timestamps, latest cumulative raw usage (including reasoning output), and model-issued tool-call events. It checks the session and turn cwd against the supplied path. It does not scan directories or count tool names mentioned in output. Function/custom-call outputs are excluded; calls inside an orchestration script are not separately represented by rollout call events.

Raw `input_tokens` includes cached input; `uncached_input_tokens` subtracts that cache count. Cumulative snapshots are never summed. Missing counters stay `null`, including derived counts that require them; they are not free usage. Invalid JSON or a cwd mismatch exits nonzero. Record process exit status and elapsed time separately, retaining failed/interrupted attempts. The report is not a completion or quality certificate, and its event interval is not a substitute for process elapsed time. Use fresh, single-model sessions for paired trials; preserve identical code, brief, CLI, permissions and acceptance gates. Report uncached/cache and reasoning/other output separately; subscription quota consumption cannot be inferred from a fixed effective-token formula.

For Codex models, prefer the stable `gpt-5.6-sol` ID by default, and never use unsupported aliases such as `codex-latest` or `codex-mini-latest` — `coord` rejects them, and the Codex CLI itself rejects `codex-latest` under a ChatGPT account.

### Architecture / decomposition role guidance

- Use `reasoning_effort_architect=high` for normal task design that splits ambiguous work into a task chain.
- Use `reasoning_effort_architect=xhigh` only when the design step is high-stakes, safety-sensitive, money/auth/security related, destructive, or a serious RCA.
- Use `model_architect=sonnet` for most Claude-led task architecture; use `model_architect=opus` only when ambiguity, blast radius, or safety risk justifies it.
- For Codex-only task architecture, keep `model_codex=gpt-5.6-sol` and raise `reasoning_effort_architect` rather than inventing Codex-specific architect model fields.

For the broader decomposition rules (prefer fewer fatter subtasks, align subtask boundaries with natural file/module interfaces, subtask handoff convention), see `agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rules 4 and 6.

### Per-tick message ceiling

A subtask is the unit of one codex/claude tick. Worker telemetry across 119 codex/coder ticks (2026-05-09…05-17) shows wall time scales near-linearly with the number of `agent_message` events the model emits — roughly **~25 s per message** (median) and **~55 s/msg at p90**. Subtasks that emit 15+ messages average **380–580 s per tick**, dominate the p90 tail, and are the ones that go pathological when an `apply_patch` retry hits.

Soft cap: **shape subtasks expected to emit ≤ 10 assistant messages**. Split when any of these are true:

- The subtask edits 4+ source files → split per-file or per-component.
- The subtask combines two or more of: add, edit, delete, verify-and-fix.
- A page-level frontend change touches multiple sub-components (header + list + grid + modal) → split per component.
- A "bundle" or "polish" name aggregates 3+ independent fixes touching different files → make each fix its own subtask. Same-file polish bundles can stay if total edited LOC is small.

Cost rule of thumb: a 16-message tick averages ~580 s; two 8-message subtasks average ~470 s combined (each pays its own ~30 s Codex startup, but the gain on the message side outweighs it and the tail risk drops sharply). The win is mostly **variance compression** (max 6,301 s → ~700 s when combined with `apply_patch` re-read discipline), not headline mean reduction.

**The split-vs-merge counterweight.** The 10-message ceiling optimizes for *worker reliability* (wall-time variance, apply_patch retry safety). Per `agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rule 4, subtask fragmentation also has a *context cost*: each cold-start subtask round re-reads the task file and codebase, producing 6-10× input:output token ratios in the project's token_log. Do NOT split below the natural file/module interface just to chase the message ceiling. Prefer 2-4 subtasks each grouping 2-3 related concerns at natural boundaries over 5+ subtasks of one bullet each, and rely on the subtask-handoff convention (rule 6) as the compression layer between cold workers. Splitting a subtask is the right call when it crosses file/module boundaries OR exceeds the message ceiling; splitting purely to hit smaller-is-better is the wrong call.

### Task naming rules

Two rules to apply on every `coord new`:

1. **Title length discipline.** Auto-generated slugs truncate at 50 chars after the date and cut mid-word (`...classificatio` instead of `...classification`). Aim for `--task` strings that yield slugs under ~50 chars. Drop noise like `.py`, `route endpoints`, `compile`, `into unified file`. Push descriptive verbs to the front. Keep the verbose explanation in the Plan body, not the title.

   - Bad: `"Backend audit: classify screening.py route endpoints"` → `2026-05-17-backend-audit-classify-screening-py-route-endpoint` (cut)
   - Good: `"Backend: classify screening operator routes"` → `2026-05-17-backend-classify-screening-operator-routes` (clean)

2. **Chain references via tags, not slugs.** When a task belongs to a multi-task plan (integrated review, split chain, etc.) and has a shorthand id in the plan (T1a, T2, etc.), pass `--tags="coordination,ref:T1a"` at create time. Later sessions find the task with `rg "ref:T1a" tasks/*.md`. Slug stays descriptive; the chain reference stays out of the slug so it can't go stale if the plan rebirths the id. Companion rule: write the Tn→slug mapping into the plan doc as the canonical lookup.

### Common shaping pitfalls (CLI behaviors that re-bite)

**1. `--set-subtasks` rejects subtasks that mix surfaces + conjunctions.**

Source: `bin/coord` `MAJOR_SURFACE_PATTERNS` and `validate_subtask_block`. Surface patterns: `backend`, `frontend`, `ios`, `database`, `docs`, `tasks`, `worker`. Any subtask body that hits 3+ surfaces, or 2+ surfaces AND a conjunction (`and`, `,`, `;`, `plus`, `also`, `then`), is rejected.

The trap is that "innocent" phrases trip surfaces unexpectedly: "dev server" → `server` → backend; "cd backend && alembic upgrade head" → backend + database; "PortfolioView.swift" → `swift` → ios; "from the backend" → backend. Fixes: replace path prefixes with relative paths, drop file extensions for cross-references, don't mention sibling surfaces in handoff text, and split per-surface verification into separate subtasks.

**2. Embedded `##` headings in `--set-plan` and `--set-subtasks` mangle section bodies.**

The parser treats `##` headings as task-file section boundaries, so a pasted mini-document with its own `##` headings can split or truncate the intended Plan or Scope notes content. Worse, `--set-plan` replaces only the text under `## Plan`: embedded `## ` headings become sibling sections, and every rerun appends another copy of them (`coord-review` still passes). Lead with prose, and use `###` or deeper headings inside any content passed to `--set-plan`, `--set-subtasks`, or `--set-acceptance`.

**3. `--set-subtasks` replaces the checklist from the first `- [ ] **S<N>:` entry onward.**

Prose before the first subtask entry is preserved; everything from that entry on — including completed `- [x]` subtasks — is replaced by the new text. To keep finished subtasks in the file, include them in the replacement. Write the full block to `/tmp/…`, pass it with `--set-subtasks=@/tmp/…`, and inspect the resulting diff before promoting.

### Round-budget table (companion to `max_seconds` above)

```
+----------------------------------+-----------------------+---------------+
| Task shape                       | Subtask pattern       | max_seconds   |
+----------------------------------+-----------------------+---------------+
| simple + code-fix                | single subtask        | 600–900       |
| simple + code-fix                | multi-subtask         | 1200          |
| simple + design audit            | any                   | 1500          |
| complex                          | per round (each sub-  | 1800–2400     |
|                                  | task is its own round)|               |
+----------------------------------+-----------------------+---------------+
```

Decision source for the turn-vs-time-limit guidance: codex-loop transcript (CONVERGED round 1).
