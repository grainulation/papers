"""arbitrate / seal / verify."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from .backend import Backend, OverturnError, default_backend
from .policy import Policy
from .types import (Contribution, Decision, Rejection, SlotDecision, VerifyResult,
                    canonical_json)

CONTRIBUTION_ID_SCHEME = "bran-contribution-id/1"
#: ``overturn --version`` ``reducer_constants_id`` of the reducer this release targets.
REDUCER_CONSTANTS_ID = "456de373bb8a3775c9e7c8755dcbc264"


def _request(contributions: Sequence[Contribution], policy: Policy, intent: str,
             criteria: Sequence[str], calibration: Optional[Mapping[str, float]],
             evidence_store: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    req: Dict[str, Any] = {
        "intent": intent,
        "criteria": list(criteria),
        "calibration": {str(k): float(v) for k, v in (calibration or {}).items()},
        "contributions": [c.to_wire(c.seq if c.seq is not None else i)
                          for i, c in enumerate(contributions)],
    }
    overlay = policy.overlay()
    if overlay:
        req["policy"] = overlay
    if evidence_store:
        req["evidence_store"] = json.loads(json.dumps(evidence_store))
    return req


def _prepare(contributions: Iterable[Contribution], policy: Optional[Policy], intent: str,
             criteria: Sequence[str], calibration: Optional[Mapping[str, float]],
             evidence_store: Optional[Mapping[str, Any]], content_ids: bool,
             backend: Optional[Backend]) -> Tuple[Backend, Dict[str, Any]]:
    be = backend or default_backend()
    contributions = list(contributions)
    pol = policy if policy is not None else Policy.generic(order_free=True)
    req = _request(contributions, pol, intent, criteria, calibration, evidence_store)
    if content_ids:
        req = be.assign_ids(req)
    else:
        missing = [i for i, c in enumerate(req["contributions"]) if not c["id"]]
        if missing:
            raise ValueError(f"content_ids=False needs an id on every contribution (missing at {missing})")
    return be, req


def _norm(o: str) -> str:
    return " ".join(o.split()).lower()  # ir.rs normalize_object


def _same_value(a: Contribution, b: Contribution) -> bool:
    return (a.claim is not None and b.claim is not None and a.claim.polarity == b.claim.polarity
            and _norm(a.claim.object) == _norm(b.claim.object))


def _decision(req: Dict[str, Any], out: Dict[str, Any]) -> Decision:
    contribs: Dict[str, Contribution] = {}
    for w in sorted(req["contributions"], key=lambda w: (w["seq"], w["id"])):
        contribs.setdefault(w["id"], Contribution.from_wire(w))
    slots = tuple(SlotDecision(
        slot=s["slot"], slot_id=s.get("slot_id"), type=s["type"], members=tuple(s["members"]),
        winner=s.get("winner"), schulze_winner=s.get("schulze_winner"),
        in_deadband=bool(s["in_deadband"]), scores_q=dict(sorted(s["scores_q"].items())),
        gate=s.get("gate"),
    ) for s in out["selections"])
    lost: Dict[str, str] = {}
    for s in slots:
        for m in s.members:
            if m != s.winner:
                lost.setdefault(m, s.slot)
    agent = {w["id"]: w["agent_id"] for w in req["contributions"]}
    rejected: List[Rejection] = [Rejection(r["id"], r["agent_id"], r["reason"])
                                 for r in out.get("p3_rejected", [])]
    winners = {s.slot: contribs.get(s.winner) for s in slots if s.winner}
    for rid in out["rejected"]:
        reason = "not_admitted"
        if rid in lost:
            reason = "lost_slot"
            w, c = winners.get(lost[rid]), contribs.get(rid)
            if w is not None and c is not None and _same_value(w, c):
                reason = "same_value_as_winner"
        rejected.append(Rejection(rid, agent.get(rid, ""), reason, lost.get(rid)))
    return Decision(root_hash=out["root_hash"], policy_hash=out["policy_hash"],
                    certificate=out["certificate"], admitted=tuple(out["admitted"]),
                    rejected=tuple(rejected), slots=slots, contributions=contribs, raw=out)


def arbitrate(contributions: Iterable[Contribution], policy: Optional[Policy] = None, *,
              intent: str = "", criteria: Sequence[str] = (),
              calibration: Optional[Mapping[str, float]] = None,
              evidence_store: Optional[Mapping[str, Any]] = None,
              content_ids: bool = True, backend: Optional[Backend] = None) -> Decision:
    """Reduce contributions to a winner per conflict slot.

    ``policy`` defaults to ``Policy.generic(order_free=True)`` (the paper's
    recommendation); pass ``Policy.rust_default()`` for the reducer's
    built-in default. ``calibration`` maps agent ids to a factor in [0, 1]
    (missing agents get 0.5). With ``content_ids`` (default) every
    contribution id is replaced by its ``bran-contribution-id/1`` content id.
    """
    be, req = _prepare(contributions, policy, intent, criteria, calibration, evidence_store,
                       content_ids, backend)
    return _decision(req, be.reduce(req))


def policy_hash(policy: Optional[Policy] = None, backend: Optional[Backend] = None) -> str:
    """The reducer's hash of ``policy`` (default: ``Policy.rust_default()``)."""
    be = backend or default_backend()
    pol = policy if policy is not None else Policy.rust_default()
    try:
        return str(be.print_policy(pol.overlay() or None)["policy_hash"])
    except NotImplementedError:
        req: Dict[str, Any] = {"contributions": []}
        if pol.overlay():
            req["policy"] = pol.overlay()
        return str(be.reduce(req)["policy_hash"])


