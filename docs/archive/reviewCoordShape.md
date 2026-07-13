# Review loop

## Subject

**Artifact under review:** A proposal to improve the `coord-shape` skill in `~/Projects/coord-wright` (and its mechanical sibling `coord-review`) by adding a bounded Codex semantic shape-review loop.

**Convergence criterion:** Agree on the shape and integration of the proposed `coord-shape-review` skill plus the modification to `coord-shape`, including: skill scope, hook position in the coord-shape workflow, prompt template, transcript persistence, escape valves, skip rules, and cost containment.

---

### Motivation (concrete incident)

On 2026-05-21 Claude shaped a 4-task chain (`2026-05-21-java-oracle-user-activity-auditor-*`) via `coord-shape`. All 4 tasks passed `coord-review` with LGTM. The user then asked Codex to inspect them; Codex committed `473db9b coord: tighten Oracle auditor task shaping`, which fixed:

1. Missing frontmatter `acceptance:` list on all 4 tasks. (Body section was present, which is why `coord-review` accepted them, but `coord show --handoff` and the worker need the frontmatter list.)
2. Missing frontmatter `verify_commands:` on all 4 tasks. (Worker auto-runs these; without them the worker has nothing to gate on.)
3. Malformed `scope:` lists caused by passing `--scope "src/.../{a,b,c}/"` — the brace expansion artifacts produced broken YAML.
4. **T2 S3 interface mismatch**: subtask body said the modern path "uses already-collected `DBA_USERS.LAST_LOGIN`" but the declared interface `resolve(Connection, DbInfo)` had no parameter to receive that data. Codex changed it to `resolve(Connection, DbInfo, List<UserRow> users)`.
5. **T4 S3 `--dry-run` contradiction**: acceptance test said dry-run requires no DB, but the subtask body said dry-run "probes DbInfo" — which requires a JDBC connection (and therefore password resolution).
6. T2 non-negotiable "no DDL/DML" contradicted the design requirement to issue `ALTER SESSION SET CONTAINER` (which is technically a DDL session statement). Codex re-worded to "do not mutate database state; the only permitted non-query statement is the documented `ALTER SESSION SET CONTAINER`".

All six are **semantic shape defects**. The mechanical `coord-review` could not catch any of them because it only checks presence/format, not consistency.

---

### Current `coord-review` checks (mechanical, in `coord-wright/bin/coord-review`)

```
1. Plan section is present (non-placeholder).
2. Acceptance present in frontmatter list OR in `## Acceptance test` body section.
   ↑ fallback to body is the root cause of defect (1) above.
3. Subtasks parseable as `- [ ] **S<N>: Title**` checkboxes with metadata lines.
4. complexity ↔ reasoning_effort combo on whitelist.
5. model_claude / model_codex on allowlists.
6. High-risk keywords → require complexity:complex and review_rounds_max ≥ 2.
```

Not checked: `verify_commands` presence; `scope` list shape; cross-subtask interface contracts; acceptance ↔ subtask coverage; non-negotiable ↔ subtask-scope contradictions; "fast-path" subtasks (`--dry-run`, `--schema-only`, `--no-network`) versus what the acceptance test actually allows; whether the design doc referenced in the plan exists; whether the depends_on chain's outputs match this task's inputs.

---

### Current `coord-shape` workflow (in `~/.claude/skills/coord-shape/SKILL.md`)

```
1. Apply broad-ask gate (run scope-brief if scope is broad).
2. Interview the user with grill-me.
3. Check for duplicates and dependencies.
4. Prepare and create the task (`coord new --set-subtasks=@...`).
5. Fill remaining shaping fields (`coord update --set-plan=@... --set-acceptance-test=@...`).
6. Show the user (`coord next-subtask`, `coord show --handoff`).
7. Run coord-review (mechanical) — fix and re-run until LGTM.
```

---

### Proposal

#### A. New skill: `coord-shape-review`

**Location:** `~/.claude/skills/coord-shape-review/SKILL.md`

**Description:** "Run a bounded Codex semantic shape-review pass on a coord task. Catches semantic shape defects (interface mismatches between subtasks, missing frontmatter the worker consumes, acceptance ↔ subtask contradictions, non-negotiable contradictions, fast-path / dry-run contradictions, `scope:` list malformations) that `coord-review`'s mechanical checks miss. Run after `coord-shape` or before promoting any non-trivial task."

**Input:** task id (required).

**Skip rules:** abort cleanly (no Codex call) when any of:
- `complexity: trivial`
- `kind` ∈ {`docs`, `smoke-test`, `review`}
- task already has a `.coord/shape-reviews/<id>.md` transcript that ends in `CONVERGED` AND the task file's `updated:` is older than the transcript's last round
- `--brainstorm` is set (the task is intentionally still fuzzy)

**Workflow:**

```
1. Resolve task file (tasks/<id>.md) in canonical project root.
   Use `coord-project-root` for the cd, same as coord-shape.

2. Build the Subject context:
   - Task file content (frontmatter + body) verbatim
   - Each depends_on task's frontmatter + subtask list (so Codex can check contracts)
   - Every design doc referenced in the task plan body (regex `docs/*.md`,
     `~/Projects/*/docs/*.md`, etc.) — load full content if under 50KB,
     otherwise embed just the table-of-contents

3. Create transcript at `.coord/shape-reviews/<id>.md` with hardened Subject.

4. Round 1: `codex exec` with prompt:

   "Review the coord task in this transcript. This is a SHAPE review — not
    a code review and not a design review. Check for:

    a) Worker-consumable frontmatter: is `acceptance:` a non-empty list?
       Is `verify_commands:` a non-empty list? Body sections do NOT substitute.

    b) `scope:` list shape: each entry must be a real path or path glob.
       No shell brace-expansion artifacts (`{a,b,c}`), no semicolons.

    c) Cross-subtask interface contracts within this task: does S(N)'s
       declared input match S(N-1)'s declared output? Do subtask bodies
       describe data that the declared interfaces have no way to pass?

    d) Cross-task contracts: does this task's S1 consume what the prior
       (depends_on) task's last subtask actually exposed? If the prior
       task produced X but this task expects Y, surface it.

    e) Acceptance ↔ subtask coverage: every acceptance bullet should be
       produced by at least one subtask; every subtask should map to at
       least one acceptance bullet.

    f) Non-negotiables ↔ scope: do non-negotiables forbid something the
       subtask scope requires? (Example: 'no DDL/DML' but design needs
       `ALTER SESSION SET CONTAINER`.)

    g) Fast-path / dry-run contradictions: if a subtask describes a
       `--dry-run`, `--schema-only`, `--offline`, or similar mode, does
       the acceptance test agree on what that mode allows?

    h) Existence: every file/path mentioned in the plan or scope should
       exist or be explicitly named as something this task will create.

    Emit a numbered findings list. If none of (a)-(h) hold, emit a
    standalone `CONVERGED` line."

5. Round 1: Claude response.
   For each finding, accept (and apply via `coord update`) or dispute with
   evidence. Apply fixes via:
     coord update <id> --acceptance="..." \
                       --verify-commands="..." \
                       --scope="path1;path2;path3" \
                       --set-plan=@... \
                       --set-acceptance-test=@... \
                       --set-subtasks=@...
   Append response as `## Claude shape-review round N`.

6. If not converged and rounds < 2, go to round 2 with the updated task.

7. After exit: re-run `coord-review` to confirm mechanical checks still pass.

8. Report: link to transcript file, summary of fixes applied.
```

**Bounds:**
- Max 2 rounds (one Codex critique, one Claude fix-and-recheck). Shape gaps usually surface in round 1.
- Per-round timeout 4 min wall-clock for Codex.
- Transcript persisted to `.coord/shape-reviews/<id>.md` (under canonical project root, not the task worktree).

**Cost expectation:** ~$0.10–$0.30 per task (1–2 rounds × ~3–8k tokens). For a 4-task chain: ≤ $1.20. Compare to the cost of the manual fix-up that just happened (a full Codex agent round + commit + push + user attention).

#### B. Hook into `coord-shape` SKILL.md

Insert as a new step **6.5** (between "Show the user" and "Run coord-review"):

```
6.5 Run coord-shape-review for non-trivial tasks.
    Invoke the `coord-shape-review` skill with the task id. It catches
    semantic shape defects that the mechanical `coord-review` misses
    (interface contract mismatches across subtasks and depends_on tasks,
    missing frontmatter the worker consumes, acceptance ↔ subtask
    contradictions, non-negotiable contradictions, fast-path contradictions,
    malformed scope lists). If objections surface, apply fixes via
    `coord update` before the final coord-review pass.

    Skip rules: trivial complexity, kind in {docs, smoke-test, review},
    or `--brainstorm`. Codex is the reviewer; Claude (the shaper)
    accepts/disputes and applies fixes.
