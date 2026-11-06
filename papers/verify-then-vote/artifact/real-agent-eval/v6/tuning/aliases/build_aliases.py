#!/usr/bin/env python3
"""Build the blind PopQA gold-alias supplement from Wikidata (English labels + aliases).

Blind to outcomes: reads ONLY benchmark/items_confirmatory.jsonl (gold, ids, Wikidata uris).
No agent answer, decision or result file is opened.

Rules
  - candidate alias = English label or alias of the gold object entity (source.obj_wikidata)
  - normalise as the frozen grader does (answer_key.grade): lower().strip(); whitespace collapsed
  - keep only aliases not already in the item's gold aliases (normalised compare)
  - drop aliases of <= 2 characters
  - drop an alias that is a label/alias of a DIFFERENT candidate entity: the item's subject entity,
    and the gold objects (and subjects) of other PopQA items that share this item's subject
    (the only other candidate answers the question could be confused with)
Usage: python3 -I build_aliases.py [--refresh]   (cache: wikidata_cache.json; network only if missing)
"""
import json, re, sys, time, hashlib, subprocess, urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
ITEMS = HERE.parents[2] / "v5" / "benchmark" / "items_confirmatory.jsonl"
CACHE = HERE / "wikidata_cache.json"
API = "https://www.wikidata.org/w/api.php"
UA = "bran-paper-alias-builder/1.0 (research; https://github.com/grainulation/papers)"


def norm(s):
    return " ".join(s.lower().strip().split())


def qid(uri):
    m = re.search(r"/(Q\d+)$", uri or "")
    return m.group(1) if m else None


def fetch(ids):
    cache = json.load(open(CACHE)) if CACHE.exists() and "--refresh" not in sys.argv else {}
    todo = sorted(i for i in ids if i not in cache)
    for k in range(0, len(todo), 50):
        batch = todo[k:k + 50]
        q = urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(batch), "props": "labels|aliases",
                                    "languages": "en", "format": "json"})
        for attempt in range(5):
            try:
                # curl, not urllib: urllib lacks the system CA store behind the corporate proxy
                r = subprocess.run(["curl", "-sf", "-m", "60", "-A", UA, API + "?" + q],
                                   capture_output=True, check=True)
                d = json.loads(r.stdout)
                if "entities" not in d:  # e.g. maxlag error body: back off and retry
                    raise RuntimeError(str(d)[:200])
                break
            except Exception as e:
                print("retry", e, file=sys.stderr); time.sleep(5 * (attempt + 1))
        else:
            raise SystemExit("wikidata fetch failed")
        for i in batch:
            e = d.get("entities", {}).get(i, {})
            cache[i] = {"label": (e.get("labels", {}).get("en") or {}).get("value"),
                        "aliases": [a["value"] for a in e.get("aliases", {}).get("en", [])],
                        "missing": "missing" in e}
        time.sleep(1.0)
        print(f"fetched {k + len(batch)}/{len(todo)}", file=sys.stderr)
    json.dump(cache, open(CACHE, "w"), indent=0, sort_keys=True, ensure_ascii=False)
    return cache


def names(c, q):
    e = c.get(q) or {}
    return {norm(x) for x in ([e.get("label")] if e.get("label") else []) + e.get("aliases", [])}


def main():
    items = [json.loads(l) for l in open(ITEMS)]
    pop = [i for i in items if i["source"]["key"] == "popqa"]
    ids = {qid(i["source"]["obj_wikidata"]) for i in pop} | {qid(i["source"]["subj_wikidata"]) for i in pop}
    ids.discard(None)
    c = fetch(ids)
    by_subj = {}
    for i in pop:
        by_subj.setdefault(qid(i["source"]["subj_wikidata"]), []).append(i)
    out, stats = {}, {"popqa_items": len(pop), "with_added": 0, "added_total": 0, "dropped_short": 0,
                      "dropped_conflict": 0, "dropped_in_gold": 0, "missing_entities": 0}
    for i in pop:
        o, s = qid(i["source"]["obj_wikidata"]), qid(i["source"]["subj_wikidata"])
        if c.get(o, {}).get("missing"):
            stats["missing_entities"] += 1
        gold = {norm(a) for a in i["gold"]["aliases"]} | {norm(i["gold"]["answer"])}
        other = set(names(c, s))
        for j in by_subj.get(s, []):
            if j is not i:
                other |= names(c, qid(j["source"]["obj_wikidata"]))
        cands = {}
        e = c.get(o) or {}
        for a in ([e["label"]] if e.get("label") else []) + e.get("aliases", []):
            cands.setdefault(norm(a), a)
        add = []
        for n in sorted(cands):
            if n in gold: stats["dropped_in_gold"] += 1
            elif len(n) <= 2: stats["dropped_short"] += 1
            elif n in other: stats["dropped_conflict"] += 1
            else: add.append(n)
        if add:
            out[i["id"]] = add
            stats["with_added"] += 1
            stats["added_total"] += len(add)
    json.dump(out, open(HERE / "aliases.json", "w"), indent=1, sort_keys=True, ensure_ascii=False)
    (HERE / "aliases.json.sha256").write_text(hashlib.sha256((HERE / "aliases.json").read_bytes()).hexdigest()
                                              + "  aliases.json\n")
    print(json.dumps(stats))


main()
