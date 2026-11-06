#!/usr/bin/env python3
"""EXPLORATORY (run only after aliases.json was frozen): regrade v5 confirmatory with augmented PopQA gold.
Imports selector_study read-only; writes nothing. Run: python3 explore_v5.py"""
import copy, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
V5 = HERE.parents[2] / "v5"
sys.dont_write_bytecode = True
sys.path.insert(0, str(V5 / "selector_study"))
import selector_study as S
E = S.E
ALI = json.load(open(HERE / "aliases.json"))
orig_load = E.load_items


def aug_items(p):
    its = orig_load(p)
    for iid, add in ALI.items():
        if iid in its:
            its[iid]["gold"]["aliases"] = list(its[iid]["gold"]["aliases"]) + add
    return its


def run(augment):
    E.load_items = aug_items if augment else orig_load
    TWW, _, _ = S.dev_trust_weights()
    ctx = S.make_ctx(S.CONF_DIR / "captures.jsonl", S.CONF_DIR / "checks.jsonl")
    items = E.load_items(V5 / "benchmark" / "items_confirmatory.jsonl")
    raws = {f.stem: E.jload(f) for f in sorted((S.CONF_DIR / "raw").glob("*.json"))}
    rows = []
    for iid in sorted(raws, key=lambda i: (items[i].get("order", 0), i)):
        rec = E.prepare_item(items[iid], raws[iid], ctx)
        row = rec["row"]
        row["set"] = E.analysis_set(rec["item"], strict=True)
        if not row["eligible"]:
            continue
        E.python_methods(rec, ctx, E.PREREG_BEST)
        ch, meta, defaults = S.decide(rec, ctx, TWW)
        r = {"id": iid, "set": row["set"], "decisive": row["decisive"], "MAJ": row["MAJ"], "_meta": meta, "_defaults": defaults}
        for k, o in ch.items():
            r[k] = E.object_correct(rec, o)[0]
        rows.append(r)
    P = [r for r in rows if r["decisive"] and r["set"] == "P"]
    return items, raws, P


def table(P):
    out = {}
    for m in ["MAJ", "VV", "VV/VDF", "BE-G", "BE-G/VDF"]:
        o = {"acc": sum(r[m] for r in P) / len(P)}
        if m != "MAJ":
            ov = E.overturn(P, m)
            o["b"], o["c"] = ov["b"], ov["c"]
            dk = P[0]["_defaults"][m] if m in P[0]["_defaults"] else "MAJ"
            o["c_D"] = sum(1 for r in P if r[dk] and not r[m])
            o["dk"] = dk
        o["H3a"] = S.h3a(P, m) if m != "MAJ" else None
        out[m] = o
    return out


base_items, raws, Pb = run(False)
aug_items_d, _, Pa = run(True)
print("n_P", len(Pb), len(Pa))
for name, P in (("BASE", Pb), ("AUG", Pa)):
    print(name)
    for m, o in table(P).items():
        h = o["H3a"]
        print(f"  {m:9} acc={o['acc']:.4f} b/c={o.get('b')}/{o.get('c')} c_D={o.get('c_D')}({o.get('dk')})"
              + (f" H3a c={h['c']} n_R={h['n_R']} UB={h['cp_upper_97_5']:.4f} reject={h['reject']}" if h else ""))

# response-level status changes (all popqa items, all responses) and harm_reading alias recovery
flip_up = flip_down = n = 0
ex = []
byitem = {}
for iid, raw in raws.items():
    b, a = base_items[iid], aug_items_d[iid]
    if b["source"]["key"] != "popqa":
        continue
    for r in raw["responses"]:
        vb, va = E.response_view(b, r), E.response_view(a, r)
        if vb["parsed"] is None:
            continue
        n += 1
        byitem.setdefault(iid, []).append((vb, va))
        if vb["correct"] and not va["correct"]:
            flip_down += 1; ex.append(iid)
        if va["correct"] and not vb["correct"]:
            flip_up += 1
print("popqa parsed responses", n, "wrong->right", flip_up, "right->wrong", flip_down, ex[:5])
hr = [json.loads(l) for l in open(V5 / "controls" / "harm_reading.jsonl")]
al = {(d["item_id"], d["value"]) for d in hr if d.get("gold_subclass") == "alias"}
items9 = sorted({i for i, _ in al})
print("alias items", len(items9), "(item,value) pairs", len(al))
rec = 0
for iid, val in sorted(al):
    hits = [(vb, va) for vb, va in byitem.get(iid, []) if vb["parsed"] == val]
    flipped = any(va["correct"] and not vb["correct"] for vb, va in hits)
    print(" ", iid, repr(val), "responses", len(hits), "flipped", flipped,
          [vb["answer"] for vb, _ in hits][:2], ALI.get(iid, [])[:6])
    rec += flipped
print("pairs recovered", rec)
print("items recovered", len({i for i, v in al if any(va["correct"] and not vb["correct"] for vb, va in byitem.get(i, []) if vb["parsed"] == v)}))
