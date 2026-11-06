"""Typed inputs and outputs. Stdlib dataclasses only.

Field names and enum values mirror the Rust `--reduce` schema
(`overturn/src/main.rs`, `run_reduce`), so `to_wire()` is a direct mapping.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple


class Polarity(str, Enum):
    AFFIRM = "AFFIRM"
    NEGATE = "NEGATE"


class Kind(str, Enum):
    ASSERTION = "ASSERTION"
    CRITIQUE = "CRITIQUE"
    SYNTHESIS = "SYNTHESIS"  # always rejected at P3 (out of scope for the reducer)


class LoweringConfidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EvidenceType(str, Enum):
    TOOL_RESULT = "TOOL_RESULT"
    EMPIRICAL = "EMPIRICAL"
    CITATION = "CITATION"
    AUTHORITY = "AUTHORITY"
    REASONING = "REASONING"


class Verification(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    REACHABILITY_CHECKED = "REACHABILITY_CHECKED"
    CONTENT_HASHED = "CONTENT_HASHED"
    CROSS_REFERENCED = "CROSS_REFERENCED"
    STALE = "STALE"


def canonical_json(value: Any) -> str:
    """Sorted keys, no whitespace, UTF-8 kept. Used for every JSON the
    package emits so equal values give equal bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass(frozen=True)
class Claim:
    """A canonical (subject, predicate, object) triple.

    Slot identity: functional predicates (a fixed list in the Rust
    reducer, e.g. ``is``, ``has``, ``has_capital``) give one slot per
    (subject, predicate), so different objects contradict each other.
    Other predicates give one slot per object unless the policy groups
    values as mutually exclusive (``Policy.values``).
    """

    subject: str
    predicate: str
    object: str
    polarity: Polarity = Polarity.AFFIRM

    def to_wire(self) -> Dict[str, Any]:
        return {"subject": self.subject, "predicate": self.predicate,
                "object": self.object, "polarity": Polarity(self.polarity).value}

    @classmethod
    def from_wire(cls, d: Mapping[str, Any]) -> "Claim":
        return cls(d["subject"], d["predicate"], d["object"], Polarity(d["polarity"]))


@dataclass(frozen=True)
class Evidence:
    type: EvidenceType
    source: str
    weight: float
    reachable: bool = True
    verification: Verification = Verification.UNVERIFIED
    capture_ref: Optional[str] = None
    support_ref: Optional[str] = None

    def to_wire(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"type": EvidenceType(self.type).value, "source": self.source,
                             "weight": float(self.weight), "reachable": bool(self.reachable),
                             "verification": Verification(self.verification).value}
        if self.capture_ref is not None:
            d["capture_ref"] = self.capture_ref
        if self.support_ref is not None:
            d["support_ref"] = self.support_ref
        return d

    @classmethod
    def from_wire(cls, d: Mapping[str, Any]) -> "Evidence":
        return cls(EvidenceType(d["type"]), d["source"], float(d["weight"]),
                   bool(d.get("reachable", True)), Verification(d.get("verification", "UNVERIFIED")),
                   d.get("capture_ref"), d.get("support_ref"))


@dataclass(frozen=True)
class Contribution:
    """One agent output, lowered to a claim.

    ``seq`` is the recorded arrival order. When ``None``, ``arbitrate``
    uses the contribution's position in the input list. Under the
    order-free policy (``Policy.order_free()``) seq does not affect which
    claim wins, though it is still sealed (it changes the root hash).

    ``id`` is filled in by the package (content id,
    ``bran-contribution-id/1``) unless ``arbitrate(..., content_ids=False)``.
    """

    agent_id: str
    claim: Optional[Claim]
    confidence: float
    lowering_confidence: LoweringConfidence = LoweringConfidence.MEDIUM
    evidence: Tuple[Evidence, ...] = ()
    raw_text: str = ""
    kind: Kind = Kind.ASSERTION
    seq: Optional[int] = None
    id: Optional[str] = None
    agent_name: str = ""

    def with_(self, **changes: Any) -> "Contribution":
        return replace(self, **changes)

    def to_wire(self, seq: int) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "agent_id": self.agent_id,
            "kind": Kind(self.kind).value,
            "canonical_form": self.claim.to_wire() if self.claim is not None else None,
            "confidence": float(self.confidence),
            "lowering_confidence": LoweringConfidence(self.lowering_confidence).value,
            "evidence": [e.to_wire() for e in self.evidence],
            "raw_text": self.raw_text,
            "seq": int(seq),
            "id": self.id if self.id is not None else "",
        }
        if self.agent_name:
            d["agent_name"] = self.agent_name
        return d

    @classmethod
    def from_wire(cls, d: Mapping[str, Any]) -> "Contribution":
        cf = d.get("canonical_form")
        return cls(
            agent_id=d["agent_id"], claim=Claim.from_wire(cf) if cf else None,
            confidence=float(d["confidence"]),
            lowering_confidence=LoweringConfidence(d["lowering_confidence"]),
            evidence=tuple(Evidence.from_wire(e) for e in d.get("evidence", [])),
            raw_text=d.get("raw_text", ""), kind=Kind(d["kind"]), seq=int(d["seq"]),
            id=d.get("id") or None, agent_name=d.get("agent_name", ""),
        )


