---
name: coord-refine
description: Fill in the evolved-policy sections of AGENTS.md after a project has been running for a while — high-risk shaping, reasoning overrides, model selection. Companion to coord-init; run at week four or later.
---

You are refining the "Project-Specific Rules" section of `AGENTS.md` for this project. These sections only make sense after operating the project — they can't be filled in at bootstrap time. Your job is to interview the user through three targeted questions and write the results back.

Project-root preflight:

- Resolve the canonical project checkout before reading, editing, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; evolved coordination policy belongs in the main checkout.

**Before asking anything:** read the current `AGENTS.md` so you know what is already there. If any subsection is already hand-edited (not a TODO marker), show the user the existing content before proposing changes — never silently overwrite it.

Keep the shared broad-ask gate in "Project-Specific Rules" intact. It is global workflow policy, not an evolved project preference:

- For broad requests, use `scope-brief` first.
- For known review surfaces, route through `review-code`, `review-ui`, or `review-security` before narrower specialists.

---

## Q1 — High-Risk Shaping Surfaces

Ask the user which task surfaces in this project are genuinely high-risk and require the heavy shaping pattern (`complex` complexity, architect + coder + reviewer roles, `review_rounds_max: 2`, `reasoning_effort: high|xhigh`).

Prompt the user with the standard categories as a starting point — edit to fit:

> "Which of these surfaces apply to this project, and are there others?
>
> - Database migrations (schema changes, Postgres/Docker cutover, destructive cleanup)
> - Auth / security / secrets
> - Money / trading / live order submission
> - Live-operations changes (touching a running service in prod)
> - Serious RCA (production incidents, data loss)
>
> Confirm, edit, add, or remove entries. Also note: should any of these escalate to `reasoning_effort: xhigh`?"

Wait for the user's answer. Record the final list and any xhigh callouts.

---

## Q2 — Reasoning Baseline Overrides

Ask the user how they want to deviate from the shared coord default (`reasoning_effort: medium` for the background loop). The key decisions are:

> "For this project:
>
> 1. Which task types should stay at `medium` even if they have several subtasks? (e.g. code-fix, refactor, docs, smoke-test)
> 2. When is it right to raise to `high` vs. splitting the task instead?
> 3. Any task types you want permanently at `high` or `xhigh` regardless of the above?
>
> If the shared defaults are fine as-is, just say so and I'll skip this section."

Wait for the user's answer. If they say the defaults are fine, leave the reasoning subsection as TODO.

---

## Q3 — Model Selection

Ask the user how they want to spend model budget on this project. Prompt with the standard tiers:

> "For Claude model selection (`model_claude`):
> - `trivial` tasks → haiku?
> - `simple` code-fix / refactor → sonnet?
> - `complex` / `xhigh` → opus?
>
> For Codex (`model_codex`): default is `gpt-5.6-sol` — any exceptions?
>
> Confirm the defaults, or describe where you want to differ."

Wait for the user's answer.

---

## Write the result

Once all three answers are collected, update `AGENTS.md`:

1. Replace (or create) the **High-Risk Shaping** subsection under "Project-Specific Rules" with the confirmed list.
2. Replace (or create) the **Reasoning Baseline** subsection with the confirmed override rules, or leave the TODO if the user said the shared defaults are fine.
3. Replace (or create) the **Model Selection** subsection with the confirmed guidance.
4. Leave all other sections (What This Repo Is, Companion Context, Repo Map, Validation, Documentation Maintenance) exactly as they are.
5. If any of the three subsections were already hand-edited and the user confirmed no change, leave them untouched.
6. Preserve the shared broad-ask gate exactly once; do not duplicate or remove it while refining local policy.

After writing:

1. **Validate** — confirm the three target subsections are present and contain no residual TODO markers.
2. **Stage and commit** — `git add AGENTS.md`, then commit with message `docs: refine AGENTS.md policy sections via coord-refine`. Pass via heredoc. Append trailer `Co-Authored-By: coord-bot <noreply@coord.local>`.
3. **Push** — `git push`. Stop on non-zero.
4. **Report** — one line listing which subsections were updated and which were left unchanged, plus "Committed and pushed."

Do not ask for further confirmation before writing. The user has already confirmed each section.
