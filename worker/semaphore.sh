#!/usr/bin/env bash
# Global N-slot semaphore for cross-project coord workers.
# Slots are files in $TOOLS/.semaphore/. Atomic acquire via noclobber.
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
    # Sweep stale holders (process no longer alive).
    for h in "$DIR"/holder-*; do
      [[ -f "$h" ]] || continue
      pid="${h##*/holder-}"
      if ! kill -0 "$pid" 2>/dev/null; then
        slot=$(cat "$h" 2>/dev/null || true)
        [[ -n "$slot" ]] && rm -f "$slot"
        rm -f "$h"
      fi
    done
    # Try to grab the first free slot atomically.
    for i in $(seq 1 "$N"); do
      SLOT="$DIR/slot-$i"
      if ( set -C; echo "$OWNER" > "$SLOT" ) 2>/dev/null; then
        echo "$SLOT" > "$DIR/holder-$OWNER"
        exit 0
      fi
    done
    exit 1
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
