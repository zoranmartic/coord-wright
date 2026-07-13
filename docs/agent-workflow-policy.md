# Agent Workflow Policy

Shared workflow policy for Codex, Claude, coord tasks, and review skills across projects.

## Subtraction as the Opening Move

Additive bias is the dominant compounding failure mode across solo-feature work. A 1-page personal portfolio accreted ~10,000 LOC of admin auth, invite gating, runtime-config admin API, session revocation, and audit log between Jan and May 2026 (a personal portfolio project). Every individual task was reasoned, reviewed, and shipped. The cumulative result over-engineered the surface by two orders of magnitude relative to the stated goal. The fix was a 5-task subtraction chain on 2026-05-25 that returned **-10,349 LOC net** across 47 files (+988 / -11,337).

The diagnosis: the closing-ritual subtraction round in rule 3 below is too late — by the time a two-agent loop converges, everyone is invested in what's been built. The defense has to start before adding anything, not after. Both agents (Claude and Codex), at every shaping interview and every implementation request, apply this opening move:

**Before the first design draft, before the first plan, before the first line of code: ask "what existing surface should this work retire?"** Refuse to proceed with shaping or implementation until that question has an answer, even if the answer is "nothing — here's why." A zero-retirement answer is allowed only when the work is genuinely additive (new surface, no overlap with existing code) AND the additive cost has been weighed against the alternative of changing what already exists.

The four subtraction questions in `${COORD_TOOLS:-$HOME/Projects/coord-wright}/skills/coord-shape/SKILL.md` step 2 are the operationalization of this opening move for coord-shape. For interactive coding requests outside coord, both agents still ask them implicitly before adding any new abstraction, helper, env var, route, or file. The four questions are:

1. What existing code, if deleted, would make this change unnecessary or smaller?
2. What becomes orphaned, redundant, or dead code after this lands?
3. Net LOC delta target — net-negative, net-zero, or net-positive band?
4. If net-positive: what existing complexity gets retired as part of this work?

The closing subtraction round (rule 3 below) is preserved as a safety net for two-agent review loops, but it is not the primary defense. The primary defense is making subtraction the first move.

When the answer to question 3 is net-negative, the task is shaped with `kind: code-cut`, which auto-injects the subtraction-discipline non-negotiables from `${COORD_TOOLS:-$HOME/Projects/coord-wright}/templates/code-cut.md`. See `task-files-reference.md` § "kind" and the template file.

## Two-Agent Loop Bias and Mitigation

Two-agent review loops (codex-loop, coord-shape-review, multi-round shaping interviews) have a documented additive bias: every round can ADD findings but cannot subtract scope. Convergence is defined as "no remaining substantive disagreements" — which rewards comprehensive coverage, not minimal viable design. Left unchecked, this inflates specs, fragments work into too many tasks, and produces over-engineered features that need to be redesigned for simplicity later.

Both agents (Claude and Codex), when invoking or participating in a two-agent loop on solo single-feature work, must apply the following counterweights:

1. **YAGNI / KISS as a settled global invariant** (not a per-task declaration). The canonical YAGNI rules live in this document under "YAGNI / KISS During Implementation" and apply automatically to every task, every round, every implementation. Agents do NOT re-state these rules in Subject blocks or per-task docs. Per-task Subject blocks should ONLY list task-specific scope exclusions the agent cannot infer from the policy (e.g. "v1 only, no Bedrock models", "no voice mode — deferred to v2"). Every finding that proposes ADDING something is rejected by default and must justify against the policy. The Subject's job is to capture what's surprising about THIS scope, not to recapitulate global engineering principles.

2. **Scope budget in the Subject block.** State the expected effort envelope: target hours of implementation work, max files touched, max new routes/endpoints/pages. If loop findings collectively exceed the budget, the design is wrong (not done) and needs to be cut, not extended. Skip the budget only for pure factual reviews where no implementation follows.

