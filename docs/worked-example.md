# Worked example: one task, shape to done

This page follows one small task through the whole CoordWright loop: shaped
with the `coord` CLI, worked by Codex as the coder, checked by Claude as the
reviewer, and closed by the worker. It is a real run, not a mock-up. Every
excerpt below is copied from the artifacts the run produced, trimmed with
`[...]`. Only paths were changed (`~/src/demo` for the project, `$COORD_TOOLS`
for the CoordWright checkout).

- **Date:** 2026-09-30, on CoordWright v0.3.0. Two worker ticks, about 6
  minutes of agent time end to end.
- **Coder:** Codex CLI, `gpt-5.6-sol`, reasoning `medium` (the default for `simple`).
- **Reviewer:** Claude Code, `sonnet` (resolved to `claude-sonnet-5`), reasoning `medium`.
- **Runtime:** a fresh clone of the public repo as `$COORD_TOOLS`. No
  `install.sh`, no launchd. Each tick was one foreground run of
  `worker/worker.sh`.
- **Honesty note:** the agents loaded `/coord-run` and the `coord-check` skill
  from the operator's existing `~/.claude` / `~/.agents` install, a private copy
  of the same `skills/` and `commands/`. `COORD_TOOLS` pointed at the fresh
  clone, so every `coord`, handoff, and commit-helper call used the public `bin/`.

## The project

`~/src/demo` is a throwaway git repo with a local bare remote, so pushes work.
It holds a 30-line `wordcount` CLI (`wordcount/cli.py`), two pytest tests, a
README, and the coord `.gitignore` pair: `.coord/*` plus `!.coord/handoffs/`.
It prints `2 lines, 3 words, 14 chars`; the task adds an opt-in `--json` flag
(the runnable version of `tasks/examples/example-add-json-flag.md`).

## Stage 1: shape, review, promote

The task was written with `coord new` and file inputs (`@file`), so the
multi-line plan and subtask block pass through without shell quoting.

```sh
python3 $COORD_TOOLS/bin/coord new --task="Add a --json output flag to the wordcount CLI" \
  --kind=code-fix --complexity=simple --model_claude=sonnet --model_codex=gpt-5.6-sol \
  --reasoning_effort=medium --roles=coder:codex,reviewer:claude --review_rounds_max=2 \
  --acceptance=@acceptance.txt --verify_commands=@verify.txt --scope=@scope.txt \
  --set-plan=@plan.md --set-subtasks=@subtasks.md --tags=example
```

The mechanical shaping check caught the one field `coord new` did not set in
v0.3.0:

```
$ python3 $COORD_TOOLS/bin/coord-review tasks/2026-09-30-add-a-json-output-flag-to-the-wordcount-cli.md
1 shaping objection(s):
  1. scope_budget.net_loc_delta_target must be a numeric band [...]. Set it with `coord update --scope-budget-loc=<band>`.

$ python3 $COORD_TOOLS/bin/coord update 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli --scope-budget-loc="+8 to +25"
$ python3 $COORD_TOOLS/bin/coord-review tasks/2026-09-30-add-a-json-output-flag-to-the-wordcount-cli.md
LGTM — no shaping objections found.
$ python3 $COORD_TOOLS/bin/coord promote 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli
promoted 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli → pending
```

Since v0.3.1, `coord new --scope-budget-loc="+8 to +25"` sets the band at
creation, so this extra update (and its commit) is no longer needed.

Key parts of the shaped task: machine-checkable acceptance, coder and reviewer
on different models, and a plan that says what is deliberately *not* built:

```yaml
status: pending
assigned: codex
[...]
roles:
  coder: codex
  reviewer: claude
acceptance:
  - `python3 -m wordcount.cli --json <file>` prints exactly one JSON object with integer keys lines/words/chars and nothing else
  - `python3 -m wordcount.cli <file>` output is unchanged (existing test_main_text_output still passes unmodified)
  - `python3 -m pytest -q` passes and includes a new test covering --json
  - README.md documents the --json flag in one usage line
verify_commands:
  - python3 -m pytest -q
  - python3 -m wordcount.cli --json README.md | python3 -c 'import json,sys; d=json.load(sys.stdin); assert set(d)=={"lines","words","chars"}'
review_rounds_max: 2
[...]
scope_budget:
  net_loc_delta_target: +8 to +25
```

```markdown
- [ ] **S1: Add the --json flag, its test, and a README line**
  complexity: simple
  model_claude: sonnet
  model_codex: gpt-5.6-sol
  In `wordcount/cli.py` add a `--json` store_true argument; when set, print
  `json.dumps(count(text))` instead of the text line. Leave the text path
  byte-for-byte unchanged. [...] Do not touch `count()`.
  Writes handoff: `.coord/handoffs/2026-09-30-add-a-json-output-flag-to-the-wordcount-cli/S1.md`

### Subtraction analysis
[...]
4. **Retirement:** None; growth is one flag, one `json.dumps` call, one test, one README line. A `--format=<x>` option, YAML/CSV output, and a pretty/compact toggle serve hypothetical consumers and are deliberately not built.
```

## Stage 2: tick 1, the Codex coder round