```

Step 7 (`Run coord-review`) is unchanged but now serves as the final mechanical gate after shape-review has settled.

#### C. Why not just bake this into `coord-review`?

Two reasons:

1. **Cost coupling.** `coord-review` is free, instant, mechanical Python. It runs on every task. Mixing it with a paid LLM call would either slow down every task or force a feature flag that splits the skill anyway.
2. **Reusability.** Some users will want to run shape-review standalone on tasks shaped by others, or as a pre-promote step. Keeping it as its own skill makes that possible without forcing it through coord-shape.

#### D. Open questions for this loop

- Should round 1 also load **completed** depends_on tasks' actual outputs (final findings + verify_commands result) when available, so Codex can check the contract against what *actually shipped* rather than the depends_on task's shape? Possibly defer to v2.
- Should the skill auto-detect referenced design docs by grep, or require the user/coord-shape to declare them explicitly via a new frontmatter field like `design_refs: [docs/auditScript.md]`? Auto-detect is simpler; explicit is more reliable. Recommend auto-detect with a fallback to explicit.
- Should the skill require the `codex` CLI to be present, or no-op gracefully if not? No-op gracefully — emit a `WARN` and let `coord-review` proceed.

---

### Verification of this proposal

If we apply this and rerun on the 4 Oracle audit tasks **at their pre-Codex-fix state** (revert commit 473db9b temporarily), the shape-review should surface:

- defects (1), (2): missing `acceptance` / `verify_commands` frontmatter
- defect (3): `scope:` brace-expansion malformation
- defect (4): T2 S3 interface contract mismatch
- defect (5): T4 S3 `--dry-run` contradiction
- defect (6): T2 non-negotiable vs `ALTER SESSION` requirement

If the shape-review surfaces fewer than 5 of those 6, the prompt template or the loaded context is insufficient. If it surfaces all 6 plus other false positives, tighten the prompt.

---

### Out of scope (explicit non-goals)

- Replacing `coord-review`. The mechanical checks stay; this is additive.
- Replacing the design phase (`codex-loop` on design docs). This skill reviews **task shape**, not the underlying design — the design is assumed already settled.
- Auto-fixing the task. Codex emits findings; Claude (the shaper) applies fixes through `coord update`. Same separation as `codex-loop`.
- Running on `pending`, `*-working`, or terminal-status tasks. Shape-review is a pre-runnable-queue gate.

## Codex round 1 (2026-05-21)

Substantive gaps remain.

1. The proposed repair path cannot fix one of the motivating defects today. `coord update` currently supports `--acceptance`, `--verify-commands`, `--set-plan`, `--set-acceptance-test`, `--set-subtasks`, and dependency/status/model fields, but it does not support `--scope`. The workflow's example fix command includes `coord update <id> ... --scope="path1;path2;path3"`, so the loop would identify malformed scope but then have no allowed `coord` command to repair it. Hand-editing the task file conflicts with the coord task-file rule. Either add and test `coord update --scope` first, or define another supported reshape path before claiming defect (3) is handled.

2. Step 6.5 is too late and also too early relative to the cheap gates. It is too late because current step 6 shows `next-subtask` and `show --handoff` to the user before the semantic review mutates the task. The user can see a handoff that is immediately made stale. It is too early because the LLM pass can waste a paid round on tasks with parse failures, invalid models, missing plan, or other cheap mechanical defects. A better order is: fill fields, run `next-subtask` plus the mechanical `coord-review` until the task is syntactically handoff-ready, run shape-review, re-run `coord-review`, then show/report the final handoff. That preserves `coord-review` as both a preflight and final invariant check.

3. The skip rules need an explicit eligibility gate, not just complexity/kind filters. The proposal says running on `pending`, working, or terminal tasks is out of scope, but the workflow does not enforce that. The eligible set should be stated precisely, for example `status: shaping` plus possibly held runnable drafts with `pickup_hold: true`; `needs-brainstorming` should normally be skipped unless the user explicitly asks for a review of the ambiguity checklist. Also, "`--brainstorm` is set" is not a durable task property in the current task file shape; the reviewer should key off status and body shape, not a creation-time CLI flag that may not be persisted.

4. The broad kind skips will skip some tasks that most need this review. Skipping all `docs`, `smoke-test`, and `review` tasks is too coarse. A docs task can change coord policy, a review task can carry a multi-task contract, and a smoke-test task can have dangerous environment or dependency assumptions. Prefer a cheap-risk rule: skip only trivial, single-subtask tasks with no `depends_on`, no explicit reviewer/architect roles, no high-risk keywords, and no design references. Treat `kind` as a signal, not a hard bypass.

5. The prompt likely catches the six named oracle defects if the right context is loaded, but it has known false positives and misses. It requires non-empty `verify_commands` even though coord also has `verify_profile`, and some review/docs tasks may have an acceptance-only human gate. It checks file existence for every plan or scope path, which will false-positive on legitimate create-new paths unless the prompt explicitly distinguishes "must already exist" from "task creates this". It does not compare frontmatter `acceptance` against the body `## Acceptance test` when both exist and contradict each other. It also frames non-negotiable checks mostly against subtask scope, but the Oracle `ALTER SESSION` issue depends on comparing task text with the loaded design doc.

6. Dependency context needs sharper boundaries. Loading every direct dependency's frontmatter plus subtask list is enough for a pre-runnable chain shape check, but it is not enough for completed dependencies where actual findings changed the delivered contract. Conversely, if dependency task files are loaded verbatim, the reviewer may report missing frontmatter or malformed scope in the dependency while reviewing the target task, creating duplicate or off-target findings. The prompt should say: report dependency defects only when they break the target task's declared inputs, and for completed dependencies load a capped final handoff/finding summary if available. Full transitive-chain loading should be opt-in or capped.

7. Design-doc discovery is under-specified. Searching only the plan body misses references in Scope notes, Rules, Acceptance test, and dependency findings. A regex like `docs/*.md` is also ambiguous between glob syntax and regex syntax and can accidentally overmatch or undermatch. Use a deterministic extractor for Markdown links, backticked repo-relative paths, and absolute paths under the canonical project root; expand globs with a hard file-count and byte cap; and record skipped docs in the transcript. A future `design_refs` field is useful, but v1 should not claim reliable design-doc context unless the fallback rules are exact.

8. Transcript caching should use a content hash, not timestamp comparison. The proposal says skip when the task `updated:` is older than the transcript's last round. That is fragile across timezone formatting, manual edits, clock skew, and transcript append behavior. Store the task content hash used for the review, including dependency status/hash inputs, in the transcript subject. Skip only when the current hash matches the reviewed hash and the final transcript state is a positive result. Also note that `.coord/shape-reviews/` is ignored in this repo, so the cache is local best-effort, not cross-machine state.

9. The Codex invocation mechanics need to mirror `codex-loop` more closely. The proposal does not specify `--cd` pinned to the canonical project root, sandbox mode, absolute transcript/log paths, how to verify that Codex actually appended the section, where stderr/stdout logs go, or what happens if the transcript is outside the writable root. Without those mechanics, the loop can silently produce no appended round or write logs into the wrong checkout.

10. The no-Codex escape valve is acceptable only if it is visibly a degraded path. "No-op gracefully" must not leave a transcript that looks reviewed, must not satisfy the semantic gate, and must be reported in the final coord-shape output as "semantic shape-review skipped: codex CLI unavailable". If this skill is invoked explicitly by a user, unavailable Codex should probably fail closed instead of silently falling back to mechanical review.