3. **One subtraction round before declaring CONVERGED (safety net, not primary defense).** After the loop reaches a normal convergence point on coverage, run one additional round whose prompt is ONLY "what can we cut? what's premature optimization? what's YAGNI? what would a simpler v0.5 of this design look like?" Treat this as a hard requirement, not a courtesy step. Convergence is only valid after the subtraction round either accepts cuts or explicitly affirms there are none. This round is the safety net — the primary defense is the opening-move subtraction questions in § "Subtraction as the Opening Move" above. Findings here that should have surfaced at opening-move time indicate the shaping interview drifted; record them in the task's `## Findings for follow-up` so the next shaping cycle catches them earlier.

4. **Decomposition preference toward fewer tasks.** A feature owned by one person, fitting one PR, completing in under one day belongs in ONE coord task with 2-5 subtasks — not a chain of N tasks. Chains earn their split only at multi-day scope, genuine parallel lanes, or where the dependency graph would block a single worker. The shaping bar's preference for "5 chained narrow tasks over 1 fat task" applies to genuinely larger work; do not auto-apply it to small features. Note that fragmentation hurts even WITHIN a single task: each subtask round spawns a fresh Codex (or Claude) worker that starts cold, re-reading the task file and codebase from scratch — observable as input:output token ratios of 6-10× in the project's token_log. The subtask-handoff convention (rule 6) is the mitigation.

5. **Auto-skip shape-review on simple single-file scope.** When a task is `complexity: simple`, has ≤3 subtasks, touches a single file or single-directory surface, has no `depends_on`, and carries no high-risk keywords (auth, money, migration, destructive), the mechanical `coord-review` is sufficient. Skip `coord-shape-review` to avoid spending Codex tokens on what amounts to a proofreading pass.

6. **Subtask handoff convention (compression layer between cold workers).** Per Cognition's "share full agent traces, not just individual messages" principle and Anthropic's external-memory pattern in `anthropic.com/engineering/built-multi-agent-research-system` (LeadResearcher saving plans to Memory before context truncation): every subtask, on completion, MUST write a handoff file at a **deterministic path** — including S1 (no first-subtask exemption) and the final subtask (which has no in-task reader but feeds downstream `depends_on` tasks and the audit trail). No improvisation about location or naming, no skipping.

   **Handoff file path** (worktree-relative, deterministic from task-id + subtask-id):
   ```
   .coord/handoffs/<task-id>/S<N>.md
   ```

   Example: for task `2026-05-23-t5-admin-config-api`, subtask S1 writes to `.coord/handoffs/2026-05-23-t5-admin-config-api/S1.md`. The `.coord/handoffs/` directory is created on first use; the per-task subdirectory groups all handoffs for one task. Handoff files are committed alongside the subtask's code changes so the audit trail spans the task file + the handoff files.

   **Handoff file content** (5-15 lines):
   ```markdown
   # S<N> handoff — <task-id>
   Completed: YYYY-MM-DD HH:MM<offset>

   ## Files committed
   - path/to/file.ts: <one-line description>

   ## Exports / types / functions added
   - <name>: <signature or shape> — covers what the shaper's `Handoff to S<N+1>:` line in the task body specified

   ## Decisions made (non-obvious only)
   - <decision>: <why>

   ## Gotchas
   - <thing the next worker should know>

   ## Acceptance items closed
   - <which subtask bullets are now satisfied>
   ```

   **Read protocol for subtask S<N> (N > 1):** worker reads `.coord/handoffs/<task-id>/S<N-1>.md` before any other action. The subtask body in `## Scope notes` of the task file MUST include three lines:
   - `Writes handoff: .coord/handoffs/<task-id>/S<N>.md` — every subtask, no exemption (S1 and the final subtask included).
   - `Reads handoff: .coord/handoffs/<task-id>/S<N-1>.md` — every subtask after S1.
   - `Handoff to S<N+1>: <one sentence>` — every subtask except the last. The shaper writes this one sentence at shape time, naming the specific artifact (type signature, file, decision, partial output, key invariant) the next subtask needs to start without re-discovering it. The S<N> worker treats this sentence as the spec for what its handoff file's `## Exports / types / functions added` section must cover. Rationale: only the shaper has the cross-subtask picture; making the S<N> worker guess what S<N+1> needs is the failure mode this line removes.

   These three lines remove all worker-side improvisation about handoff location and content.

   Subtask sizing now reflects this: prefer **2-4 subtasks each grouping 2-3 related concerns** over 5+ subtasks of one bullet each. Fewer cold starts means less re-reading cost; the handoff file compresses what each worker needs to carry forward into ~10 lines. Subtask boundaries should align with natural local interfaces (file or module boundaries, not message-budget splits): a subtask edits one file or one tightly-coupled module group, completes, writes its handoff, and the next worker reads the handoff without re-grepping the whole codebase.

   The shaping rules' 10-message-per-tick ceiling (in `task-files-reference.md` § "Per-tick message ceiling") still applies as the wall-time variance fuse, but it is NOT a license to fragment subtasks below natural interface boundaries. If a single file's worth of work fits one subtask within the message ceiling, keep it as one subtask.

