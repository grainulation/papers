#!/usr/bin/env python3
"""
Eval v6 analysis wrapper (PREREGISTRATION.md section 11).

Loads the frozen v5 evaluator by path and runs it unchanged. That gives F2 (H1a-rep, H1b-rep, H3a-rep,
H3b-rep), H4 and H5 exactly as v5 computed them. Then it runs `vdf_v6.run` on the same inputs, which writes
`evaluation_v6_vdf.json` (F1, the BE-G/VDF secondary, the VDF H4 rows and the design-set sensitivity).

Only one constant is overridden: `evaluate_v5.PREREG_BEST` (the conf guard compares --best-model with it)
is set to the BEST agent recorded in v6/FREEZE.json -> identities.BEST_agent. Everything else is v5's.
v5's own guard still requires evaluate_v5.py and the binary to match v5/FREEZE.json.

Conf mode (`--split conf`, no --synthetic-test) needs v6/FREEZE.json: status FROZEN, `pending` empty,
every listed hash matching. Nothing here calls a model; the frozen Rust binary is the only subprocess.

Usage (plan section 8; extra flags are passed through to evaluate_v5.main)
  evaluate_v6.py --split conf --bin v5/frozen-bin/bran --items .. --raw-dir .. --captures .. --checks ..
      --judge .. --accepted-checker f2a1.. --be-g-config .. --be-config .. --best-model <BEST> --out DIR
  evaluate_v6.py --reproduce-v5 [--out DIR] [--report FILE]
      dry mode: re-runs the frozen evaluator on v5's own confirmatory data and diffs its F2 outputs against
      v5/results/conf/eval/evaluation_v5.json and paired_decisions_v5.csv. No v6 freeze needed.
  evaluate_v6.py --selftest | --synthetic-test ...    (passed through)
"""
import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
ROOT = V6.parents[1]


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


VDF = _load("vdf_v6", V6 / "vdf_v6.py")          # also loads evaluate_v5 by path
E = VDF.E

# the arguments of the published v5 confirmatory run (inputs.* in v5 evaluation_v5.json, RUN_NOTES, prereg section 8)
V5_CONF = V5 / "results" / "conf"
V5_ARGS = ["--split", "conf", "--bin", str(V5 / "frozen-bin" / "bran"), "--items", str(V5 / "benchmark/items_confirmatory.jsonl"),
           "--raw-dir", str(V5_CONF / "raw"), "--captures", str(V5_CONF / "captures.jsonl"),
           "--checks", str(V5_CONF / "checks.jsonl"), "--judge", str(V5_CONF / "judge.jsonl"),
           "--judge-local", str(V5_CONF / "judge_local.jsonl"), "--local-judge-agent", "mistral",
           "--accepted-checker", E.PREREG_CHECKER, "--be-g-config", E.PREREG_CONFIGS["BE-G"],
           "--be-config", E.PREREG_CONFIGS["BE"], "--best-model", "mistral", "--strict",
           "--expect-judge-id", "CB-S=1de78d843c35f57cfa9d2ebfd708f681"]


MINICHECK_ID = VDF.MINICHECK_ID


def be_g_l_template():
    """policy_template_sha256 of BE-G-L (member/nei0.5/gated with accepted = [MiniCheck]); derivable offline."""
    return E.template_sha("BE", E.PREREG_CONFIGS["BE-G"], [MINICHECK_ID])


def verify_v6_freeze(need_frozen=True):
    """Check v6/FREEZE.json (format bran-v6-freeze/1): FROZEN, nothing pending, every hash matches. Returns the dict."""
    fz = V6 / "FREEZE.json"
    if not fz.exists():
        raise SystemExit("ABORT: real-agent-eval/v6/FREEZE.json does not exist (prereg section 15: not frozen yet)")
    d = json.loads(fz.read_text())
    if need_frozen:
        if d.get("status") != "FROZEN":
            raise SystemExit(f"ABORT: v6/FREEZE.json status is {d.get('status')!r}, not FROZEN")
        if d.get("pending"):
            raise SystemExit(f"ABORT: v6/FREEZE.json still lists pending items: {d['pending']}")
    bad = {p: h for p, h in d.get("sha256", {}).items()
           if not (ROOT / p).exists() or hashlib.sha256((ROOT / p).read_bytes()).hexdigest() != h}
    if bad:
        raise SystemExit(f"ABORT: v6/FREEZE.json hash mismatch: {sorted(bad)}")
    return d


# ── diff helpers for the --reproduce-v5 gate ────────────────────

