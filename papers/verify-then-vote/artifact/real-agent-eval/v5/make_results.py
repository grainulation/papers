#!/usr/bin/env python3
"""Render eval v5 RESULTS.md from evaluate_v5.py output, in the order PREREGISTRATION.md §8 item 7
fixes: preregistered analyses (§2: H1 Holm family, H3 no-harm, H2 local arm, H4 gate soundness,
§2.4 references, the §14 reading), then deviations, then descriptive / exploratory analyses (H5,
sensitivity), then (dev only) the dev gate and the selections.

Reads only `evaluation_v5.json` files (never raw records), so the numbers in RESULTS.md are
exactly the evaluator's.

Usage
  python3 make_results.py --eval results/conf/evaluation_v5.json \
      [--dev results/dev_checker2/eval/evaluation_v5.json] --out RESULTS.md
"""
import argparse
import json
import sys

METHOD_NAMES = {
    "MAJ": "canonical majority (baseline)", "BE-G": "gated reducer member/nei0.5/gated (H1a)",
    "BE": "ungated reducer member/nei0.1 (H1b)", "BE-G-L": "BE-G with the local checker (H2)",
    "B0": "order-free reducer, no evidence policy", "EO": "evidence-only weights at BE's mode / NEI",
    "VV": "verified vote", "VV-L": "verified vote, local labels", "D": "reducer plurality default (H4)",
    "D-L": "plurality default, local arm", "CV": "cite vote (unverified)", "CONF": "confidence-weighted vote",
    "BEST": "best single model (mistral, fixed on dev)", "J": "Sonnet judge (upper reference)",
    "RS": "Sonnet reader (upper reference)", "CB-S": "closed-book Sonnet (memorisation reference)",
    "J_local": "local judge (H2b)", "ORC": "oracle (any agent right)",
}
SETS = ("P", "T", "pooled")
SET_NAMES = {"P": "P (SciFact, PopQA, FEVER)", "T": "T (TruthfulQA stratum)", "pooled": "pooled (descriptive only)"}


def jload(p):
    with open(p) as f:
        return json.load(f)


def pct(x, d=1):
    return "n/a" if x is None else f"{100 * x:.{d}f}%"


def num(x, d=3):
    return "n/a" if x is None else f"{x:.{d}f}"


def ci(c, d=3):
    return "n/a" if not c else f"[{c[0]:.{d}f}, {c[1]:.{d}f}]"


def pval(p):
    return "n/a" if p is None else (f"{p:.2e}" if p < 1e-3 else f"{p:.4f}")


def yn(b):
    return "yes" if b else "no"


def reading(pr):
    """The PREREGISTRATION.md §14 rows that apply (several can)."""
    h1a, h3a, h2 = pr["H1"]["H1a"], pr["H3"]["H3a"], pr["H2"]
    out = []
    h1_better = h1a["reject"] and h1a["b"] > h1a["c"]
    h2_conf = h2.get("confirmatory")
    if h1_better and h3a["reject"] and h2_conf:
        if h2["H2b_NI"].get("reject"):
            out.append("Local verify-then-vote matches or beats a same-size judge, with no harm and full replay.")
        else:
            out.append(f"Verification needs a strong labeler. With a hosted checker, gated arbitration overturns "
                       f"{h1a['b']} wrong majorities with no harm and full replay. Small holistic judges beat small "
                       f"verifiers by {num(-(h2['H2b_NI'].get('diff') or 0))}.")
    if not h2_conf:
        out.append("H2 \"not run as confirmatory; checker unvalidated\". Headline H1a + H3 with the hosted checker. Cost "
                   "is framed as \"per-label, reusable, auditable\", never \"cheaper than J\".")
    if h1_better and not h3a["reject"]:
        out.append("\"Harm equals checker false supports, as the bound predicts.\" H4 (c_D <= F, F against F-hat) leads.")
    if not h1a["reject"]:
        out.append("H1a null: report H1b and VV as they fall, through the evidence-availability split.")
    elif not h1_better:
        out.append("H1a rejected in the wrong direction (c > b): BE-G is worse than majority vote on P.")
    ref = pr["references"]["P"]["vs_MAJ"]
    acc = pr["accuracy"]["P"]["decisive"]
    if "CB-S" in ref and "J" in ref and acc.get("CB-S") is not None and acc.get("J") is not None:
        if abs(acc["CB-S"] - acc["J"]) <= 0.03:
            out.append("CB-S ≈ J (|accuracy difference| <= 0.03 on P): J and RS measure knowledge of public "
                       "benchmarks. The regime of interest is a fleet whose decider must not be the frontier model.")
    return out


