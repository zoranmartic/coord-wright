---
name: coord-shape
description: Create a properly shaped coord task by interviewing the user with grill-me first, then writing the task with structured plan, acceptance test, subtasks, and dependencies. Use when the user asks to shape, plan, or create a non-trivial coord task and the scope is not already crisp.
---

Goal: avoid creating broad runnable tasks or thin shaping stubs. The shaping bar in `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md` requires plan, acceptance test, parseable subtasks, and dependencies — fill them through `coord update` so the next agent can execute without rediscovering intent. Defaults for complexity, reasoning effort, models, and decomposition live in `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files-reference.md` — apply those when filling grill answers into the task.

**Review findings are tasks, not edits.** When any review tool (`codex-loop`, `ultrareview`, integrated review, `review-security`, `review-code`, etc.) returns findings, the default response is to TRIAGE them into a `tasks/findings/<date>-<topic>.md` document and SHAPE the ones worth fixing into new coord tasks via this skill. Inline fixes in the same session bypass the shaping bar (acceptance criteria, scope limits, non-negotiables, max_turns) and are the dominant compounding mode of additive bias. Single trivial one-line typo fixes may land inline; anything else requires shaping. See `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Review Findings Are Tasks, Not Edits" for the cross-agent commitment.

## When multi-agent (Codex + Claude) is the right shape

Multi-agent coord (`roles.architect`, `roles.reviewer`, or shape-review on top of Codex implementation) has TWO distinct values, and they should be separated when deciding task shape:

1. **Quality via cross-agent review.** A second model catches what the first missed. This is genuinely valuable for high-risk surfaces (auth, money, security, migrations, destructive ops, more than one repo), genuinely ambiguous designs, and decisions that change global workflow.

2. **Audit trail and decision persistence across sessions.** The coord task file holds plan, subtasks, findings, token_log, and the diff trail — visible from any session, surviving context window resets, queryable later. This is the user's stated primary reason for reaching for multi-agent.

These two values are NOT the same need. **Audit trail does not require multiple tasks**, multiple agents, or shape-review. A single coord task with rich subtasks, structured findings, and the standard token_log already gives full persistence and visibility. Splitting one feature across N tasks does NOT improve the audit trail; it fragments context (per Cognition's analysis in `cognition.ai/blog/dont-build-multi-agents`: parallel subagents lose conversation history and make conflicting implicit decisions) AND inflates token spend for the same end result.

Apply these defaults when shaping:

- **Need audit trail, not extra quality**: shape ONE coord task with 2-5 subtasks. Use `assigned: codex` (or `assigned: claude`) and skip `roles.reviewer`. The task file carries the audit trail; no shape-review needed for simple single-file/single-feature work.
- **Need both audit trail AND quality**: shape ONE coord task with `roles.reviewer` to get the post-task review pass, OR pair with `coord-shape-review` only if the spec has cross-subtask interface contracts that mechanical review can't catch.
- **High-risk surface OR genuinely ambiguous design**: full Codex+Claude review-rounds chain is justified. This is the exception, not the default.

Per `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation": prefer fewer tasks with rich subtask tracking over many tasks with thin tracking. The audit trail is preserved either way; the over-engineering cost only appears when you fragment.

Project-root preflight:

- Resolve the canonical project checkout before duplicate checks, `coord` commands, task-file writes, git staging, commits, or pushes:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; shaped coord tasks belong to the main checkout that the launchd worker reads.

Workflow:

1. **Apply the broad-ask gate.**
   - If the request has no concrete target (file/path, route/screen, component/symbol, command, PR/branch/commit, task id, or explicit single surface), run `scope-brief` first.
   - Use the six fields from `scope-brief` — scope, mode, stop rule, verification, output, next route — as the shaping input.
   - If more than one surface remains, shape a dependent task chain instead of one runnable task.

