#!/usr/bin/env python3
"""Build the tamper set for the bran-artifact/4 cross-architecture check.

usage: python3 -I tamper.py <bran-artifact/4 dump> <out dir>

Recomputes root_hash (ir::SealedArtifactSet::canonical_json) and content
ids (ir::content_id, bran-contribution-id/1) in Python, and first checks
that both reproduce the untouched dump exactly, so a "resealed" forgery
is a consistent forgery of everything the tamper does not target.
Writes <out dir>/<case>.json and <out dir>/expected.tsv (case, expected
exit code, description).
"""
import copy, hashlib, json, sys
from pathlib import Path

SCHEME = "bran-contribution-id/1"


def h16(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]


def compact(v) -> str:
    # serde_json::to_string over BTreeMap-backed Values: sorted keys, no
    # whitespace, non-ASCII unescaped. Python float repr is shortest
    # round-trip, like ryu (checked below against the stored hashes).
    return json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


CANON_KEYS = ["id", "seq", "agent_id", "kind", "canonical_form", "confidence",
              "lowering_confidence", "evidence", "raw_text"]


def root_hash(a) -> str:
    v = {"intent": a["intent"], "criteria": a["criteria"], "calibration": a["calibration"],
         "contributions": [{k: c.get(k) for k in CANON_KEYS} for c in a["contributions"]]}
    if a.get("evidence_store") is not None:
        v["evidence_store"] = a["evidence_store"]
    if a.get("id_scheme") is not None:
        v["id_scheme"] = a["id_scheme"]
    return h16(compact(v))


def content_id(c) -> str:
    ev = []
    for e in c["evidence"]:
        d = {k: e[k] for k in ("type", "source", "weight", "reachable", "verification")}
        if e.get("capture_ref") is not None:
            d["capture_ref"] = e["capture_ref"]
        ev.append(d)
    p = {"scheme": SCHEME, "agent_id": c["agent_id"], "kind": c["kind"],
         "canonical_form": c["canonical_form"], "confidence": c["confidence"],
         "lowering_confidence": c["lowering_confidence"], "evidence": ev, "raw_text": c["raw_text"]}
    return h16(compact(p))


src, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
base = json.load(open(src))
assert base["format"] == "bran-artifact/4", base["format"]
A = base["artifact"]
assert A["id_scheme"] == SCHEME
assert root_hash(A) == A["root_hash"], "python root hash does not reproduce the dump"
bad = [c["id"] for c in A["contributions"] if content_id(c) != c["id"]]
assert not bad, f"python content id does not reproduce {len(bad)} ids"
print(f"python reproduces root_hash {A['root_hash']} and all {len(A['contributions'])} content ids")

cases = []


def case(name, expect, desc, fn):
    f = copy.deepcopy(base)
    fn(f)
    json.dump(f, open(out / f"{name}.json", "w"), indent=1, ensure_ascii=False)
    cases.append((name, expect, desc))


def reseal(f):
    f["artifact"]["root_hash"] = root_hash(f["artifact"])


def c0(f):
    return f["artifact"]["contributions"][0]


def claim_unsealed(f):
    c0(f)["canonical_form"]["object"] += "x"


def claim_kept_id(f):
    c0(f)["canonical_form"]["object"] += "x"
    reseal(f)
    assert content_id(c0(f)) != c0(f)["id"]


def claim_new_id(f):
    c = c0(f)
    old = c["id"]
    c["canonical_form"]["object"] += "x"
    c["id"] = content_id(c)
    # the id is also referenced by labels; keep labels consistent
    if old in f.get("labels", {}):
        f["labels"][c["id"]] = f["labels"].pop(old)
    reseal(f)


def synthesis(f):
    c = c0(f)
    old = c["id"]
    c["kind"] = "SYNTHESIS"
    c["id"] = content_id(c)
    if old in f.get("labels", {}):
        f["labels"][c["id"]] = f["labels"].pop(old)
    reseal(f)


def policy(f):
    f["policy"]["deadband_threshold"] = 501


def seq(f):
    c0(f)["seq"] += 1000


def winner(f):
    # first contested selection: stored winner replaced by another member
    for s in f["outputs"]["selections"]:
        others = [m for m in s.get("members", []) if m != s.get("winner")]
        if s.get("winner") is not None and others:
            s["winner"] = others[0]
            return
    raise SystemExit("no contested selection found")


def scheme_strip(f):
    del f["artifact"]["id_scheme"]
    f["format"] = "bran-artifact/2"


def retag(f):
    f["format"] = "bran-artifact/2"


case("claim-edit-unsealed", 3, "contributions[0].canonical_form.object += 'x'; id and root_hash kept (root hash mismatch)", claim_unsealed)
case("claim-edit-resealed-kept-id", 3, "same edit, root_hash recomputed, id kept (content id mismatch; new /4 check)", claim_kept_id)
case("synthesis-in-set", 3, "contributions[0].kind = SYNTHESIS, id = its content id, root_hash recomputed (SYNTHESIS sealed in a /4 set)", synthesis)
case("claim-edit-resealed-new-id", 1, "same edit, id = new content id, root_hash recomputed; outputs not recomputed (output tuples differ)", claim_new_id)
case("policy-deadband-501", 4, "policy.deadband_threshold 500 -> 501, policy_hash kept (POLICY MISMATCH)", policy)
case("seq-plus-1000", 3, "contributions[0].seq += 1000, root_hash kept (root hash mismatch)", seq)
case("winner-swap", 1, "first contested selection's stored winner swapped (output tuples differ)", winner)
case("scheme-strip-v2-tag", 3, "artifact.id_scheme removed and format retagged bran-artifact/2, root_hash kept (root hash mismatch)", scheme_strip)
case("format-retag-only", 1, "format retagged bran-artifact/2, id_scheme kept (unsupported format)", retag)

with open(out / "expected.tsv", "w") as fh:
    for n, e, d in cases:
        fh.write(f"{n}\t{e}\t{d}\n")
print(f"wrote {len(cases)} cases to {out}")
