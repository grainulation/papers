"""Parse --stress outputs (5 runs per mode) into a summary table (median time, range)."""
import json, re, statistics, sys
from pathlib import Path

D = Path(sys.argv[1])
TOPICS = ["australia", "tcp", "nutrition"]
def t2ms(s):
    s = s.strip()
    if s.endswith("μs"): return float(s[:-2]) / 1000
    if s.endswith("ms"): return float(s[:-2])
    if s.endswith("s"): return float(s[:-1]) * 1000
    raise ValueError(s)

res = {}
for mode in ["member", "value_max", "value_pooled"]:
    runs = []
    for r in range(1, 6):
        rows, ti = [], -1
        for line in open(D / f"stress_{mode}_run{r}.txt"):
            if "Topic:" in line:
                ti += 1
            cells = [c.strip() for c in line.strip().strip("│").split("│")]
            if len(cells) == 9 and re.match(r"^[\d,]+$", cells[0]):
                rows.append(dict(topic=TOPICS[ti], n=int(cells[0].replace(",", "")), claims=int(cells[1].replace(",", "")),
                                 conflicts=int(cells[2]), output=int(cells[3]), prec=cells[4], fp=int(cells[5]),
                                 ms=t2ms(cells[8])))
        runs.append(rows)
    agg = []
    for i, row in enumerate(runs[0]):
        for k in ["claims", "conflicts", "output", "prec", "fp"]:
            assert all(rr[i][k] == row[k] for rr in runs), (mode, row)
        ts = [rr[i]["ms"] for rr in runs]
        agg.append({**{k: row[k] for k in ["topic", "n", "claims", "conflicts", "output", "prec", "fp"]},
                    "ms_median": round(statistics.median(ts), 2), "ms_min": round(min(ts), 2), "ms_max": round(max(ts), 2)})
    res[mode] = agg
json.dump(res, open(D / "stress_summary.json", "w"), indent=1)
print("| Topic | N | Claims | mode | Slots (conflict sets) | Output keys | Prec | FP | Time median ms [min–max] |")
print("|---|---:|---:|---|---:|---:|---:|---:|---|")
for i in range(len(res["member"])):
    for mode in res:
        r = res[mode][i]
        if r["n"] not in (100, 1000, 10000): continue
        print(f"| {r['topic']} | {r['n']:,} | {r['claims']:,} | {mode} | {r['conflicts']} | {r['output']} | {r['prec']} | {r['fp']} | {r['ms_median']} [{r['ms_min']}–{r['ms_max']}] |")