def test_row(name, t, extra=""):
    return (f"| {name} | {t['contrast']} | {t['n']} | {t['b']} | {t['c']} | {num(t['diff'])} | {ci(t['newcombe_ci95'])} | "
            f"{ci(t.get('bootstrap_ci95'))} | {pval(t['p_exact_mcnemar'])}{extra} |")


def render(ev, dev=None):
    L = []
    w = L.append
    split = ev["split"]
    pr = ev["prereg"]
    if ev.get("synthetic"):
        w("> **SYNTHETIC.** These numbers come from generated test records (`tests/synth_v5.py`), not from "
          "model runs. They test the code path and say nothing about Bran.\n")
    if split == "dev":
        w("> **DEV.** The preregistered analyses below are computed on the dev split, on which BE and BE-G were "
          "selected. They are dev-informed and provide no evidence (PREREGISTRATION.md §13).\n")
    w(f"# Eval v5 results ({'confirmatory' if split == 'conf' else 'dev'})\n")
    p = ev["provenance"]
    w(f"Items: {ev['n_items']}. Eligible: {ev['eligible']}. Decisive conflicts: **{ev['decisive']}** "
      f"(yield {num(ev['yield'])}). BE-G: `{pr['methods']['BE-G']}`. BE: `{pr['methods']['BE']}`. "
      f"BE-G-L: `{pr['methods']['BE-G-L'] or 'not run'}`. BEST agent: `{ev['BEST_agent']}`.\n")
    w(f"Binary `{p['binary_sha256'][:16]}`; evaluator `{p['evaluate_v5_py_sha256'][:16]}`; propositions "
      f"`{p['propositions']['renderer_version']}`; accepted checkers "
      f"{', '.join('`%s`' % c for c in p['accepted_checkers']) or 'none'}"
      f"{'; local ' + ', '.join('`%s`' % c for c in p['local_accepted_checkers']) if p.get('local_accepted_checkers') else ''}.\n")
    tc = pr["template_check"]
    w("| method | policy_template_sha256 |")
    w("|---|---|")
    for k, v in pr["policy_template_sha256"].items():
        w(f"| {k} | `{v}` |")
    w(f"\nTemplate check against the prereg: {'checked' if tc['against_prereg'] else 'not applicable (accepted checker is not the prereg checker)'}; "
      f"mismatches: {len(tc['mismatches'])}.\n")
    s = pr["analysis_sets"]
    w("| analysis set | items | eligible | decisive | disagreement | yield | decisive by source |")
    w("|---|---|---|---|---|---|---|")
    for k in SETS:
        v = s[k]
        w(f"| {SET_NAMES[k]} | {v['items']} | {v['eligible']} | {v['decisive']} | {v['disagreement']} | {num(v['yield'])} | "
          f"{', '.join(f'{a} {b}' for a, b in sorted(v['by_source'].items()))} |")
    w(f"\nSet rule: {s['rule']}. P and T are never pooled for a test.\n")

    w("## 1. Preregistered analyses\n")
    h1 = pr["H1"]
    w("### H1: primary family on P (exact two-sided McNemar, Holm, family-wise α = 0.05)\n")
    w("| | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | Holm threshold | Holm-adjusted p | reject | reading |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for k in ("H1a", "H1b"):
        t = h1[k]
        w(test_row(k, t, f" | {num(t['holm']['threshold'], 3)} | {pval(t['holm']['p_holm'])} | {yn(t['reject'])} | {t['reading']}"))
    w("")
    w("| | MAJ wrong | p̂_w = b / #wrong (Wilson 95%) | MAJ right | q̂_r = c / #right (Wilson 95%) |")
    w("|---|---|---|---|---|")
    for k in ("H1a", "H1b"):
        t = h1[k]
        w(f"| {k} | {t['base_wrong']} | {num(t['p_w'])} {ci(t['p_w_wilson95'])} | {t['base_right']} | "
          f"{num(t['q_r'])} {ci(t['q_r_wilson95'])} |")
    w(f"\nHolm order: {', '.join(h1['family']['order'])}. A rejection reads as \"better\" only if b > c.\n")

    h3 = pr["H3"]
    w("### H3: no harm (own α each, outside the H1 family)\n")
    w("| test | method | set | n_R | c | q̂_r | one-sided 97.5% Clopper–Pearson upper bound | bound | largest c that rejects | reject |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for lab, t in (("H3a", h3["H3a"]), ("H3a (BE, descriptive)", h3["BE_descriptive"]["H3a"])):
        w(f"| {lab} | {t['method']} | P | {t['n_R']} | {t['c']} | {num(t['q_r'])} | {num(t['cp_upper_97_5'], 4)} | < {t['bound']} | "
          f"{t['c_max_that_rejects'] if t['c_max_that_rejects'] is not None else 'none'} | {yn(t['reject'])} |")
    w("")
    w("| test | method | set | N | b | c | difference | Newcombe 95% CI | lower bound > −0.03 | reading |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    for lab, t in (("H3b", h3["H3b"]), ("H3b (BE, descriptive)", h3["BE_descriptive"]["H3b"])):
        w(f"| {lab} | {t['method']} | T | {t['n']} | {t['b']} | {t['c']} | {num(t['diff'])} | {ci(t['newcombe_ci95'])} | "
          f"{yn(t['reject'])} | {t['reading']} |")
    w(f"\nPower warning (pre-declared): {h3['H3b']['power_warning']}.\n")

    h2 = pr["H2"]
    w("### H2: local arm (fixed sequence, own α = 0.05)\n")
    if h2["status"] == "not_run":
        w(f"{h2['text']}. H2 is reported as \"not run as confirmatory; local checker unvalidated\".\n")
    else:
        w(f"Status: **{h2['status']}**{'' if h2['confirmatory'] else ' — ' + h2['text']}. {h2['sequence']}.\n")
        w("| step | contrast | N | b | c | difference | Newcombe 95% CI | exact McNemar p | criterion | tested | reject |")
        w("|---|---|---|---|---|---|---|---|---|---|---|")
        a = h2["H2a"]
        w(f"| H2a | {a['contrast']} | {a['n']} | {a['b']} | {a['c']} | {num(a['diff'])} | {ci(a['newcombe_ci95'])} | "
          f"{pval(a['p_exact_mcnemar'])} | p ≤ 0.05, b > c | {yn(a['tested'])} | {yn(a['reject'])} |")
        b = h2["H2b_NI"]
        if "contrast" in b:
            w(f"| H2b-NI | {b['contrast']} | {b['n']} | {b['b']} | {b['c']} | {num(b['diff'])} | {ci(b['newcombe_ci95'])} | "
              f"{pval(b['p_exact_mcnemar'])} | Newcombe lower > −0.05 | {yn(b['tested'])} | {yn(b['reject'])} |")
            c = h2["H2b_S"]
            w(f"| H2b-S | {c['contrast']} | {b['n']} | {c['b']} | {c['c']} | | | {pval(c['p_exact_mcnemar'])} | p ≤ 0.05, b > c | "
              f"{yn(c['tested'])} | {yn(c['reject'])} |")
        else:
            w(f"| H2b | {b['text']} | | | | | | | | no | no |")
        d = h2["diagnostics"]
        sp = d["self_preference"]
        w(f"\nSelf-preference ({sp['set']}, {sp['items']} items): J_local picks agent `{sp['agent']}`'s answer at "
          f"{pct(sp['J_local'])}; J at {pct(sp['J'])} (RS value match {pct(sp['RS_value_match'])}, CB-S "
          f"{pct(sp['CB-S_value_match'])}).")
        sm = d["shared_model"]
        w(f"Shared model: checker {sm['local_checker_models']}, J_local {sm['J_local_models']}, agent {sm['agent_models']}"
          f"{' — ' + sm['note'] if sm['note'] else ''}.\n")

    h4 = pr["H4"]
    rate = h4.get("fhat_rate")
    w(f"### H4: gate soundness ({h4['theorem']})\n")
    w(f"F-hat rate: {num(rate['rate'], 4) if rate else 'n/a'}{f' ({rate['num']}/{rate['den']})' if rate and rate.get('num') else ''}"
      f"{'; local ' + num(h4['local_fhat_rate']['rate'], 4) if h4.get('local_fhat_rate') else ''}.\n")
    w("| set | method | N | c_D | b_D | F | c_D items ⊆ F items | F-hat | checked incorrect pairs | c vs MAJ | c vs MAJ not in F (tied) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for k in ("P", "T"):
        for m, v in h4[k].items():
            w(f"| {k} | {m} | {v['n']} | {v['c_D']} | {v['b_D']} | {v['F']} | {yn(v['harm_bound_holds'])} | {num(v['F_hat'], 2)} | "
              f"{v['checked_incorrect_pairs']} | {v['c_vs_MAJ']} | {len(v['c_vs_MAJ_not_in_F'])} ({v['c_vs_MAJ_not_in_F_tied']}) |")
    w(f"\nharm_bound_holds on P and T: **{h4['harm_bound_holds']}**"
      f"{' — IMPLEMENTATION DEFECT (reported, not re-analysed)' if h4['implementation_defect'] else ''}. "
      f"F items (P, BE-G): {', '.join('`%s`' % x for x in h4['P']['BE-G']['F_items']) or 'none'}. "
      f"c against MAJ not explained by F (tied pluralities, GATE_SPEC §3 caveat 1): "
      f"{', '.join('`%s`' % x for k in ('P', 'T') for x in h4[k]['BE-G']['c_vs_MAJ_not_in_F']) or 'none'}.\n")

    w("### §2.4 references and baselines (descriptive; Holm-adjusted p for the reference family vs MAJ)\n")
    for k in ("P", "T"):
        r = pr["references"][k]
        acc = pr["accuracy"][k]["decisive"]
        w(f"**{SET_NAMES[k]}.** Not run: {', '.join(r['not_run']) or 'none'}.\n")
        w("| method | role | accuracy | b / c vs MAJ | p | Holm p | BE-G vs method: b / c, p |")
        w("|---|---|---|---|---|---|---|")
        for m, t in r["vs_MAJ"].items():
            bg = r["BE-G_vs"].get(m)
            w(f"| {m} | {METHOD_NAMES.get(m, m)} | {pct(acc.get(m))} | {t['b']} / {t['c']} | {pval(t['p_exact_mcnemar'])} | "
              f"{pval(t.get('p_holm_ref_family'))} | {f'{bg['b']} / {bg['c']}, {pval(bg['p_exact_mcnemar'])}' if bg else '—'} |")
        w("")
    w("### Reading (PREREGISTRATION.md §14)\n")
    for x in reading(pr):
        w(f"- {x}")
    w("")

    w("## 2. Deviations\n")
    dv = []
    if tc["mismatches"]:
        dv.append(f"policy template mismatches: {tc['mismatches']}")
    for k in ("P", "T"):
        for m in ("J", "RS", "CB-S", "J_local"):
            c = pr["H5"]["cost"][k].get(m)
            if c and not c["cost_basis_complete"]:
                dv.append(f"{m} on {k}: rows for {c['rows']} of {pr['H5']['cost'][k]['decisions']} disagreement items "
                          f"(uniform cost basis incomplete)")
        hct = pr["H5"]["cost"][k]["hosted_checks"]["total"]
        if hct["model_calls"] and hct["input_tokens"] is None:
            dv.append(f"hosted check records on {k} carry no token counts (only $ and wall time are reported for checks)")
        miss = hct["checks_missing"]
        if miss:
            dv.append(f"{miss} cited checks without a record on {k}")
    if ev.get("counts", {}).get("missing_capture"):
        dv.append(f"{ev['counts']['missing_capture']} citations without a capture")
    w("\n".join(f"- {x}" for x in dv) + "\n" if dv else "None detected by the evaluator.\n")

    w("## 3. Descriptive analyses (H5, sensitivity)\n")
    w("### Accuracy and overturn rates by set\n")
    for k in SETS:
        a = pr["accuracy"][k]
        o = pr["overturn_vs_MAJ"][k]
        w(f"**{SET_NAMES[k]}** ({a['n_decisive']} decisive, {a['n_eligible']} eligible).\n")
        w("| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |")
        w("|---|---|---|---|---|---|---|---|")
        for m in pr["methods_reported"]:
            ov = o.get(m)
            w(f"| {m} | {METHOD_NAMES.get(m, m)} | {pct(a['decisive'].get(m))} | {pct(a['eligible'].get(m))} | "
              f"{ov['b'] if ov else '—'} | {ov['c'] if ov else '—'} | "
              f"{(num(ov['p_w']) + ' ' + ci(ov['p_w_wilson95'])) if ov else '—'} | {(num(ov['q_r']) + ' ' + ci(ov['q_r_wilson95'])) if ov else '—'} |")
        od = pr["overturn_vs_D"][k]
        w("\nAgainst D: " + "; ".join(f"{m} b_D {v['b']}, c_D {v['c']}, q_r(D) {num(v['q_r'])}" for m, v in od.items()) + ".\n")
    w("### Gap-closed fraction G = (acc − acc_MAJ) / (acc_REF − acc_MAJ)\n")
    w("| set | method | REF | G | bootstrap 95% CI | undefined resamples |")
    w("|---|---|---|---|---|---|")
    for k in SETS:
        for m, d in pr["H5"]["gap_closed"][k].items():
            for ref, e in d.items():
                w(f"| {k} | {m} | {ref} | {num(e['G'])} | {ci(e.get('bootstrap_ci95'))} | "
                  f"{(e.get('bootstrap') or {}).get('undefined_resamples', 'n/a')} |")
    w("")
    w("### Cost (uniform basis: every disagreement item), latency, replay and audit\n")
    for k in ("P", "T", "pooled"):
        c, lt = pr["H5"]["cost"][k], pr["H5"]["latency"][k]
        hc = c["hosted_checks"]
        w(f"**{SET_NAMES[k]}**: {c['decisions']} decisions; {c['forced_no_call_items']} single-value items forced with no call.\n")
        w("| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | "
          "local wall s / decision | latency per decision | coverage |")
        w("|---|---|---|---|---|---|---|---|")
        pdc = hc["per_decision"]
        crit = lt["BE-G"]["critical_path_s"]
        w(f"| BE-G / BE / VV (hosted checks, shared labels) | {num(pdc['usd'], 4)} | {num(pdc['model_calls'], 2)} | "
          f"{num(pdc['input_tokens'], 0)} / {num(pdc['output_tokens'], 0)} | {num(pdc['cache_creation_input_tokens'], 0)} | — | "
          f"critical path median {num(crit['median'], 2)} s, p95 {num(crit['p95'], 2)} s | {hc['total']['model_calls']} checks, "
          f"{hc['total']['checks_missing']} missing |")
        if "local_checks" in c:
            lp = c["local_checks"]["per_decision"]
            lc = lt["BE-G-L"]["critical_path_s"]
            w(f"| BE-G-L / VV-L (local checks) | 0 | {num(lp['model_calls'], 2)} | {num(lp['input_tokens'], 0)} / "
              f"{num(lp['output_tokens'], 0)} | — | {num(c['local_checks']['local_wall_s_per_decision'], 2)} | "
              f"critical path median {num(lc['median'], 2)} s | |")
        for m in ("J", "RS", "CB-S", "J_local"):
            if m in c:
                q = c[m]["per_decision"]
                w(f"| {m} | {num(q['usd'], 4)} | {num(q['model_calls'], 2)} | {num(q['input_tokens'], 0)} / "
                  f"{num(q['output_tokens'], 0)} | {num(q['cache_creation_input_tokens'], 0)} | "
                  f"{num(c[m].get('local_wall_s_per_decision'), 2) if m == 'J_local' else '—'} | "
                  f"median {num(lt[m]['call_wall_ms']['median'], 0)} ms, p95 {num(lt[m]['call_wall_ms']['p95'], 0)} ms | "
                  f"{pct(c[m]['coverage'])} |")
        w(f"| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |\n")
        rw = lt["BE-G"]["reducer_wall_s"]
        w(f"Reducer wall time (BE-G): median {num((rw['median'] or 0) * 1000, 2)} ms, p95 {num((rw['p95'] or 0) * 1000, 2)} ms.\n")
    gs = pr["H5"]["cost"]["gold_shown_diagnostic_checks"]
    w(f"Gold-shown diagnostic checks (excluded from $/decision): {gs['model_calls']} checks, ${num(gs['usd'], 2)}.\n")
    rp = pr["H5"]["replay"]
    w("| replay | result |")
    w("|---|---|")
    for m, v in rp["identity"].items():
        w(f"| {m} identity (each reduction run twice) | byte-identical on {v['identical']} / {v['checked']} eligible items |")
    jr = rp["J_regeneration"]
    w(f"| J regeneration | agreement {pct(jr['agreement'])} on {jr['items']} items (planned set matched: {jr['ids_match_planned']}) |")
    for d in rp["J_local_drift"]:
        w(f"| J_local drift run {d['run']} {d['condition']} | agreement {pct(d['agreement'])} on {d['items']} items |")
    lb, lj = rp["LOAO"]["BE-G"], rp["LOAO"]["J"]
    w(f"| BE-G leave-one-agent-out | {lb['redecisions']} re-decisions on {lb['items']} items, 0 model calls, "
      f"{num(lb['wall_s_total'], 2)} s total; decision changed in {lb['changed_redecisions']} ({pct(lb['change_rate'])}) |")
    w(f"| J leave-one-agent-out | counterfactual 5 calls per item ≈ ${num(lj.get('counterfactual_usd_per_item'), 3)}, "
      f"{num((lj.get('counterfactual_wall_ms_per_item') or 0) / 1000, 1)} s per item; subsample rows {lj['subsample_rows']}"
      f"{', decision changed ' + pct(lj.get('change_rate')) if lj.get('change_rate') is not None else ''} |\n")
    w("| set | BE-G overturns | labelled passages per overturn (median, max) | characters (median, max) | J context tokens per decision (median) |")
    w("|---|---|---|---|---|")
    for k in SETS:
        a = pr["H5"]["audit"][k]
        w(f"| {k} | {a['BE-G_overturns']} | {num(a['passages']['median'], 0)}, {num(a['passages']['max'], 0)} | "
          f"{num(a['chars']['median'], 0)}, {num(a['chars']['max'], 0)} | {num(a['J_context_tokens']['median'], 0)} |")
    w("")
    w("### Majority-following (agreement with MAJ on majority-wrong decisive items)\n")
    w("| set | majority-wrong items | " + " | ".join(m for m in ("J", "RS", "CB-S", "J_local")) + " |")
    w("|---|---|" + "---|" * 4)
    for k in SETS:
        mf = pr["H5"]["majority_following"][k]
        w(f"| {k} | {mf['majority_wrong_items']} | " + " | ".join(
            (f"{mf[m]['follows_majority']} / {mf[m]['decided']}" if m in mf else "not run") for m in ("J", "RS", "CB-S", "J_local")) + " |")
    w("")
    w("### Close pairs and subgroups\n")
    w("| set | pair | N | b | c | p |")
    w("|---|---|---|---|---|---|")
    for k in SETS:
        for name, t in pr["H5"]["pairs"][k].items():
            w(f"| {k} | {name.replace('_vs_', ' vs ')} | {t['n']} | {t['b']} | {t['c']} | {pval(t['p_exact_mcnemar'])} |")
    w("")
    sg = pr["H5"]["subgroups"]
    w("| subgroup | N | MAJ | BE-G | BE | J | BE-G vs MAJ b / c, p |")
    w("|---|---|---|---|---|---|---|")
    rows = list(sg["by_source"].items()) + [("popqa " + k, v) for k, v in sg["popqa_stratum"].items()] + [("SciFact REFUTED", sg["scifact_refuted"])]
    for name, v in rows:
        a = v["accuracy"]
        t = v["BE-G_vs_MAJ"]
        w(f"| {name} | {v['n']} | {pct(a.get('MAJ'))} | {pct(a.get('BE-G'))} | {pct(a.get('BE'))} | {pct(a.get('J'))} | "
          f"{t['b']} / {t['c']}, {pval(t['p_exact_mcnemar'])} |")
    w("")
    w("### Sensitivity analyses (pre-declared, descriptive)\n")
    se = pr["sensitivity"]
    w("| analysis | contrast | N | b | c | p |")
    w("|---|---|---|---|---|---|")
    for h in ("H1a", "H1b"):
        t = se["popqa_excluded"][h]
        w(f"| PopQA excluded | {h}: {t['method']} vs MAJ on P | {t['n']} | {t['b']} | {t['c']} | {pval(t['p_exact_mcnemar'])} |")
        t = se["MAJ_earliest_arrival_ties"][h]
        w(f"| MAJ with earliest-arrival ties | {h}: {t['method']} vs MAJ_early on P | {t['n']} | {t['b']} | {t['c']} | {pval(t['p_exact_mcnemar'])} |")
    d = se["against_D"]["BE-G"]
    w(f"| c and q_r against D | BE-G vs D on P | {d['n']} | {d['b']} | {d['c']} (q_r {num(d['q_r'])}) | |")
    for k in ("P", "T"):
        for m, v in se["null_judge_scored_wrong"].get(k, {}).items():
            t = v["BE-G_vs"]
            w(f"| null {m} decisions scored wrong ({v['nulls']} nulls) | BE-G vs {m} on {k} | {t['n']} | {t['b']} | {t['c']} | {pval(t['p_exact_mcnemar'])} |")
    w(f"\nWitness sample for blinded labelling: {se['witness_sample']['n']} BE-G overturn witnesses in "
      f"`{se['witness_sample']['file']}` (labels and κ against G-AK are added outside the evaluator).\n")
    al = pr["also"]
    w("### Also reported\n")
    w(f"- Gate stages (BE-G, decisive): " + "; ".join(f"{k} {json.dumps(v, sort_keys=True)}" for k, v in al["gate_stage_counts"].items()) + ".")
    s4 = al["S4_separation"]
    w(f"- S4 separation (δ = {s4['delta']}): BE-G {s4['BE-G']['separated']} / {s4['BE-G']['decisive_with_slot']}; "
      f"BE {s4['BE']['separated']} / {s4['BE']['decisive_with_slot']}.")
    ck = al["checks"]
    w(f"- Hosted checks cited: {ck['cited_checks']}; status {json.dumps(ck['status'], sort_keys=True)}; mapped labels on "
      f"citations {json.dumps(ck['mapped_labels_on_citations'], sort_keys=True)}.")
    if al.get("local_checks"):
        lc = al["local_checks"]
        w(f"- Local checks cited: {lc['cited_checks']}; status {json.dumps(lc['status'], sort_keys=True)}; mapped labels "
          f"{json.dumps(lc['mapped_labels_on_citations'], sort_keys=True)}.")
    w("- Evidence availability (decisive, diagnostic): " + "; ".join(
        f"{k} {pct(v['availability'])}" for k, v in al["evidence_availability"].items()) + ".")
    w("- Fallbacks on decisive conflicts: " + "; ".join(f"{k} {json.dumps(v, sort_keys=True)}" for k, v in al["fallbacks"].items()) + ".")
    w(f"- Mirror check: {ev['mirror_check']['slots_checked']} slots, {ev['mirror_check']['mismatches']} mismatches. "
      f"Counts: {json.dumps(ev['counts'], sort_keys=True)}.\n")

    d = dev or (ev if split == "dev" else None)
    if d and d.get("dev_gate"):
        g = d["dev_gate"]
        w("## 4. Dev gate (§6.2) and the selections (PREREGISTRATION.md §5.2)\n")
        w("| check | value | threshold | pass | if it fails |")
        w("|---|---|---|---|---|")
        w(f"| yield y_dev | {num(g['yield']['value'])} | ≥ {g['yield']['threshold']} | {g['yield']['pass']} | {g['yield']['if_fail']} |")
        mw = g["majority_wrong_share"]
        w(f"| majority-wrong share m_dev | {num(mw['value'])} (expected tie-break {num(mw['value_expected_tiebreak'])}) | "
          f"≥ {mw['threshold']} | {mw['pass']} | {mw['if_fail']} |")
        ea = g["evidence_availability"]
        w(f"| evidence availability per source | " + "; ".join(
            f"{s} {pct(v['availability'])}{' (lower bound)' if v['lower_bound'] else ''}" for s, v in ea["per_source"].items())
          + f" | ≥ {ea['threshold']} | {ea['pass']} | {ea['if_fail']} |")
        pf = g["parse_failure"]
        w(f"| parse failure, worst agent | {pct(pf['worst'])} | < {pf['threshold']} | {pf['pass']} | {pf['if_fail']} |\n")
        w(f"All four pass: **{g['all_pass']}**. Stopping rule: ψ_dev = {num(g['stopping_rule']['psi_dev'])} "
          f"(used {num(g['stopping_rule']['psi_used'])}), N\\* = {g['stopping_rule']['N_star']}, "
          f"I = **{g['stopping_rule']['I']}** items (unclamped {g['stopping_rule']['I_unclamped']}).\n")
        w("| configuration | gated | changed fields | b | c | b − c | ψ | policy template sha256 |")
        w("|---|---|---|---|---|---|---|---|")
        sel = {d["BE_config"]: " **(BE)**", d.get("BE_G_config") or (d.get("dev_informed") or {}).get("selected_gated"): " **(BE-G)**"}
        for r in d["BE_grid"]:
            w(f"| `{r['config']}`{sel.get(r['config'], '')} | {yn(r.get('gated'))} | {r['changed_fields']} | {r['b']} | {r['c']} | "
              f"{r['b_minus_c']} | {num(r['psi'])} | `{r['policy_template_sha256'][:16]}` |")
        w("")
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", required=True)
    ap.add_argument("--dev")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ev = jload(a.eval)
    dev = jload(a.dev) if a.dev else None
    if dev and dev.get("synthetic") != ev.get("synthetic"):
        raise SystemExit("refused: mixing synthetic and real evaluation files")
    if "prereg" not in ev:
        raise SystemExit("refused: evaluation file has no `prereg` block (made by an older evaluate_v5.py)")
    with open(a.out, "w") as f:
        f.write(render(ev, dev))
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
