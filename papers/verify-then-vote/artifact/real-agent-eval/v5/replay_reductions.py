#!/usr/bin/env python3
"""Re-run every sealed reducer call of an evaluate_v5.py run with another reducer binary.

    python3 replay_reductions.py --rust-dir <evaluate_v5 --out>/rust --bin ../../overturn/target/release/overturn

evaluate_v5.py writes each reducer input and the frozen binary's output to
`<out>/rust/<item>/<method>.{in,out}.json`. This script runs `BIN --reduce <in> --no-color` on every
input and checks that its stdout is byte-identical to the stored output. It is a cross-check for a
reducer rebuilt from `overturn/` (on another platform, say): the confirmatory evaluator itself accepts
only the frozen binary. Exit status 1 if any output differs.
"""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rust-dir", required=True, type=Path)
    ap.add_argument("--bin", required=True)
    a = ap.parse_args()
    inputs = sorted(a.rust_dir.glob("*/*.in.json"))
    if not inputs:
        raise SystemExit(f"no reducer inputs under {a.rust_dir} (run evaluate_v5.py with --out first)")
    differ = []
    for fin in inputs:
        fout = fin.with_name(fin.name[: -len(".in.json")] + ".out.json")
        r = subprocess.run([a.bin, "--reduce", str(fin), "--no-color"], capture_output=True)
        if r.returncode != 0 or r.stdout != fout.read_bytes():
            differ.append(fin.relative_to(a.rust_dir).as_posix())
    print(f"{len(inputs)} reductions replayed with {a.bin}: {len(inputs) - len(differ)} identical, {len(differ)} differ")
    for d in differ[:20]:
        print("  differs:", d)
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main())
