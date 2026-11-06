"""Reduction policy, as an overlay on the reducer's built-in default.

Every field left as ``None`` keeps the Rust default, so ``Policy()``
hashes to the Rust default policy hash. A set field replaces that policy
field wholesale (same semantics as the ``policy`` key of ``--reduce``).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

#: Rust ``OverturnCompiler::with_weights`` default weights: (ev, conf, cs, rec, ca).
DEFAULT_WEIGHTS: Tuple[float, float, float, float, float] = (0.35, 0.20, 0.25, 0.05, 0.15)
#: Schulze dimension bitmask with every dimension voting (Rust default).
SCHULZE_DIMS_ALL = 0b11111
#: Every Schulze dimension except recency (bit 3).
SCHULZE_DIMS_NO_RECENCY = 0b10111
#: ``values`` with no value-incompatibility groups (the ``generic`` preset).
NO_VALUE_GROUPS: Mapping[str, Any] = {"incompatible_values": {}}
#: Values of ``evidence.overturn_gate`` (Rust ``OverturnGate``). ``"none"`` is the
#: default and is never hashed; ``"verified"`` is the verify-then-vote gate
#: (repository ``v3/GATE_SPEC.md``).
OVERTURN_GATES: Tuple[str, ...] = ("none", "verified")
EVIDENCE_POLICY_FORMAT = "bran-evidence-policy/1"


@dataclass(frozen=True)
class Policy:
    weights: Optional[Sequence[float]] = None
    deadband_threshold: Optional[int] = None  # quantized units, 500 = 0.05
    schulze_dim_epsilon: Optional[int] = None
    max_severity_budget: Optional[float] = None
    schulze_dims: Optional[int] = None  # bitmask over (ev, conf, cs, rec, ca)
    tiebreak: Optional[str] = None  # "schulze" | "score_then_canonical"
    tiebreak_order: Optional[str] = None  # "seq" | "id"
    candidate_mode: Optional[str] = None  # experimental
    hardening: Optional[Mapping[str, Any]] = None
    #: ``{"incompatible_values": {predicate: {group: [objects]}}}``
    values: Optional[Mapping[str, Any]] = None
    #: ``bran-evidence-policy/1`` object
    evidence: Optional[Mapping[str, Any]] = None
    #: Extra FUNCTIONAL predicates (one slot per (subject, predicate)),
    #: extending the reducer's built-in list.
    functional_predicates: Optional[Sequence[str]] = None
    #: Any further top-level policy keys (the reducer rejects unknown ones).
    extra: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def rust_default(cls) -> "Policy":
        """The reducer's built-in default (arrival order can break ties)."""
        return cls()

    @classmethod
    def order_free(cls) -> "Policy":
        """The paper's recommended preset: recency weight 0, recency removed
        from the Schulze voters, residual ties broken by content id. With
        these three set, the winner does not depend on arrival order."""
        w = list(DEFAULT_WEIGHTS)
        w[3] = 0.0
        return cls(weights=tuple(w), schulze_dims=SCHULZE_DIMS_NO_RECENCY, tiebreak_order="id")

    @classmethod
    def generic(cls, order_free: bool = False) -> "Policy":
        """The reducer default without the TCP demo's
        ``values.incompatible_values`` groups (Rust ``--preset generic``):
        the recommended base for external use. With ``order_free``, also
        apply the three ``order_free()`` settings."""
        base = cls.order_free() if order_free else cls()
        return replace(base, values=dict(NO_VALUE_GROUPS))

    @classmethod
    def verify_then_vote(cls, accepted_checkers: Sequence[str], *, not_enough_info: float = 0.5,
                         unchecked_factor: float = 0.5, base: Optional["Policy"] = None) -> "Policy":
        """Verified-overturn gate ("verify, then vote"): in each contradiction
        slot the plurality value (by distinct agents) is the default winner,
        and another value can win only if one of its contributions carries a
        ``supports`` label from a checker in ``accepted_checkers``; among the
        verified values the policy score decides. Sets ``evidence`` on
        ``base`` (default ``Policy.generic(order_free=True)``) with
        ``overturn_gate = "verified"``; ``not_enough_info = 0`` is allowed."""
        b = base if base is not None else cls.generic(order_free=True)
        ev: Dict[str, Any] = dict(_plain(b.evidence)) if b.evidence is not None else {}
        ev.update({"format": EVIDENCE_POLICY_FORMAT,
                   "accepted_checkers": sorted({str(c) for c in accepted_checkers}),
                   "unchecked_factor": float(unchecked_factor),
                   "support_factor": {"supports": 1.0, "not_enough_info": float(not_enough_info),
                                      "refutes": 0.0},
                   "overturn_gate": "verified"})
        return replace(b, evidence=ev)

    def overlay(self) -> Dict[str, Any]:
        """The ``policy`` object sent to ``--reduce`` (only set fields)."""
        out: Dict[str, Any] = {}
        for name in ("deadband_threshold", "schulze_dim_epsilon", "schulze_dims",
                     "tiebreak", "tiebreak_order", "candidate_mode"):
            v = getattr(self, name)
            if v is not None:
                out[name] = v
        if self.weights is not None:
            if len(self.weights) != 5:
                raise ValueError("weights must have 5 entries: ev, conf, cs, rec, ca")
            out["weights"] = [float(x) for x in self.weights]
        if self.max_severity_budget is not None:
            out["max_severity_budget"] = float(self.max_severity_budget)
        if self.functional_predicates is not None:
            out["functional_predicates"] = [str(p) for p in self.functional_predicates]
        gate = (self.evidence or {}).get("overturn_gate")
        if gate is not None and gate not in OVERTURN_GATES:
            raise ValueError(f"evidence.overturn_gate must be one of {OVERTURN_GATES}, got {gate!r}")
        for name in ("hardening", "values", "evidence"):
            v = getattr(self, name)
            if v is not None:
                out[name] = _plain(v)
        for k, v in self.extra.items():
            if k in out:
                raise ValueError(f"policy field {k!r} given twice")
            out[k] = _plain(v)
        return out


def _plain(v: Any) -> Any:
    if isinstance(v, Mapping):
        return {str(k): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v