2. **Interview the user with grill-me.**
   - Invoke the `grill-me` skill with the user's rough request as the topic.
   - Drive it until you can answer all of:
     - What is the single main outcome?
     - What is the final verification path (one acceptance test or `verify_commands` set)?
     - What 2–5 subtasks each fit one agent round and cover one major surface?
     - What other active tasks does this depend on (`depends_on`)?
     - Should this use the default Codex route, explicit Claude assignment, explicit review, or `--brainstorm`?
     - `complexity` (trivial/simple/complex) and `kind` (design/refactor/code-fix/code-cut/smoke-test/docs/review/sql-diagnostic)?
   - If the user wants to skip grilling for a tiny task, create it directly with `coord new` only after the outcome, acceptance, and routing are crisp.

   **Mandatory subtraction questions — ask these BEFORE writing the task body.** Additive bias is the dominant compounding failure mode (see `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Subtraction as the Opening Move"). Every shaped task must extract explicit answers to all four:

   - What existing code, if deleted, would make this change unnecessary or smaller?
   - What becomes orphaned, redundant, or dead code after this lands?
   - Net LOC delta target — is this task net-negative, net-zero, or net-positive? Give a band (e.g. `-800 to -1200` for a cut, `+50 to +200` for a feature).
   - If net-positive: what existing complexity (env vars, configs, abstractions, feature flags, helper layers) gets retired as part of this work? If nothing, why not?

   These four answers go verbatim into a `## Subtraction analysis` section in the task body, written above `## Plan`. If the answer to the third question is "I don't know," shaping does not proceed until the user nails a band — that band becomes the `scope_budget.net_loc_delta_target` frontmatter (see step 5). The third answer is also the input that decides whether `kind: code-cut` is the right shape (net-negative band → code-cut, see `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files-reference.md` § "kind").

   **Subtask sizing — be aggressive about narrowness.** A subtask is one agent round, not a feature. Reject your own draft if any of these hold:
   - Body has more than one paragraph, more than ~6 lines of prose, or describes more than one local smoke check.
   - Title contains "and" joining two concrete actions ("Implement X and wire Y", "Build component and tests"). Split it.
   - Touches more than ~3 files or more than one directory at a different surface (e.g. backend + frontend + docs in one subtask).
   - Bundles implementation with verification ("Add feature X and run the full test suite", "Build component and capture screenshots"). Verification is its own subtask, or — if it needs simulator/browser/API rigging — its own dependent task.
   - Bundles design/spec work with implementation. A spec is its own subtask or its own dependent task; the coder must not infer the design while building.
   - Bundles refactor + new behavior in one subtask. Land the refactor first, then the new behavior.

   When a draft subtask fails these checks, prefer splitting into a **dependent task chain** rather than stretching to a 6th subtask. 5 chained narrow tasks executes more reliably than one task with 5 fat subtasks, because each task closes independently, accumulates its own findings, and benefits from the review-once-at-end gate. The chain shape (spec → component → integration → wiring → verify) is the natural shape of any non-trivial change; do not collapse it into one runnable task.

   **Counter-rule against over-fragmentation.** The above split-into-chain preference applies to *genuinely larger work* — multi-day scope, parallel lanes, or dependency graphs that would block a single worker. It does NOT apply to small features. Per `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation", rule 4: a feature owned by one person, fitting one PR, completing in under one day belongs in ONE coord task with 2-5 subtasks — not a chain of N tasks. Before splitting into a chain, ask: "would a single developer ship this in one PR?" If yes, it's one task. If the answer is no because of independent surfaces that can ship separately, then a chain is right. Token spend on shape-review across N tasks is real; do not pay it to satisfy a decomposition aesthetic.

3. **Check for duplicates, overlaps, and missing dependencies.**
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list --search="<key words>" --format=ids`
   - Also scan recently-completed tasks: `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" list --status=done --limit=10 --format=ids`
   - For every active or recent task whose scope overlaps the new task's scope (same files, same surface), explicitly ask the user: "should this depend on `<id>`?" Add via `--depends_on=<id>` if yes.
   - This is the most-skipped step. Tasks that should chain (audit → spec → rebuild → cleanup) often get created without `depends_on`, breaking the precondition graph and hiding deferred items from the next agent. When in doubt, add the dependency — it's cheap to remove and expensive to retrofit after the fact.
   - If a related active task exists with the same outcome, surface it instead of creating a duplicate.

4. **Prepare and create the task.**
   - Write the subtask block from the grill answers to `/tmp/coord-subtasks-<slug>.txt` before calling `coord new`. Each subtask must use this exact checkbox template and carry `complexity:`, `model_claude:`, and `model_codex:` metadata. Multi-subtask tasks also carry deterministic handoff file paths so the worker never improvises about location:
     ```markdown
     - [ ] **S1: Title**
       complexity: simple
       model_claude: sonnet
       model_codex: gpt-5.6-sol
       One focused body paragraph with the work boundary and local smoke check.
       Writes handoff: `.coord/handoffs/<task-id>/S1.md` listing files committed, exports added, decisions, gotchas (see task-files-reference.md for shape).
       Handoff to S2: <one sentence naming the specific signature, file, decision, or invariant S2 needs to start without re-discovering it>.

     - [ ] **S2: Title** (shown as the final subtask — omit the `Handoff to S3` line on the last subtask only)
       complexity: simple
       model_claude: sonnet
       model_codex: gpt-5.6-sol
       One focused body paragraph with the work boundary and local smoke check.
       Reads handoff: `.coord/handoffs/<task-id>/S1.md`.
       Writes handoff: `.coord/handoffs/<task-id>/S2.md`.
     ```
   - The `<task-id>` placeholder in the Writes/Reads handoff lines is substituted with the actual id after `coord new` returns it. The worker treats these paths as authoritative — no scanning the task file for handoff blocks. Handoff files are committed alongside the subtask's code changes. Every subtask writes a handoff file (no exemption for S1 or the final subtask); only the final subtask omits the `Handoff to S<N+1>` line because there is no next subtask. The `Handoff to S<N+1>` sentence is the shaper's job — only the shaper has the cross-subtask picture, so the worker for S<N> never has to guess what S<N+1> needs.
   - Subtask sizing per `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rule 4 + 6: prefer 2-4 subtasks each grouping 2-3 related concerns at a natural file/module boundary, NOT 5+ subtasks of one bullet each. The handoff file is the compression layer between cold-start subtask workers.
   - Never write YAML-style subtasks such as `- title: ...`; `coord` rejects them.
   - Write the acceptance criteria to `/tmp/coord-acceptance-<slug>.txt`.
   - Call `coord new` with `--task`, `--complexity`, `--kind`, `--scope`, optional `--assigned`/`--agents`, `--depends_on`, and `--set-subtasks=@/tmp/coord-subtasks-<slug>.txt`.
   - **`kind` selection from the subtraction analysis.** The third grill question (net LOC band) is the input. A net-negative band (e.g. `-500 to -1500`) → `--kind=code-cut`. A net-zero band on existing surfaces → `--kind=refactor`. A net-positive band → `--kind=code-fix` for narrow bug-touching work, or other supported kind. Do not retrofit `code-cut` on legacy tasks; it must be set explicitly when the band is net-negative.
   - **`code-cut` template injection.** When shaping with `--kind=code-cut`, the task body's `## Non-negotiables` section must contain the verbatim subtraction-discipline block from `${COORD_TOOLS:-$HOME/Projects/coord-wright}/templates/code-cut.md`, with `{target_low}` and `{target_high_added}` substituted from the `scope_budget.net_loc_delta_target` band (see step 5). Write the substituted block into the plan file you pass to `--set-plan=@`, so the worker reads it as part of the plan body. Do not paraphrase or compress — the literal text is the contract.
   - Do not add `roles.architect` for normal work. Architecture should already be captured by the shaping interview, subtasks, and `depends_on` chain. Add `roles.reviewer` only when independent review is explicitly required, and add `roles.architect` only when a design handoff must run after queueing.
   - Escalate to Claude+Codex review only when the task changes global workflow, security/auth/trading/money behavior, destructive operations, or more than one repo.
   - Use batch/multi-agent task chains only for independent lanes. Each lane must have one surface, one output, and one verification path; merge with `review-integrate`.
   - For unclear scope after grilling, prefer `--brainstorm` over `--shape-override`; brainstorm tasks do not require `--set-subtasks` at creation.

5. **Fill the remaining shaping fields immediately.**
   - `coord update <id> --set-plan=@<file>` — plan derived from grill answers (for `kind: code-cut`, the plan file must contain the verbatim non-negotiables block from `${COORD_TOOLS:-$HOME/Projects/coord-wright}/templates/code-cut.md` with `{target_low}` and `{target_high_added}` substituted)
   - `coord update <id> --set-acceptance-test=@<file>` — final verification path
   - `coord update <id> --acceptance="bullet1,bullet2"` — populate frontmatter `acceptance:` list (the handoff renderer needs this; body-only acceptance passes `coord-review` but produces a hollow handoff card)
   - `coord update <id> --verify-commands="cmd1,cmd2"` — machine-runnable verification commands
   - `coord update <id> --scope="path1,path2"` — populate frontmatter `scope:` (NEVER pass shell brace-expansion like `{a,b}/`; coord parses comma-separated lists, not shell globs at the shell)
   - `coord update <id> --scope-creates="path1,path2"` — subset of `scope:` entries that this task creates; exempts them from preflight existence checks
   - `coord update <id> --depends_on=<csv>` if any dependencies surfaced
   - `coord update <id> --scope-budget-loc="<band>"` — write the net LOC delta band from the third grill question (e.g. `'-800 to -1200'` for a cut, `'+50 to +200'` for a feature). The CLI defaults `abort_if_exceeded_by_pct=50`; override with `--scope-budget-abort-pct=<n>` when the budget needs a tighter or looser fuse. Required for `kind: code-cut`; recommended for every shaped task. See `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files-reference.md` § `scope_budget`.

   The shaped task body must also include an empty `## Findings for follow-up` section at the bottom (write it into the plan file before `--set-plan`). This gives the coder a clear destination for cuts/issues spotted in flight, preserving the "do not fix it, write it down" half of the subtraction-discipline non-negotiables. Cheap to add at shape time; preserves the discipline at run time.

6. **Scan for orphan candidates (when the task deletes or shrinks existing surfaces).**

   Run this step for any task that removes code paths — `kind: code-cut`, `kind: refactor` that drops files, or `kind: code-fix` whose scope deletes a module. Skip it for pure-additive features.

   For each file/symbol in `--scope` that this task will delete or shrink, search the project for non-test callers. The exact grep depends on the project's primary language; common patterns:

   ```bash
   # TypeScript / TSX
   for f in <files in task scope>; do
     rg "from.*${f%.ts}" --type ts --type tsx -l | grep -v test
   done

   # Python
   for mod in <modules in task scope>; do
     rg "^(from|import) +${mod%.py}\b" --type py -l | grep -v test
   done

   # Generic (symbol lookup)
   rg --no-heading "<symbol-or-route>" -l | grep -v -E '(test|spec|__mocks__|fixtures)'
   ```

   Anything with **zero non-test callers** after the planned cut becomes an orphan candidate. Write them into a new `## Orphan candidates after this cut` section in the task body (via `coord update --set-plan=@` or by extending the plan file before its first write).

   For each orphan candidate, the shaper picks one of three resolutions and records it inline:

   - **Widen this task** to include the orphan in `--scope` and the subtraction analysis. Best when the orphan is small, on the same surface, and naturally falls in the same cut.
   - **Split into a follow-up code-cut task** chained via `--depends_on`. Best when the orphan is on a different surface or large enough to justify its own scope/budget.
   - **Leave with rationale** ("orphan retained because: <reason>"). Best when the surface is intentionally preserved (public API, scheduled for a later cut, etc.). Record the reason — silent leaves are forbidden.

   This step is what would have prevented a real C1↔C3 collision (C1 absorbed C3's scope because the build forced it). With orphan-candidates visible at shape time, the shaper either merges deliberately or splits precisely; the "build forced it" outcome should not recur.

7. **Run coord-review (mechanical preflight).**
   - Invoke the `coord-review` skill with the task id.
   - If it returns objections, fix them via `coord update` and re-run.
   - Continue once `coord-review` exits 0 (LGTM).

8. **Run coord-shape-review (semantic loop) for non-trivial tasks.**
   - Invoke the `coord-shape-review` skill with the task id. This catches semantic shape defects that the mechanical `coord-review` misses: interface contract mismatches between subtasks and across `depends_on` tasks, missing frontmatter the worker consumes (`acceptance:` / `verify_commands:`), acceptance↔subtask contradictions, non-negotiable↔design contradictions, fast-path/dry-run contradictions, malformed `scope:` lists, AND credential/secret leakage in committed task text.
   - Skip rules: the skill auto-skips when `complexity: trivial` AND ≤1 subtask AND no `depends_on` AND no reviewer/architect roles AND no high-risk keywords AND no design refs. Trust the skill's own gate.
   - Apply fixes via `coord update` (`--scope`, `--scope-creates`, `--acceptance`, `--verify-commands`, `--set-plan=@`, `--set-acceptance-test=@`, `--set-subtasks=@`). Never hand-edit the task file.
   - Each subtask body has a hard limit of ~900 characters compact (title + body, whitespace-collapsed). If a fix bloats a subtask past that, split it or trim.
   - If `codex` CLI is unavailable: the skill warns and skips; proceed to step 9 anyway. Do not fail the shaping pass for missing tooling.

9. **Re-run coord-review (final invariant).**
   - Semantic fixes from step 8 (especially `--set-subtasks=@` and `--set-plan=@`) can in principle regress a mechanical gate — a new subtask body the parser can't read, a plan that drops a required field, an acceptance list shape the validator rejects. Re-run `coord-review` and confirm exit 0 before reporting.
   - If `coord-review` fails here: fix and re-run — but do NOT re-run shape-review on the same content. The semantic checks already converged; only the mechanical re-validation matters at this stage.

10. **Show the user.**
   - Run `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" next-subtask <id>` and confirm it returns `S1`. If it does not, fix the subtask block before reporting the task.
   - `python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord" show <id> --handoff` and report the id.

Notes:
- Source of truth for task shape: `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md`.
- Do not bypass shaping with `--shape-override` unless the user explicitly approves a recorded reason.
- For trivial code fixes the user wants done now, skip this skill and do the work inline, or create a narrow fully shaped Codex task only when the user explicitly wants it queued.
