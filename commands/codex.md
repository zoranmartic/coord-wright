---
description: Manually run Codex on a prompt and capture the resulting diff.
---

This command is for foreground/manual debugging. Wrapper-managed coord tasks
must hand off to `assigned: codex` so the Codex wrapper records its own token
usage.

mkdir -p .coord/codex-runs
codex exec --sandbox workspace-write "$ARGUMENTS" 2>&1 | tee -a .coord/codex-runs/$(date +%s).log
git diff --stat

The sandboxed `workspace-write` mode is deliberate for a foreground command.
Full filesystem access (`--sandbox danger-full-access`) is reserved for the
acknowledged unattended worker path — set `COORD_UNSAFE_AUTONOMOUS=1` and use
the worker instead if you need that (see README "Blast radius").
