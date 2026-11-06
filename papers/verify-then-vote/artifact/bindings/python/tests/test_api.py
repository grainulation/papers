from __future__ import annotations

import copy
import json
import random
from dataclasses import replace
from typing import Any, Dict, List

import pytest

import overturn_arbiter as b
from overturn_arbiter import (Claim, Contribution, Evidence, EvidenceType, Kind, LoweringConfidence,
                          Policy, arbitrate, policy_hash, seal, verify)

Q = "capital of australia"


def contribs(seqs: bool = True) -> List[Contribution]:
    rows = [("a1", "Canberra", 0.8, [("CITATION", "https://en.wikipedia.org/wiki/Canberra", 0.9)]),
            ("a2", "Sydney", 0.9, []),
            ("a3", "Canberra", 0.6, [("AUTHORITY", "Australian Parliament", 0.7)]),
            ("a4", "Melbourne", 0.7, [("REASONING", "former capital", 0.3)]),
            ("a5", "Sydney", 0.5, [])]
    out = []
    for i, (agent, obj, conf, ev) in enumerate(rows):
        out.append(Contribution(
            agent_id=agent, claim=Claim("australia", "has_capital", obj), confidence=conf,
            lowering_confidence=LoweringConfidence.HIGH,
            evidence=tuple(Evidence(EvidenceType(t), s, w) for t, s, w in ev),
            raw_text=f"The capital of Australia is {obj}.", seq=i if seqs else None))
    return out


def test_default_policy_hash_matches_rust() -> None:
    assert policy_hash() == b.RUST_DEFAULT_POLICY_HASH == "dd8d36e6def3a6d598765e82d461a473"
    assert policy_hash(Policy()) == b.RUST_DEFAULT_POLICY_HASH
    assert arbitrate(contribs(), Policy.rust_default()).policy_hash == b.RUST_DEFAULT_POLICY_HASH


def test_order_free_preset_differs_and_generic_order_free_is_default() -> None:
    of = policy_hash(Policy.order_free())
    assert of != b.RUST_DEFAULT_POLICY_HASH
    assert arbitrate(contribs()).policy_hash == policy_hash(Policy.generic(order_free=True))
    assert Policy.order_free().overlay() == {
        "weights": [0.35, 0.2, 0.25, 0.0, 0.15], "schulze_dims": 23, "tiebreak_order": "id"}


def test_decision_shape() -> None:
    d = arbitrate(contribs(), intent=Q)
    assert len(d.slots) == 1 and d.slots[0].type == "CONTRADICTION"
    w = d.winner()
    assert w is not None and w.claim is not None and w.id in d.admitted
    assert set(d.slots[0].scores_q) == set(d.slots[0].members)
    assert len(d.certificate) == 16 and len(d.root_hash) == 32
    for r in d.rejected:
        assert r.reason in {"lost_slot", "same_value_as_winner"} and r.slot == d.slots[0].slot


def test_round_trip_determinism() -> None:
    a = arbitrate(contribs(), intent=Q)
    for _ in range(3):
        assert arbitrate(contribs(), intent=Q).to_json() == a.to_json()
    json.loads(a.to_json())  # valid JSON


def test_permutation_invariance_fixed_seq() -> None:
    """Shuffling the input list (seq kept) never changes the decision bytes."""
    base = arbitrate(contribs(), Policy.rust_default(), intent=Q).to_json()
    rng = random.Random(7)
    for _ in range(5):
        cs = contribs()
        rng.shuffle(cs)
        assert arbitrate(cs, Policy.rust_default(), intent=Q).to_json() == base


def test_permutation_invariance_order_free() -> None:
    """Under the order-free preset, re-deriving seq from a shuffled order keeps
    the winner and every score (the root hash and certificate change, since
    seq is sealed)."""
    base = arbitrate(contribs(seqs=False), intent=Q)
    rng = random.Random(11)
    for _ in range(5):
        cs = contribs(seqs=False)
        rng.shuffle(cs)
        d = arbitrate(cs, intent=Q)
        assert d.slots[0].winner == base.slots[0].winner
        assert d.slots[0].scores_q == base.slots[0].scores_q
        assert sorted(d.admitted) == sorted(base.admitted)