These rules are operationalized by `codex-loop`, `coord-shape`, and `coord-shape-review` skill files — the policy here is the rationale and the cross-agent commitment.

## YAGNI / KISS During Implementation

The two-agent review loop has additive bias; the implementation phase has its own. Agents writing code tend to add scaffolding the task did not ask for: defensive abstractions, premature configurability, error handling for impossible states, helpers used once, wrappers "for symmetry", and "while I'm here" refactors. Each individual addition is small and defensible; the accumulated effect is bloat that has to be re-simplified later.

**The default disposition is "no, unless it earns its place."** Before adding any line of code, abstraction, parameter, env var, helper, test, type guard, comment, or error path beyond what the task literally asked for, ask the explicit question: *do we really need this at all?* The burden of proof is on the addition, not on the omission. If the answer is "we might need it later", the answer is no — write the smaller version, ship it, and let the second real requirement drive the abstraction. If the answer is "it's a good practice in general", the answer is no — good practice in general is not a justification for this specific addition. If the answer is "for safety", check whether the unsafe state can actually occur given the existing type system and contracts; if it can't, the answer is no.

Both agents must apply these rules when implementing any coord task or interactive coding request:

1. **Do exactly what the task asked for. No more.** A bug fix touches only the bug. A new feature touches only the surfaces named in the task scope. Surrounding cleanup, formatting tweaks on untouched code, "while I'm here" refactors — none of these belong in the same change. If you notice unrelated debt, file a follow-up coord task, do not silently fold it in.

2. **No error handling for impossible states.** Validate at system boundaries only: user input (form bodies, URL params, file uploads), external APIs (HTTP fetches, database results that could be null), parsing untrusted data. Trust internal code: if function `A` always returns a non-empty array, do not check for empty inside function `B` that calls `A`. Trust framework guarantees: do not null-check React props with default values, do not type-guard a value the type system already proves. Catch blocks that re-throw or only log are dead weight — remove them.

3. **No abstractions for hypothetical second consumers.** A function used once is just code. Do not extract a helper before there is a second caller. Do not introduce an interface for a class with one implementation. Do not build a factory for a thing that's constructed in one place. Three similar lines is preferable to a premature abstraction; the pattern is allowed to repeat until the third copy reveals the right shape.

4. **No premature configurability.** Hardcoded constants are fine if the value is unlikely to change. Do not add env vars for things that have one correct value. Do not parameterize functions that have one caller passing one combination of arguments. Configurability earns its place when at least two real call sites genuinely need different values.

5. **No defensive wrappers.** Do not wrap third-party APIs "for testability" unless tests actually need to mock them — and even then, prefer dependency injection at the call site over a wrapper module. Do not wrap `console.log`, `fetch`, `crypto`, or other stdlib functions; tests can mock the originals.

6. **No comments explaining what the code does.** Well-named identifiers already do that. Comments earn their place only when the WHY is non-obvious: a hidden constraint, a subtle invariant, a workaround for a specific bug, behavior that would surprise a reader. Do not write comments that reference the current task, fix, or callers — those rot as the codebase evolves; put them in the PR description.

