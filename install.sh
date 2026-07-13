#!/usr/bin/env bash
# Symlink CoordWright sources into ~/.claude/, merge global settings,
# and load one launchd worker per project listed in projects.txt.
#
# Idempotent. Safe to re-run after editing projects.txt.

set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
LAUNCHD_DIR="$HOME/Library/LaunchAgents"

if ! command -v jq >/dev/null 2>&1; then
  echo "install.sh requires jq before modifying ~/.claude, ~/.agents, or launchd." >&2
  echo "Install it, then re-run: brew install jq && ./install.sh" >&2
  exit 127
fi

mkdir -p "$CLAUDE_DIR/agents" "$CLAUDE_DIR/commands" "$CLAUDE_DIR/skills" "$LAUNCHD_DIR"

link() {
  local src="$1" dst="$2"
  if [[ -L "$dst" ]] || [[ ! -e "$dst" ]]; then
    ln -sfn "$src" "$dst"
    echo "linked $dst -> $src"
  else
    # $dst exists as a real file/dir (e.g. a pre-symlink-era copy). `ln -sfn`
    # cannot replace a real directory, so the old behaviour skipped it —
    # leaving a stale copy that silently drifts from src (the coord-shape-review
    # drift). Heal it non-destructively: move the copy aside to a timestamped
    # backup, then symlink. (Never delete — the backup is recoverable.)
    local backup="${dst}.bak.$(date +%Y%m%d%H%M%S)"
    mv "$dst" "$backup"
    echo "backed up pre-existing copy $dst -> $backup" >&2
    ln -sfn "$src" "$dst"
    echo "linked $dst -> $src"
  fi
}

