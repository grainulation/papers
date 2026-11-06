#!/usr/bin/env python3
"""
Eval v5 non-binding futility look (PREREGISTRATION.md §8, step 2).

Reduces the H1a configuration BE-G (member/nei0.5/gated) against MAJ on the decisive P-source
conflicts among the first 300 collected items in frozen order, with the frozen binary and the
prereg checker, and prints only b and c. No p-value, CI or other method is computed; J, RS, CB-S
and J_local are not loaded.

Usage
  python3 futility_look.py --items <first-300 items> --raw-dir <their raw records> \
      --captures .. --checks .. --out <dir>
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate_v5 as E  # noqa: E402

N_LOOK = 300


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--captures", required=True)
    ap.add_argument("--checks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bin", default=str(HERE / "frozen-bin" / "bran"))
    args = ap.parse_args(argv)

    frozen = E.jload(HERE / "FREEZE.json")["sha256"]
    if frozen.get("real-agent-eval/v5/frozen-bin/bran") != E.sha256_file(args.bin):
        raise SystemExit("ABORT: --bin is not the frozen binary of v5/FREEZE.json")
    if frozen.get("real-agent-eval/v5/evaluate_v5.py") != E.sha256_file(E.__file__):
        raise SystemExit("ABORT: evaluate_v5.py is not frozen by hash in v5/FREEZE.json")

    args.accepted_checker = [E.PREREG_CHECKER]
    ctx = E.Ctx(args, E.load_captures(args.captures), E.load_checks(args.checks), {})
    out_dir = Path(args.out).resolve()
    ctx.rdir = out_dir / "rust"

    items = E.load_items(args.items)
    raw_dir = Path(args.raw_dir)
    raws = {f.stem: E.jload(f) for f in sorted(raw_dir.glob("*.json"))}
    ids = sorted(raws, key=lambda i: (items[i].get("order", 0), i))
    if len(ids) != N_LOOK or set(ids) != set(items):
        raise SystemExit(f"ABORT: the look needs exactly the first {N_LOOK} items ({len(ids)} raw records)")

    cfg = E.PREREG_CONFIGS["BE-G"]
    rows = []
    for i in ids:
        rec = E.prepare_item(items[i], raws[i], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not (row["eligible"] and row["decisive"] and row["set"] == "P"):
            continue
        g = E.reduce_method(rec, "BE", cfg, ctx, "BE_" + cfg.replace("/", "_"))
        maj, _ = E._plurality([v["parsed"] for v in rec["parsed"]], "v5-majority:" + i)
        row["MAJ"], _ = E.object_correct(rec, maj)
        row["BE-G"] = g["correct"]
        rows.append(row)

    b = sum(1 for r in rows if r["BE-G"] and not r["MAJ"])
    c = sum(1 for r in rows if not r["BE-G"] and r["MAJ"])
    res = {"look": "futility", "n_items": len(ids), "config": cfg, "checker": E.PREREG_CHECKER,
           "decisive_P": len(rows), "b": b, "c": c, "stop": b - c <= 0}
    (out_dir / "futility_look.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