@dataclass(frozen=True)
class SlotDecision:
    """One conflict slot: its members, the winner, and the quantized
    scores (integers on the reducer's 10,000-point scale) that decided it."""

    slot: str
    slot_id: Optional[str]
    type: str
    members: Tuple[str, ...]
    winner: Optional[str]
    schulze_winner: Optional[str]
    in_deadband: bool
    scores_q: Mapping[str, int]
    #: Verified-overturn gate trace (``evidence.overturn_gate = "verified"``):
    #: ``stage`` (``verified`` | ``plurality``), ``default_winner``,
    #: ``plurality_agents``, ``candidates``, ``witnesses``, ``overturned``.
    #: ``None`` when the slot is ungated.
    gate: Optional[Mapping[str, Any]] = None

    @property
    def scores(self) -> Dict[str, float]:
        return {k: v / 10_000 for k, v in self.scores_q.items()}

    def to_dict(self) -> Dict[str, Any]:
        d = {"slot": self.slot, "slot_id": self.slot_id, "type": self.type,
             "members": list(self.members), "winner": self.winner,
             "schulze_winner": self.schulze_winner, "in_deadband": self.in_deadband,
             "scores_q": dict(sorted(self.scores_q.items()))}
        if self.gate is not None:
            d["gate"] = dict(self.gate)
        return d


@dataclass(frozen=True)
class Rejection:
    """A contribution that was not admitted, and why.

    Reasons: ``synthesis_out_of_scope``, ``no_canonical_form``,
    ``duplicate_id`` (dropped at P3, never sealed); ``lost_slot`` (sealed,
    lost its conflict slot; ``slot`` names it); ``same_value_as_winner``
    (as ``lost_slot``, but it states the winner's value: the reducer admits
    one member per slot, so agreeing claims are not admitted twice);
    ``not_admitted`` (sealed,
    rejected by P6 outside any slot, e.g. a critique or a hardening rule).
    """

    id: str
    agent_id: str
    reason: str
    slot: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "agent_id": self.agent_id, "reason": self.reason, "slot": self.slot}


@dataclass(frozen=True)
class Decision:
    """The result of one arbitration. ``to_json()`` is a pure function of
    the sealed inputs and the policy: identical inputs give identical bytes."""

    root_hash: str
    policy_hash: str
    certificate: str
    admitted: Tuple[str, ...]
    rejected: Tuple[Rejection, ...]
    slots: Tuple[SlotDecision, ...]
    contributions: Mapping[str, Contribution] = field(compare=False, repr=False)
    raw: Mapping[str, Any] = field(compare=False, repr=False)

    def winner(self, slot: Optional[str] = None) -> Optional[Contribution]:
        """The winning contribution of ``slot`` (default: the only slot)."""
        s = self._slot(slot)
        return self.contributions.get(s.winner) if s and s.winner else None

    def in_deadband(self, slot: Optional[str] = None) -> bool:
        s = self._slot(slot)
        return bool(s and s.in_deadband)

    def _slot(self, slot: Optional[str]) -> Optional[SlotDecision]:
        if slot is None:
            if len(self.slots) > 1:
                raise ValueError(f"{len(self.slots)} slots; name one of {[s.slot for s in self.slots]}")
            return self.slots[0] if self.slots else None
        for s in self.slots:
            if s.slot == slot or s.slot_id == slot:
                return s
        raise KeyError(slot)

    def to_dict(self) -> Dict[str, Any]:
        return {"root_hash": self.root_hash, "policy_hash": self.policy_hash,
                "certificate": self.certificate, "admitted": list(self.admitted),
                "rejected": [r.to_dict() for r in self.rejected],
                "slots": [s.to_dict() for s in self.slots]}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())


@dataclass(frozen=True)
class VerifyResult:
    """Outcome of replaying an artifact under the bundled reducer.

    ``reason`` is ``None`` on success, else one of ``format`` (unknown
    format tag, or one that does not match the content; exit 5),
    ``artifact_hash`` (input or evidence record tampered, or a
    contribution id that is not its content id; exit 3), ``policy_hash``
    (policy edited, or a reducer with different constants; exit 4),
    ``output`` (stored decision differs from the replayed one; exit 1),
    ``envelope`` (``topic``/``agents``/``seed``/``labels`` or another
    unhashed field edited under an ``envelope_hash``; exit 6), ``parse``
    (not an artifact; exit 2).
    """

    ok: bool
    reason: Optional[str]
    exit_code: int
    message: str
    certificate: Optional[str] = None

    def __bool__(self) -> bool:
        return self.ok
