#!/usr/bin/env bash
# audit-projects-secrets.sh — security sweep across every project in
# projects.txt. Looks for the same classes of issues we hand-checked manually:
# .env file modes, credential-bearing files, and tracked files
# whose content matches secret-keyword patterns (manual review needed).
#
# Read-only. Prints findings; exits 0 always (advisory, not gate).
# Usage: bash ~/Projects/coord-wright/bin/audit-projects-secrets.sh

set -uo pipefail

TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
PROJECTS_TXT="$TOOLS/projects.txt"

[[ -f "$PROJECTS_TXT" ]] || { echo "projects.txt missing at $PROJECTS_TXT"; exit 1; }

# Patterns for the keyword grep. False positives are expected — flagged
# files need human review. Patterns reused below are kept here so the
# user can copy/adjust.
SECRET_RX='(password|api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|bearer)[[:space:]]*[:=]'

# Paths we skip in find/grep because false-positive density is too high.
PRUNE='-path */node_modules -o -path */.venv -o -path */venv -o -path */.git -o -path */dist -o -path */build -o -path */test-results -o -path */playwright-report'

mode_label() {
  # Translate stat mode string into a "(loose|tight)" hint.
  case "$1" in
    -r--------|-rw-------)  echo "tight" ;;
    -rw-r--r--|-rw-rw-r--)  echo "world-readable" ;;
    *)                       echo "$1" ;;
  esac
}

while IFS= read -r proj; do
  [[ -z "$proj" || "$proj" =~ ^# ]] && continue
  name=$(basename "$proj")
  [[ -d "$proj" ]] || { echo "=== $name (skip: dir missing) ==="; continue; }

  echo "=== $name ==="

  # 1. .env files anywhere in the project
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    m=$(stat -f %Sp "$f")
    label=$(mode_label "$m")
    tracked=$(git -C "$proj" ls-files --error-unmatch "${f#$proj/}" >/dev/null 2>&1 && echo "TRACKED" || echo "untracked")
    printf "  env-file  %s  mode=%s [%s] git=%s\n" "${f#$proj/}" "$m" "$label" "$tracked"
  done < <(find "$proj" \( $PRUNE \) -prune -o -type f -name '.env*' -print 2>/dev/null | grep -vE '\.env\.(example|sample|template)$' || true)

  # 2. Credential-pattern files
  while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    m=$(stat -f %Sp "$f")
    label=$(mode_label "$m")
    printf "  cred-file %s  mode=%s [%s]\n" "${f#$proj/}" "$m" "$label"
  done < <(find "$proj" \( $PRUNE \) -prune -o -type f \
    \( -name 'credentials*' -o -name 'secrets*' -o -name 'auth.json' \
       -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \
       -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'wallet.dat' \) \
    -print 2>/dev/null || true)

  # 3. Tracked files containing secret-keyword patterns (advisory)
  if git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
    hits=$(cd "$proj" && git ls-files -z | grep -zvE '\.(md|rst|txt|html|sample|example|template|lock|sum)$|^docs/|^README|^CHANGELOG' \
      | xargs -0 grep -lIE "$SECRET_RX" 2>/dev/null | head -8 || true)
    if [[ -n "$hits" ]]; then
      echo "  keyword hits (tracked files, manual review needed):"
      printf '%s\n' "$hits" | sed 's/^/    /'
    fi
  fi

  # 4. Worker runtime files visible in git status (sign that .gitignore is incomplete)
  if git -C "$proj" rev-parse --git-dir >/dev/null 2>&1; then
    coord_dirty=$(cd "$proj" && git status --porcelain --untracked-files=all 2>/dev/null | grep -E '^\?\? \.coord/' || true)
    if [[ -n "$coord_dirty" ]]; then
      echo "  coord runtime untracked (gitignore gap):"
      printf "    %s\n" "$coord_dirty"
    fi
  fi
done < "$PROJECTS_TXT"

echo
echo "=== Commands used (for your reference) ==="
cat <<'CMDS'
  # Find env files anywhere in a project:
  find <project> \( -path '*/node_modules' -o -path '*/.venv' -o -path '*/venv' -o -path '*/.git' \) -prune \
    -o -type f -name '.env*' -print | grep -v '\.env\.\(example\|sample\|template\)$'

  # Find credential-pattern files:
  find <project> \( ...prunes... \) -prune -o -type f \
    \( -name 'credentials*' -o -name 'secrets*' -o -name 'auth.json' \
       -o -name '*.pem' -o -name '*.key' -o -name '*.p12' -o -name '*.pfx' \
       -o -name 'id_rsa*' -o -name 'id_ed25519*' -o -name 'wallet.dat' \) -print

  # Grep tracked files for secret-keyword patterns:
  cd <project> && git ls-files -z | grep -zvE '\.(md|rst|txt|...)$' \
    | xargs -0 grep -lIE '(password|api[_-]?key|secret[_-]?key|access[_-]?token|client[_-]?secret|private[_-]?key|bearer)[[:space:]]*[:=]'

  # Check a single file's mode:
  stat -f %Sp <file>

  # Tighten a file to owner-read-only:
  chmod 400 <file>
CMDS