TIMING = re.compile(r"(wall|latency|critical_path|elapsed|_ms$|median|p95|^mean$|^max$|^total$)")
F2_KEYS = ("H1", "H3", "H4", "references", "accuracy", "overturn_vs_MAJ", "overturn_vs_D", "methods",
           "policy_template_sha256", "template_check", "analysis_sets", "available", "methods_reported")


def deep_diff(a, b, path=""):
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if k not in a or k not in b:
                out.append((f"{path}/{k}", "missing in one side"))
            else:
                out += deep_diff(a[k], b[k], f"{path}/{k}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((path, f"length {len(a)} vs {len(b)}"))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                out += deep_diff(x, y, f"{path}[{i}]")
    elif a != b:
        out.append((path, f"{str(a)[:60]} vs {str(b)[:60]}"))
    return out


def reproduce_v5(out_dir, report_path):
    """Dry mode: the frozen evaluator on v5's own data, diffed against the published v5 outputs."""
    out_dir = Path(out_dir).resolve()
    if V5 in out_dir.parents or out_dir == V5:
        raise SystemExit("ABORT: --out must not be under real-agent-eval/v5 (hash-frozen)")
    if E.PREREG_BEST != "mistral":
        raise SystemExit("ABORT: dry reproduction must run with v5's BEST (mistral)")
    fz = E.jload(V5 / "FREEZE.json")["sha256"]
    for rel_p in ("real-agent-eval/v5/evaluate_v5.py", "real-agent-eval/v5/frozen-bin/bran"):
        if fz.get(rel_p) != E.sha256_file(ROOT / rel_p):
            raise SystemExit(f"ABORT: {rel_p} differs from v5/FREEZE.json")
    rc = E.main(V5_ARGS + ["--out", str(out_dir)])
    if rc:
        return rc
    new, old = E.jload(out_dir / "evaluation_v5.json"), E.jload(V5_CONF / "eval" / "evaluation_v5.json")
    res = {"mode": "dry reproduction of the frozen evaluator on v5 confirmatory data", "out_dir": str(out_dir),
           "evaluate_v5_sha256": E.sha256_file(E.__file__), "binary_sha256": E.sha256_file(V5 / "frozen-bin" / "bran")}
    # F2 outputs: no tolerance at all
    f2 = []
    for k in F2_KEYS:
        f2 += deep_diff(new["prereg"].get(k), old["prereg"].get(k), f"prereg/{k}")
    f2 += deep_diff({k: new[k] for k in ("n_items", "eligible", "decisive", "yield", "BEST_agent", "BE_config", "BE_G_config",
                                          "accuracy_decisive", "accuracy_eligible", "overturn_vs_MAJ", "by_source", "per_agent",
                                          "mirror_check", "fallbacks")},
                    {k: old[k] for k in ("n_items", "eligible", "decisive", "yield", "BEST_agent", "BE_config", "BE_G_config",
                                          "accuracy_decisive", "accuracy_eligible", "overturn_vs_MAJ", "by_source", "per_agent",
                                          "mirror_check", "fallbacks")}, "top")
    res["F2_diff_paths"] = [p for p, _ in f2]
    res["F2_identical"] = not f2
    # everything else in evaluation_v5.json: report, and mark the diffs that are timing or input paths
    rest = [(p, d) for p, d in deep_diff(new, old) if not any(p.startswith(f"/prereg/{k}") for k in F2_KEYS)]
    other = [(p, d) for p, d in rest if not p.startswith("/prereg/figures")]
    res["other_diff_count"] = len(other)
    res["other_diffs_not_timing_or_paths"] = [p for p, _ in other if not TIMING.search(p.split("/")[-1]) and
                                              "/provenance/" not in p and "wall" not in p and "latency" not in p
                                              and "/loao" not in p and "/H5/cost" not in p][:40]
    res["other_diff_sample"] = [f"{p}: {d}" for p, d in other[:12]]
    # the per-item decision table, byte for byte
    csv_new = (out_dir / "paired_decisions_v5.csv").read_bytes()
    csv_old = (V5_CONF / "eval" / "paired_decisions_v5.csv").read_bytes()
    res["paired_decisions_csv_identical"] = csv_new == csv_old
    res["paired_decisions_csv_sha256"] = {"new": hashlib.sha256(csv_new).hexdigest(), "published": hashlib.sha256(csv_old).hexdigest()}
    for name in ("items_v5.csv", "overturns_v5.jsonl", "loao_v5.jsonl"):
        a, b = out_dir / name, V5_CONF / "eval" / name
        res[f"{name}_identical"] = a.read_bytes() == b.read_bytes()
    # F1 chained on the fresh evaluator output, as in conf mode
    vres, _ = VDF.run(V5 / "benchmark/items_confirmatory.jsonl", V5_CONF / "raw", V5_CONF / "captures.jsonl",
                      V5_CONF / "checks.jsonl", out_dir, out_dir / "evaluation_v6_vdf.json")
    res["vdf_on_v5_data_descriptive_only"] = {
        "VV/VDF P": {k: vres["F1"]["H1a"][k] for k in ("b", "c", "p_exact_mcnemar")},
        "H3a_VDF": {k: vres["F1"]["H3a"][k] for k in ("n_R", "c", "cp_upper_97_5")}}
    res["pass"] = bool(res["F2_identical"] and res["paired_decisions_csv_identical"])
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: res[k] for k in ("F2_identical", "paired_decisions_csv_identical", "other_diff_count",
                                          "other_diffs_not_timing_or_paths", "pass")}, indent=1))
    return 0 if res["pass"] else 1


