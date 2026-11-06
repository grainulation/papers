#!/usr/bin/env python3
"""Per-slot comparison of candidate modes on the synthetic workload (seed 42).

Input: artifacts dumped with `overturn --dump-artifact --topic T --agents N --seed 42
--candidate-mode M` (M in member, value:max, value:pooled), named
<mode>_<topic>_<N>.json in DUMP_DIR. Reads only `outputs.selections` and the
contributions' eval-only `is_correct` label.

For each contradiction slot: number of distinct values, whether the winning
VALUE (object, polarity) differs from member mode, winner correctness, and
whether the slot was in the deadband. Writes synthetic_slots.json/.csv.

Usage: python3 synthetic_slots.py DUMP_DIR
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODES = ["member", "value_max", "value_pooled"]
TOPICS = ["australia", "tcp", "nutrition"]
NS = [100, 1000, 10000]


def norm(o):
    return " ".join(o.split()).lower()


def load(d, mode, topic, n):
    f = json.load(open(d / f"{mode}_{topic}_{n}.json"))
    by_id = {c["id"]: c for c in f["artifact"]["contributions"]}
    sels = {s["slot"]: s for s in f["outputs"]["selections"] if s["type"] == "CONTRADICTION"}
    return by_id, sels, f["policy_hash"]


def value(c):
    t = c["canonical_form"]
    return (norm(t["object"]), t["polarity"])


def main():
    d = Path(sys.argv[1])
    rows, summary = [], {}
    for topic in TOPICS:
        for n in NS:
            data = {m: load(d, m, topic, n) for m in MODES}
            by_id = data["member"][0]
            slots = sorted(data["member"][1])
            for m in MODES:
                assert sorted(data[m][1]) == slots
            key = f"{topic}|{n}"
            st = {"contradiction_slots": len(slots), "policy_hash": {m: data[m][2] for m in MODES}}
            for m in MODES:
                sels = data[m][1]
                st[m] = {"winner_correct": sum(by_id[sels[s]["winner"]]["is_correct"] for s in slots),
                         "in_deadband": sum(sels[s]["in_deadband"] for s in slots)}
                if m != "member":
                    st[m]["winner_value_changed_vs_member"] = sum(
                        value(by_id[sels[s]["winner"]]) != value(by_id[data["member"][1][s]["winner"]]) for s in slots)
                    st[m]["winner_id_changed_vs_member"] = sum(
                        sels[s]["winner"] != data["member"][1][s]["winner"] for s in slots)
            summary[key] = st
            for s in slots:
                mem = data["member"][1][s]["members"]
                vals = Counter(value(by_id[i]) for i in mem)
                row = {"topic": topic, "n": n, "slot": s, "members": len(mem), "values": len(vals),
                       "correct_values": len({value(by_id[i]) for i in mem if by_id[i]["is_correct"]}),
                       "largest_value_share": round(max(vals.values()) / len(mem), 3)}
                for m in MODES:
                    sel = data[m][1][s]
                    w = by_id[sel["winner"]]
                    row[f"{m}_winner"] = f"{value(w)[0]}|{value(w)[1]}"
                    row[f"{m}_correct"] = int(w["is_correct"])
                    row[f"{m}_deadband"] = int(sel["in_deadband"])
                rows.append(row)
    json.dump(summary, open(HERE / "synthetic_slots.json", "w"), indent=1)
    with open(HERE / "synthetic_slots.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("| Topic | N | contradiction slots | correct winners member / max / pooled | deadband member / max / pooled | winning value changed (max, pooled) |")
    print("|---|---:|---:|---|---|---|")
    for k, st in summary.items():
        t, n = k.split("|")
        print(f"| {t} | {int(n):,} | {st['contradiction_slots']} | "
              f"{st['member']['winner_correct']} / {st['value_max']['winner_correct']} / {st['value_pooled']['winner_correct']} | "
              f"{st['member']['in_deadband']} / {st['value_max']['in_deadband']} / {st['value_pooled']['in_deadband']} | "
              f"{st['value_max']['winner_value_changed_vs_member']}, {st['value_pooled']['winner_value_changed_vs_member']} |")


if __name__ == "__main__":
    main()