7. **No half-finished implementations.** If a path is in scope, finish it. Do not leave `TODO`, `FIXME`, "implement later", or stubs that return placeholders. If something is genuinely out of scope, omit it entirely and surface the gap in the task's findings.

8. **No tests for functionality not in scope.** A task that adds function `foo()` adds tests for `foo()`. It does NOT add tests for sibling function `bar()` that was already untested. Test debt is its own follow-up task — fold the surrounding test gap into a finding, not into this change.

When a finding from coord-shape-review, codex review, or interactive feedback proposes ADDING one of the above patterns, justify it against this list before accepting. The default disposition is "reject, simplify what's there." When in doubt: write the smaller version, ship it, and let the second real requirement drive the next abstraction.

## Review Findings Are Tasks, Not Edits

When any review tool (`codex-loop`, `ultrareview`, `/review-code`, `/review-security`, `/review-ui`, `/review-migration`, `/review-contract`, `/review-ops`, or the post-task coord reviewer) returns findings, the default response is to TRIAGE them into a `tasks/findings/<date>-<topic>.md` document and SHAPE the ones worth fixing into new coord tasks via `coord-shape`.

Inline fixes in the same session bypass the shaping bar (acceptance criteria, scope limits, non-negotiables, `max_turns`, `scope_budget`) and are the dominant compounding mode of additive bias: each finding looks small in isolation, lands without the YAGNI counterweight, and accumulates into the over-engineered surface that subtraction chains then have to undo. The discipline is asymmetric — write findings down (cheap), shape the worthwhile ones into tasks (cheap), and let the shaping bar pre-filter the rest.

Allowed inline fixes:

- Single trivial one-line typo fixes
- Reverting work the same session just landed when the reviewer caught a defect before commit
- Edits the user explicitly requests in the same turn ("just fix this one too")

Everything else flows through `coord-shape`. When in doubt, file the finding and shape later — the queue is cheap, additive bias is not.

This rule is operationalized in `${COORD_TOOLS:-$HOME/Projects/coord-wright}/skills/coord-shape/SKILL.md`'s opening preamble and applies to both Claude and Codex.

## One Default Flow

Use this when the request is broad, vague, or spans more than one surface:

1. `scope-brief`
2. `coord-shape`
3. `coord-split` when more than one surface remains
4. `review-code`, `review-ui`, `review-security`, `review-migration`, `review-contract`, or `review-ops`
5. Narrow specialist skills only when the scoped surface requires them
6. `review-integrate` when multiple agents, reports, or loops produced findings

Do not rely on the user remembering this. If a user starts with a broad ask inside a review skill, state the gate briefly and run `scope-brief` first.

## Post-Task Review Ladder

After coord marks a task `done`, match the change profile to the review depth. Composite skills (`/review-code`, `/review-ui`, `/review-security`, `/review-migration`, `/review-contract`, `/review-ops`) spawn parallel specialists — token-conscious; use the one(s) the change calls for. The coord built-in reviewer is a coverage layer (does the diff satisfy acceptance?) bounded by `max_turns`; the composite skills are the quality layer for non-trivial work.

