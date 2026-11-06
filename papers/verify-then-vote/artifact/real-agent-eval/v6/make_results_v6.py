#!/usr/bin/env python3
"""
Eval v6 RESULTS.md renderer (PREREGISTRATION.md section 10: results order F1, F2, secondary, descriptive, exploratory).

Loads the frozen v5 renderer (make_results.py) by path and patches only its BEST label string. It renders:
  1. F1 from evaluation_v6_vdf.json (H1a-VDF, then H3a-VDF only if the sequence continues; the design-set sensitivity; VDF H4);
  2. F2 and everything else through v5's own `render`, with its H1/H3 headings and row labels relabelled "-rep";
  3. the secondary block (BE-G/VDF, VV/VDF on T, H3a-pool, cross-pool table) before the Deviations section;
  4. the section 14 pre-written readings for F1 and F2.
Reads only evaluation JSON files, never raw records. Re-run after pooled_h3a_v6.py to include H3a-pool (--pooled).

Usage
  make_results_v6.py --eval O/eval/evaluation_v5.json --vdf O/eval/evaluation_v6_vdf.json [--pooled O/pooled_h3a_v6.json]
                     [--aliases-eval O/eval_aliases/evaluation_v5.json --aliases-vdf O/eval_aliases/evaluation_v6_vdf.json] --out O/RESULTS.md
  (the MiniCheck block appears when the vdf json has a local_arm; the G-AK+A block when the aliases files are given)
"""
import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"


