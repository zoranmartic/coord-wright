---
name: coord-shape-review
description: Run a bounded semantic shape-review on a coord task. Catches interface contract mismatches between subtasks, missing frontmatter the worker consumes, acceptance↔subtask contradictions, non-negotiable contradictions, fast-path/dry-run contradictions, and malformed scope lists — all defects that the mechanical coord-review misses. Use after coord-shape produces a non-trivial task, or before promoting any task with depends_on, complex SQL, or external system contracts.
---

Goal: catch semantic shape defects before a task enters the runnable queue. The mechanical `coord-review` verifies presence and format; this skill verifies *coherence*. The full design (5-round Claude+Codex convergence) lives at `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/archive/reviewCoordShape.md` — read it once before running the skill on substantial work.

## Input

Required: task id (e.g. `2026-05-21-some-task-id`), or `--task-file <abs-path>` for hermetic verification mode.

## Skip rules (no Codex call)

Abort cleanly when any of these hold:
- `complexity: trivial` AND ≤ 1 subtask AND no `depends_on` AND no reviewer/architect roles AND no high-risk keywords AND no design refs detected in the body.
- `complexity: simple` AND ≤ 3 subtasks AND scope is single-file or single-directory AND no `depends_on` AND no reviewer/architect roles AND no high-risk keywords (auth, money, migration, destructive, security, trading, rca). Per `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` § "Two-Agent Loop Bias and Mitigation" rule 5: shape-review on small single-surface tasks burns Codex tokens on what amounts to a proofreading pass the mechanical `coord-review` already covers.
- `status` is not in {`shaping`, `needs-review`} and `pickup_hold: true` is not set.
- A `.coord/shape-reviews/<id>.cache.json` exists, its `manifest_hash` matches the current task+deps+design hashes, and the previous run ended in `CONVERGED`.

Document the skip in stderr (`shape-review: skipped — <reason>`) and exit 0.

## Workflow

### Step 1 — Resolve project root and target

Resolve canonical project root: `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`.

In normal mode, target task is at `tasks/<id>.md`. In hermetic mode, target task is the absolute path passed via `--task-file`; design refs must come from `--design-refs`; dependencies must come from `--depends-on-file <id>=<path>` (repeatable). Hermetic mode fails closed if any `depends_on` id in the fixture lacks a `--depends-on-file` mapping.

### Step 2 — Mechanical preflight (free, deterministic)

Run both mechanical gates:
```
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-review" tasks/<id>.md
python3 "${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-shape-preflight" <id>
```

- If `coord-review` exits 1: surface objections, apply fixes via `coord update`, re-run. Do not proceed until LGTM.
- If `coord-shape-preflight` exits 1: surface hard findings, apply fixes via `coord update` (`--scope`, `--scope-creates`, `--acceptance`, `--verify-commands` are the usual repair tools), re-run.
- Advisory findings on stderr are surfaced to the user but do not block — they go into the Subject context for Codex to reason about.

### Step 3 — Build subject context

Create transcript at `.coord/shape-reviews/<id>.md` with a Subject section containing:

1. **Artifact**: the task id and its current path.
2. **Convergence criterion**: "agree the task is implementation-ready: no remaining interface mismatches, acceptance↔subtask contradictions, non-negotiable contradictions, fast-path contradictions, or leaked credentials."
3. **Task content**: full frontmatter + body, verbatim, in a fenced block.
4. **Dependencies**: for each direct `depends_on` id, embed: frontmatter (full), subtask titles + complexity (titles only). For completed deps, also embed the latest `coord show --handoff <dep-id>` output capped at 4 KB.
5. **Design refs**: prefer **inline invariants** over embedding full design docs. The lesson from the first run: embedding a 32 KB design doc with its own review-loop transcript caused Codex to exhaust its context window reading prior-round metadata that was irrelevant to the current shape check. Instead, distill the design into a bullet list of 6-15 invariants directly in the Subject ("**Settled design invariants for T<N>:**" followed by short bullets). The deterministic markdown-link extractor is a fallback when no inline invariants are available; apply caps (max 5 files, max 50 KB combined; aggregate cap 120 KB with TOC fallback above).
6. **Context Manifest**: a YAML block (see `docs/archive/reviewCoordShape.md` final design for the schema) recording task_hash, deps_hashes, design_refs with hashes+sizes+loaded-state, aggregate sizes, preflight ran/findings, and provenance. The skill ALSO writes a canonical JSON sidecar `.coord/shape-reviews/<id>.cache.json` over the identity-only subset, with `manifest_hash` (SHA256 over canonical JSON bytes per RFC 8785 JCS) recorded in the YAML.

### Step 4 — Round 1: Codex semantic review

Run Codex with `--cd <canonical-project-root> --sandbox workspace-write` and absolute paths. The prompt MUST explicitly tell Codex NOT to read other docs — the first run failed because Codex spent its entire budget reading SKILL.md, coordination.md, task-files.md, and the embedded design transcript before producing any findings:

