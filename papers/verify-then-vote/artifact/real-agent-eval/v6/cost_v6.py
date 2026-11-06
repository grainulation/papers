"""Checker cost per contested decision with label caching (PREREGISTRATION.md §7).

For the cited labels on the contested items of P and T, reports:
  (i)  marginal: only the live calls made in v6 (confirmatory run and futility look);
  (ii) full-label: each label priced at its original call cost, from the v5 and v6 call logs.
BE-G, BE and VV read the same cited labels, so they share one cost. Also reports the cache share:
the fraction of v6 cited and gold-shown checks served from v5 labels.

Reads only sealed logs; makes no model call. Writes results/conf/cost_v6.json.
"""
import glob
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(HERE, "results", "conf")
V5 = os.path.join(HERE, "..", "v5", "results")


def calls(path):
    with open(path) as f:
        return {j["check_key"]: j for j in map(json.loads, f)}


def main():
    live = calls(os.path.join(CONF, "check_calls.jsonl"))
    live.update(calls(os.path.join(HERE, "results", "conf_futility", "check_calls.jsonl")))
    v5 = {}
    for path in sorted(glob.glob(os.path.join(V5, "*", "check_calls.jsonl"))):
        v5.update(calls(path))
    with open(os.path.join(CONF, "checks_plan.jsonl")) as f:
        plan = [json.loads(line) for line in f]
    with open(os.path.join(CONF, "disagreement_ids.txt")) as f:
        contested = set(f.read().split())

    def price(key):
        call = live.get(key) or v5.get(key)
        if call is None or call.get("cost_usd") is None:
            raise SystemExit(f"ABORT: no priced call for label {key}")
        return call["cost_usd"]

    out = {"format": "bran-v6-cost/1", "methods_sharing_labels": ["BE-G", "BE", "VV", "VV/VDF"], "sets": {}}
    for name, member in (("P", lambda i: not i.startswith("v5-tqa")), ("T", lambda i: i.startswith("v5-tqa"))):
        items = {i for i in contested if member(i)}
        keys = {p["check_key"] for p in plan if "cited" in p["reasons"] and any(i in items for i in p["item_ids"])}
        marginal = sum(live[k]["cost_usd"] or 0 for k in keys if k in live)
        full = sum(price(k) for k in keys)
        out["sets"][name] = {
            "contested_items": len(items),
            "labels": len(keys),
            "labels_per_decision": len(keys) / len(items),
            "live_labels": sum(1 for k in keys if k in live),
            "marginal_usd": marginal,
            "marginal_usd_per_decision": marginal / len(items),
            "full_label_usd": full,
            "full_label_usd_per_decision": full / len(items),
        }
    for reason in ("cited", "gold"):
        keys = {p["check_key"] for p in plan if ("cited" in p["reasons"]) == (reason == "cited")}
        hits = sum(1 for k in keys if k not in live)
        out[f"cache_share_{reason}"] = {"checks": len(keys), "v5_cache_hits": hits, "share": hits / len(keys)}
    judge = [json.loads(line) for line in open(os.path.join(CONF, "judge-store", "log", "calls.jsonl"))]
    costs = [j["cost_usd"] for j in judge if j.get("cost_usd") and j.get("method") == "J"] or \
            [j["cost_usd"] for j in judge if j.get("cost_usd")]
    out["judge_usd_per_call"] = sum(costs) / len(costs)
    with open(os.path.join(CONF, "cost_v6.json"), "w") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
