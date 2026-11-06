#!/usr/bin/env python3
"""bran-artifact/4 variant. Compare dumped artifacts across platforms byte-for-byte and summarize the
replay matrix. Writes results/compare.txt (and prints it)."""
import hashlib, json, pathlib, re, sys
EV = pathlib.Path(__file__).resolve().parent
TOPICS = ["australia", "pluto", "tides", "tcp", "nutrition"]
plats = sorted(p.name for p in (EV / "dumps").iterdir() if p.is_dir())
out, ok = [], True
def sha(b): return hashlib.sha256(b).hexdigest()
out.append("platforms: " + ", ".join(plats))
out.append("")
out.append("| topic | root_hash | policy_hash | certificate | outputs sha256 (canonical) | dump file sha256 | identical on all |")
out.append("|---|---|---|---|---|---|---|")
for t in TOPICS:
    rows = {}
    for p in plats:
        raw = (EV / "dumps" / p / f"{t}.json").read_bytes()
        f = json.loads(raw)
        ok &= f["format"] == "bran-artifact/4"
        o = f["outputs"]
        osha = sha(json.dumps(o, sort_keys=True, separators=(",", ":")).encode())
        rows[p] = (o["root_hash"], f["policy_hash"], o["certificate"], osha, sha(raw))
    same = len(set(rows.values())) == 1
    ok &= same
    r = rows[plats[0]]
    out.append(f"| {t} | `{r[0]}` | `{r[1]}` | `{r[2]}` | `{r[3][:16]}…` | `{r[4][:16]}…` | {'yes' if same else 'NO'} |")
    if not same:
        for p, v in rows.items(): out.append(f"|   {p} | {' | '.join(v)} |")
out.append("")
out.append("Replay matrix (replayer <- dumper: PASS count / 5 topics):")
reps = sorted(EV.glob("results/*-replay.txt"))
out.append("| replayer \\ dumper | " + " | ".join(plats) + " |")
out.append("|---|" + "---|" * len(plats))
for rf in reps:
    who = rf.name[: -len("-replay.txt")]
    text = rf.read_text()
    cells = []
    for p in plats:
        n = len(re.findall(rf"^{re.escape(who)} <- {re.escape(p)}/\w+: +PASS", text, re.M))
        ok &= n == len(TOPICS)
        cells.append(f"{n}/{len(TOPICS)}")
    out.append(f"| {who} | " + " | ".join(cells) + " |")
out.append("")
out.append("Tamper table (results/tamper-<build>.txt; exit code got / expected):")
tfs = sorted(EV.glob("results/tamper-*.txt"))
tw = {}
for tf in tfs:
    for line in tf.read_text().splitlines():
        parts = line.split("\t")
        if len(parts) == 5 and parts[2].startswith("expected="):
            tw.setdefault(parts[1], {})[parts[0]] = (parts[3][4:], parts[2][9:])
            ok &= parts[4] == "OK"
builds = sorted({b for v in tw.values() for b in v})
out.append("| case | expected | " + " | ".join(builds) + " |")
out.append("|---|---|" + "---|" * len(builds))
for case, v in tw.items():
    exp = next(iter(v.values()))[1]
    out.append(f"| {case} | {exp} | " + " | ".join(v[b][0] if b in v else "-" for b in builds) + " |")
out.append("")
out.append("ALL IDENTICAL / ALL PASS" if ok else "DIVERGENCE DETECTED")
s = "\n".join(out)
(EV / "results" / "compare.txt").write_text(s + "\n")
print(s)
sys.exit(0 if ok else 1)
