#!/bin/sh
# Cross-architecture replay driver (POSIX sh; runs on macOS and in the Linux image).
#   run_platform.sh dump   <label> <overturn-cmd...>   dump 5 topics -> dumps/<label>/
#   run_platform.sh replay <label> <overturn-cmd...>   replay every dumps/*/ with this binary
# Results go to results/<label>-{dump,replay}.txt. Exit != 0 on any failure.
set -u
EV=$(cd "$(dirname "$0")" && pwd)
MODE=$1; LABEL=$2; shift 2
TOPICS="australia pluto tides tcp nutrition"
N=100; SEED=42
mkdir -p "$EV/results"
case "$MODE" in
dump)
  OUT="$EV/results/$LABEL-dump.txt"; mkdir -p "$EV/dumps/$LABEL"
  { echo "# label=$LABEL"; uname -a; echo "bin=$*"; } > "$OUT"
  for t in $TOPICS; do
    "$@" --dump-artifact "$EV/dumps/$LABEL/$t.json" --topic "$t" --agents $N --seed $SEED --no-color >> "$OUT" 2>&1 || { echo "DUMP FAIL $t" >> "$OUT"; exit 1; }
  done
  cat "$OUT" ;;
replay)
  OUT="$EV/results/$LABEL-replay.txt"; RC=0
  { echo "# replayer=$LABEL"; uname -a; echo "bin=$*"; } > "$OUT"
  for d in "$EV"/dumps/*/; do
    src=$(basename "$d")
    for t in $TOPICS; do
      printf '%s <- %s/%s: ' "$LABEL" "$src" "$t" >> "$OUT"
      "$@" --replay-from "$d$t.json" --no-color >> "$OUT" 2>&1 || { RC=1; echo "  (exit $?)" >> "$OUT"; }
    done
  done
  cat "$OUT"; exit $RC ;;
esac