```
codex exec --cd <canonical-project-root> --sandbox workspace-write \
  "SHAPE-REVIEW pass on the transcript at <abs-transcript-path>.

   The transcript already contains the task content, depends_on context, and settled design invariants. DO NOT read any other docs (no SKILL.md, no coordination.md, no design docs, no other task files). Work only from what is in the transcript.

   Check for:
   (a) Worker-consumable frontmatter: `acceptance:`, `verify_commands:` / `verify_profile:` per `bin/coord` line 1028 semantics.
   (b) `scope:` list shape: gitignore-style globs, no shell-meta. `scope_creates:` exempts paths from existence check.
   (c) Cross-subtask interface contracts: does S(N)'s declared input match S(N-1)'s declared output? Bodies must not describe data the interfaces have no way to pass.
   (d) Cross-task contracts: does this task's S1 consume what the prior depends_on task's last subtask actually exposed?
   (e) Acceptance↔subtask coverage: every acceptance bullet produced by at least one subtask; every subtask maps to at least one acceptance bullet.
   (f) Non-negotiables↔scope and non-negotiables↔design invariants: contradictions either way.
   (g) Fast-path/dry-run contradictions: if a subtask describes --dry-run, --schema-only, --offline, --no-network, etc., does the acceptance test agree on what that mode allows?
   (h) Existence: every file path in plan or scope must exist OR be listed in `scope_creates:` OR be described as 'creates' in a subtask body.
   (i) Credential leakage: any literal in the task text that looks like a real password fragment, API key, token, or wallet path. Flag even partial leaks (the original incident leaked a 7-char password prefix into an acceptance grep regex).

   Emit a numbered findings list. If nothing substantive remains, emit a standalone CONVERGED line.
   Append your entire response as ONE new section titled '## Codex shape-review round N (YYYY-MM-DD)' to the transcript. Append only — do not modify other parts." \
  < /dev/null 2>&1 | tee <canonical-project-root>/.coord/codex-runs/<ts>-shape-review-r1.log
```

Subtask body bloat: when applying fixes via `coord update --set-subtasks=@`, each subtask compact text (title + body, whitespace-collapsed) must stay under 900 characters or the validator rejects the update. Trim or split.

Append Codex's response to the transcript as `## Codex shape-review round 1 (YYYY-MM-DD)`.

### Step 5 — Claude response

Read the transcript. For each finding:
- **Accept** and apply the fix via `coord update <id>` with the appropriate flags (`--scope`, `--scope-creates`, `--acceptance`, `--verify-commands`, `--set-plan=@`, `--set-acceptance-test=@`, `--set-subtasks=@`). Never hand-edit the task file.
- **Dispute** with evidence — grep the source, read the design doc, point to specific lines.

Append the response as `## Claude shape-review round 1 (YYYY-MM-DD)`. Include the convergence sentinel `CONVERGED` (standalone line) only when no substantive issues remain.

### Step 6 — Round 2 (only if not converged after round 1)

Same as steps 4–5 with the updated task. Cap at round 2; if not converged, surface remaining findings to the user and exit 1.

### Step 7 — Final mechanical invariant

Re-run `coord-review tasks/<id>.md`. The semantic fixes must not have broken the mechanical gates. If it fails, fix and re-run until LGTM.

### Step 8 — Persist cache and report

Write `.coord/shape-reviews/<id>.cache.json` (canonical JSON) and report:
- Transcript path
- Round count and final state (CONVERGED / unresolved)
- Per-finding summary (accepted, disputed, deferred)
- Token spend (input + output) from `codex exec` logs

## Bounds

- Max 2 rounds. Each round capped at 4 min wall-clock for Codex.
- On Codex timeout / empty output: retry once; on second failure surface `SKIPPED — codex timeout` and exit 1 (do not silently pass).
- Aggregate context cap: 120 KB. Above that, design docs fall back to TOC-only.

## Escape valves

- **Codex CLI unavailable, implicit call from `coord-shape`**: emit `WARN: shape-review skipped — codex CLI unavailable` to stderr; do not write a transcript; let the final `coord-review` proceed.
- **Codex CLI unavailable, explicit user call**: fail closed with exit 2 and message `codex CLI not found; install codex or invoke from a host that has it`.
- **Hermetic `--task-file` mode**: see Step 1; entirely independent of the canonical project root.

## Rules

- Never hand-edit task files. All fixes go through `coord update`.
- Never `--shape-override` a finding without recording a reason via the supported CLI surface.
- Run on `status: shaping` or `needs-review` tasks only. Reject `pending`, `*-working`, terminal statuses.
- Persist the transcript so the next session can verify what was checked.
- Cache hits must verify `manifest_hash` byte-for-byte (canonical JSON) before trusting.
- Always redirect `< /dev/null` on the `codex exec` call (the prompt is passed as an argument, so stdin is unused). Without it `codex exec` intermittently blocks on a stdin read and hangs at 0% CPU indefinitely — the round never completes.

## See also

- `docs/archive/reviewCoordShape.md` — the converged design (5-round transcript). Read for the rationale behind every rule above.
- `bin/coord-shape-preflight` — the mechanical preflight implementation.
- `bin/coord-review` — the upstream mechanical validator.
