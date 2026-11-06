#!/usr/bin/env python3
"""Reconstruct the memory-only study from published records.

Usage: python3 reanalyze.py --out OUTPUT --bin REBUILT_REDUCER --compare

Verifies original freeze hashes, accepting only exact original/published pairs
in FROZEN_REDACTIONS.md. The frozen evaluator is loaded unchanged; documented
redacted input hashes are mapped solely for its historical integrity checks.
The actual binary hash is retained in output provenance.

Amendment 5 runs in memory with output/input directories and the selected
binary substituted explicitly. Its binary assertion checks the actual selected
binary hash, after the historical public artifact preflight. This is a
source-rebuilt reconstruction, not execution of the historical frozen binary.
Comparisons exclude timings, runtime paths and binary identities; decisions
and statistical results must match. No model calls are made.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARTIFACT = HERE.parents[1]
REDACTIONS_DOC = ARTIFACT / "FROZEN_REDACTIONS.md"

# FREEZE.json key -> (frozen sha256, published sha256 of the redacted document), as listed in
# FROZEN_REDACTIONS.md. Only these documents may differ from their frozen hash.
def published_redactions():
    rows = re.findall(r"^\|\s*`real-agent-eval/v4/([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]{64})`", REDACTIONS_DOC.read_text(), re.M)
    return {p: (old, new) for p, old, new in rows}

REDACTED = published_redactions()
COMMITTED_ARGS = ["--split", "conf", "--bin", "frozen-bin/bran-v4-eval", "--m11-model", "qwen2.5_3b"]


def sha256_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def check_redaction_table():
    """The hardcoded pairs must be the ones FROZEN_REDACTIONS.md publishes."""
    text = REDACTIONS_DOC.read_text()
    for key, (frozen, redacted) in REDACTED.items():
        row = re.search(r"^\|\s*`real-agent-eval/v4/%s`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]{64})`"
                        % re.escape(key), text, re.M)
        if not row or row.groups() != (frozen, redacted):
            raise SystemExit(f"ABORT: {key}: redaction hashes differ from {REDACTIONS_DOC.name}")


def verify_freeze():
    freeze = json.load(open(HERE / "FREEZE.json"))
    report = []
    for key, want in freeze["sha256"].items():
        got = sha256_file(HERE / key)
        if got == want:
            report.append(f"ok        {key}")
        elif key in REDACTED and REDACTED[key] == (want, got):
            report.append(f"redacted  {key} (published redacted sha256 {got[:12]}...)")
        else:
            raise SystemExit(f"ABORT: FREEZE.json mismatch: {key} has {got}, frozen {want}")
    got = sha256_file(HERE / "frozen-bin" / "bran-v4-eval")
    if got != freeze["binary"]["sha256"] and REDACTED.get("frozen-bin/bran-v4-eval") != (freeze["binary"]["sha256"], got):
        raise SystemExit(f"ABORT: frozen-bin/bran-v4-eval has {got}, frozen {freeze['binary']['sha256']}")
    report.append("ok        frozen-bin/bran-v4-eval")
    return report


def redaction_aware(orig):
    targets = {(HERE / key).resolve(): pair for key, pair in REDACTED.items() if key != "frozen-bin/bran-v4-eval"}

    def sha256_file_v(p):
        h = orig(p)
        pair = targets.get(Path(p).resolve())
        return pair[0] if pair is not None and h == pair[1] else h
    return sha256_file_v


def load_evaluator():
    spec = importlib.util.spec_from_file_location("evaluate_v4", HERE / "evaluate_v4.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate_v4"] = mod           # the Amendment 5 script imports it by this name
    spec.loader.exec_module(mod)
    mod.sha256_file = redaction_aware(mod.sha256_file)
    return mod


def run_amendment5(out, binary):
    script = HERE / "results" / "conf" / "amendment5_h4_s9_s10.py"
    src = script.read_text()
    for old, new in (("HERE = Path(__file__).resolve().parent\n", "HERE = Path(__reanalysis_out__)\n"),
                     ("V4 = HERE.parents[1]\n", "V4 = Path(__reanalysis_v4__)\n"),
                     ('BIN = V4 / "frozen-bin" / "bran-v4-eval"\n', 'BIN = Path(__reanalysis_binary__)\n'),
                     ('assert E.sha256_file(BIN) == freeze["binary"]["sha256"]\n', 'assert E.sha256_file(BIN) == __reanalysis_binary_sha256__\n')):
        if src.count(old) != 1:
            raise SystemExit(f"ABORT: {script.name}: expected one line {old.strip()!r}")
        src = src.replace(old, new)
    g = {"__name__": "__main__", "__file__": str(script),
         "__reanalysis_out__": str(out), "__reanalysis_v4__": str(HERE),
         "__reanalysis_binary__": str(binary), "__reanalysis_binary_sha256__": sha256_file(binary)}
    exec(compile(src, str(script), "exec"), g)


JSON_OUTPUTS = ("evaluation_v4.json",)
BYTE_OUTPUTS = ("paired_decisions_v4.csv", "separation_margins_v4.csv", "policy_hashes_v4.csv",
                "items_v4_blind.csv", "parse_audit_v4.csv", "responses_v4.jsonl", "popqa_label_sheet.csv")
# Exact paths only. Missing keys still fail, including keys whose values may vary.
VARIABLE_JSON_PATHS = {
    "evaluation_v4.json/provenance/binary",
    "evaluation_v4.json/provenance/binary_sha256",
    "evaluation_v4.json/provenance/FREEZE.json_sha256",
    "evaluation_v4.json/provenance/canon/path",
    "amendment5_v4.json/S10/binary_sha256",
}
for _metric in ("M3_time_s", "all5_time_s", "M3_time_over_gen_span", "M3_time_over_gen_sum"):
    for _stat in ("median", "p95", "max"):
        VARIABLE_JSON_PATHS.add(f"amendment5_v4.json/S10/{_metric}/{_stat}")
VARIABLE_CSV_COLUMNS = {"M1_s", "M3_s", "M4_s", "M5_s", "M6_s"}


def compare(out, include_amendment=True):
    """Require every result and compare all but explicitly named runtime values."""
    committed = HERE / "results" / "conf"
    diffs = []

    def walk(a, b, p):
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b)):
                q = f"{p}/{k}"
                if k not in a or k not in b:
                    diffs.append(f"{q}: present only in {'re-run' if k in b else 'committed'}")
                elif q in VARIABLE_JSON_PATHS:
                    continue
                else:
                    walk(a[k], b[k], q)
        elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f"{p}[{i}]")
        elif a != b:
            diffs.append(f"{p}: committed {str(a)[:80]} != re-run {str(b)[:80]}")

    json_files = JSON_OUTPUTS + (("amendment5_v4.json",) if include_amendment else ())
    required = json_files + BYTE_OUTPUTS + (("s10_per_item_v4.csv",) if include_amendment else ())
    for name in required:
        if not (out / name).is_file():
            diffs.append(f"{name}: required output missing")
        elif not (committed / name).is_file():
            diffs.append(f"{name}: published reference missing")
    if diffs:
        return diffs
    for name in json_files:
        try:
            walk(json.loads((committed / name).read_text()), json.loads((out / name).read_text()), name)
        except (ValueError, OSError) as exc:
            diffs.append(f"{name}: cannot compare JSON: {exc}")
    for name in BYTE_OUTPUTS:
        if (out / name).read_bytes() != (committed / name).read_bytes():
            diffs.append(f"{name}: bytes differ")
    if include_amendment:
        name = "s10_per_item_v4.csv"
        def stable_rows(path):
            with path.open(newline="") as f:
                reader = csv.DictReader(f)
                fields = reader.fieldnames
                rows = [{k: v for k, v in row.items() if k not in VARIABLE_CSV_COLUMNS} for row in reader]
            return fields, rows
        if stable_rows(out / name) != stable_rows(committed / name):
            diffs.append(f"{name}: non-timing fields differ")
    return diffs


def prepare_output(path):
    """Allow only a fresh output directory, outside sources or under bench-output."""
    out = Path(path).resolve()
    root = ARTIFACT.resolve()
    if out == root or (root in out.parents and (root / "bench-output") not in out.parents):
        raise ValueError("output inside artifact must be beneath bench-output/")
    out.mkdir(parents=True, exist_ok=False)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="fresh output directory, outside artifact or beneath bench-output/")
    ap.add_argument("--bin", help="reducer binary for evaluate_v4.py (default: the published binary)")
    ap.add_argument("--skip-amendment5", action="store_true", help="run and compare only the main evaluator outputs")
    ap.add_argument("--compare", action="store_true", help="diff the outputs against results/conf/")
    a = ap.parse_args(argv)

    binary = Path(a.bin).resolve(strict=True) if a.bin else HERE / "frozen-bin/bran-v4-eval"
    check_redaction_table()
    print("\n".join(verify_freeze()))
    out = prepare_output(a.out)
    receipt = {
        "mode": "public-artifact reconstruction; not historical frozen-binary replay",
        "binary_sha256": sha256_file(binary),
        "historical_binary_sha256": json.loads((HERE / "FREEZE.json").read_text())["binary"]["sha256"],
        "published_binary_sha256": sha256_file(HERE / "frozen-bin/bran-v4-eval"),
        "amendment5_included": not a.skip_amendment5,
        "comparison_requested": a.compare,
        "status": "started",
    }
    receipt_path = out / "reconstruction.json"
    def save_receipt():
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    save_receipt()
    previous_cwd, previous_argv = Path.cwd(), sys.argv
    try:
        os.chdir(HERE)
        (out / "raw").symlink_to(HERE / "results/conf/raw", target_is_directory=True)
        E = load_evaluator()
        args = list(COMMITTED_ARGS)
        args[args.index("--bin") + 1] = str(binary)
        sys.argv = ["evaluate_v4.py", *args, "--out", str(out)]
        result = E.main()
        if result:
            raise RuntimeError(f"evaluator exited with status {result}")
        if not a.skip_amendment5:
            run_amendment5(out, binary)
        if a.compare:
            diffs = compare(out, include_amendment=not a.skip_amendment5)
            receipt["status"] = "failed" if diffs else "passed"
            receipt["comparison_differences"] = diffs
            save_receipt()
            print("\ncompare with results/conf/: " + (f"{len(diffs)} differences" if diffs
                  else "no differences outside explicitly allowed runtime/provenance values"))
            for d in diffs:
                print("  " + d)
            return 1 if diffs else 0
        receipt["status"] = "completed_not_compared"
        save_receipt()
        return 0
    except BaseException as exc:
        receipt.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        save_receipt()
        raise
    finally:
        os.chdir(previous_cwd)
        sys.argv = previous_argv


if __name__ == "__main__":
    sys.exit(main())
