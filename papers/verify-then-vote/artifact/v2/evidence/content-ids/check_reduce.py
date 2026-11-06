#!/usr/bin/env python3
"""`--reduce` checks for content-addressed ids (bran-contribution-id/1).

usage: check_reduce.py <overturn binary> <bran-artifact/4 dump> <scratch dir>

1. Feeding a /4 dump's sealed contributions back through `--reduce` with
   "id_scheme" reproduces the dump's root hash and certificate.
2. Editing one claim but keeping its id is rejected (exit 2).
3. A SYNTHESIS contribution is dropped at P3 and reported in
   `p3_rejected` with reason `synthesis_out_of_scope`; outputs are
   otherwise unchanged.
   (`--assign-ids` computes the ids, and reproduces the dump's ids.)
4. Without "id_scheme" the same input is reduced as before (legacy:
   any id accepted, no scheme in the root hash).
"""
import copy, json, subprocess, sys
from pathlib import Path

binary, dump, scratch = sys.argv[1], sys.argv[2], Path(sys.argv[3])
scratch.mkdir(parents=True, exist_ok=True)
f = json.load(open(dump))
assert f["format"] == "bran-artifact/4", f["format"]
a = f["artifact"]
base = {"intent": a["intent"], "criteria": a["criteria"], "calibration": a["calibration"],
        "id_scheme": "bran-contribution-id/1", "contributions": a["contributions"]}


def reduce(inp, name):
    p = scratch / f"{name}.json"
    json.dump(inp, open(p, "w"))
    r = subprocess.run([binary, "--reduce", str(p), "--no-color"], capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.returncode == 0 else r.stderr.strip())


fails = 0
def check(ok, msg):
    global fails
    print(("  PASS " if ok else "  FAIL ") + msg)
    fails += 0 if ok else 1

rc, out = reduce(base, "content")
check(rc == 0 and out["root_hash"] == a["root_hash"] and out["certificate"] == f["outputs"]["certificate"]
      and "p3_rejected" not in out,
      f"--reduce with id_scheme reproduces dump root {a['root_hash']} and cert {f['outputs']['certificate']}")

t = copy.deepcopy(base)
t["contributions"][0]["canonical_form"]["object"] += "x"
rc, err = reduce(t, "tampered")
check(rc == 2 and "content id" in err, f"edited claim with kept id rejected (exit {rc}): {err[:120]}")

s = copy.deepcopy(base)
syn = copy.deepcopy(s["contributions"][0])
syn["kind"] = "SYNTHESIS"
syn["agent_id"] = "synthesizer"
del syn["id"]
s["contributions"].append(syn)
p = scratch / "synthesis-noids.json"
json.dump(s, open(p, "w"))
s = json.loads(subprocess.run([binary, "--assign-ids", str(p)], capture_output=True, text=True, check=True).stdout)
syn = s["contributions"][-1]
check([c["id"] for c in s["contributions"][:-1]] == [c["id"] for c in base["contributions"]],
      "--assign-ids reproduces the dump's content ids")
rc, out = reduce(s, "synthesis")
check(rc == 0 and out.get("p3_rejected") == [{"id": syn["id"], "agent_id": "synthesizer", "seq": syn["seq"],
                                               "reason": "synthesis_out_of_scope"}]
      and out["root_hash"] == a["root_hash"] and syn["id"] not in out["admitted"],
      "SYNTHESIS dropped at P3 with reason synthesis_out_of_scope; root hash unchanged")

legacy = {k: v for k, v in base.items() if k != "id_scheme"}
rc, out = reduce(legacy, "legacy")
check(rc == 0 and out["root_hash"] != a["root_hash"] and out["admitted"] == f["outputs"]["admitted"],
      "without id_scheme: legacy seal (scheme not hashed), same admitted ids")
lt = copy.deepcopy(legacy)
lt["contributions"][0]["id"] = "foreign-id-0001"
rc, out = reduce(lt, "legacy-foreign")
check(rc == 0, "without id_scheme: foreign ids still accepted (evaluate_v4.py path)")
sys.exit(1 if fails else 0)
