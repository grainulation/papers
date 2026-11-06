#!/usr/bin/env python3
"""Regenerate the data files for Figure 4 (total-score margins of decisive sets).

Sources (lexical grader, implemented-reducer correctness, Python slot table):
  Collection 1: real-agent-eval/v3/results/separation_margins_v1orig_A_python_slots_v1.csv
  Collection 2: real-agent-eval/v3/results/separation_margins_v3_A_python_slots_v1.csv

A set is decisive when it has both correct and incorrect members. The margin is
`score_gap` (min correct score - max incorrect score); fill is `rust_correct`.
Points are stacked vertically when their margins round to the same 0.01 bin,
as in the original SVG figure.

Run from anywhere:  python3 tex/figures/make_fig3_data.py
Writes fig3-c{1,2}-{correct,incorrect}.dat next to this script. The .dat files
are committed so that the LaTeX build needs no Python.
"""
import csv
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent.parent / "artifact" / "real-agent-eval" / "v3" / "results"
SOURCES = {
    "c1": RESULTS / "separation_margins_v1orig_A_python_slots_v1.csv",
    "c2": RESULTS / "separation_margins_v3_A_python_slots_v1.csv",
}
BASE_Y = {"c1": 1.0, "c2": 0.0}
STEP = -0.15


def q(x: str, places: str) -> Decimal:
    return Decimal(x).quantize(Decimal(places), rounding=ROUND_HALF_UP)


def main() -> None:
    for coll, path in SOURCES.items():
        with path.open(newline="") as fh:
            rows = [r for r in csv.DictReader(fh)
                    if int(r["n_correct"]) > 0 and int(r["n_incorrect"]) > 0]
        pts = sorted(((Decimal(r["score_gap"]), int(r["rust_correct"])) for r in rows),
                     key=lambda p: (q(str(p[0]), "0.001"), p[1]))
        stacks: dict = {}
        out = {0: [], 1: []}
        for margin, correct in pts:
            b = q(str(margin), "0.01")
            row = stacks.get(b, 0)
            stacks[b] = row + 1
            out[correct].append((margin, BASE_Y[coll] + STEP * row))
        for correct, name in ((1, "correct"), (0, "incorrect")):
            dest = HERE / f"fig3-{coll}-{name}.dat"
            with dest.open("w") as fh:
                fh.write("margin y\n")
                for m, y in out[correct]:
                    fh.write(f"{m} {y:.2f}\n")
        n = len(pts)
        sep = sum(1 for m, _ in pts if m > Decimal("0.05"))
        print(f"{coll}: {n} decisive sets, {sep} separated (margin > 0.05)")


if __name__ == "__main__":
    main()
