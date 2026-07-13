#!/usr/bin/env bash
# Dependency audit dispatcher — detects manifests in the directory tree under
# the given path and runs the appropriate vulnerability scanner for each.
# Read-only; never modifies lockfiles or installs packages.
#
# Usage:
#   bin/dep-audit.sh [path]      # default path = current directory
#
# Exit-code policy (strict precedence — highest first):
#   2 = at least one detected manifest could not be scanned (tool missing,
#       lockfile missing for a manifest that needs one, scanner operational
#       failure with rc not in {0,1}).
#   1 = all applicable scanners ran and at least one reported vulnerabilities
#       above its default threshold.
#   0 = no manifests detected, or all scanners ran clean.

set -u

ROOT="${1:-.}"
ROOT_ABS=$(cd "$ROOT" 2>/dev/null && pwd) || { echo "dep-audit: cannot enter $ROOT" >&2; exit 64; }

# Directories to skip when searching for manifests.
PRUNE=(-name node_modules -o -name .git -o -name target -o -name dist -o -name build -o -name venv -o -name .venv -o -name __pycache__ -o -name vendor)

found_any=0
any_vuln_reported=0
any_scanner_problem=0
missing_tools=()

note_problem() {
  any_scanner_problem=1
}

note_vuln() {
  any_vuln_reported=1
}

# update_status interprets a scanner's exit code under the documented contract:
#   0   → clean
#   1   → vulnerabilities reported
#   *   → operational failure (treated as scanner problem, not vuln)
update_status() {
  local rc=$1
  if (( rc == 0 )); then
    return 0
  elif (( rc == 1 )); then
    note_vuln
  else
    note_problem
  fi
}

run_scan() {
  local label=$1; shift
  echo
  echo "=== $label ==="
  echo "+ $*"
  "$@"
}

note_missing() {
  local manifest=$1
  local tool=$2
  echo
  echo "=== $manifest detected — $tool not installed ==="
  echo "Install $tool to enable scanning. Skipping."
  missing_tools+=("$tool")
  note_problem
}

note_incomplete() {
  local manifest=$1
  local reason=$2
  echo
  echo "=== $manifest detected — incomplete scan ==="
  echo "$reason"
  note_problem
}

# find_manifests writes matching files (one per line) to stdout. Honors PRUNE.
find_manifests() {
  local name=$1
  find "$ROOT_ABS" \( "${PRUNE[@]}" \) -prune -o -name "$name" -type f -print 2>/dev/null
}

# --- npm ---------------------------------------------------------------------
# Audit at each package.json that owns a lockfile (package-lock.json,
# yarn.lock, or pnpm-lock.yaml). Skip leaf workspace packages whose lockfile
# lives at the workspace root — auditing them would re-audit the same tree.
while IFS= read -r pkg; do
  [[ -z "$pkg" ]] && continue
  dir=$(dirname "$pkg")
  has_lock=0
  for lock in package-lock.json yarn.lock pnpm-lock.yaml; do
    [[ -f "$dir/$lock" ]] && has_lock=1 && break
  done
  if (( has_lock == 0 )); then
    continue
  fi
  found_any=1
  if command -v npm >/dev/null 2>&1; then
    (cd "$dir" && run_scan "npm audit ($pkg)" npm audit --omit=dev --audit-level=high)
    update_status $?
  else
    note_missing "$pkg" npm
  fi
done < <(find_manifests package.json)

# --- pip (requirements.txt — recursive) --------------------------------------
while IFS= read -r req; do
  [[ -z "$req" ]] && continue
  found_any=1
  if command -v pip-audit >/dev/null 2>&1; then
    run_scan "pip-audit ($req)" pip-audit -r "$req" --strict
    update_status $?
  else
    note_missing "$req" pip-audit
  fi
done < <(find_manifests requirements.txt)