def check_reducer(backend: Optional[Backend] = None) -> Dict[str, Any]:
    """Check the reducer is compatible with this package: its
    reducer-constants id (which every policy hash depends on) must equal
    ``REDUCER_CONSTANTS_ID`` and it must read ``bran-artifact/4``. Returns
    the ``--version`` object; raises ``OverturnError`` otherwise."""
    be = backend or default_backend()
    v = be.version()
    if v.get("reducer_constants_id") != REDUCER_CONSTANTS_ID:
        raise OverturnError(f"reducer constants id {v.get('reducer_constants_id')!r} != expected "
                        f"{REDUCER_CONSTANTS_ID!r}: policy hashes would differ from this package's")
    if "bran-artifact/4" not in v.get("artifact_formats", []):
        raise OverturnError(f"reducer does not read bran-artifact/4 (formats {v.get('artifact_formats')})")
    return v


# ── Artifacts ──────────────────────────────────────────────


@dataclass(frozen=True)
class Artifact:
    """A sealed, replayable record: the sealed input set, the full policy
    and its hash, and the decision. ``data`` is exactly the Rust
    ``bran-artifact/{2,3,4}`` file, so ``overturn --replay-from`` reads it too."""

    data: Mapping[str, Any]
    decision: Optional[Decision] = None

    @property
    def certificate(self) -> str:
        return self.data["outputs"]["certificate"]

    @property
    def format(self) -> str:
        return self.data["format"]

    def to_json(self) -> str:
        return canonical_json(self.data)

    def save(self, path: Union[str, Path]) -> None:
        Path(path).write_text(json.dumps(self.data, sort_keys=True, indent=1, ensure_ascii=False) + "\n",
                              encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path]) -> "Artifact":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    @classmethod
    def from_json(cls, text: str) -> "Artifact":
        return cls(json.loads(text))


def seal(contributions: Iterable[Contribution], policy: Optional[Policy] = None, *,
         intent: str = "", criteria: Sequence[str] = (),
         calibration: Optional[Mapping[str, float]] = None,
         evidence_store: Optional[Mapping[str, Any]] = None, content_ids: bool = True,
         topic: str = "external", backend: Optional[Backend] = None) -> Artifact:
    """``arbitrate`` and package the result as a replayable artifact.

    The reducer seals it (``--reduce --emit-artifact``): the sealed set
    exactly as reduced (P3 filter, calibration and evidence-store
    restriction), the full effective policy and its hash, the decision,
    and an ``envelope_hash`` over the unhashed metadata (``topic``,
    ``agents``, ``seed``, ``labels``). It is replayed once before it is
    returned; a mismatch raises ``OverturnError`` rather than handing back an
    unverifiable file.
    """
    be, req = _prepare(contributions, policy, intent, criteria, calibration, evidence_store,
                       content_ids, backend)
    out, data = be.seal(dict(req, topic=topic))
    check = be.replay(data)
    if not check.ok:
        raise OverturnError(f"sealed artifact failed its own replay ({check.reason}): {check.message}",
                        check.exit_code)
    return Artifact(data, _decision(req, out))


def verify(artifact: Union[Artifact, Mapping[str, Any], str, Path],
           backend: Optional[Backend] = None) -> VerifyResult:
    """Replay an artifact: check the root hash, content ids and evidence
    records, the policy hash, then re-reduce and compare the outputs."""
    be = backend or default_backend()
    if isinstance(artifact, Artifact):
        data: Any = artifact.data
    elif isinstance(artifact, Mapping):
        data = artifact
    else:
        try:
            data = json.loads(Path(artifact).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            return VerifyResult(False, "parse", 2, str(e))
    return be.replay(json.loads(json.dumps(data)))
