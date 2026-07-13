#!/usr/bin/env bash
# PreToolUse hook for Bash: block a small set of high-blast-radius commands.
# Input: JSON on stdin with tool_input.command.
# Output: JSON decision to stdout.

set -euo pipefail

input=$(cat)
cmd=$(python3 -c "import sys,json; d=json.loads(sys.argv[1]); print(d.get('tool_input',{}).get('command',''))" "$input" 2>/dev/null || echo "")

block() {
  printf '{"decision":"block","reason":"%s"}\n' "$1"
  exit 0
}

projects_path_re="(^|[[:space:]])[\"']?($HOME/Projects|\\\$HOME/Projects|~/Projects)(/[^[:space:]\"']*)?([[:space:]\"']|$)"
projects_redirect_re="(^|[[:space:]])[0-9]*>{1,2}[[:space:]]*[\"']?($HOME/Projects|\\\$HOME/Projects|~/Projects)(/[^[:space:]\"']*)?([[:space:]\"']|$)"

# rm -rf / or similarly broad home/project roots.
if printf '%s' "$cmd" | grep -qE '\brm\b' && \
   printf '%s' "$cmd" | grep -qE '\-[a-zA-Z]*[rR][a-zA-Z]*' && \
   printf '%s' "$cmd" | grep -qE '\-[a-zA-Z]*[fF][a-zA-Z]*'; then
  if printf '%s' "$cmd" | grep -qE '[[:space:]]/([[:space:]]|$)'; then
    block "rm -rf / is blocked by coord safety hook"
  fi
  if printf '%s' "$cmd" | grep -qE '[[:space:]](~|\$HOME|$HOME)(/)?([[:space:]]|$)'; then
    block "rm -rf home directory is blocked by coord safety hook"
  fi
  if printf '%s' "$cmd" | grep -qE '[[:space:]]$HOME/Projects(/)?([[:space:]]|$)'; then
    block "rm -rf Projects root is blocked by coord safety hook"
  fi
  if printf '%s' "$cmd" | grep -qE "$projects_path_re"; then
    block "rm -rf Projects path is blocked by coord safety hook"
  fi
fi

# Interpreter one-liners that write to the filesystem.
interpreter_oneliner_re='(^|[[:space:];&|])(python3?|node|perl|ruby)[[:space:]]+([^[:space:];&|]+[[:space:]]+)*(-c|-e)([[:space:]]|$)'
interpreter_write_sink_re="open[[:space:]]*\\([^)]*,[[:space:]]*[\"'][wa]b?\\+?[\"']|Path[[:space:]]*\\([^)]*\\)[[:space:]]*\\.[[:space:]]*write_text[[:space:]]*\\(|fs[[:space:]]*\\.[[:space:]]*writeFile(Sync)?[[:space:]]*\\(|(File|IO)[[:space:]]*\\.[[:space:]]*write[[:space:]]*\\("
if printf '%s' "$cmd" | grep -qE "$interpreter_oneliner_re" && \
   { printf '%s' "$cmd" | grep -qE "$interpreter_write_sink_re" || \
     printf '%s' "$cmd" | grep -qE "$projects_redirect_re"; }; then
  block "interpreter one-liner filesystem write is blocked by coord safety hook"
fi

# git push --force (any remote or branch)
if printf '%s' "$cmd" | grep -qE 'git[[:space:]]+push[[:space:]]+(.*[[:space:]])?--force(-with-lease)?([[:space:]]|$)'; then
  block "git push --force is blocked by coord safety hook"
fi

# git clean -fdx at repository root or broad paths
if printf '%s' "$cmd" | grep -qE 'git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+clean[[:space:]]+.*-[a-zA-Z]*f[a-zA-Z]*d[a-zA-Z]*x'; then
  block "git clean -fdx is blocked by coord safety hook"
fi

# docker system prune -a
if printf '%s' "$cmd" | grep -qE 'docker[[:space:]]+system[[:space:]]+prune[[:space:]]+(.*[[:space:]])?-a([[:space:]]|$)'; then
  block "docker system prune -a is blocked by coord safety hook"
fi

# chmod/chown recursive changes against broad roots.
if printf '%s' "$cmd" | grep -qE '\bchmod\b[[:space:]]+.*-[a-zA-Z]*R[a-zA-Z]*[[:space:]]+.*[[:space:]](/|~|\$HOME|$HOME)(/)?([[:space:]]|$)'; then
  block "recursive chmod on a broad root is blocked by coord safety hook"
fi

if printf '%s' "$cmd" | grep -qE '\bchown\b[[:space:]]+.*-[a-zA-Z]*R[a-zA-Z]*[[:space:]]+.*[[:space:]](/|~|\$HOME|$HOME)(/)?([[:space:]]|$)'; then
  block "recursive chown on a broad root is blocked by coord safety hook"
fi

# Disk erase/format and raw disk writes.
if printf '%s' "$cmd" | grep -qE '\b(diskutil[[:space:]]+(erase|partition)|mkfs(\.|[[:space:]])|newfs_)'; then
  block "disk erase or format command is blocked by coord safety hook"
fi

if printf '%s' "$cmd" | grep -qE '\bdd\b.*[[:space:]]of=/dev/(disk|rdisk)'; then
  block "raw disk write is blocked by coord safety hook"
fi

exit 0