| Task profile | After coord finishes, run |
|---|---|
| Trivial (one-liner, typo, docs) | Nothing — coord's built-in reviewer covers it |
| Small code-fix / refactor | Project verification gates only (per repo's `AGENTS.md` / `docs/bestWay.html`) |
| Medium change (multi-file, new logic) | Gates + `/review-code` |
| Frontend / UI change | Gates + `/review-ui` (Playwright + desktop+mobile screenshots) |
| Auth / secrets / data-sensitive | Gates + `/review-security` |
| Database migration / schema change (DDL, backfill, Flyway/Liquibase/Alembic) | Gates + `/review-migration`; cross-references `/review-contract` when columns are externally consumed |
| API / wire-format / handoff schema change (OpenAPI / protobuf / GraphQL / CLI flags / event payloads) | Gates + `/review-contract` |
| CI / Dockerfile / IaC / k8s / launchd-plist change | Gates + `/review-ops` |
| Dependency manifest change (package.json, requirements.txt, Cargo.toml, go.mod, Gemfile, composer.json) | Gates + `/review-code` (auto-runs `bin/dep-audit.sh` for vulns; license/SBOM surfaces inline). CVE deep-dive → `/review-security`. |
| High-risk (auth, migrations, trading, live ops, RCA) | Gates + `/review-code` + `/review-security`; consider `/ultrareview` before merging to main |
| Post-deploy handoff (server or browser layer touched) | Whatever the project's `AGENTS.md` handoff block mandates (e.g. `npm run test:e2e:smoke` + `/healthz` curl) |

Rules of thumb:

- Don't double up. `/review-code` already loads playwright-best-practices, vercel-react-best-practices, vercel-composition-patterns, and dispatches to `/review-migration` / `/review-contract` / `/review-ops` when those surfaces appear in the diff. Running them on top duplicates the dispatch. Pick the entry that matches the dominant surface.
- File findings as follow-up coord tasks, not in-place fixes — the queue stays the source of truth.
- `/ultrareview` is billed (cloud run) and more thorough than the slash-command composites. Reserve for high-stakes changes where the local pass left material doubt.
- **Default shaped coord tasks to no `roles.reviewer` unless the work is genuinely high-risk** (auth, money, migrations, destructive operations, multi-repo changes — the table above already covers these). Per-subtask review is over-eager — the coord built-in mechanical reviewer plus an end-of-feature integrated review on the cumulative diff is the preferred quality loop. Reviewing every small subtask compounds noise without finding real defects, and "spare token budget" is not a reason to multiply review rounds on simple work.
- **After 3+ tightly-coupled coord tasks land on the same module surface in <48 hours, run an integrated review across the cumulative diff before queuing more features on that surface.** Run `pr-review-toolkit:code-reviewer` and `pr-review-toolkit:silent-failure-hunter` in parallel (independent agents, ~3-4 min faster than sequential). Per-task reviews miss integration bugs that only surface across the cohort. Worked example (a 2026-05-24 admin sprint, ~10 coord tasks in 36 hours): per-task reviews passed cleanly, but the integrated review surfaced 17 unique findings — 2 CRITICAL + 7 HIGH + 5 MEDIUM/LOW + 2 NIT — because each defect crossed task boundaries (e.g. `isSessionRevoked` fail-open vs admin-login fail-closed only visible by comparing endpoints; `enforceInvite` throw becoming opaque 500 across four handlers only visible by looking at all four).

## Broad Ask Gate

Run `scope-brief` first when the ask has no concrete target.

A concrete target is at least one of:

- file or path
- route or screen
- component or symbol
- command
- PR, branch, commit, or task id
- explicit single surface

`scope-brief` must output:

- `scope`
- `mode`
- `stop rule`
- `verification`
- `output`
- `next route`

## Agent Escalation

Single-agent is the default.

Escalate to Claude+Codex review only when the result affects:

- global workflow or reusable skills
- security, auth, secrets, money, trading, or destructive operations
- more than one repository
- unresolved disagreement after a normal review

Use batch or multi-agent work only for independent lanes such as UI, backend, security, and docs. Each lane needs one surface, one output, and one verification path. Merge with `review-integrate`.

## Markdown Artifacts

Write a short markdown artifact when work involved:

- multiple agents
- review loops
- reusable workflow policy
- non-trivial findings
- follow-up task creation

Do not write artifacts for tiny fixes, simple status checks, routine summaries, or work already captured clearly in a coord task.

Paths:

- Repo-local reviews: `docs/archive/reviews/<topic>.md`
- Cross-project workflow policy/history: `~/Projects/coord-wright/docs/archive/reviews/<topic>.md`

Artifact shape:

- `Scope`
- `Findings` or `Decisions`
- `Follow-ups`
- `Verification`
- `Sources`
