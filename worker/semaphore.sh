#!/usr/bin/env bash
# Global N-slot semaphore for cross-project coord workers.
# Slots are files in $TOOLS/.semaphore/. Sweep and acquire share an OS file lock.
#
# Usage:
#   semaphore.sh acquire    # exit 0 if slot taken, 1 if all full
#   semaphore.sh release    # release the slot held by current PID
#
# Slot count is COORD_SEMAPHORE_N (default 5).

set -euo pipefail

ACTION="${1:?usage: semaphore.sh acquire|release}"
TOOLS="$(cd "$(dirname "$0")/.." && pwd)"
DIR="$TOOLS/.semaphore"
N="${COORD_SEMAPHORE_N:-5}"
OWNER="${COORD_SEMAPHORE_OWNER:-$PPID}"

mkdir -p "$DIR"

case "$ACTION" in
  acquire)
    python3 - "$DIR" "$N" "$OWNER" <<'PYEOF'
import fcntl
import os
import sys
from pathlib import Path

slots = Path(sys.argv[1])
owner = sys.argv[3]
with (slots / ".acquire-lock").open("a") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        sys.exit(1)
    for slot in slots.glob("slot-*"):
        try:
            pid = slot.read_text().strip()
        except FileNotFoundError:
            continue
        if not pid:
            continue
        try:
            os.kill(int(pid), 0)
        except ProcessLookupError:
            slot.unlink()
        except PermissionError:
            pass
    for i in range(1, int(sys.argv[2]) + 1):
        slot = slots / f"slot-{i}"
        try:
            with slot.open("x") as handle:
                handle.write(owner + "\n")
        except FileExistsError:
            continue
        (slots / f"holder-{owner}").write_text(str(slot) + "\n")
        sys.exit(0)
    sys.exit(1)
PYEOF
    ;;
  release)
    HOLDER="$DIR/holder-$OWNER"
    if [[ -f "$HOLDER" ]]; then
      SLOT=$(cat "$HOLDER" 2>/dev/null || true)
      [[ -n "$SLOT" ]] && rm -f "$SLOT"
      rm -f "$HOLDER"
    fi
    exit 0
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 2
    ;;
esac