ensure_local_exclude() {
  local worktree="$1" pattern="$2"
  local gitdir exclude
  gitdir=$(git -C "$worktree" rev-parse --git-common-dir 2>/dev/null || true)
  [[ -n "$gitdir" ]] || return 0
  case "$gitdir" in
    /*) ;;
    *) gitdir="$worktree/$gitdir" ;;
  esac
  mkdir -p "$gitdir/info"
  exclude="$gitdir/info/exclude"
  touch "$exclude"
  if ! grep -Fxq "$pattern" "$exclude"; then
    {
      printf '\n# Coord local editor defaults\n'
      printf '%s\n' "$pattern"
    } >> "$exclude"
    echo "updated $exclude"
  fi
}

ensure_coord_runtime_ignored() {
  # Goal pattern: `.coord/*` ignores ephemeral worker state, while
  # `!.coord/handoffs/` re-includes subtask handoff files so the audit trail
  # mandated by agent-workflow-policy.md rule 6 can live in git.
  #
  # Migration is intentionally minimal: replace the old `.coord/` line in
  # place (preserving surrounding comments and ordering) or append the
  # two-line pair at the end if the project has no coord ignore yet. We do
  # NOT strip arbitrary surrounding comments because projects customize
  # them.
  local worktree="$1" gitignore="$1/.gitignore"
  if ! git -C "$worktree" rev-parse --git-dir >/dev/null 2>&1; then
    return 0
  fi
  local ephemeral_ignored=no handoffs_ignored=no
  git -C "$worktree" check-ignore -q .coord/worker.state 2>/dev/null && ephemeral_ignored=yes
  git -C "$worktree" check-ignore -q .coord/handoffs/.keep 2>/dev/null && handoffs_ignored=yes
  if [[ "$ephemeral_ignored" == "yes" && "$handoffs_ignored" == "no" ]]; then
    return 0
  fi
  touch "$gitignore"
  python3 - "$gitignore" <<'PYEOF'
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text() if path.exists() else ""
lines = text.splitlines()
out = []
replaced = False
already_has_pair = any(l.strip() == "!.coord/handoffs/" for l in lines)
for line in lines:
    stripped = line.strip()
    if stripped == ".coord/" and not replaced:
        # Migrate old wholesale ignore to the new pair, preserving indentation.
        prefix = line[: len(line) - len(line.lstrip())]
        out.append(f"{prefix}.coord/*")
        if not already_has_pair:
            out.append(f"{prefix}!.coord/handoffs/")
        replaced = True
        continue
    out.append(line)

if not replaced and not any(l.strip() == ".coord/*" for l in out):
    # No prior coord line — append fresh block at end.
    if out and out[-1].strip() != "":
        out.append("")
    out.append("# Coord worker runtime files (handoffs tracked, rest ephemeral)")
    out.append(".coord/*")
    out.append("!.coord/handoffs/")
elif not already_has_pair and any(l.strip() == ".coord/*" for l in out) and not replaced:
    # `.coord/*` is present but the handoffs exception is not — insert it
    # immediately after the `.coord/*` line so the pair stays together.
    new_out = []
    for line in out:
        new_out.append(line)
        if line.strip() == ".coord/*":
            prefix = line[: len(line) - len(line.lstrip())]
            new_out.append(f"{prefix}!.coord/handoffs/")
    out = new_out

path.write_text("\n".join(out) + "\n")
PYEOF
  echo "ensured coord gitignore in $gitignore (.coord/* + !.coord/handoffs/)"
}

is_tracked() {
  local worktree="$1" path="$2"
  git -C "$worktree" ls-files --error-unmatch "$path" >/dev/null 2>&1
}

for f in "$TOOLS"/agents/*.md; do
  link "$f" "$CLAUDE_DIR/agents/$(basename "$f")"
done

for f in "$TOOLS"/commands/*.md; do
  link "$f" "$CLAUDE_DIR/commands/$(basename "$f")"
done

for d in "$TOOLS"/skills/*/; do
  [[ -d "$d" ]] || continue
  name=$(basename "$d")
  link "${d%/}" "$CLAUDE_DIR/skills/$name"
done

AGENTS_DIR="$HOME/.agents"
mkdir -p "$AGENTS_DIR/skills"
for d in "$TOOLS"/skills/*/; do
  [[ -d "$d" ]] || continue
  name=$(basename "$d")
  link "${d%/}" "$AGENTS_DIR/skills/$name"
done

# Merge settings/global.json into ~/.claude/settings.json.
GLOBAL="$CLAUDE_DIR/settings.json"
SRC="$TOOLS/settings/global.json"
# Resolve placeholders to this machine's absolute paths before merging.
# Parse the JSON first and substitute inside parsed string values, then
# re-serialize: raw text substitution (sed/str.replace) corrupts the JSON
# when a checkout path contains \, ", & or the sed delimiter.
SRC_RESOLVED=$(mktemp)
python3 - "$SRC" "$SRC_RESOLVED" "$TOOLS" "$HOME" <<'PYEOF'
import json
import sys

src, dst, tools, home = sys.argv[1:]
replacements = {"__COORD_TOOLS__": tools, "__HOME__": home}

def resolve(node):
    if isinstance(node, dict):
        return {resolve(k): resolve(v) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(item) for item in node]
    if isinstance(node, str):
        for needle, value in replacements.items():
            node = node.replace(needle, value)
        return node
    return node

with open(src) as f:
    data = json.load(f)
with open(dst, "w") as f:
    json.dump(resolve(data), f, indent=2)
    f.write("\n")
PYEOF
SRC="$SRC_RESOLVED"
if [[ -f "$GLOBAL" ]]; then
  backup="${GLOBAL}.bak.$(date +%Y%m%d%H%M%S)"
  cp "$GLOBAL" "$backup"
  tmp=$(mktemp)
  jq -s '
    def array($value):
      if $value == null then []
      elif ($value | type) == "array" then $value
      else [$value]
      end;
    def unique_items:
      reduce .[] as $item ([]; if any(.[]; . == $item) then . else . + [$item] end);

    .[0] as $base
    | .[1] as $src
    | ($base * $src)
    | .permissions.allow = ((array($base.permissions.allow) + array($src.permissions.allow)) | unique_items)
    | .permissions.additionalDirectories = ((array($base.permissions.additionalDirectories) + array($src.permissions.additionalDirectories)) | unique_items)
    | .hooks = (($base.hooks // {}) * ($src.hooks // {}))
    | reduce (((($base.hooks // {}) | keys_unsorted) + (($src.hooks // {}) | keys_unsorted)) | unique[]) as $event (.;
        .hooks[$event] = ((array($base.hooks[$event]) + array($src.hooks[$event])) | unique_items)
      )
  ' "$GLOBAL" "$SRC" > "$tmp"
  mv "$tmp" "$GLOBAL"
  echo "backed up $GLOBAL -> $backup"
  echo "merged $SRC into $GLOBAL"
else
  cp "$SRC" "$GLOBAL"
  echo "wrote $GLOBAL"
fi

# Generate and load one launchd worker per project.
if [[ ! -f "$TOOLS/projects.txt" ]]; then
  echo "no projects.txt; skipping launchd setup" >&2
  exit 0
fi

while IFS= read -r PROJ || [[ -n "$PROJ" ]]; do
  [[ -z "$PROJ" || "$PROJ" =~ ^[[:space:]]*# ]] && continue
  PROJ="${PROJ%/}"
  if [[ ! -d "$PROJ" ]]; then
    echo "skip missing project: $PROJ" >&2
    continue
  fi
  NAME=$(basename "$PROJ")
  SAFE_NAME=$(printf '%s' "$NAME" | LC_ALL=C tr -c '[:alnum:]._-' '_')
  PLIST="$LAUNCHD_DIR/com.coord.worker.${SAFE_NAME}.plist"
  ensure_coord_runtime_ignored "$PROJ"
  # Propagate the unattended-autonomy acknowledgement into the worker plist
  # only when it is set in the installing environment. Re-running install
  # without it regenerates the plist WITHOUT the key, so revocation is the
  # same command as installation. See README "Blast radius".
  python3 - "$PLIST" "$TOOLS/worker/worker.sh" "$PROJ" "$SAFE_NAME" "${COORD_UNSAFE_AUTONOMOUS:-}" <<'PYEOF'
import plistlib
import sys

plist, worker, project, name, unsafe_ack = sys.argv[1:]
env = {
    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
}
if unsafe_ack == "1":
    env["COORD_UNSAFE_AUTONOMOUS"] = "1"
data = {
    "Label": f"com.coord.worker.{name}",
    "ProgramArguments": [worker, project],
    "StartInterval": 60,
    "RunAtLoad": True,
    "WorkingDirectory": project,
    "StandardOutPath": f"{project}/.coord/worker.log",
    "StandardErrorPath": f"{project}/.coord/worker.log",
    "EnvironmentVariables": env,
}
with open(plist, "wb") as f:
    plistlib.dump(data, f, sort_keys=False)
PYEOF
  plutil -lint "$PLIST" >/dev/null
  mkdir -p "$PROJ/.coord"
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  echo "loaded launchd worker for $PROJ"

  # Normalize the tracked agent workspace in the canonical checkout to the
  # single main checkout. Use an absolute folder path so the file stays valid
  # in any checkout. Persistent task-a/task-b slots were retired in favor of
  # on-demand session worktrees, which are opened ad hoc and not tracked here.
  AGENT_WORKSPACE="$PROJ/${NAME}-agents.code-workspace"
  if command -v jq >/dev/null 2>&1 && [[ -f "$AGENT_WORKSPACE" ]]; then
    tmp=$(mktemp)
    jq --indent 4 \
      --arg name "$NAME" \
      --arg main "$PROJ" \
      '.folders = [
        {"name": ($name + "-main"), "path": $main}
      ]' "$AGENT_WORKSPACE" > "$tmp"
    mv "$tmp" "$AGENT_WORKSPACE"
    echo "updated $AGENT_WORKSPACE"
  fi

  # Apply project-local editor defaults to the main checkout. On-demand session
  # worktrees are created off origin/main and inherit tracked config, so they
  # are not wired here.
  for WORKTREE in "$PROJ"; do
    [[ -d "$WORKTREE" ]] || continue
    MARKDOWNLINT_CONFIG="$WORKTREE/.markdownlint-cli2.jsonc"
    if [[ ! -f "$MARKDOWNLINT_CONFIG" ]]; then
      printf '{\n  "config": {\n    "MD013": false\n  },\n  "ignores": [\n    "tasks/**"\n  ]\n}\n' > "$MARKDOWNLINT_CONFIG"
      echo "wrote $MARKDOWNLINT_CONFIG"
    fi

    # Ensure .vscode/settings.json suppresses the default zsh terminal on open.
    # Skip the rewrite when the key is already set to avoid jq re-indenting
    # the file from 4-space to 2-space on every run.
    VSCODE_SETTINGS="$WORKTREE/.vscode/settings.json"
    ensure_local_exclude "$WORKTREE" ".vscode/settings.json"
    if is_tracked "$WORKTREE" ".vscode/settings.json"; then
      echo "skip tracked $VSCODE_SETTINGS; untrack or ignore it to keep coord worker clean" >&2
      continue
    fi
    mkdir -p "$WORKTREE/.vscode"
    if command -v jq >/dev/null 2>&1 && [[ -f "$VSCODE_SETTINGS" ]]; then
      current=$(jq -r '."terminal.integrated.hideOnStartup" // empty' "$VSCODE_SETTINGS" 2>/dev/null || true)
      if [[ "$current" != "always" ]]; then
        tmp=$(mktemp)
        jq --indent 4 '. + {"terminal.integrated.hideOnStartup": "always"}' "$VSCODE_SETTINGS" > "$tmp"
        mv "$tmp" "$VSCODE_SETTINGS"
        echo "updated $VSCODE_SETTINGS"
      fi
    elif [[ ! -f "$VSCODE_SETTINGS" ]]; then
      printf '{\n    "terminal.integrated.hideOnStartup": "always"\n}\n' > "$VSCODE_SETTINGS"
      echo "wrote $VSCODE_SETTINGS"
    fi
  done
done < "$TOOLS/projects.txt"

# Reconcile stale workers: a project removed from projects.txt must not keep a
# loaded plist — with a previously-acknowledged COORD_UNSAFE_AUTONOMOUS key that
# would silently keep autonomy enabled after the operator revoked the entry.
EXPECTED_LABELS=$(while IFS= read -r PROJ || [[ -n "$PROJ" ]]; do
  [[ -z "$PROJ" || "$PROJ" =~ ^[[:space:]]*# ]] && continue
  PROJ="${PROJ%/}"
  NAME=$(basename "$PROJ")
  # printf, not a pipe from basename: tr -c would mangle the trailing newline
  # into an underscore and the label would never match the generated plist.
  printf 'com.coord.worker.%s\n' "$(printf '%s' "$NAME" | LC_ALL=C tr -c '[:alnum:]._-' '_')"
done < "$TOOLS/projects.txt")
for PLIST in "$LAUNCHD_DIR"/com.coord.worker.*.plist; do
  [[ -e "$PLIST" ]] || continue
  LABEL=$(basename "$PLIST" .plist)
  if ! grep -Fxq "$LABEL" <<< "$EXPECTED_LABELS"; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "removed stale worker $LABEL (project no longer in projects.txt)"
  fi
done

echo "install done."
