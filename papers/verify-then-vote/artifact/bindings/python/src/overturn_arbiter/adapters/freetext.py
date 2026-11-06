"""Framework-free helper: plain answer strings (+ optional citations) to
contributions that compete for one slot."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

from ..api import arbitrate
from ..backend import Backend
from ..policy import Policy
from ..types import (Claim, Contribution, Decision, Evidence, EvidenceType,
                     LoweringConfidence)

#: A functional predicate in the Rust reducer: one slot per subject, so
#: different answers to the same question contradict each other.
ANSWER_PREDICATE = "is"


@dataclass(frozen=True)
class Answer:
    agent_id: str
    text: str
    citations: Tuple[str, ...] = ()
    confidence: float = 0.5
    seq: Optional[int] = None


AnswerLike = Union[Answer, str, Mapping[str, Any]]


def normalize(text: str) -> str:
    """Collapse whitespace, lowercase, drop trailing sentence punctuation."""
    return re.sub(r"[\s.!;]+$", "", " ".join(text.split()).lower())


def _coerce(agent_id: Optional[str], a: AnswerLike) -> Answer:
    if isinstance(a, Answer):
        return a
    if isinstance(a, str):
        if agent_id is None:
            raise ValueError("a bare answer string needs an agent id (pass a mapping)")
        return Answer(agent_id, a)
    d = dict(a)
    aid = d.get("agent_id", agent_id)
    if aid is None:
        raise ValueError(f"answer without agent_id: {d!r}")
    text = d.get("answer", d.get("text"))
    if text is None:
        raise ValueError(f"answer without text: {d!r}")
    return Answer(str(aid), str(text), tuple(d.get("citations", ()) or ()),
                  float(d.get("confidence", 0.5)), d.get("seq"))


def answers_to_contributions(question: str,
                             answers: Union[Mapping[str, AnswerLike], Iterable[AnswerLike]], *,
                             citation_weight: float = 0.5,
                             lowering_confidence: LoweringConfidence = LoweringConfidence.MEDIUM,
                             ) -> List[Contribution]:
    """One contribution per answer, all in the slot (question, ``is``).

    ``answers`` is a mapping ``agent_id -> text | Answer | dict`` or a
    sequence of ``Answer`` / dicts with ``agent_id``, ``answer`` (or
    ``text``), optional ``citations`` and ``confidence``. Each citation
    becomes a ``CITATION`` evidence item. The claim object is the
    normalized answer, so answers differing only in case or whitespace
    corroborate rather than contradict; ``raw_text`` keeps the original.
    """
    items = ([_coerce(k, v) for k, v in answers.items()] if isinstance(answers, Mapping)
             else [_coerce(None, a) for a in answers])
    subject = " ".join(question.split()).lower()
    return [Contribution(
        agent_id=a.agent_id,
        claim=Claim(subject, ANSWER_PREDICATE, normalize(a.text)),
        confidence=a.confidence,
        lowering_confidence=lowering_confidence,
        evidence=tuple(Evidence(EvidenceType.CITATION, src, citation_weight) for src in a.citations),
        raw_text=a.text.strip(),
        seq=a.seq,
    ) for a in items]


@dataclass(frozen=True)
class AnswerDecision:
    question: str
    winner_text: Optional[str]
    winner_agent: Optional[str]
    #: agents whose normalized answer equals the winner's
    agreeing_agents: Tuple[str, ...]
    in_deadband: bool
    decision: Decision

    def to_dict(self) -> dict:
        return {"question": self.question, "winner_text": self.winner_text,
                "winner_agent": self.winner_agent, "agreeing_agents": list(self.agreeing_agents),
                "in_deadband": self.in_deadband, "certificate": self.decision.certificate,
                "policy_hash": self.decision.policy_hash, "root_hash": self.decision.root_hash,
                "decision": self.decision.to_dict()}


def arbitrate_answers(question: str, answers: Union[Mapping[str, AnswerLike], Iterable[AnswerLike]],
                      policy: Optional[Policy] = None, *, backend: Optional[Backend] = None,
                      calibration: Optional[Mapping[str, float]] = None,
                      **kwargs: Any) -> AnswerDecision:
    """``answers_to_contributions`` then ``arbitrate`` (order-free by default)."""
    contribs = answers_to_contributions(question, answers, **kwargs)
    d = arbitrate(contribs, policy, intent=question, calibration=calibration, backend=backend)
    return summarize(question, d)


def summarize(question: str, d: Decision) -> AnswerDecision:
    w = d.winner() if len(d.slots) == 1 else None
    if not d.slots and d.admitted:  # all answers agree: no conflict slot
        w = d.contributions.get(d.admitted[0])
    agreeing: Sequence[str] = ()
    if w is not None and w.claim is not None:
        agreeing = sorted({c.agent_id for c in d.contributions.values()
                           if c.claim is not None and c.claim.object == w.claim.object})
    return AnswerDecision(question, w.raw_text if w else None, w.agent_id if w else None,
                          tuple(agreeing), d.in_deadband() if len(d.slots) == 1 else False, d)
