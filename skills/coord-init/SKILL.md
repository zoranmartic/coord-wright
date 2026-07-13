---
name: coord-init
description: Create or populate a project's AGENTS.md by scanning the repo and interviewing the user. Use when registering a new project with CoordWright or when AGENTS.md is missing the standard structure.
---

You are creating the `AGENTS.md` for this project. If a file already exists, treat any present section as the user's confirmed content unless the user asks to rewrite it. If no file exists, generate one from scratch using the three interview answers below plus the constant sections defined in "Write the result".

Project-root preflight:

- Resolve the canonical project checkout before scanning, editing, staging, committing, or pushing:
  `COORD_MAIN=$("${COORD_TOOLS:-$HOME/Projects/coord-wright}/bin/coord-project-root") && cd "$COORD_MAIN"`
- This is required when the skill is invoked from a sibling task worktree; project bootstrap policy belongs in the main checkout.

**Before you ask anything:** scan the repo root for signals:
- Top-level directories (`ls` the project root)
- `package.json` → framework, test runner, e2e tools
- `pyproject.toml` / `requirements.txt` / `setup.py` → Python stack
- `pom.xml` / `build.gradle` → Java stack
- `Makefile` → build/test targets
- `alembic/` or `migrations/` → database migrations present
- `Dockerfile` / `docker-compose.yml` → containerized services
- Notable domain signals: `ibapi`, `stripe`, `twilio`, broker/trading deps, etc.

Use those signals to **prefill your proposed answers** so the user only confirms or corrects — never ask an open "tell me about your project" prompt.

---

## Q1 — What This Repo Is

State what you detected, then propose one paragraph. Example format:

> "I see: FastAPI backend with `ibapi` (IBKR trading), Alembic migrations, Postgres, React frontend with Playwright, a `worker/` process, and a `demo/` directory.
>
> Proposed: *An automated stock-trading control room: a FastAPI backend that submits orders to Interactive Brokers, a worker process that runs a strategy lifecycle, a React operator UI for approvals and monitoring, and a Postgres-backed event store with Alembic migrations.*
>
> Confirm, or edit?"

Wait for the user's answer. Record their final paragraph as the "What This Repo Is" content.

---

## Q2 — Repo Map

List the top-level directories you found (excluding hidden dirs, `node_modules`, `__pycache__`, dist/build dirs). Propose one bullet per directory with a short description inferred from its contents. Example:

> "Proposed Repo Map:
> - `backend/` — FastAPI app, Alembic migrations, unit tests
> - `frontend/` — React + Playwright e2e
> - `worker/` — background strategy executor
> - `demo/` — standalone demo with no live API dependency
> - `docs/` — project docs and coordination notes
>
> Confirm, edit, or drop any entries?"

Wait for the user's answer.

---

## Q3 — Validation

Propose the validation commands based on what you detected:
- Python project with `pytest` → `cd backend && pytest` (or wherever tests live)
- Node/npm with Playwright → `npm run build && npm run test:e2e`
- Maven → `mvn -q test`
- Makefile with test target → `make test`
- Healthz endpoint pattern detected → include `curl --fail <url>`

Example:

> "Proposed Validation:
> - Backend: `cd backend && pytest`
> - Frontend: `cd frontend && npm run build && npm run test:e2e`
> - Post-deploy: `curl --fail http://127.0.0.1:8000/api/v1/system/healthz`
>
> Confirm, edit, or add steps?"

Wait for the user's answer.

---

## Write the result

Once all three answers are confirmed, write `AGENTS.md` with this structure:

```
# <project> Agent Guide

This file is the repo-local guide for coding agents working in `<project>`.

## What This Repo Is

<Q1 paragraph>

## Companion Context

- [README.md](README.md) — human quickstart
- [CLAUDE.md](CLAUDE.md) — pointer to this file (`@AGENTS.md`)

Shared coord protocol is loaded automatically by the global trigger when coord work is in scope. For coord behavior, use `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/coordination.md`, `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/codex-coordination.md`, and `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files.md`. For shared workflow policy (broad-ask gate, dual-agent escalation, markdown artifact rules), use `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/agent-workflow-policy.md` and `${COORD_TOOLS:-$HOME/Projects/coord-wright}/docs/task-files-reference.md`.

## Project-Specific Rules

- For broad requests, use `scope-brief` first. If the ask has no concrete target (file, route, artifact, command, task id, or explicit single surface), do not call review/implementation specialists yet; shape a narrow request, then route.
- For review requests with a known surface, start with `review-code`, `review-ui`, or `review-security`; load narrower skills only when that surface is confirmed.

<!-- TODO: add project-specific domain rules here as they emerge. Run coord-refine after week 4 to populate high-risk shaping, reasoning baseline overrides, and model selection. -->

## Repo Map

<Q2 bullets>

## Validation

<Q3 commands>

## Documentation Maintenance

- Update [README.md](README.md) when the human quickstart changes.
- Update this AGENTS.md when project-specific rules, repo map, or validation expectations change.
```

If an existing `AGENTS.md` already has user-edited sections, leave those untouched and only fill in the missing sections. Always preserve the broad-ask gate exactly once.

Also ensure `CLAUDE.md` exists and contains `@AGENTS.md` so Claude Code loads this guide. If `CLAUDE.md` is absent, create it with that single line.

After writing:

1. **Validate** — scan the written file and confirm: all major headings present, shared broad-ask gate present exactly once, no `<Q1>`/`<Q2>`/`<Q3>` placeholders remaining.
2. **Stage and commit** — `git add AGENTS.md CLAUDE.md`, then commit with message `docs: populate AGENTS.md via coord-init`. Pass via heredoc. Append trailer `Co-Authored-By: coord-bot <noreply@coord.local>`.
3. **Push** — `git push`. Stop on non-zero.
4. **Report** — one line: "AGENTS.md written — 3 sections populated, shared broad-ask gate installed, project-specific policy left for coord-refine. Committed and pushed."

Do not ask for further confirmation before writing. The user has already confirmed each section.