# --- pyproject.toml (recursive) — needs a lockfile or pip-audit will audit
#     the active Python env, not project deps. Detect a sibling
#     poetry.lock / uv.lock / pdm.lock and use that; otherwise mark
#     incomplete.
while IFS= read -r pyproject; do
  [[ -z "$pyproject" ]] && continue
  dir=$(dirname "$pyproject")
  found_any=1
  if ! command -v pip-audit >/dev/null 2>&1; then
    note_missing "$pyproject" pip-audit
    continue
  fi
  if [[ -f "$dir/poetry.lock" ]] && command -v poetry >/dev/null 2>&1; then
    (cd "$dir" && run_scan "pip-audit (poetry.lock @ $dir)" bash -c "pip-audit -r <(poetry export -f requirements.txt --without-hashes) --strict")
    update_status $?
  elif [[ -f "$dir/uv.lock" ]] && command -v uv >/dev/null 2>&1; then
    (cd "$dir" && run_scan "pip-audit (uv.lock @ $dir)" bash -c "pip-audit -r <(uv export --format requirements-txt) --strict")
    update_status $?
  elif [[ -f "$dir/pdm.lock" ]] && command -v pdm >/dev/null 2>&1; then
    (cd "$dir" && run_scan "pip-audit (pdm.lock @ $dir)" bash -c "pip-audit -r <(pdm export -f requirements --without-hashes) --strict")
    update_status $?
  else
    note_incomplete "$pyproject" "No supported lockfile (poetry.lock / uv.lock / pdm.lock) with matching tool present. Bare 'pip-audit' on pyproject.toml audits the active Python environment, not project deps, which can mask vulnerabilities. Export a lockfile or pin a requirements.txt."
  fi
done < <(find_manifests pyproject.toml)

# --- cargo (recursive) -------------------------------------------------------
while IFS= read -r cargo; do
  [[ -z "$cargo" ]] && continue
  dir=$(dirname "$cargo")
  # Audit only the Cargo.toml that owns a Cargo.lock — workspace members typically don't.
  [[ ! -f "$dir/Cargo.lock" ]] && continue
  found_any=1
  if command -v cargo-audit >/dev/null 2>&1 || cargo audit --version >/dev/null 2>&1; then
    (cd "$dir" && run_scan "cargo audit ($cargo)" cargo audit -D warnings)
    update_status $?
  else
    note_missing "$cargo" cargo-audit
  fi
done < <(find_manifests Cargo.toml)

# --- go (recursive) ----------------------------------------------------------
while IFS= read -r gomod; do
  [[ -z "$gomod" ]] && continue
  dir=$(dirname "$gomod")
  found_any=1
  if command -v govulncheck >/dev/null 2>&1; then
    (cd "$dir" && run_scan "govulncheck ($gomod)" govulncheck ./...)
    update_status $?
  else
    note_missing "$gomod" govulncheck
  fi
done < <(find_manifests go.mod)

# --- gem (recursive) ---------------------------------------------------------
while IFS= read -r lockfile; do
  [[ -z "$lockfile" ]] && continue
  dir=$(dirname "$lockfile")
  found_any=1
  if command -v bundle-audit >/dev/null 2>&1; then
    (cd "$dir" && run_scan "bundle-audit ($lockfile)" bundle-audit check --update)
    update_status $?
  else
    note_missing "$lockfile" bundle-audit
  fi
done < <(find_manifests Gemfile.lock)

# --- composer (recursive) ----------------------------------------------------
while IFS= read -r lockfile; do
  [[ -z "$lockfile" ]] && continue
  dir=$(dirname "$lockfile")
  found_any=1
  if command -v composer >/dev/null 2>&1; then
    (cd "$dir" && run_scan "composer audit ($lockfile)" composer audit --no-dev)
    update_status $?
  else
    note_missing "$lockfile" composer
  fi
done < <(find_manifests composer.lock)

echo
echo "=== Summary ==="
if (( found_any == 0 )); then
  echo "No dependency manifests found under $ROOT_ABS."
  exit 0
fi

if (( ${#missing_tools[@]} > 0 )); then
  echo "Missing scanners (manifest detected but tool not installed):"
  printf '  - %s\n' "${missing_tools[@]}"
fi

if (( any_scanner_problem == 1 )); then
  echo "Incomplete: at least one detected manifest could not be scanned."
  exit 2
fi
if (( any_vuln_reported == 1 )); then
  echo "Findings reported. Review scanner output above and update lockfiles or open mitigations."
  exit 1
fi
echo "All scanners passed (no high/critical findings at default thresholds)."
exit 0