def _load(name, path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load("make_results", V5 / "make_results.py")
num, pct, ci, pval, yn = M.num, M.pct, M.ci, M.pval, M.yn


# ── readings (prereg section 14) ────────────────────────────────

def f1_reading(vdf):
    f1, nd = vdf["F1"], vdf["F1_without_design_set"]
    out = []
    if not f1["H1a"]["reject"] or f1["H1a"]["b"] <= f1["H1a"]["c"]:
        out.append("H1a-VDF null or worse: the sequence stops. The post-hoc VDF gain does not carry to a new pool.")
    elif not f1["H3a"]["reject"]:
        out.append("H1a-VDF rejects, H3a-VDF fails: VDF's gains are confirmed; harm below 5% is not shown. Report H4 (c <= F against MAJ) "
                   "and the remaining unverified-default harms.")
    else:
        out.append("H1a-VDF and H3a-VDF both reject: verified default first beats majority and shows harm below 5% on a new, "
                   "family-disjoint pool. This is its first confirmatory test; the rule was designed post hoc on v5.")
    if f1["sequence_completed"] and not nd["sequence_completed"]:
        out.append("F1 holds on all of P but not without the 15 design-set items: reported as dependent on the items that informed the rule.")
    return out


def f2_reading(pr, pooled):
    h1a, h3a = pr["H1"]["H1a"], pr["H3"]["H3a"]
    better = h1a["reject"] and h1a["b"] > h1a["c"]
    pool_ok = bool(pooled and pooled["pooled_exact"]["reject"])
    if not h1a["reject"] or not better:
        return ["H1a-rep null or worse: the v5 gain is pool-specific. Report the cross-pool table."]
    if h3a["reject"]:
        return ["H1a-rep rejects and H3a-rep holds: v5's BE-G result replicates, now with harm below 5% shown."]
    if pooled is None:
        return ["H1a-rep rejects, H3a-rep fails: gains replicate. H3a-pool not computed yet (run pooled_h3a_v6.py and re-render)."]
    if pool_ok:
        return ["H1a-rep rejects, H3a-rep fails, H3a-pool holds: gains replicate. BE-G harm is below 5% across both pools pooled "
                "(secondary), but not shown in either pool alone."]
    return ["H1a-rep rejects, H3a-rep and H3a-pool fail: gains replicate. Harm equals checker false supports, as the bound predicts (H4)."]


# ── blocks ──────────────────────────────────────────────────────

def test_line(name, t):
    return (f"| {name} | {t['contrast']} | {t['n']} | {t['b']} | {t['c']} | {num(t['diff'])} | {ci(t['newcombe_ci95'])} | "
            f"{ci(t.get('bootstrap_ci95'))} | {pval(t['p_exact_mcnemar'])} | {yn(t['reject'])} | {t['reading']} |")


def h3a_line(name, t):
    cm = t.get("c_max_that_rejects")
    rej = "not tested" if t.get("tested") is False else yn(t["reject"])
    return (f"| {name} | {t['method']} | {t['n_R']} | {t['c']} | {num(t['q_r'])} | {num(t['cp_upper_97_5'], 4)} | < {t['bound']} | "
            f"{cm if cm is not None else 'none'} | {rej} |")


def seq_table(w, f1, label):
    w("| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    w(test_line(f"H1a-VDF{label}", f1["H1a"]))
    w("")
    w("| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |")
    w("|---|---|---|---|---|---|---|---|---|")
    w(h3a_line(f"H3a-VDF{label}", f1["H3a"]))
    w(f"\nH3a-VDF reading: {f1['H3a']['reading']}.\n")


def render_f1(vdf):
    L = []
    w = L.append
    f1 = vdf["F1"]
    w("### F1 (primary): VV/VDF, fixed sequence (H1a-VDF at α = 0.05, then H3a-VDF at one-sided 0.025 only if step 1 rejects with b > c)\n")
    w("> VDF was designed post hoc on v5 confirmatory data. This is its first confirmatory test, on a new pool (PREREGISTRATION.md §13).\n")
    seq_table(w, f1, "")
    h = f1["H1a"]
    w("| | MAJ wrong | p̂_w = b / #wrong (Wilson 95%) | MAJ right | q̂_r = c / #right (Wilson 95%) |")
    w("|---|---|---|---|---|")
    w(f"| VV/VDF | {h['base_wrong']} | {num(h['p_w'])} {ci(h['p_w_wilson95'])} | {h['base_right']} | {num(h['q_r'])} {ci(h['q_r_wilson95'])} |\n")
    w(f"Sequence completed: **{yn(f1['sequence_completed'])}**.\n")
    nd = vdf["F1_without_design_set"]
    w(f"**Pre-declared sensitivity: P without the 15 v5 design-set items** (sorted id list sha256 `{nd['design_set_sha256']}`; "
      f"{nd['n_in_P_decisive']} of them are decisive P conflicts in this run; N = {nd['n']}).\n")
    seq_table(w, nd, " (no design set)")
    w(f"Sequence completed without the design set: **{yn(nd['sequence_completed'])}**.\n")
    h4 = vdf["H4"]
    w("**H4 analogue for VDF** (c ≤ F; VV/VDF against MAJ, BE-G/VDF against D; a violation is an implementation defect)\n")
    w("| set | method | N | c_D | b_D | F | c_D items ⊆ F items | c vs MAJ | c vs MAJ not in F (tied) |")
    w("|---|---|---|---|---|---|---|---|---|")
    for s in ("P", "T"):
        for m, v in h4[s].items():
            w(f"| {s} | {m} | {v['n']} | {v['c_D']} | {v['b_D']} | {v['F']} | {yn(v['harm_bound_holds'])} | {v['c_vs_MAJ']} | "
              f"{len(v['c_vs_MAJ_not_in_F'])} ({v['c_vs_MAJ_not_in_F_tied']}) |")
    w(f"\nharm_bound_holds on P and T: **{h4['harm_bound_holds']}**"
      f"{' — IMPLEMENTATION DEFECT (reported, not re-analysed)' if h4['implementation_defect'] else ''}.\n")
    return L


def render_secondary(vdf, pooled):
    L = []
    w = L.append
    sec = vdf["secondary"]
    w("## 1b. Secondary analyses (pre-declared, unadjusted, no confirmatory claim)\n")
    b = sec["BE-G/VDF"]
    w("### BE-G/VDF against MAJ on P (H1a form and H3a form), next to BE-G\n")
    w("| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    w(test_line("H1a-form", b["H1a_form"]))
    w("")
    w("| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |")
    w("|---|---|---|---|---|---|---|---|---|")
    w(h3a_line("H3a-form", b["H3a_form"]))
    w("")
    t = sec["VV/VDF_on_T"]
    w("### VV/VDF on T (H3b form: Newcombe lower bound > −0.03)\n")
    w("| method | N | b | c | difference | Newcombe 95% CI | lower bound > −0.03 | reading |")
    w("|---|---|---|---|---|---|---|---|")
    w(f"| VV/VDF | {t['n']} | {t['b']} | {t['c']} | {num(t['diff'])} | {ci(t['newcombe_ci95'])} | {yn(t['reject'])} | {t['reading']} |")
    t = b["H3b_form_T"]
    w(f"| BE-G/VDF | {t['n']} | {t['b']} | {t['c']} | {num(t['diff'])} | {ci(t['newcombe_ci95'])} | {yn(t['reject'])} | {t['reading']} |\n")
    w("### H3a-pool (BE-G only; declared after v5's H3a miss; the v5 half is fixed at c = 12, n_R = 376)\n")
    if pooled is None:
        w("Not computed yet: run `pooled_h3a_v6.py` and re-render with `--pooled`.\n")
    else:
        pe, pr, bo = pooled["pooled_exact"], pooled["pooled_robust"], pooled["c_events_in_both_pools"]
        w("pooled across two pools (secondary; declared after v5's H3a miss)\n")
        w("| test | c | n | q̂_pool | one-sided 97.5% CP upper bound | < 0.05 | c₆ allowed |")
        w("|---|---|---|---|---|---|---|")
        w(f"| exact pooled (decides H3a-pool) | {pe['c']} | {pe['n']} | {num(pe['q_pool'], 4)} | {num(pe['cp_upper_97_5'], 4)} | "
          f"{yn(pe['reject'])} | {pe['c6_allowed']} |")
        w(f"\nDependence-robust sensitivity: U₅ = {num(pr['U5'], 4)}, U₆ = {num(pr['U6'], 4)}, U = {num(pr['U'], 4)}; holds robustly "
          f"(U < 0.05): **{yn(pr['holds_robustly'])}** (c₆ allowed {pr['c6_allowed']}). It does not decide H3a-pool.")
        w(f"\nItems that are c-events in both pools: {bo['count']} (v5 only {bo['v5_only']}, v6 only {bo['v6_only']}). "
          f"Item-cluster bootstrap 95% interval of q_pool: {ci(pooled['bootstrap']['ci95'], 4)} "
          f"({pooled['bootstrap']['resamples']} resamples, seed {pooled['bootstrap']['seed']}).\n")
        w("### Cross-pool consistency (descriptive; v6 − v5 with Newcombe hybrid 95% intervals; no test of 'same effect in both pools')\n")
        w("| set | method | (b − c)/N v5 → v6 | difference | q̂_r v5 → v6 | difference | p̂_w v5 → v6 | difference |")
        w("|---|---|---|---|---|---|---|---|")
        for s in ("P", "T"):
            for m, c in pooled["cross_pool_table"]["table"][s].items():
                d = lambda k: f"{num(c[k]['diff'], 3)} {ci(c[k]['newcombe_ci95'])}" if c.get(k) else "n/a"
                tag = " (v5 side post hoc)" if c.get("v5_side") else ""
                w(f"| {s} | {m}{tag} | {num(c['v5']['net'])} → {num(c['v6']['net'])} | {d('net_v6_minus_v5')} | "
                  f"{num(c['v5']['q_r'])} → {num(c['v6']['q_r'])} | {d('q_r_v6_minus_v5')} | "
                  f"{num(c['v5']['p_w'])} → {num(c['v6']['p_w'])} | {d('p_w_v6_minus_v5')} |")
        w("")
    w("Cost with caching (prereg §7: marginal and full-label $ per decision, cache share) is not computed here; it needs the v5 and v6 "
      "`check_calls.jsonl` logs.\n")
    return L


def render_local(vdf):
    L = []
    w = L.append
    la = vdf["local_arm"]
    w("## 1c. Local-checker arm: MiniCheck (secondary, unadjusted; PREREGISTRATION.md §2.5)\n")
    w(f"Checker `{la['checker_id']}` (bespoke-minicheck:7b; Yes → supports, No → not_enough_info; never refutes). "
      "Validation criterion for a binary checker: supports precision ≥ 0.85 on both slices, stability ≥ 0.95, binary macro-F1 ≥ 0.80 (set after MiniCheck's results were known).\n")
    w("| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    w(test_line("H1a-L", la["H1a_L"]))
    w(test_line("BE-G-L (H1a form)", la["BE-G-L"]["H1a_form"]))
    w("")
    w("| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |")
    w("|---|---|---|---|---|---|---|---|---|")
    w(h3a_line("H3a-L (reported whether or not H1a-L rejects)", la["H3a_L"]))
    w(h3a_line("BE-G-L (H3a form)", la["BE-G-L"]["H3a_form"]))
    t = la["VV/VDF-L_on_T"]
    w(f"\nVV/VDF-L on T: b {t['b']}, c {t['c']}, difference {num(t['diff'])} {ci(t['newcombe_ci95'])}, non-inferior (> −0.03): {yn(t['reject'])}.\n")
    w("**Decision agreement, VV/VDF-L vs hosted VV/VDF** (same selected value; Wilson 95%)\n")
    w("| set | items | agree | disagreement items | agree | McNemar b / c on decisive (p) |")
    w("|---|---|---|---|---|---|")
    for s_, a in la["agreement_with_hosted_VV/VDF"].items():
        x, y, z = a["all_eligible"], a["disagreement_items"], a["decisive_paired"]
        w(f"| {s_} | {x['n']} | {x['agree']} ({num(x['rate'])} {ci(x['wilson95'])}) | {y['n']} | {y['agree']} ({num(y['rate'])} {ci(y['wilson95'])}) | "
          f"{z['b']} / {z['c']} ({pval(z['p_exact_mcnemar'])}) |")
    w("")
    w("| set | method | N | c_D | F_L | c_D items ⊆ F_L items | F̂ |")
    w("|---|---|---|---|---|---|---|")
    for s_ in ("P", "T"):
        for m, v in la["H4"][s_].items():
            w(f"| {s_} | {m} | {v['n']} | {v['c_D']} | {v['F']} | {yn(v['harm_bound_holds'])} | {num(v['F_hat'], 2)} |")
    w("")
    return L


GRADER_ROWS = (("F1 H1a-VDF", lambda ev, v: v["F1"]["H1a"]["reject"]), ("F1 H3a-VDF", lambda ev, v: v["F1"]["H3a"]["reject"]),
               ("F2 H1a-rep", lambda ev, v: ev["prereg"]["H1"]["H1a"]["reject"]), ("F2 H1b-rep", lambda ev, v: ev["prereg"]["H1"]["H1b"]["reject"]),
               ("F2 H3a-rep", lambda ev, v: ev["prereg"]["H3"]["H3a"]["reject"]), ("F2 H3b-rep", lambda ev, v: ev["prereg"]["H3"]["H3b"]["reject"]))


def render_grader(ev, vdf, ev_a, vdf_a):
    L = []
    w = L.append
    w("## 1d. Secondary grader G-AK+A (frozen Wikidata aliases on PopQA gold; PREREGISTRATION.md §3.1)\n")
    w("Rejections are decided under G-AK only. G-AK+A re-derives the decisive set; a verdict that differs between the graders is flagged.\n")
    w("| test | G-AK | G-AK+A | |")
    w("|---|---|---|---|")
    for name, fn in GRADER_ROWS:
        a, b = fn(ev, vdf), fn(ev_a, vdf_a)
        w(f"| {name} | {yn(a)} | {yn(b)} | {'**DIFFERS**' if a != b else ''} |")
    pa, pb = ev["prereg"], ev_a["prereg"]
    w(f"\nDecisive conflicts: {ev['decisive']} → {ev_a['decisive']}; P {pa['analysis_sets']['P']['decisive']} → {pb['analysis_sets']['P']['decisive']}. "
      f"H1a-VDF b/c {vdf['F1']['H1a']['b']}/{vdf['F1']['H1a']['c']} → {vdf_a['F1']['H1a']['b']}/{vdf_a['F1']['H1a']['c']}; "
      f"H1a-rep b/c {pa['H1']['H1a']['b']}/{pa['H1']['H1a']['c']} → {pb['H1']['H1a']['b']}/{pb['H1']['H1a']['c']}.\n")
    return L


REL = re.compile(r"^\| (H1a|H1b|H3a|H3b)( \(BE, descriptive\))? \|", re.M)


def relabel_f2(text):
    text = text.replace("### H1: primary family on P", "### F2 · H1-rep: BE-G and BE vs MAJ on P")
    text = text.replace("### H3: no harm (own α each, outside the H1 family)", "### F2 · H3-rep: no harm (own α each, outside the H1 family)")
    text = REL.sub(lambda m: f"| {m.group(1)}-rep{m.group(2) or ''} |", text)
    text = re.sub(r"^Holm order: H1a, H1b\.", "Holm order: H1a-rep, H1b-rep.", text, flags=re.M)
    text = re.sub(r"^Holm order: H1b, H1a\.", "Holm order: H1b-rep, H1a-rep.", text, flags=re.M)
    return text


def render(ev, vdf, pooled=None, aliases=None):
    best = ev["BEST_agent"]
    M.METHOD_NAMES["BEST"] = f"best single model ({best}, fixed on dev)"       # v5's label hardcodes mistral
    M.METHOD_NAMES["VV/VDF"] = "verified default first over MAJ and VV (F1)"
    M.METHOD_NAMES["BE-G/VDF"] = "verified default first over D and BE-G (secondary)"
    text = M.render(ev, None)
    text = text.replace("# Eval v5 results (confirmatory)", "# Eval v6 results (confirmatory)", 1)
    text = text.replace("Items:", "Pool: falcon3:3b, olmo2:7b, exaone3.5:7.8b, nemotron-mini:4b, granite3.3:2b (family-disjoint from v5). Items:", 1)
    text = relabel_f2(text)
    head = "## 1. Preregistered analyses\n\n"
    i = text.index(head) + len(head)
    f1 = "\n".join(render_f1(vdf)) + "\n"
    text = text[:i] + f1 + text[i:]
    # the v5 reading block (its H1a/H3a rows) is replaced by the v6 section 14 readings
    j = text.index("### Reading (PREREGISTRATION.md §14)")
    k = text.index("## 2. Deviations")
    reading = ["### Reading (v6 PREREGISTRATION.md §14)\n", "**F1 (VV/VDF).**\n"] + [f"- {x}" for x in f1_reading(vdf)] + \
              ["", "**F2 (replication of v5).**\n"] + [f"- {x}" for x in f2_reading(ev["prereg"], pooled)] + [""]
    sec = render_secondary(vdf, pooled)
    if "local_arm" in vdf:
        sec += render_local(vdf)
    if aliases:
        sec += render_grader(ev, vdf, *aliases)
    text = text[:j] + "\n".join(sec) + "\n" + "\n".join(reading) + "\n" + text[k:]
    return text


def main(argv=None):
    ap = argparse.ArgumentParser(description="eval v6 RESULTS.md")
    ap.add_argument("--eval", required=True, help="evaluation_v5.json from evaluate_v6.py (the frozen evaluator's output)")
    ap.add_argument("--vdf", required=True, help="evaluation_v6_vdf.json")
    ap.add_argument("--pooled", help="pooled_h3a_v6.json (optional; re-render after pooled_h3a_v6.py)")
    ap.add_argument("--aliases-eval", help="eval_aliases/evaluation_v5.json (the G-AK+A run)")
    ap.add_argument("--aliases-vdf", help="eval_aliases/evaluation_v6_vdf.json")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ev, vdf = M.jload(a.eval), M.jload(a.vdf)
    if ev.get("split") != "conf" or "prereg" not in ev:
        raise SystemExit("refused: --eval must be a confirmatory evaluation_v5.json with a `prereg` block")
    if vdf.get("rule") != "vdf-1":
        raise SystemExit("refused: --vdf is not an evaluation_v6_vdf.json (rule vdf-1)")
    pooled = M.jload(a.pooled) if a.pooled else None
    if bool(a.aliases_eval) != bool(a.aliases_vdf):
        raise SystemExit("refused: --aliases-eval and --aliases-vdf go together")
    aliases = (M.jload(a.aliases_eval), M.jload(a.aliases_vdf)) if a.aliases_eval else None
    Path(a.out).write_text(render(ev, vdf, pooled, aliases))
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