def test_p3_rejections_have_reasons() -> None:
    cs = contribs() + [
        Contribution("a6", None, 0.9, raw_text="no claim", seq=10),
        Contribution("a7", Claim("australia", "has_capital", "Perth"), 0.9, kind=Kind.SYNTHESIS, seq=11),
        contribs()[0],  # exact duplicate -> same content id
    ]
    d = arbitrate(cs, intent=Q)
    reasons = {r.agent_id: r.reason for r in d.rejected}
    assert reasons["a6"] == "no_canonical_form"
    assert reasons["a7"] == "synthesis_out_of_scope"
    assert "duplicate_id" in {r.reason for r in d.rejected}


def test_seal_and_verify() -> None:
    art = seal(contribs(), intent=Q)
    assert art.format == "bran-artifact/4"
    assert art.decision is not None and art.certificate == art.decision.certificate
    res = verify(art)
    assert res.ok and res.reason is None and res.certificate == art.certificate
    # same inputs -> byte-identical artifact
    assert seal(contribs(), intent=Q).to_json() == art.to_json()


def test_seal_save_load(tmp_path: Any) -> None:
    art = seal(contribs(), intent=Q)
    p = tmp_path / "a.json"
    art.save(p)
    assert verify(p).ok
    assert verify(b.Artifact.load(p)).ok


def _tampered(art: b.Artifact) -> Dict[str, Any]:
    return copy.deepcopy(dict(art.data))


def test_tamper_input_fails() -> None:
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    t["artifact"]["contributions"][1]["confidence"] = 0.99
    res = verify(t)
    assert not res.ok and res.reason == "artifact_hash" and res.exit_code == 3


def test_tamper_policy_fails() -> None:
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    t["policy"]["weights"] = [1.0, 0.0, 0.0, 0.0, 0.0]
    res = verify(t)
    assert not res.ok and res.reason == "policy_hash" and res.exit_code == 4


def test_tamper_output_fails() -> None:
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    sel = t["outputs"]["selections"][0]
    loser = next(m for m in sel["members"] if m != sel["winner"])
    sel["winner"] = loser
    res = verify(t)
    assert not res.ok and res.reason == "output" and res.exit_code == 1


def test_tamper_claim_with_rehash_fails_on_content_id() -> None:
    """Edit a claim and keep its id: even a recomputed root hash cannot hide it."""
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    t["artifact"]["contributions"][0]["canonical_form"]["object"] = "Perth"
    res = verify(t)
    assert not res.ok and res.reason == "artifact_hash"


def test_verify_garbage() -> None:
    res = verify({"format": "nope"})
    assert not res.ok and res.reason == "parse"


def test_content_ids_false_requires_ids() -> None:
    with pytest.raises(ValueError):
        arbitrate(contribs(), content_ids=False)
    cs = [c.with_(id=f"id{i}") for i, c in enumerate(contribs())]
    d = arbitrate(cs, content_ids=False)
    assert set(d.contributions) == {f"id{i}" for i in range(5)}
    assert verify(seal(cs, content_ids=False)).ok


def test_bad_policy_raises() -> None:
    with pytest.raises(b.OverturnError):
        arbitrate(contribs(), Policy(extra={"not_a_field": 1}))


# ── Reducer CLI features used by the package ──


def test_generic_preset_matches_rust_preset() -> None:
    be = b.SubprocessBackend()
    assert policy_hash(Policy.generic()) == b.GENERIC_POLICY_HASH
    assert be.print_policy({"values": {"incompatible_values": {}}})["policy_hash"] == b.GENERIC_POLICY_HASH
    assert policy_hash(Policy.generic(order_free=True)) not in {b.GENERIC_POLICY_HASH, b.RUST_DEFAULT_POLICY_HASH}
    assert verify(seal(contribs(), Policy.generic(order_free=True), intent=Q)).ok


