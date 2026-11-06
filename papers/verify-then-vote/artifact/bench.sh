#!/usr/bin/env bash
# bench.sh — Run the overturn benchmark modes and write CSV and text output
set -euo pipefail

OVERTURN="./overturn/target/release/overturn"
OUTDIR="bench-output"
mkdir -p "$OUTDIR"

echo "=== overturn benchmark suite ==="
echo ""

# ── 1. Scaling benchmark (compilation time vs N) ─────────────────
echo "--- Scaling benchmark ---"
SCALING_CSV="$OUTDIR/scaling.csv"
echo "n,claims,conflicts,output,precision,fp,ees,compress,time_us" > "$SCALING_CSV"

for n in 3 5 10 20 50 100 200 500 1000 2000 5000 10000; do
    # Run overturn with --scaling is table-formatted; instead compile directly and parse
    OUTPUT=$($OVERTURN -n "$n" --topic tcp --no-color --seed 42 2>&1 | grep -A1 "Compilation time" | tail -1 || true)

    # Use per-pass timing for more structured data
    # Actually, let's just time the compilation directly
    START_NS=$(python3 -c "import time; print(int(time.time_ns()))")
    RESULT=$($OVERTURN -n "$n" --topic tcp --no-color --seed 42 2>&1)
    END_NS=$(python3 -c "import time; print(int(time.time_ns()))")

    WALL_US=$(( (END_NS - START_NS) / 1000 ))

    # Parse output
    CLAIMS=$(echo "$RESULT" | grep "Total claims:" | awk '{print $NF}')
    ADMITTED=$(echo "$RESULT" | grep "Admitted:" | awk '{print $NF}')
    FP=$(echo "$RESULT" | grep "False positives:" | awk '{print $1}' | head -1)
    TIME_MS=$(echo "$RESULT" | grep "Compilation time:" | awk '{print $NF}' | sed 's/ms//')

    # Convert TIME_MS to microseconds
    TIME_US=$(python3 -c "print(int(float('${TIME_MS:-0}') * 1000))")

    echo "$n,$CLAIMS,0,$ADMITTED,0,$FP,0,0,$TIME_US" >> "$SCALING_CSV"
    echo "  N=$n: ${TIME_US}μs"
done

echo ""
echo "Scaling data written to $SCALING_CSV"

# ── 2. Per-pass timing breakdown ──────────────────────────────────
echo ""
echo "--- Per-pass timing ---"
$OVERTURN --pass-timing --no-color --seed 42 > "$OUTDIR/pass-timing.txt" 2>&1
echo "Per-pass timing written to $OUTDIR/pass-timing.txt"

# ── 3. Stress test ────────────────────────────────────────────────
echo ""
echo "--- Stress test ---"
$OVERTURN --stress --no-color --seed 42 > "$OUTDIR/stress.txt" 2>&1
echo "Stress test results written to $OUTDIR/stress.txt"

# ── 4. Replay determinism ─────────────────────────────────────────
echo ""
echo "--- Replay determinism (1000 iterations) ---"
$OVERTURN --replay --no-color --seed 42 > "$OUTDIR/replay.txt" 2>&1
cat "$OUTDIR/replay.txt" | grep -E "PASS|OK|FAIL"

# ── 5. Baseline comparison ────────────────────────────────────────
echo ""
echo "--- Baseline comparison ---"
$OVERTURN --baselines --no-color --seed 42 > "$OUTDIR/baselines.txt" 2>&1
echo "Baseline comparison written to $OUTDIR/baselines.txt"

# ── 6. Property checks ───────────────────────────────────────────
echo ""
echo "--- Property checks ---"
$OVERTURN --properties --no-color --seed 42 > "$OUTDIR/properties.txt" 2>&1
cat "$OUTDIR/properties.txt" | grep -E "✓|✗|passed|failed"

# ── 7. Replay variance ───────────────────────────────────────────
echo ""
echo "--- Replay variance (overturn vs baselines) ---"
$OVERTURN --replay-variance --no-color --seed 42 > "$OUTDIR/replay-variance.txt" 2>&1
echo "Replay variance written to $OUTDIR/replay-variance.txt"

echo ""
echo "=== All benchmarks complete. Output in $OUTDIR/ ==="