# ── main ────────────────────────────────────────────────────────

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--reproduce-v5", action="store_true")
    ap.add_argument("--report", default=str(V6 / "results" / "evaluate_reproduction_v5.json"))
    ap.add_argument("-h", "--help", action="store_true")
    own, rest = ap.parse_known_args(argv)
    if own.help:
        print(__doc__)
        return 0
    if own.reproduce_v5:
        po = argparse.ArgumentParser(add_help=False)
        po.add_argument("--out")
        o, _ = po.parse_known_args(rest)
        if not o.out:
            raise SystemExit("ABORT: --reproduce-v5 needs --out DIR (outside v5/; it holds the evaluator's rust/ replay files)")
        return reproduce_v5(o.out, own.report)
    if "--selftest" in rest:
        return E.main(rest)
    p = argparse.ArgumentParser(add_help=False)
    for k in ("--split", "--bin", "--items", "--raw-dir", "--captures", "--checks", "--out", "--best-model", "--be-g-config"):
        p.add_argument(k)
    p.add_argument("--accepted-checker", action="append")
    p.add_argument("--local-checks")
    p.add_argument("--local-accepted-checker")
    p.add_argument("--local-arm")
    p.add_argument("--expect-template", action="append", default=[])
    p.add_argument("--strict", action="store_true")
    p.add_argument("--bootstrap", type=int, default=10000)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--synthetic-test", action="store_true")
    a, _ = p.parse_known_args(rest)
    conf = a.split == "conf" and not a.synthetic_test
    if a.out and (V5 in Path(a.out).resolve().parents):
        raise SystemExit("ABORT: --out must not be under real-agent-eval/v5")
    if conf:
        fz = verify_v6_freeze(need_frozen=True)
        best = (fz.get("identities") or {}).get("BEST_agent")
        if not best:
            raise SystemExit("ABORT: v6/FREEZE.json identities.BEST_agent is missing")
        if a.best_model != best:
            raise SystemExit(f"ABORT: --best-model {a.best_model!r} is not the frozen BEST {best!r}")
        E.PREREG_BEST = best            # the one constant of the frozen evaluator that v6 overrides
        if a.local_checks or a.local_accepted_checker or a.local_arm:   # prereg 2.5: the MiniCheck arm was removed before the freeze
            raise SystemExit("ABORT: the MiniCheck local arm is not part of the frozen v6 analysis (prereg 2.5)")
    rc = E.main(rest)
    if rc or not (a.split and a.out):
        return rc
    out_dir = Path(a.out).resolve()
    if a.split != "conf":
        print("note: VDF (F1) is computed only for conf runs (and synthetic conf); skipped on dev", file=sys.stderr)
        return rc
    if a.be_g_config:
        VDF.CFG = a.be_g_config
    res, _ = VDF.run(a.items, a.raw_dir, a.captures, a.checks, out_dir, out_dir / "evaluation_v6_vdf.json",
                     a.bootstrap, a.seed, strict=not a.synthetic_test,
                     accepted=sorted(set(a.accepted_checker)) if a.synthetic_test and a.accepted_checker else None,
                     ctx_strict=a.strict, local_checks=a.local_checks, local_accepted=a.local_accepted_checker)
    f1 = res["F1"]
    print(json.dumps({"F1": {"H1a_VDF": {k: f1["H1a"][k] for k in ("n", "b", "c", "p_exact_mcnemar", "reject", "reading")},
                             "H3a_VDF": {k: f1["H3a"][k] for k in ("n_R", "c", "cp_upper_97_5", "tested", "reject")}}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