def test_functional_predicates_policy_field() -> None:
    cs = [c.with_(claim=Claim("australia", "capital_city", c.claim.object)) for c in contribs() if c.claim]
    # Non-functional by default: values never compete (only redundant copies group).
    assert all(s.type == "REDUNDANCY" for s in arbitrate(cs).slots)
    d = arbitrate(cs, Policy(functional_predicates=["capital_city"]))
    assert [(s.slot, s.type) for s in d.slots] == [("(australia, capital_city)", "CONTRADICTION")]
    assert policy_hash(Policy(functional_predicates=["is"])) == b.RUST_DEFAULT_POLICY_HASH


def test_check_reducer_and_version() -> None:
    v = b.check_reducer()
    assert v["reducer_constants_id"] == b.REDUCER_CONSTANTS_ID
    assert v["presets"]["default"] == b.RUST_DEFAULT_POLICY_HASH
    assert v["presets"]["generic"] == b.GENERIC_POLICY_HASH


def test_sealed_artifact_comes_from_reducer() -> None:
    art = seal(contribs(), intent=Q, topic="capitals")
    assert art.data["topic"] == "capitals" and art.data["agents"] == 5 and art.data["seed"] == 0
    assert isinstance(art.data["envelope_hash"], str) and len(art.data["envelope_hash"]) == 32
    assert "p3_rejected" not in art.data["outputs"]
    assert art.data["policy"] == b.SubprocessBackend().print_policy(Policy.generic(order_free=True).overlay())["policy"]


def test_tamper_metadata_fails_on_envelope() -> None:
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    t["topic"] = "something else"
    res = verify(t)
    assert not res.ok and res.reason == "envelope" and res.exit_code == 6


def test_format_retag_fails_on_format() -> None:
    art = seal(contribs(), intent=Q)
    t = _tampered(art)
    t["format"] = "bran-artifact/2"
    res = verify(t)
    assert not res.ok and res.reason == "format" and res.exit_code == 5
    assert "does not match content" in res.message


def test_verify_then_vote_policy() -> None:
    pol = Policy.verify_then_vote(["ck2", "ck1"], not_enough_info=0.0)
    ev = pol.overlay()["evidence"]
    assert ev["overturn_gate"] == "verified" and ev["accepted_checkers"] == ["ck1", "ck2"]
    assert ev["support_factor"]["not_enough_info"] == 0.0
    ev_none: Dict[str, Any] = {**ev, "overturn_gate": "none"}
    off = replace(pol, evidence=ev_none)
    gated_h, none_h = policy_hash(pol), policy_hash(off)
    assert gated_h != none_h
    no_key = replace(pol, evidence={k: v for k, v in ev.items() if k != "overturn_gate"})
    assert policy_hash(no_key) == none_h          # "none" is never hashed
    with pytest.raises(ValueError):
        Policy(evidence={"overturn_gate": "majority"}).overlay()


def test_verify_then_vote_without_labels_is_plurality() -> None:
    # No support labels: the gate falls back to the plurality values (Canberra, Sydney:
    # two agents each); Melbourne (one agent) cannot win whatever its score.
    pol = replace(Policy.verify_then_vote(["ck"]), functional_predicates=["has_capital"])
    d = arbitrate(contribs(), pol, intent=Q)
    (s,) = [s for s in d.slots if s.type == "CONTRADICTION"]
    assert s.gate is not None and s.gate["stage"] == "plurality" and s.gate["witnesses"] == []
    assert s.gate["plurality_agents"] == 2 and not s.gate["overturned"]
    winner = d.contributions[s.winner].claim.object  # type: ignore[union-attr,index]
    assert winner in {"Canberra", "Sydney"}
    assert all(d.contributions[m].claim.object != "Melbourne" for m in s.gate["candidates"])  # type: ignore[union-attr]
    assert "gate" in s.to_dict()
    assert verify(seal(contribs(), pol, intent=Q)).ok
    ungated = arbitrate(contribs(), Policy(functional_predicates=["has_capital"]), intent=Q)
    assert all(x.gate is None and "gate" not in x.to_dict() for x in ungated.slots)

