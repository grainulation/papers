#!/bin/bash
# Synthetic workload: --stress (seed 42) in each candidate mode, 5 runs each; plus value-mode dump/replay.
# Artifact root, resolved from this script's location (real-agent-eval/v4/value_mode/synthetic).
W="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
B=$W/overturn/target/release/overturn
O=$W/real-agent-eval/v4/value_mode/synthetic
mkdir -p $O
uptime > $O/uptime_before.txt
for m in member value:max value:pooled; do
  tag=${m/:/_}
  for r in 1 2 3 4 5; do
    $B --stress --no-color --seed 42 --candidate-mode $m > $O/stress_${tag}_run$r.txt
  done
done
uptime > $O/uptime_after.txt
# value-mode artifacts replay from their seal
for m in value:max value:pooled; do
  tag=${m/:/_}
  for t in australia tcp nutrition; do
    $B --dump-artifact $O/dump_${tag}_$t.json --topic $t --agents 100 --seed 42 --no-color --candidate-mode $m
    $B --replay-from $O/dump_${tag}_$t.json --no-color
  done
done > $O/value_mode_replay.txt 2>&1
echo done
