#!/bin/sh
# Replay every tamper case with one build; compare exit code to expected.tsv.
#   run_tamper.sh <label> <overturn-cmd...>   -> results/tamper-<label>.txt
# Exit != 0 if any case's exit code differs from the expected one.
set -u
EV=$(cd "$(dirname "$0")" && pwd)
LABEL=$1; shift
T="$EV/tamper"; OUT="$EV/results/tamper-$LABEL.txt"; RC=0
{ echo "# tamper replayer=$LABEL"; uname -a; echo "bin=$*"; } > "$OUT"
while IFS="$(printf '\t')" read -r name want desc; do
  msg=$("$@" --replay-from "$T/$name.json" --no-color 2>&1); got=$?
  if [ "$got" = "$want" ]; then v=OK; else v=UNEXPECTED; RC=1; fi
  printf '%s\t%s\texpected=%s\tgot=%s\t%s\n' "$LABEL" "$name" "$want" "$got" "$v" >> "$OUT"
  printf '    %s\n' "$msg" >> "$OUT"
done < "$T/expected.tsv"
cat "$OUT"; exit $RC