```sh
cd ~/src/demo
COORD_UNSAFE_AUTONOMOUS=1 /bin/bash $COORD_TOOLS/worker/worker.sh ~/src/demo
```

`COORD_UNSAFE_AUTONOMOUS=1` is the opt-in for unattended rounds (README "Blast
radius"); the demo repo is disposable. The model came from the subtask metadata:

```
[06:46:53] pickup: role=coder model=gpt-5.6-sol model_source=subtask.model_codex reasoning=medium reasoning_source=reasoning_effort
[...]
[06:51:14] tick: done 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli with codex
```

Codex's whole code change (commit `coord: work <id>`):

```diff
+import json
 [...]
+    parser.add_argument("--json", action="store_true", help="output counts as JSON")
 [...]
-    print(f"{stats['lines']} lines, {stats['words']} words, {stats['chars']} chars")
+    if args.json:
+        print(json.dumps(stats))
+    else:
+        print(f"{stats['lines']} lines, {stats['words']} words, {stats['chars']} chars")
```

It also added one test and one README usage line. Its finding reports what it
changed, what it ran, and its actual LOC delta against the budget:

```
Outcome: S1 complete.
Changed: added `--json` output using the existing count dictionary, one JSON-mode test, one README usage line, and the required S1 handoff.
Verification: `python3 -m pytest -q` passed (3 tests); JSON acceptance pipeline passed; `git diff --check` passed.
Scope: actual +15 net LOC across declared scope vs target +8 to +25.
```

The S1 handoff (`Files committed`, `Decisions made`, `Acceptance items
closed`) was committed with the code, at the path the task file named. Because
the task has `roles.reviewer: claude`, finishing S1 did not close it; it moved
to `needs-review` and was handed to Claude:

```
coord: update <id> complete-subtask=S1 status=needs-review assigned=claude codex-finding
```

## Stage 3: tick 2, the Claude reviewer round

Same command. The worker now resolved a reviewer round on the other model:

```
[06:51:33] pickup: role=reviewer model=claude-sonnet-5 model_source=model_claude reasoning=medium reasoning_source=reasoning_effort
[...]
[06:53:00] mechanical verify gate: all verify_commands passed for 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli
[06:53:01] tick: done 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli with claude
```

Claude re-ran the checks itself instead of trusting Codex's report:

```
Outcome: APPROVE.
Verified: `python3 -m pytest -q` passes (3 tests, includes new test_main_json_output); JSON acceptance pipeline (`--json README.md` piped through json.load, key-set check) passes; text output path byte-for-byte unchanged; `count()` untouched.
[...]
Scope: actual +15 net LOC (README +1, tests +9, cli.py +5) vs target +8 to +25 — within band.
```

After the reviewer closed the task, the worker ran every `verify_commands`
entry again on its own (the `mechanical verify gate` line). An APPROVE with a
failing verify command would have been demoted to `review-failed`, not
archived. Both passed, so the task stayed `done` and moved to `tasks/archive/`.

The archived task file still shows a `_No findings yet._` line above each
`### Round 1`; that is the v0.3.0 placeholder bug, fixed in v0.3.1.

## Stage 4: done

`coord show <id> --result` is the one-screen summary:

```
# 2026-09-30-add-a-json-output-flag-to-the-wordcount-cli
task: Add a --json output flag to the wordcount CLI
status: done  assigned: claude  round: 1
queue_wait: 1m
exec_duration: 4m
[...]
token_total: effective=347461 (in=44376 out=10744 cache_read=1634874)
```

The worker captured token usage from each agent's own output (Codex 131843
effective, Claude 215618); most of the volume is cache reads.
`bin/coord-log ~/src/demo --once` shows the two rounds as `S1 4m21s` (codex)
and `review 1m28s ✓verify` (claude).

The full history lives in git (`<id>` abbreviates the task id):

```
872a48f coord: update <id>                      # reviewer token row
86bdca8 coord: update <id> status=done
367126b coord: update <id> claude-finding
0827b35 coord: update <id>                      # coder token row
4c882bc coord: update <id> complete-subtask=S1 status=needs-review assigned=claude codex-finding
fa085f7 coord: work <id>                        # code + handoff
f015365 coord: update <id> status=codex-working
28affdb coord: promote <id> → pending
6bf56bd coord: update <id> scope_budget
a458549 coord: new <id>
4fbd2a7 wordcount: initial CLI and tests
```

One code commit (`coord: work`); every other commit is a queue transition, so
the log reads as an audit trail.

## What the discipline bought here

- **The scope held.** The plan named what was not being built; Codex built
  none of it. +15 net LOC against a +8 to +25 band, measured by both agents.
- **The shaping check caught a gap.** `coord-review` refused the first draft
  because it had no numeric LOC budget to measure against.
- **Verification was independent three times.** Codex ran the verify
  commands, Claude re-ran them on a different model, and the worker ran them
  again before letting `done` stand.
- **State lives in plain files.** Task file, handoff, and findings are
  committed next to the code; `git log` alone rebuilds what happened.

This run shows the happy path. A REJECT would send the task back to Codex with
the reviewer's finding, at most `review_rounds_max: 2` times before a human decides.
