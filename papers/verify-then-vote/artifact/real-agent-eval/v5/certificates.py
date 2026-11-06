#!/usr/bin/env python3
"""Root hashes and certificates of every OVERTURN reduction, the trusted reference for the sealed sets.

    python3 certificates.py --rust-dir <evaluate_v5 --out>/rust --write   # (re)write the reference
    python3 certificates.py --rust-dir <evaluate_v5 --out>/rust --check   # compare a re-run with it

evaluate_v5.py writes each reducer input and the frozen binary's output to
`<out>/rust/<item>/<reduction>.{in,out}.json`. This script reads every output and writes one record
per reduction to `results/conf/eval/certificates_v5.jsonl`: the item id, the reduction (file name),
the method, its configuration, the dropped agent for leave-one-agent-out re-decisions, the SHA-256
of the preregistered policy template, and the reducer's policy hash, root hash and certificate.
Records are sorted by item id and reduction and written as compact JSON with sorted keys, one per
line. `--check` regenerates the records from a re-run and exits 1 unless they equal the committed
file byte for byte. Standard library only.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCE = HERE / "results" / "conf" / "eval" / "certificates_v5.jsonl"
EVALUATION = HERE / "results" / "conf" / "eval" / "evaluation_v5.json"
N_EXPECTED = 7910

# Reduction file names written by evaluate_v5.py for the confirmatory run
# (--be-config member/nei0.1 --be-g-config member/nei0.5/gated).
BE_CONFIG, BE_G_CONFIG = "member/nei0.1", "member/nei0.5/gated"
FIXED = {
    "B0": ("B0", None),
    "BE_member_nei0.1": ("BE", BE_CONFIG),
    "BE_member_nei0.5_gated": ("BE-G", BE_G_CONFIG),
    "EO": ("EO", BE_CONFIG),
}


def classify(reduction):
    if reduction in FIXED:
        return (*FIXED[reduction], None)
    if reduction.startswith("LOAO_"):
        return "BE-G", BE_G_CONFIG, reduction[len("LOAO_"):]
    raise SystemExit(f"unknown reduction {reduction!r}")


def records(rust_dir):
    templates = json.load(open(EVALUATION))["provenance"]["policy_template_sha256"]
    outs = sorted(rust_dir.glob("*/*.out.json"), key=lambda p: (p.parent.name, p.name))
    if not outs:
        raise SystemExit(f"no reducer outputs under {rust_dir} (run `make overturn-reanalysis` first)")
    rows = []
    for p in outs:
        reduction = p.name[: -len(".out.json")]
        method, config, dropped = classify(reduction)
        out = json.loads(p.read_bytes())
        rows.append({"item_id": p.parent.name, "reduction": reduction, "method": method, "config": config,
                     "dropped_agent": dropped, "policy_template_sha256": templates[method],
                     "policy_hash": out["policy_hash"], "root_hash": out["root_hash"],
                     "certificate": out["certificate"]})
    if len(rows) != N_EXPECTED:
        raise SystemExit(f"{len(rows)} reductions under {rust_dir}, expected {N_EXPECTED}")
    return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows).encode()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rust-dir", required=True, type=Path)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    a = ap.parse_args()
    data = records(a.rust_dir)
    if a.write:
        REFERENCE.write_bytes(data)
        print(f"wrote {N_EXPECTED} records to {REFERENCE.relative_to(HERE)}")
        return 0
    if REFERENCE.read_bytes() != data:
        print(f"  FAIL root hashes and certificates differ from {REFERENCE.relative_to(HERE)}")
        return 1
    print(f"  PASS {N_EXPECTED} root hashes and certificates match {REFERENCE.relative_to(HERE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