11. `--shape-override` handling is missing. The proposal asks about it but never defines behavior. Existing override reasons, when present, should be included in the subject and reviewed as "is this override targeted and still justified?", not treated as a skip. Separately, the current `coord` parser does not appear to expose a `--shape-override` argument even though docs mention it, so implementation should verify that flag before building workflow rules around it.

12. Some motivating claims should move to cheap deterministic checks rather than the paid semantic loop. Missing frontmatter `acceptance`, missing frontmatter `verify_commands` or `verify_profile`, and malformed `scope` entries are mechanically detectable. If these are now required for handoff quality, add them to `coord-review`, `coord promote`, or a small preflight inside `coord-shape-review`. Keeping them only in the semantic prompt means skipped/degraded runs still allow the exact incident class through. Also, the claim that the worker auto-runs `verify_commands` is not supported by the current worker code I inspected; the worker auto-handles `verify_profile` artifact capture/verification, while `verify_commands` are exposed in handoff/prompt context and used by agents/watchdog logic.

13. Cost containment is not yet demonstrated. The token estimate of 3-8k per round is too low for the proposed context in the Oracle case: `docs/auditScript.md` alone is about 32 KB before adding the task file, dependency tasks, and prior transcript rounds. The 50 KB "load full doc" threshold can make a single design doc exceed the whole estimated round budget. Before keeping a dollar claim, measure the four-task oracle run with prompt-size logging and record p50/max input tokens. Also define timeout behavior: a 4 minute Codex timeout can produce partial output, no output, or a nonzero exit; the workflow needs exact retry/skip/fail rules.

14. The v1/v2 line should be tightened. Reasonable v1: direct dependencies only, deterministic mechanical preflight, deterministic design-ref extraction with caps, no auto-fix by Codex, and a local ignored transcript cache keyed by content hash. I would not defer completed-dependency findings entirely if the skill is advertised as checking cross-task contracts; load a capped final handoff for completed direct dependencies in v1. Reasonable v2: explicit `design_refs`, transitive dependency summaries, historical shipped-output comparison, and measured token-based resume/caching optimizations.

15. The verification plan would not work exactly as written. I verified the four pre-fix task blobs from `473db9b^` still pass the current `coord-review`, so they are valid oracle inputs for this proposal. But "revert commit 473db9b temporarily" is unsafe and underspecified in the shared main checkout; use `git show 473db9b^:<task>` into a scratch directory or a disposable worktree. The harness should clear any local shape-review transcript cache, run each of the four task ids independently, and define expected findings per target task. Otherwise dependency loading can duplicate predecessor findings, and the "fewer than 5 of 6" threshold is too subjective to tell prompt failure from target/dependency attribution failure.

## Claude round 1 (2026-05-21)

All 15 findings are substantive and accepted. Per-finding resolution:

**1. `coord update --scope` does not exist.** Confirmed by `coord update --help`: the flag is absent. Two-step fix in v1: (a) extend `coord` with `--scope` on the `update` subcommand (~10 lines next to the existing `--tags` handling — small, low-risk change); (b) if (a) is not in scope, the skill must report malformed `scope:` as a finding the user must hand-fix (with a one-shot `sed`/editor instruction), since direct task-file editing violates the coord rule. Recommend (a) — added as a prerequisite to landing this skill.

**2. Step 6.5 ordering is wrong.** Accepted. Revised coord-shape order:
- 4. Create task (`coord new`)
- 5. Fill plan/acceptance/verify_commands/scope frontmatter
- 6. Run mechanical `coord-review` (cheap preflight; fix and re-run until LGTM)
- 7. Run `coord-shape-review` (paid semantic; fix and re-run until CONVERGED)
- 8. Re-run mechanical `coord-review` (final invariant — semantic fixes must not break mechanical gates)
- 9. Show user (`coord next-subtask`, `coord show --handoff`)

`coord-review` becomes both preflight and final invariant.

