#!/usr/bin/env python3
"""
Eval v6 non-binding futility look on the F1 primary method (PREREGISTRATION.md section 8, step 2; plan section 6).

On the decisive P-source conflicts among the first 300 collected items in frozen order, it prints b and c for
VV/VDF against MAJ, and nothing else (no p-value, CI, other method; J, RS, CB-S, J_local are not loaded).
The frozen BE-G reduction (evaluate_v5.reduce_method with the frozen binary) is run only to obtain the reducer's
default D (which the H4 check needs); no BE-G b or c is computed or printed. VV/VDF then comes from vdf_v6.vdf_decide.
Stop rule: b - c <= 0  ->  stop the collector for futility.

Usage
  futility_v6.py --items <first-300 items> --raw-dir <their raw records> --captures .. --checks .. --out <dir>
                 [--bin v5/frozen-bin/bran]
When --raw-dir is under v6/results/, v6/FREEZE.json must be FROZEN (the look happens during the confirmatory run).
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
N_LOOK = 300


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


VDF = _load("vdf_v6", V6 / "vdf_v6.py")
EV6 = _load("evaluate_v6", V6 / "evaluate_v6.py")     # verify_v6_freeze
E = VDF.E


def look(items, raws, ctx, cfg):
    """Rows of the decisive P conflicts: MAJ and VV/VDF correctness. D comes from the frozen reducer."""
    rows = []
    ids = sorted(raws, key=lambda i: (items[i].get("order", 0), i))
    for i in ids:
        rec = E.prepare_item(items[i], raws[i], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not (row["eligible"] and row["decisive"] and row["set"] == "P"):
            continue
        g = E.reduce_method(rec, "BE", cfg, ctx, "BE_" + cfg.replace("/", "_"))
        gt = (g["sel"] or {}).get("gate")
        d_obj = rec["by_id"][gt["default_winner"]]["parsed"] if gt else None
        dec = VDF.vdf_decide(rec["parsed"], i, d_obj, g["obj"] if gt else None, ctx.accepted)
        row["MAJ"] = E.object_correct(rec, dec["MAJ"])[0]
        row[VDF.VV_VDF] = E.object_correct(rec, dec[VDF.VV_VDF])[0]
        rows.append(row)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--items", required=True)
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--captures", required=True)
    ap.add_argument("--checks", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--bin", default=str(V5 / "frozen-bin" / "bran"))
    args = ap.parse_args(argv)

    frozen = E.jload(V5 / "FREEZE.json")["sha256"]
    if frozen.get("real-agent-eval/v5/frozen-bin/bran") != E.sha256_file(args.bin):
        raise SystemExit("ABORT: --bin is not the frozen binary of v5/FREEZE.json")
    if frozen.get("real-agent-eval/v5/evaluate_v5.py") != E.sha256_file(E.__file__):
        raise SystemExit("ABORT: evaluate_v5.py is not frozen by hash in v5/FREEZE.json")
    raw_dir, out_dir = Path(args.raw_dir).resolve(), Path(args.out).resolve()
    if V5 in out_dir.parents:
        raise SystemExit("ABORT: --out must not be under real-agent-eval/v5")
    if (V6 / "results") in raw_dir.parents:
        EV6.verify_v6_freeze(need_frozen=True)

    cfg = E.PREREG_CONFIGS["BE-G"]
    args.accepted_checker = [E.PREREG_CHECKER]
    ctx = E.Ctx(args, E.load_captures(args.captures), E.load_checks(args.checks), {})
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx.rdir = out_dir / "rust"
    items = E.load_items(args.items)
    raws = {f.stem: E.jload(f) for f in sorted(raw_dir.glob("*.json"))}
    if len(raws) != N_LOOK or set(raws) != set(items):
        raise SystemExit(f"ABORT: the look needs exactly the first {N_LOOK} items ({len(raws)} raw records)")
    first = sorted(items.values(), key=lambda x: x["order"])[:N_LOOK]
    if {x["id"] for x in first} != set(items):
        raise SystemExit(f"ABORT: --items is not the first {N_LOOK} items in frozen order")

    rows = look(items, raws, ctx, cfg)
    b = sum(1 for r in rows if r[VDF.VV_VDF] and not r["MAJ"])
    c = sum(1 for r in rows if not r[VDF.VV_VDF] and r["MAJ"])
    res = {"look": "futility", "method": "VV/VDF vs MAJ", "rule": "vdf-1", "n_items": len(raws), "checker": E.PREREG_CHECKER,
           "decisive_P": len(rows), "b": b, "c": c, "stop": b - c <= 0}
    (out_dir / "futility_look.json").write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
