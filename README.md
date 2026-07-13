# CoordWright

**A local-first coordination runtime for coding agents** — file-backed queues, deterministic handoffs, launchd workers, and cross-model review for [Claude Code](https://docs.claude.com/en/docs/claude-code) and [Codex](https://developers.openai.com/codex/cli).

CoordWright is the runtime I use to run two AI coding agents — Claude and Codex — against the same repositories under one disciplined workflow: tasks are *shaped*, *assigned* to a model, *worked*, and — when you configure a reviewer — *checked by the other model* before they land. Everything is plain files on your own machine: no CoordWright server, no hosted backend. (You bring your own Claude and Codex CLI accounts — the agents themselves are cloud services.)

> Licensed under Apache-2.0. The companion essay, *[The additive bias of two-agent review loops](https://zoranmartic.com/essay.html)*, explains the discipline this runtime is built around.

---

## The loop

```
   shape ────▶ assign ────▶ work ────▶ [review] ────▶ done
  (coord-      (coder:      (worker     (optional:    (archive +
   shape)       claude or    runs the    the OTHER     handoff
                codex)       agent)      model, when   trail)
                                         a reviewer
                                         role is set)
     ▲                                           │
     └──────────── reject / iterate ◀────────────┘
```

Each task is a Markdown file with a typed contract (`acceptance` + `verify_commands` the reviewer gates on). Configure a `roles.reviewer` and the *other* model checks the work before it lands — cross-model review is where most defects die; simpler tasks can skip it and complete directly.

### Subtasks and handoffs

Bigger tasks split into subtasks (S1, S2, …) — and the split happens **at shape time**, not mid-flight. The shaper picks the subtask boundaries (typically 2–4, at natural file/module seams), gives each its own `complexity` and per-model metadata, and writes the handoff contract — including a one-line spec of what each subtask must leave for the next. Workers execute the shape; they don't re-plan it.

Every subtask then runs as a **fresh, cold-start worker** — no shared session, no context window accumulating across steps. The bridge between workers is a handoff file at a deterministic path:

```
.coord/handoffs/<task-id>/S<N>.md
```

Each subtask ends by writing one (~10 lines: files committed, exports added, non-obvious decisions, gotchas), and the next begins by reading its predecessor's. The task file names these paths explicitly (`Writes handoff:` / `Reads handoff:` lines on every subtask), so no worker improvises where state lives. Cold starts stay cheap, the audit trail lands in git next to the code, and a crashed worker costs you one subtask — not the task.

A shaped task looks like [`tasks/examples/example-add-json-flag.md`](tasks/examples/example-add-json-flag.md).

## Why it's built this way

The hard problem with two agents in a loop isn't getting them to *do* more — it's stopping them from *adding* more. Two-agent review loops have a strong additive bias: each pass proposes additions, and the cumulative result over-engineers the surface. CoordWright bakes the counter-discipline into the runtime — mandatory subtraction rounds, scope budgets, a "what are we consciously NOT building?" block on every task. That discipline, not the loop itself, is the point. See [`docs/agent-workflow-policy.md`](docs/agent-workflow-policy.md).

## Prior art / how this differs

Coordinating coding agents is an active space — e.g. [coord.io](https://coord.io/) offers a commercial, cloud-hosted platform for teams. CoordWright is deliberately the opposite end:

| | CoordWright | cloud/team platforms |
|---|---|---|
| Where it runs | your machine, file-backed | cloud service |
| Who it's for | one operator (you) | teams |
| State | plain files you can read + `git` | a managed backend |
| Source | open, hackable | closed |
| Emphasis | the *discipline* of working well | orchestration + collaboration |

It's also not an agent *framework* — there's no SDK to program against (the AutoGen / CrewAI / LangGraph category); the agents are the off-the-shelf Claude and Codex CLIs, and the runtime state is plain files. And it's not a parallel-session multiplexer fanning you out to N agent instances: it runs **two** agents on purpose, so one model's work can be checked by the other.

If you want a managed team product, those exist and are good at it. CoordWright is for an operator who wants an inspectable runtime on their own machine and full control of the workflow.

## Requirements

- **macOS** (workers are wired via `launchd`; Linux/systemd is not provided yet — the CLI and skills are portable, the autostart isn't)
- [Claude Code CLI](https://docs.claude.com/en/docs/claude-code) and [Codex CLI](https://developers.openai.com/codex/cli) (the two agents)
- **Python 3.9+** (`python3 --version` to check; the CLI uses `zoneinfo` and modern type syntax), `jq`, `git`

CoordWright orchestrates those two CLIs; it does not bundle or replace them, and you bring your own accounts.

## Blast radius

`install.sh` writes symlinks into `~/.claude/` and `~/.agents/`, merges `~/.claude/settings.json` (backing up the previous file first), and creates a `launchd` worker for every absolute path in `projects.txt`. Those workers can edit, commit, and push inside registered repositories according to each task's scope and your local agent credentials. Keep `projects.txt` narrow, review the scripts before running them, and start with a disposable repo if you are evaluating CoordWright for the first time.

**Unattended worker rounds are disabled by default.** Installed workers and the watchdog exit idle until you explicitly acknowledge autonomous execution by setting the exact value `COORD_UNSAFE_AUTONOMOUS=1`:

- set it in the environment where you run `./install.sh` — it is then written into each generated worker's `launchd` environment (re-running `./install.sh` without it removes the key again: revocation is the same command), or
- set it per-project in that repo's `.coord/config.env` (reaches the worker; the watchdog plist is managed by `/coord-unblocker` and follows the same acknowledgement).

With the acknowledgement, worker-launched Claude runs with `--dangerously-skip-permissions` and Codex runs with `--sandbox danger-full-access` — full, promptless power inside the registered repos. That is what you are switching on; leave it off for interactive-only use (shaping, status, review from your own Claude/Codex sessions), which works without it.

## Install

```sh
mkdir -p ~/Projects
git clone https://github.com/zoranmartic/coord-wright ~/Projects/coord-wright
cd ~/Projects/coord-wright
./install.sh
```

`install.sh` symlinks the skills, agents, and commands into `~/.claude/` and `~/.agents/`, merges the Claude Code permission settings (resolving paths to your machine). For each repo listed in `projects.txt` it installs a `launchd` worker and adjusts that repo's `.gitignore` / git-exclude for coord's runtime files. **It modifies the repositories you register, so read it before running.** Idempotent; re-run after editing `projects.txt`.

If you clone somewhere other than `~/Projects/coord-wright`, set `COORD_TOOLS` to your checkout path (e.g. in your shell profile) so the `coord-*` skills resolve.

`./uninstall.sh` reverses it: unloads the launchd workers and removes the symlinks (the merged settings are left for you to review by hand).

After install, commit the files it wrote into each registered repo (`.gitignore` changes and `.markdownlint-cli2.jsonc`) before promoting the first task; the worker refuses to auto-commit into a worktree that was already dirty, and leaving them untracked makes every tick report `uncommitted work remains`.

## Quickstart

```sh
# 1. register a repo for the workers to run against
cp projects.txt.example projects.txt   # then add your project's absolute path
# read "Blast radius" above, then acknowledge unattended execution:
COORD_UNSAFE_AUTONOMOUS=1 ./install.sh

# 2. inside that repo, from Claude Code, shape a task
/coord-shape add a --json flag to the status command

# 3. promote it; a worker picks it up and works it
#    (set a reviewer role and the other model checks it before it lands)
/coord-promote
```

The `/coord-*` skills (`coord-shape`, `coord-check`, `coord-status`, `coord-promote`, and friends) are the interface; the `coord` CLI underneath does the bookkeeping. Per-project worker config goes in `<project>/.coord/config.env` — see [`templates/config.example.env`](templates/config.example.env). Without the `COORD_UNSAFE_AUTONOMOUS=1` acknowledgement everything except unattended worker rounds still works — shape, promote, and review from your own sessions, or run a task in the foreground with `/coord-run`.

A git remote is optional; without one coord commits locally and skips the push. A push that *fails* (rejected, no credentials) is a loud non-zero error — coord never reports a queue write as done when it didn't land. The worker is silent while idle (`.coord/worker.log` records one line saying rounds are disabled if the acknowledgement is missing); `launchctl list | grep com.coord.worker` confirms it is loaded.

## What this is — and isn't

- **Is:** an opinionated, local, inspectable runtime that shows how I run a disciplined two-agent coding workflow. Read the skills and docs to see the whole thing; it is meant to be understood, not just installed.
- **Isn't:** a maintained product, a team service, or a turnkey install. It assumes macOS, two configured agent CLIs, and a willingness to read shell. It's a working artifact, released as-is.

## Layout

```
bin/        the `coord` CLI and helpers
worker/     launchd worker, watchdog, semaphore, rate-limit
skills/     the /coord-* Claude Code skills (the operator interface)
hooks/      pre/post tool-use safety + session-start hooks
agents/     architect / coder / reviewer role definitions
docs/       the coordination protocol + the workflow-discipline policy
tests/      the test suite (run: python3 -m pytest tests/)
```

Reading order, if you want to understand it rather than run it: [`docs/architecture.md`](docs/architecture.md) (how the parts fit) → [`docs/task-files.md`](docs/task-files.md) (the task contract) → [`docs/coordination.md`](docs/coordination.md) (the shared protocol) → [`docs/agent-workflow-policy.md`](docs/agent-workflow-policy.md) (the discipline).

## License

Code: [Apache-2.0](LICENSE). Built by Zoran Martic.