**3. Eligibility gate by status.** Accepted. Skill operates only on tasks with `status` ∈ {`shaping`, `needs-review`} or `pickup_hold: true` runnable drafts. Refuses to run on `pending`, `*-working`, `done`, `archived`. Skips `needs-brainstorming` unless the user explicitly invokes `coord-shape-review --include-brainstorm <id>`. Drops the `--brainstorm` skip rule (it's a creation-time CLI flag, not a durable property) in favor of detecting brainstorm-stage tasks via `status` + body shape (no concrete subtasks).

**4. Kind-based skips are too coarse.** Accepted. Replace with a cheap-risk predicate:
```
skip iff (
    complexity == 'trivial' AND
    subtasks <= 1 AND
    depends_on is empty AND
    roles.reviewer in {None, 'skip'} AND
    roles.architect in {None, 'skip'} AND
    no high-risk keywords in task/tags AND
    no design refs detected in body
)
```
`kind` becomes a signal in the prompt (so Codex weights checks differently for `docs` vs `code-fix`), not a hard bypass.

**5. Prompt false positives and misses.** Accepted. Six prompt revisions:
- (a) Require `acceptance:` AND (`verify_commands:` OR `verify_profile:` OR concrete `## Acceptance test` section). Match the existing `coord` validator on line 1028 of `bin/coord`.
- (b) When `kind` ∈ {`docs`, `review`} and the acceptance body explicitly marks `human-gate: true`, do not flag missing `verify_commands`.
- (c) Distinguish "must already exist" paths (referenced as design source) from "task creates" paths (under `scope:` or new files in subtask bodies). Only verify existence for the first class.
- (d) Cross-check frontmatter `acceptance:` against body `## Acceptance test` — when both present, surface contradictions.
- (e) When a design doc is loaded, prompt explicitly compares non-negotiables against design requirements (the oracle `ALTER SESSION` case).
- (f) Make the prompt aware that `verify_commands` is exposed via `coord show --handoff` to agents/watchdog, while `verify_profile` drives worker artifact capture — so it doesn't conflate them.

**6. Dependency context boundary.** Accepted. v1 rules:
- Load direct `depends_on` task files only (no transitive).
- For each dependency, embed: frontmatter (full), subtask titles + complexity (titles only, not bodies, unless the dependency is incomplete and its full subtask body matters for the contract check).
- For completed dependencies, also embed the latest `coord show --handoff` output (capped at 4 KB per dep).
- Prompt explicitly says: "Report a defect in a dependency only when it breaks THIS task's declared inputs. Do not surface internal defects of a dependency unless they propagate."

**7. Design-doc discovery under-specified.** Accepted. Deterministic extractor:
- Scan all body sections (Plan, Scope notes, Non-negotiables, Acceptance test, Rules).
- Match: markdown links `[text](path)`, backticked paths, absolute paths under canonical project root.
- Resolve relative to project root. Reject paths outside the worktree or with `..` traversal.
- Apply hard caps: max 5 files, max 50 KB combined bytes. If over, prefer files in `docs/` first; record skipped paths in the transcript.
- v1: auto-detect only. v2: add optional `design_refs:` frontmatter list for explicit override.

**8. Hash-based caching, not timestamp.** Accepted. Subject section stores:
- `task_hash:` SHA256 of the canonical task file content (without trailing whitespace)
- `deps_hash:` SHA256 of concatenated dependency content
- `design_hash:` SHA256 of concatenated loaded design docs
Skip rule: current trio matches previous trio AND last round was CONVERGED. Note: `.coord/shape-reviews/` is best-effort local cache only (already gitignored in this repo).

**9. Codex invocation mechanics mirror codex-loop.** Accepted. Required mechanics:
- `--cd <canonical-project-root>` (from `coord-project-root`)
- `--sandbox workspace-write`
- Absolute transcript path in the prompt
- Absolute `tee` log path under `<project-root>/.coord/codex-runs/<timestamp>-shape-review-rN.log`
- Read the transcript after each Codex round; if the round section was not appended (zero new content under the expected heading), retry once; if still empty, fail and surface to the user.

**10. No-Codex escape valve.** Accepted. Two paths:
- **Implicit call from coord-shape**: emit `WARN: coord-shape-review skipped — codex CLI unavailable` to stderr, mark the coord-shape report as `shape-review: SKIPPED`, do NOT write any transcript file. Step 8 (final `coord-review`) still runs.
- **Explicit user call**: fail closed with exit 2, message `codex CLI not found; install codex or invoke from a host that has it`.

**11. `--shape-override` handling.** Accepted. Verified that `shape_override` exists as a recognized frontmatter field (line 123 of `bin/coord`) but the CLI flag wiring requires checking. Behavior: if the task frontmatter has a `shape_override:` reason string, embed it in the transcript Subject and prompt Codex with: "This task has a recorded shape-override reason: '<reason>'. Treat this not as a skip but as a claim to validate — is the override still targeted, still justified, and does the task still need shape-review of the non-overridden axes?" Verify CLI surface (`coord new --shape-override`) before relying on it; if absent, skip this branch in v1.

**12. Move cheap checks out of the paid loop.** Accepted. Preflight in `coord-shape-review` BEFORE Codex invocation (and also proposable upstream into `coord-review` as a separate change):
- `acceptance:` frontmatter list non-empty (no body-only fallback for new tasks)
- `verify_commands:` OR `verify_profile:` OR explicit `human-gate: true` marker present
- `scope:` list entries each match `^[A-Za-z0-9_./@-]+$` plus optional `*` glob — reject `{`, `;`, whitespace
- `depends_on:` task files all exist
If preflight fails, skip the paid Codex round; emit findings directly from the preflight. Also: factual correction baked in — `verify_commands` is consumed by agents/watchdog through `coord show --handoff`, while `verify_profile` drives worker artifact capture. The prompt template (#5f) is updated to reflect this.

**13. Cost containment.** Accepted. Concrete caps for v1:
- Max 5 design files; max 50 KB combined design bytes; max 30 KB task file; max 8 KB per dependency embed.
- If aggregate input > 120 KB, fall back to loading dependency frontmatter only (no subtask bodies) and design table-of-contents only. Record fallback in transcript.
- Round wall-clock timeout 4 min. On timeout/empty output: log to `.coord/codex-runs/`, retry once, then surface as `SKIPPED — timeout` (do not silently pass).
- Cost claim in the proposal is removed until measured. Verification plan (#15) now requires a real measurement on the oracle 4-task run.

**14. v1/v2 line tightened.** Accepted. Final split:
- **v1**: direct deps only; mechanical preflight (#12); deterministic design-ref extractor with caps (#7); hash-keyed local cache (#8); load capped final-handoff for completed direct deps (#6); no Codex auto-fix (Codex emits findings; Claude applies via `coord update`).
- **v2**: explicit `design_refs:` frontmatter; transitive dependency summaries; historical shipped-output comparison; measured token-based caching/`codex resume`.

**15. Verification plan rewritten.** Accepted. Revised harness:
- Create scratch dir `/tmp/coord-shape-review-verify/` per task id (not in main checkout, not in a tracked worktree).
- Extract pre-fix task content: `git -C $HOME/Projects/example-app show 473db9b^:tasks/<id>.md > /tmp/coord-shape-review-verify/<id>.md`.
- Clear any `.coord/shape-reviews/<id>.md` for that id.
- Run the shape-review skill against each id independently.
- Expected findings per task (predicted from defect inventory):
  - T1 skeleton: defects (1), (2), (3) — three findings minimum
  - T2 database access: defects (1), (2), (3), (4), (6) — five findings minimum
  - T3 classification: defects (1), (2), (3) — three findings minimum
  - T4 CLI integration: defects (1), (2), (3), (5) — four findings minimum
- Per-task expected findings list; "≥ N of M overall" is dropped.
- Also record: false positives, p50 + max input tokens, p50 + max wall-clock. Below 10% false-positive rate is the acceptance bar.

---

All 15 are accepted with concrete v1 resolutions. No remaining open questions on my side; the proposal now has a single, internally-consistent shape:

1. Preflight (mechanical, free) catches what shouldn't reach Codex.
2. Codex semantic loop catches what the preflight can't (interface mismatches, contradictions, design-vs-task drift).
3. Hash-keyed local cache avoids re-running on unchanged tasks.
4. The flow inserts at coord-shape step 7 (between mechanical preflight and final mechanical invariant), not at step 6.5.
5. `coord update --scope` lands as a small prerequisite change to coord-wright.

This round is substantive — not converged. Codex should verify the resolutions are internally consistent and complete, or raise remaining gaps.

## Codex round 2 (2026-05-21)

Substantive gaps remain, but they are now narrow.

1. The #12 preflight is not quite implementable as written. The `human-gate: true` escape is not pinned to a parse location or spelling: frontmatter field, YAML inside `## Acceptance test`, or a literal body line would all fit the prose. The scope rule also says entries match `^[A-Za-z0-9_./@-]+$` "plus optional `*` glob", which is not a precise accepted grammar. Define the exact regex: whether `*` may appear anywhere, whether `**` is allowed, whether a leading `/` or `@` is intentional, and whether matching globs must expand to at least one path. Without that, two implementations can pass/reject different task files while both claiming to follow #12.

2. #12 and #15 conflict on the Oracle verification case. #12 says a preflight failure skips the paid Codex round and emits only preflight findings. The pre-fix Oracle tasks all fail preflight on missing frontmatter and malformed scope, so the semantic reviewer would not run on T2/T4 in that invocation and cannot surface the interface mismatch, non-negotiable/design contradiction, or dry-run contradiction. #15 still expects those semantic findings from a direct run against the raw pre-fix blobs. The harness needs two phases: first validate raw preflight defects, then create normalized fixtures that fix only `acceptance`, verifier metadata, and `scope` while preserving the semantic bugs, and run Codex on those.

3. The #15 harness still does not cleanly separate prompt failure from context-loading failure. It should assert the transcript/context manifest before evaluating findings: loaded design paths include `docs/auditScript.md`; loaded/skipped docs are recorded; dependency ids and hashes are recorded; fallback-to-TOC did or did not happen. If a required finding is missing and the manifest lacks the design doc or dependency context, classify it as context-loading failure. If the manifest is complete and the finding is still missing, classify it as prompt/reasoning failure. Right now both collapse into "expected finding missing."

Checks that look settled: the revised order avoids the stale user-handoff window by putting `next-subtask` / `show --handoff` after semantic fixes and the final mechanical invariant; #7's caps keep the Oracle design doc loaded (`docs/auditScript.md` is 32,098 bytes, under the 50 KB combined design cap, and it is the only detected design file); #8's dependency hashing handles dependency-only edits provided the stored hash is taken from the exact dependency material embedded for the successful final review round.

## Claude round 2 (2026-05-21)

All 3 findings accepted with concrete resolutions.

**1. Preflight precision (human-gate location + scope grammar).** Pinned exactly:

- **`human_gate` location**: a top-level frontmatter field, spelled `human_gate: true` (snake_case, matching `pickup_hold` / `shape_override`). The preflight reads only from frontmatter. A `human-gate:` line in the body, or a YAML block inside `## Acceptance test`, does NOT count and the preflight will still require `verify_commands` / `verify_profile`.

- **`scope:` entry grammar** (each list item validated independently):
  - Allowed character class: `[A-Za-z0-9_./@*-]`
  - Disallowed substrings (any occurrence rejects the entry): `..` (path traversal), `;`, `{`, `}`, whitespace (incl. tab), `\\`
  - Disallowed leading character: `/` (absolute paths are out — entries are repo-relative)
  - Glob rules: `*` and `**` are permitted only as full path segments (between `/` separators or at start/end). A bare `*` entry is rejected. `**` is only allowed as a path segment (`**/`, `/**`, `/**/`).
  - Glob expansion validation: at preflight time, each entry containing a glob is expanded against the worktree; if it expands to zero paths AND the entry is not in a `task creates` list, surface a finding (not a hard failure — the task may legitimately create the path). Non-glob entries that don't currently exist follow the same "must exist" vs "task creates" rule (#5c).
  - Examples accepted: `pom.xml`, `src/main/java/com/example/audit/cli/`, `src/test/**/*Test.java`, `docs/*.md`
  - Examples rejected: `src/{a,b}/`, `src/../escape/`, `/etc/passwd`, `src;test`, `*`, `src/  /test`

**2. #12/#15 conflict — two-phase verification harness.** Codex correctly identified that preflight short-circuits the paid round, so the verification cannot reach semantic findings (4)(5)(6) by running raw pre-fix blobs. Revised harness:

**Phase 1 — preflight assertion on raw pre-fix blobs:**
- Extract: `git -C $HOME/Projects/example-app show 473db9b^:tasks/<id>.md > /tmp/coord-shape-review-verify/<id>-raw.md`
- Run preflight ONLY (no Codex call)
- Assert per task:
  - T1-raw: preflight surfaces defects (1) missing `acceptance:` frontmatter, (2) missing `verify_commands:`, (3) malformed `scope:` (T1 had `{cli,config,util}/` brace expansion)
  - T2-raw: preflight surfaces (1), (2), (3) (had `{collect,util}/` brace expansion)
  - T3-raw: preflight surfaces (1), (2), (3) (had `{classify,report}/` brace expansion)
  - T4-raw: preflight surfaces (1), (2), (3) (had `{cli,integration}/` brace expansion)
- No Codex tokens spent in Phase 1.

**Phase 2 — semantic assertion on normalized fixtures:**
- For each pre-fix task, mechanically apply the minimum frontmatter fixes that the preflight would surface — `acceptance:` list, `verify_commands:` list, properly-listed `scope:` — preserving the body semantic bugs.
- Save as `/tmp/coord-shape-review-verify/<id>-normalized.md`. A small fixture-builder script handles this; it operates on the YAML frontmatter only, never touches body content.
- Run the full shape-review skill (including Codex) on each `-normalized.md`.
- Assert per task:
  - T1-normalized: CONVERGED (no semantic bugs left after normalization)
  - T2-normalized: surfaces (4) interface mismatch in S3 and (6) `ALTER SESSION` non-negotiable contradiction. False positives below the 10% bar.
  - T3-normalized: CONVERGED (no semantic bugs left)
  - T4-normalized: surfaces (5) `--dry-run` contradiction in S3. False positives below 10%.
- Phase 2 is the actual cost-and-quality measurement.

**3. Manifest assertion to separate prompt failure from context-loading failure.** Accepted. The skill writes a `## Context Manifest` section into the transcript BEFORE the first Codex invocation. Schema:

```markdown
## Context Manifest

- task_path: tasks/<id>.md
- task_hash: <sha256>
- task_bytes: <int>
- depends_on:
  - id: <dep-id-1>
    path: tasks/<dep-id-1>.md
    hash: <sha256>
    bytes: <int>
    status: <status>
- design_refs:
  - path: docs/auditScript.md
    bytes: 32098
    loaded: full
  - path: docs/skipped.md
    bytes: 65000
    loaded: skipped (over per-file cap)
- aggregate_input_bytes: <int>
- fallback_to_toc: false
- codex_invocation:
  - cd: $HOME/Projects/example-app
  - sandbox: workspace-write
  - log_path: .coord/codex-runs/<ts>-shape-review-r1.log
```

The verification harness reads the manifest before evaluating findings. Classification:
- Expected design path NOT in `design_refs[loaded=full|toc]` → **CONTEXT_LOADING_FAILURE** (extractor bug — fix the regex/glob logic)
- Expected dependency NOT in `depends_on` → **CONTEXT_LOADING_FAILURE**
- `aggregate_input_bytes` > 120 KB and `fallback_to_toc: true` → flag as **DEGRADED_CONTEXT**; missing semantic findings get a tolerance grace
- All expected context loaded AND expected finding missing → **PROMPT_REASONING_FAILURE** (tighten the prompt)
- All expected context loaded AND expected finding present → **PASS**

The harness output ends with a per-finding classification table so the user can see *why* a finding was missed when one is, not just *that* it was missed.

---

All 3 round-2 gaps now have implementable resolutions. The proposal is now:
- v1 mechanically precise (preflight regex pinned, manifest format pinned, two-phase verification pinned)
- Codex-loop pattern (subject hardening + bounded rounds + persisted transcript) reused verbatim
- A one-line prerequisite change to `coord-wright` (`coord update --scope`)
- Cost claim removed pending Phase-2 measurement
- Hash-keyed local cache, deterministic design-ref extractor with caps, capped completed-dep handoffs

This round is substantive — not converged. Codex should verify the round-2 resolutions are internally consistent and complete, or raise remaining gaps.

## Codex round 3 (2026-05-21)

Substantive gaps remain.

1. The pinned scope grammar is still internally inconsistent. The rule says `*` and `**` are permitted only as full path segments, but the accepted examples include `src/test/**/*Test.java` and `docs/*.md`; in both cases `*` appears inside a filename segment, not as the whole segment. Either allow ordinary shell-style filename globs within a segment, or change the examples. The same rule also references a `task creates` list without defining where that list lives or how it is extracted, so two implementations can disagree on whether a missing scoped path is a real defect or a create-new file.

2. `human_gate: true` is now pinned to frontmatter, but there is no lawful way to set it through the current coord CLI. `coord new` and `coord update` expose `acceptance`, `verify_commands`, `verify_profile`, `pickup_hold`, and `scope` on new only, but no `human_gate` flag. Since task-file hand editing is disallowed, the escape hatch needs a companion CLI surface such as `coord new --human-gate` and `coord update --human-gate[=true|false]`, or it should be dropped from v1.

3. The two-phase harness is directionally right, but Phase 2 does not say how the full skill reviews `/tmp/.../<id>-normalized.md`. The skill input is still a task id resolved as `tasks/<id>.md` under the canonical project root; a loose `/tmp` Markdown file will be ignored unless the harness creates a disposable project root with `tasks/<id>.md` and runs with that cwd/config, or the skill adds an explicit test-only `--task-file` mode. Without that, the semantic run can accidentally review the live fixed task instead of the normalized fixture.

4. The Context Manifest is not yet precise enough for deterministic harness assertions. It is shown as Markdown bullets rather than a parseable YAML/JSON block, and the allowed `design_refs.loaded` values are inconsistent: the schema shows `full` and `skipped (...)`, while the classifier expects `full|toc`. It also does not define sort order, repo-relative path normalization, whether `bytes` means source bytes or embedded bytes, or whether dependency `hash` covers the full task file, the embedded subset, or the capped handoff material. Those details matter because the cache and the failure classifier both depend on exact manifest equality.

5. The `coord update --scope` prerequisite itself looks safe, but the resolution understates the actual contract. It should mirror `coord new --scope`: add the update parser flag, update only frontmatter `scope`, use the existing `as_list` normalization, clear the field on an empty update, leave `## Scope notes` untouched, and include regression coverage for comma-separated values, `@file` input, and an empty clear. Implemented that way it should not break pickup, handoff rendering, subtask parsing, or worker state transitions.

Checks that remain settled: the revised coord-shape ordering avoids stale handoffs; the raw-vs-normalized two-phase split is the right verification structure once the fixture entry point is pinned; and adding a scope update path to coord-wright is a valid prerequisite rather than a conceptual blocker.

## Claude round 3 (2026-05-21)

All 4 findings accepted. Resolutions:

**1. Scope grammar — allow shell-style filename globs within segments + drop the undefined "task creates" list.**

Revised grammar (gitignore-style, the standard most users expect):

- Allowed character class per character: `[A-Za-z0-9_./@*-]`
- Disallowed substrings: `..`, `;`, `{`, `}`, `\\`, whitespace
- Disallowed leading character: `/`
- Glob semantics: `*` matches any run of characters within a single path segment (no `/`); `**` matches across `/` boundaries and is permitted only as a full path segment (`**/`, `/**`, `/**/`, leading `**/`, trailing `/**`). `*` may appear inside a filename segment (e.g. `*.md`, `*Test.java`); a bare `*` entry (a single character) is rejected as too broad.
- Per-entry minimum length 2 characters after the disallow checks.

Accepted (matches v1 oracle scopes):
- `pom.xml`, `README.md`
- `src/main/java/com/example/audit/cli/`
- `src/main/java/com/example/audit/Main.java`
- `src/test/**/*Test.java` (`**` segment + filename glob in trailing segment — both legal)
- `docs/*.md` (filename glob in trailing segment)

Rejected:
- `src/{a,b}/` (brace), `src/../escape/` (traversal), `/etc/passwd` (absolute), `src;test` (separator), `*` (bare wildcard), `src/  /test` (whitespace)

The undefined "task creates" list is dropped in v1. Replacement rule for the "must exist vs will create" distinction in the existence check (#5c):
- If a `scope:` entry contains a glob (`*` or `**`), the preflight does not flag it on zero-match (globs legitimately match new files).
- If a non-glob `scope:` entry does not exist on disk, the preflight searches the task body (Plan + Subtasks) for the same literal path or its basename within 200 characters of a verb in {`create`, `creates`, `add`, `adds`, `write`, `writes`, `new`, `produce`, `produces`}. Match → treated as "task creates"; no finding. No match → finding.
- This is a heuristic, not a contract, but it covers the common case (`src/main/.../Foo.java` mentioned in S2 as "Implement com.example.audit.collect.Foo …" → match on basename `Foo.java` near "Implement").

**2. `human_gate` deferred to v2.**

Accepted. Drop `human_gate:` from v1 entirely. The preflight in v1 requires:

```
acceptance (frontmatter list, non-empty)  AND
(verify_commands non-empty  OR  verify_profile non-empty)
```

The existing `shape_override:` frontmatter is the escape valve for tasks with no machine-verifiable gate. The user records the reason via the existing override path; the preflight respects it the same way `coord new` does today. v2 can add `coord update --human-gate` if the use case proves real, but the v1 implementation has no dependency on a field with no CLI surface.

**3. Phase 2 fixture entry point — add `--task-file` mode to the skill.**

Accepted. Cleaner than a disposable project root. The skill gains a test-only mode:

```
coord-shape-review --task-file <path-to-md> \
                   [--design-refs <path1>,<path2>,...] \
                   [--depends-on-file <dep-path1>,...] \
                   [--no-cache]
```

Constraints on this mode:
- All paths must be absolute or under the cwd.
- Skips status/eligibility checks (the file may not even live under a `tasks/` directory).
- Writes the transcript to the same directory as the input file: `<dir>/<basename>-shape-review.md`.
- Documented as for verification harnesses only; the normal path is by task id.

Phase 2 harness then uses:
```bash
for id in <T1..T4>; do
  coord-shape-review --task-file /tmp/coord-shape-review-verify/${id}-normalized.md \
                     --design-refs /tmp/coord-shape-review-verify/auditScript.md \
                     --depends-on-file <upstream-fixture-paths> \
                     --no-cache
done
```

The skill never touches `tasks/<id>.md` in main when invoked via `--task-file`. No ambiguity.

**4. Context Manifest schema — pin to YAML with full field semantics.**

Accepted. The manifest is now a fenced YAML block (not Markdown bullets), parseable by `yaml.safe_load`. Full schema:

````markdown
## Context Manifest

```yaml
schema_version: 1
task:
  path: tasks/<id>.md          # repo-relative, forward-slash, no ./
  task_hash: <sha256-hex>      # SHA256 of full file as written to disk (frontmatter + body, LF-normalized, no trailing whitespace stripped)
  source_bytes: <int>          # bytes on disk
  embedded_bytes: <int>        # bytes embedded into transcript (= source_bytes for task itself; may differ for design docs under fallback)
depends_on:                    # sorted by id ascending; empty list if none
  - id: <dep-id>
    path: tasks/<dep-id>.md
    status: <one of: shaping|needs-review|pending|claude-working|codex-working|done|archived>
    hash: <sha256-hex>         # SHA256 of full dependency task file as written to disk
    source_bytes: <int>
    embedded_bytes: <int>      # if status=done, may be the capped handoff bytes (~4 KB); otherwise full
    embed_mode: <full | frontmatter_only | handoff_capped>
design_refs:                   # sorted by path ascending; empty list if none
  - path: docs/<file>.md
    source_bytes: <int>
    embedded_bytes: <int>
    loaded: <full | toc | skipped>
    skip_reason: <string or null>   # required when loaded=skipped; null otherwise
aggregate:
  total_source_bytes: <int>
  total_embedded_bytes: <int>
  fallback_to_toc: <bool>           # true iff aggregate_source exceeded 120 KB and TOC fallback was applied
codex_invocation:
  cd: <absolute-path>
  sandbox: workspace-write
  log_path: <absolute-path-under-.coord/codex-runs>
preflight:
  ran: <bool>
  passed: <bool>
  findings: [<short-string>, ...]   # empty list if passed=true
```
````

Field semantics (pinned):
- `task_hash` and dependency `hash`: SHA256 hex of the file's bytes-on-disk after LF normalization (no whitespace trimming, no trailing-newline removal). Same hash function for tasks and design docs.
- Path normalization: all paths in the manifest are repo-relative with forward slashes; no `./` prefix; no trailing slash on files; trailing slash preserved on directories listed in `scope:`.
- Sort order: `depends_on` by `id` ASCII ascending; `design_refs` by `path` ASCII ascending; `preflight.findings` in detection order.
- `bytes` semantics: `source_bytes` is the on-disk size; `embedded_bytes` is the count of bytes actually inserted into the transcript (after any truncation/TOC reduction).
- `embed_mode` enum is exhaustive — no other values allowed.
- `loaded` enum is exhaustive: `full` (entire file embedded), `toc` (only headings + first paragraph per section, used under fallback), `skipped` (not embedded at all).
- `skip_reason` is required iff `loaded=skipped`; standard reasons: `over per-file cap`, `over aggregate cap after caps exhausted`, `path outside worktree`, `path contains ..`, `read error: <message>`.
- The classifier (#3 verification harness) uses exact equality on `task_hash`/`depends_on[*].hash`/`design_refs[*].path` to detect context-load reproducibility.

**5. `coord update --scope` contract — accepted as Codex wrote it.**

For the prerequisite change to `coord-wright/bin/coord`:
- Mirror `coord new --scope` argument parsing exactly.
- Update only frontmatter `scope:` (not the body `## Scope notes` section).
- Reuse the existing `as_list` (or `coerce_str_list`) normalization function — no new code path.
- Empty value (`--scope ""`) clears the field (removes the key entirely from frontmatter for cleanliness, or sets to `[]` — match whatever `coord new` does today).
- Support both comma-separated input (`--scope "a,b,c"`) and `@file` input (`--scope @/tmp/scopes.txt`) using the existing helper.
- Regression tests cover: setting from empty, replacing existing, clearing via empty string, `@file` input, multi-comma split, leaving body intact.

---

The proposal is now fully implementable with no remaining ambiguities. All 4 round-3 gaps closed. Codex round 3's "remain settled" list (ordering, two-phase split, scope-update prerequisite) holds.

This round is substantive — Codex should verify the round-3 resolutions are internally consistent and complete, or emit CONVERGED.

## Codex round 4 (2026-05-21)

Substantive gaps remain.

1. The scope grammar and "task creates" heuristic will still false-positive on common project structures and even misses its own example. The restricted character class rejects common route/file names such as Next.js `app/(admin)/[id]/page.tsx` and route groups using parentheses/brackets; if the intent is a gitignore-style path glob, that subset needs to allow common literal path characters or be renamed as a stricter coord path-glob grammar. Separately, the create-new heuristic says `src/main/.../Foo.java` near "Implement com.example.audit.collect.Foo" is covered, but the verb list does not include `implement`, and the body text does not contain the basename `Foo.java`. That means normal new-file subtasks such as "Implement Foo" or "Add the Bar adapter" can be flagged as missing paths unless they repeat the exact filename near one of the listed verbs. Either add an explicit `created_paths`/`scope_creates` contract, or expand and test the heuristic against package/class-name descriptions and common frontend route filenames.

2. `--task-file` mode still has fixture-vs-live ambiguity through context resolution. It states the task file itself is isolated, but it does not say that normal design-ref auto-discovery and `depends_on` id resolution are disabled. A normalized fixture can still mention `docs/auditScript.md` or carry `depends_on: <id>` in frontmatter; if the skill resolves those relative to the canonical project root or cwd, the semantic run can review a `/tmp` task against live design docs or live predecessor tasks. In fixture mode, explicit `--design-refs` and `--depends-on-file` should either fully replace auto-discovery/id resolution, or the command should fail closed unless every referenced doc/dependency is mapped to an explicit fixture path. Dependency fixture files should also be matched by their frontmatter id so an omitted or mismatched predecessor cannot silently fall back to `tasks/<id>.md`.

3. The Context Manifest is parseable, but not canonical enough for byte-identical output or cache equality. YAML syntax alone leaves quoting, null spelling, inline-vs-block lists, key order, and line wrapping implementation-dependent; `preflight.findings` are free-form strings; `codex_invocation.log_path` contains a timestamped run path; and the schema says design docs use the same hash function but does not include a per-design-doc hash. The manifest also says paths are repo-relative, which conflicts with `/tmp` fixture inputs in `--task-file` mode. Pin a canonical serialization form, preferably canonical JSON or a tightly specified YAML emitter profile, use stable finding codes, separate run metadata from deterministic context identity, and include design-ref hashes if design content participates in cache validity.

4. Deferring `human_gate` to v2 is not safe as written. The v1 preflight now requires frontmatter `acceptance` plus `verify_commands` or `verify_profile`, while current runnable-shape validation accepts a concrete `## Acceptance test` body as verifier intent. Claude's replacement escape hatch is `shape_override`, but the current `coord` parser recognizes it only as frontmatter, not as a lawful `coord new`/`coord update` flag, and existing validation does not define it as a verifier substitute. A legitimate docs/review/policy task with no machine-verifiable gate can therefore regress from accepted to blocked with no supported way to record the exception. Either keep a v1 CLI-backed human gate, add and test `--shape-override` semantics for this exact preflight exception, or preserve the existing concrete-acceptance fallback for the narrow no-machine-gate task classes.

## Claude round 4 (2026-05-21)

All 4 findings accepted. Resolutions:

**1. Scope grammar — widen character class + replace fragile heuristic with explicit `scope_creates:` opt-in.**

Revised character class: `[A-Za-z0-9_./@*+=()\[\]-]`. This admits Next.js route conventions (`app/(admin)/[id]/page.tsx`), version-suffixed paths, and other common modern filename shapes. Disallow rules are unchanged: `..`, `;`, `{`, `}`, `\\`, whitespace, leading `/`. Glob semantics are unchanged.

Replace the "task creates" verb heuristic — Codex correctly flagged that verb proximity is fragile and my own example wouldn't have matched. Two-tier replacement:

- **Primary (explicit, deterministic):** new optional frontmatter field `scope_creates:` — a list of paths or globs the task will create. Format identical to `scope:`. Preflight: any `scope:` entry that is also listed in `scope_creates:` is exempt from existence checking. This is the contract; shapers set it explicitly when a task creates files. Adding `coord update --scope-creates` mirrors the `--scope` prerequisite.

- **Fallback (advisory, not blocking):** when `scope_creates:` is empty and a non-glob `scope:` entry does not exist on disk, the preflight emits an *advisory* finding `PREFLIGHT_SCOPE_PATH_NOT_FOUND` listing the entry. The user decides whether the task creates it (and should set `scope_creates:`) or it's a real defect. No verb heuristic.

Drop the verb-proximity heuristic entirely. Codex's catch was correct; the heuristic was net-negative.

Prerequisites for v1 grow to two small `coord-wright` changes:
- `coord update --scope` (already proposed)
- `coord new --scope-creates` + `coord update --scope-creates` (new)

Both mirror existing `--scope` argument parsing exactly.

**2. `--task-file` mode — fully hermetic, fail-closed on missing fixture mappings.**

Revised semantics: when invoked with `--task-file`, the skill operates in **hermetic mode**:

- **Design refs:** auto-discovery from the task body is DISABLED. Only paths passed via `--design-refs` are loaded. If the task body references `docs/X.md` but `--design-refs` does not include a fixture path for it, the run records `design_refs: [{path: docs/X.md, loaded: skipped, skip_reason: "no fixture mapping in hermetic mode"}]` in the manifest. Each `--design-refs` argument is an absolute path; relative resolution is disabled.

- **Dependencies:** `depends_on` ID resolution is replaced by an explicit map. Flag syntax: `--depends-on-file <id>=<path>` (repeatable). For each id in the fixture's `depends_on:`, the map must include a path; if any id is unmapped, **fail closed with exit 3** and the error `hermetic mode: depends_on id "<id>" has no --depends-on-file mapping`.

- Each fixture file passed via `--depends-on-file` is parsed for its own `task` frontmatter field (the id); if the file's recorded id does not match the map key, fail closed with `hermetic mode: --depends-on-file mapping "<id>=<path>" but file declares id "<actual>"`.

- The skill never reads `tasks/` or `docs/` under any project root in hermetic mode. Confirmed by routing all file reads through a `read_with_root(path)` helper whose root is `None` in hermetic mode (absolute paths only) and the canonical project root in normal mode.

This makes the live-vs-fixture boundary a property of the invocation mode, not of individual files within an invocation.

**3. Context Manifest — canonical form + stable finding codes + design hashes + separation of identity from provenance.**

Three changes:

(a) **Canonical serialization for cache identity, human-readable rendering separately.**
The transcript displays a YAML block as before (human-readable). The cache key is a separate canonical JSON file written to `<transcript-dir>/<id>.cache.json` containing only the identity fields. Cache identity JSON is canonicalized per RFC 8785 JCS (sorted keys, no insignificant whitespace, UTF-8 NFC, integer floats unmodified). The `manifest_hash` field in the YAML block is the SHA256 of the canonical JSON bytes — the verifier independently regenerates the canonical JSON from the YAML and confirms the hash matches before trusting any cache hit.

(b) **Stable finding codes.** Replace free-form strings with a closed enum for preflight findings:

```
PREFLIGHT_MISSING_ACCEPTANCE          # neither frontmatter list, verify_commands, verify_profile, nor concrete body
PREFLIGHT_RENDERER_HANDOFF_INCOMPLETE # frontmatter `acceptance:` empty but body section present (advisory)
PREFLIGHT_MISSING_VERIFY              # acceptance present but no verify_commands or verify_profile
PREFLIGHT_MALFORMED_SCOPE             # at least one scope entry violates the grammar
PREFLIGHT_SCOPE_PATH_NOT_FOUND        # advisory, see #1 fallback
PREFLIGHT_DEPENDS_ON_MISSING_FILE     # depends_on id has no corresponding task file
PREFLIGHT_SUBTASKS_UNPARSEABLE        # at least one subtask cannot be parsed
```
Future codes follow the `PREFLIGHT_<UPPER_SNAKE>` pattern. The manifest's `preflight.findings` list contains code strings only; details (path, line, context) go in a parallel `preflight.finding_details` map keyed by code occurrence.

(c) **Design-ref hashes + identity/provenance separation.**

Schema additions:
```yaml
design_refs:
  - path: docs/auditScript.md
    source_bytes: 32098
    embedded_bytes: 32098
    loaded: full
    skip_reason: null
    hash: <sha256-hex>          # SHA256 of file bytes on disk; required when loaded != skipped, null when skipped

identity:                        # contributes to manifest_hash
  schema_version: 1
  task_hash: <sha256>
  depends_on_hashes: [<sha256>, ...]   # sorted ascending
  design_hashes: [<sha256>, ...]       # sorted ascending
  aggregate.fallback_to_toc: <bool>

provenance:                      # NOT part of manifest_hash; for traceability only
  log_path: <absolute>
  invocation_cd: <absolute>
  invocation_mode: <normal | hermetic>
  invoked_at: <ISO-8601 timestamp>
```

Repo-relative paths apply in normal mode; hermetic mode uses absolute paths. The manifest schema documents both, and `provenance.invocation_mode` disambiguates.

**4. `human_gate` deferral — replaced with: preserve the existing concrete-body fallback + emit advisory finding when frontmatter is empty.**

Codex is right that strict tightening regresses legitimate docs/review tasks. The v1 preflight now mirrors the existing `coord-review` validator behavior exactly, with one addition:

```
HARD REQUIREMENT (any one satisfies — matches current bin/coord line 1028):
  acceptance frontmatter list non-empty
  OR verify_commands non-empty
  OR verify_profile non-empty
  OR concrete `## Acceptance test` body section

ADVISORY (does NOT block; surfaces as a finding):
  PREFLIGHT_RENDERER_HANDOFF_INCOMPLETE when frontmatter `acceptance:` is empty
  AND the task has subtasks (i.e. it's a runnable task not a brainstorm).
  Reason: `coord show --handoff` renders only frontmatter; an empty list
  produces an incomplete handoff card even when validation passes.
```

The advisory finding is what would have caught the oracle case: my tasks had concrete body acceptance sections (which is why coord-review passed) but no frontmatter `acceptance:` list (which is why the renderer was hollow). The user (or Claude) sees the advisory in the preflight and chooses to fix it before promotion. No regression for legitimate human-gate tasks — they keep their concrete body and the advisory is informational, not blocking.

No `human_gate` field needed. No `--shape-override` CLI prerequisite. The v1 prerequisite list stays at two:
- `coord update --scope`
- `coord new --scope-creates` + `coord update --scope-creates`

---

The proposal now:
- Scope grammar admits real-world path shapes (Next.js routes etc.)
- "Task creates" is an explicit opt-in field with an advisory fallback (no heuristics)
- `--task-file` mode is fully hermetic with fail-closed dependency mapping
- Context Manifest separates cache identity (canonical JSON) from human display (YAML), with stable finding codes
- Preflight matches existing coord-review behavior + adds advisory findings; no regression for legitimate no-machine-gate tasks

This round is substantive — Codex should verify the round-4 resolutions or emit CONVERGED.

## Codex round 5 (2026-05-21)

No substantive disagreements remain. Claude's round 4 resolutions are internally consistent and implementable.

Specific checks:

1. The widened scope character class admits literal path characters needed for common frontend routes, but still excludes the shell-dangerous command/control characters that caused the original risk: whitespace, `;`, `{}`, backslash, path traversal via `..`, and leading absolute paths. The remaining metacharacters (`*`, `[]`, `()`, `+`, `=`) are path/glob syntax, not command separators or substitution forms; implementation should expand with Python/pathlib-style APIs, not shell evaluation. That is already implied by the preflight design and does not require another design change.

2. `scope_creates:` is a clean opt-in field for coord-wright. It can be added beside `scope:` in frontmatter ordering, parsed with the same list normalization, and exposed via `coord new --scope-creates` plus `coord update --scope-creates` without changing pickup, handoff rendering, subtask parsing, or verifier behavior. Existing tasks omit the field and keep current semantics.

3. Hermetic `--task-file` mode now fails closed on fixture/live ambiguity. It disables normal design-doc discovery, replaces dependency id lookup with explicit `id=path` mappings, verifies mapped dependency ids against frontmatter, and routes reads through absolute fixture paths only. Unmapped dependency ids are hard failures, and unmapped design references are recorded as skipped rather than silently read from the live checkout.

4. The cache identity split is sufficient. Human-readable YAML remains presentation only; cache equality is based on an RFC 8785 canonical JSON identity object with stable hashes, sorted hash arrays, stable booleans, and provenance excluded. Given the same task/dependency/design bytes and fallback state, two implementations should produce byte-identical canonical JSON bytes and therefore the same `manifest_hash`.

5. `PREFLIGHT_RENDERER_HANDOFF_INCOMPLETE` preserves compatibility. The hard preflight condition mirrors current runnable validation: frontmatter acceptance, verify commands, verify profile, or concrete body acceptance can satisfy intent. The renderer warning is advisory only and targets the known handoff-renderer blind spot, so docs, review, policy, smoke-test, verifier-only, and body-acceptance task shapes currently in use are not newly blocked.

Only style-level choices remain, such as exact wording of advisory details and field ordering in rendered frontmatter.

CONVERGED

## Claude round 5 (2026-05-21)

Codex has confirmed convergence. Loop closes at round 5.

Status: CONVERGED

**Final settled design (consolidated):**

**New skill** `coord-shape-review` (location: `~/.claude/skills/coord-shape-review/SKILL.md`). Takes a task id; runs a bounded mechanical preflight + Codex semantic loop; persists transcript to `.coord/shape-reviews/<id>.md`.

**Preflight (mechanical, free, runs before any Codex call):**
- Hard gate (any one satisfies, matching current `bin/coord` line 1028): frontmatter `acceptance:` non-empty OR `verify_commands:` OR `verify_profile:` OR concrete `## Acceptance test` body.
- Advisory finding `PREFLIGHT_RENDERER_HANDOFF_INCOMPLETE` when frontmatter `acceptance:` is empty but a body section is present (preserves backward compat; surfaces the oracle defect class).
- Scope grammar: chars `[A-Za-z0-9_./@*+=()\[\]-]`; no `..`/`;`/`{`/`}`/`\\`/whitespace/leading-`/`; globs `*` (intra-segment) and `**` (full segment) per gitignore semantics.
- `scope_creates:` opt-in frontmatter field exempts listed paths from existence check; non-glob `scope:` entries that don't exist and aren't in `scope_creates:` get advisory finding `PREFLIGHT_SCOPE_PATH_NOT_FOUND`.
- Closed enum of finding codes (`PREFLIGHT_<UPPER_SNAKE>`); details in parallel `finding_details` map.

**Semantic loop (Codex, max 2 rounds):**
- Subject context: task file + direct depends_on (frontmatter + subtask titles, capped handoff for completed deps) + design refs (deterministic markdown-link extractor, max 5 files, max 50 KB combined, TOC fallback above 120 KB aggregate).
- Prompt checks: worker-consumable frontmatter, scope grammar, cross-subtask interface contracts, cross-task contracts, acceptance ↔ subtask coverage, non-negotiable ↔ design contradictions, fast-path/dry-run contradictions, existence (respecting `scope_creates:`).
- Skip conditions: `complexity: trivial` + single subtask + no `depends_on` + no reviewer/architect roles + no high-risk keywords + no design refs.
- Status eligibility: `status: shaping` or `needs-review` only.

**Hermetic `--task-file` mode** (for verification harnesses): absolute paths only, design-ref auto-discovery disabled, `--depends-on-file <id>=<path>` required for every depends_on id, fail-closed on missing fixture mapping.

**Context Manifest:** YAML in transcript for humans; canonical JSON (RFC 8785 JCS) sidecar `<transcript>.cache.json` for cache identity; SHA256 `manifest_hash` over identity fields only; provenance (cd, log_path, timestamp, mode) excluded from hash.

**CoordWright prerequisites (small, low-risk):**
- `coord update --scope` (mirrors `coord new --scope`)
- `coord new --scope-creates` and `coord update --scope-creates`

**Coord-shape hook (revised ordering):**
- Steps 1–4 unchanged (broad-ask gate → grill-me → dup check → `coord new`).
- 5. Fill plan/acceptance/verify/scope frontmatter.
- 6. Run mechanical `coord-review` until LGTM (cheap preflight).
- 7. Run `coord-shape-review` until CONVERGED (paid semantic).
- 8. Re-run mechanical `coord-review` (final invariant).
- 9. Show user (`coord next-subtask`, `coord show --handoff`).

**Verification plan (two-phase):**
- Phase 1: preflight on raw pre-fix oracle blobs from `473db9b^` → expect defects (1)(2)(3) per task.
- Phase 2: Codex semantic on normalized fixtures (preflight defects pre-fixed, semantic defects preserved) → expect T1/T3 CONVERGED, T2 surfaces (4) interface mismatch + (6) ALTER SESSION, T4 surfaces (5) dry-run contradiction. Measure tokens, wall-clock, false-positive rate.

**Cost claim removed** until Phase-2 measurement.

**v1/v2 split:**
- v1: direct deps only, mechanical preflight, deterministic design-ref extractor with caps, hash-keyed local cache, capped completed-dep handoffs, no Codex auto-fix.
- v2: explicit `design_refs:` frontmatter, transitive dependency summaries, shipped-output comparison, measured caching/`codex resume`, optional `coord update --human-gate` if real demand emerges.

Ready to implement.
