#!/usr/bin/env python3
"""Reconstruct published decisions using a reducer rebuilt for this platform.

No frozen file is modified. All frozen hashes are checked before importing the
historical evaluator. Only its in-memory expected binary hash is substituted;
actual binary provenance remains intact. This is not a frozen-binary replay.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
import platform
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_freezes(root=ROOT):
    rows = re.findall(r"^\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*`([0-9a-f]{64})`\s*\|", (root / "FROZEN_REDACTIONS.md").read_text(), re.M)
    redactions = {p: (old, new) for p, old, new in rows}
    verified = {}
    for version in (4, 5, 6):
        folder = root / f"real-agent-eval/v{version}"
        freeze = json.loads((folder / "FREEZE.json").read_text())
        if version >= 5 and (freeze.get("status") != "FROZEN" or freeze.get("pending")):
            raise ValueError(f"v{version} is not frozen")
        base = folder if version == 4 else root
        for name, expected in freeze["sha256"].items():
            path = base / name
            relative = path.relative_to(root).as_posix()
            actual = digest(path)
            if actual != expected and redactions.get(relative) != (expected, actual):
                raise ValueError(f"frozen hash mismatch: {relative}")
        if version == 4:
            actual = digest(folder / "frozen-bin/bran-v4-eval")
            expected = freeze["binary"]["sha256"]
            if actual != expected and redactions.get("real-agent-eval/v4/frozen-bin/bran-v4-eval") != (expected, actual):
                raise ValueError("frozen hash mismatch: v4 binary")
        verified[f"v{version}"] = len(freeze["sha256"])
    return verified


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def compare_statistics(reference, actual):
    """Compare every field except explicitly enumerated runtime metadata."""
    def ignored(path):
        return (path in {"/provenance/binary", "/provenance/binary_sha256", "/provenance/canon/path", "/inputs/eval_dir", "/design_v3/H3/BE/reducer_wall_s_mean"}
                or re.fullmatch(r"/provenance/inputs/[^/]+/path", path)
                or re.fullmatch(r"/prereg/H5/replay/LOAO/BE-G/wall_s_(per_item|total)", path)
                or re.fullmatch(r"/prereg/H5/latency/(pooled|P|T)/(BE|BE-G)/(reducer_wall_s|critical_path_s)", path))
    def walk(left, right, path=""):
        if ignored(path):
            return
        if type(left) is not type(right):
            raise ValueError(f"statistics type differs: {path}")
        if isinstance(left, dict) and isinstance(right, dict):
            if left.keys() != right.keys():
                raise ValueError(f"statistics keys differ: {path}")
            for key in left:
                walk(left[key], right[key], path + "/" + key)
        elif isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            for index, (x, y) in enumerate(zip(left, right)):
                walk(x, y, path + "/" + str(index))
        elif isinstance(left, float) and isinstance(right, float) and math.isclose(left, right, rel_tol=1e-12, abs_tol=0.0):
            return
        elif left != right:
            raise ValueError(f"statistics differ: {path}")
    walk(reference, actual)


def compare_results(study, out):
    records = study / "results/conf"
    for name in ["evaluation_v5.json", "figures_v5.json"] + (["evaluation_v6_vdf.json"] if study.name == "v6" else []):
        compare_statistics(json.loads((records / "eval" / name).read_text()), json.loads((out / name).read_text()))
    if study.name == "v5":
        subprocess.run([sys.executable, str(study / "make_results.py"), "--eval", str(out / "evaluation_v5.json"),
                        "--dev", str(study / "results/dev_checker2/eval/evaluation_v5.json"), "--out", str(out / "RESULTS.md")], check=True)
        def mask(text):
            text = re.sub(r"(?m)^Binary `[0-9a-f]{16}`;", "Binary `<rebuilt>`;", text)
            text = re.sub(r"[0-9]+\.[0-9]+ (ms|s total)", r"<t> \1", text)
            return re.sub(r"critical path median [0-9.]+ s(, p95 [0-9.]+ s)?", "critical path <t>", text)
        if mask((records / "RESULTS.md").read_text()) != mask((out / "RESULTS.md").read_text()):
            raise ValueError("published RESULTS.md differs outside timing fields")


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("Python 3.12 or newer is required by the published results renderer")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", choices=("v5", "v6"), required=True)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    verified = verify_freezes()
    binary = args.bin.resolve(strict=True)
    out = args.out.resolve()
    # Outputs cannot overwrite archived evidence, source or a previous run.
    if ROOT in out.parents and (ROOT / "bench-output") not in out.parents:
        raise ValueError("output inside artifact must be beneath bench-output/")
    out.mkdir(parents=True, exist_ok=False)
    study = ROOT / "real-agent-eval" / args.study
    v5 = ROOT / "real-agent-eval/v5"
    if args.study == "v6":
        evaluator = load("evaluate_v6", study / "evaluate_v6.py")
        historical = evaluator.E
        wrapper = load("reanalyze_v6", study / "reanalyze_v6.py")
        evaluator.verify_v6_freeze = wrapper.verify_v6_freeze
    else:
        evaluator = historical = load("evaluate_v5", study / "evaluate_v5.py")
    original_load = historical.jload
    binary_sha = digest(binary)
    def reconstructed_load(path):
        value = original_load(path)
        if Path(path).resolve() == v5 / "FREEZE.json":
            value = copy.deepcopy(value)
            value["sha256"]["real-agent-eval/v5/frozen-bin/bran"] = binary_sha
        return value
    historical.jload = reconstructed_load
    receipt = {"mode": "source-rebuilt reconstruction; not frozen-binary replay", "study": args.study,
               "platform": platform.system() + " " + platform.machine(), "binary_sha256": binary_sha,
               "original_binary_sha256": original_load(v5 / "FREEZE.json")["sha256"]["real-agent-eval/v5/frozen-bin/bran"], "published_binary_sha256": digest(v5 / "frozen-bin/bran"), "verified_freeze_entries": verified,
               "status": "started"}
    receipt_path = out / "reconstruction.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    records = study / "results/conf"
    command = ["--split", "conf", "--bin", str(binary), "--items", str(v5 / "benchmark/items_confirmatory.jsonl"),
               "--raw-dir", str(records / "raw"), "--captures", str(records / "captures.jsonl"),
               "--checks", str(records / "checks.jsonl"), "--judge", str(records / "judge.jsonl"),
               "--accepted-checker", "f2a14bd8988371bd231ca6ff137be13e", "--be-g-config", "member/nei0.5/gated",
               "--be-config", "member/nei0.1", "--best-model", "mistral" if args.study == "v5" else "exaone3.5_7.8b",
               "--expect-judge-id", "CB-S=1de78d843c35f57cfa9d2ebfd708f681", "--out", str(out)]
    if args.study == "v5":
        command += ["--judge-local", str(records / "judge_local.jsonl")]
    result = evaluator.main(command)
    if result:
        return result
    files = ["paired_decisions_v5.csv", "items_v5.csv", "overturns_v5.jsonl"]
    files += (["planned_subsamples_v5.json", "witness_sample_v5.jsonl"] if args.study == "v5"
              else ["evaluation_v6_vdf_items.csv"])
    for name in files:
        if (out / name).read_bytes() != (records / "eval" / name).read_bytes():
            raise ValueError(f"published result differs: {name}")
    if args.study == "v5":
        subprocess.run([sys.executable, str(v5 / "certificates.py"), "--rust-dir", str(out / "rust"), "--check"], check=True)
    compare_results(study, out)
    receipt.update(status="passed", byte_identical_files=files, statistics_match=True, numerical_files=["evaluation_v5.json", "figures_v5.json"] + (["evaluation_v6_vdf.json"] if args.study == "v6" else []), float_relative_tolerance=1e-12, float_absolute_tolerance=0.0)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"PASS {args.study}: source-rebuilt decisions match published records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
