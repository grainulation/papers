from __future__ import annotations

import operator
from typing import Any, Callable, Dict, List

import pytest

import overturn_arbiter as b
from overturn_arbiter.adapters import (Answer, answers_to_contributions, arbiter_node,
                                   arbitrate_answers, normalize)

Q = "What is the capital of Australia?"
OUTPUTS: List[Dict[str, Any]] = [
    {"agent_id": "planner", "answer": "Canberra", "citations": ["https://en.wikipedia.org/wiki/Canberra"],
     "confidence": 0.8},
    {"agent_id": "critic", "answer": "Sydney", "confidence": 0.9},
    {"agent_id": "researcher", "answer": "canberra.", "citations": ["https://www.aph.gov.au"],
     "confidence": 0.7},
    {"agent_id": "writer", "answer": "Melbourne", "confidence": 0.6},
    {"agent_id": "checker", "answer": "Sydney", "confidence": 0.5},
]


def test_normalize() -> None:
    assert normalize("  Canberra. ") == normalize("canberra") == "canberra"


def test_answers_to_contributions_forms() -> None:
    a = answers_to_contributions(Q, OUTPUTS)
    m = answers_to_contributions(Q, {o["agent_id"]: Answer(o["agent_id"], o["answer"],
                                                           tuple(o.get("citations", ())), o["confidence"])
                                     for o in OUTPUTS})
    assert a == m
    assert {c.claim.object for c in a if c.claim} == {"canberra", "sydney", "melbourne"}
    assert a[0].evidence[0].type == b.EvidenceType.CITATION
    s = answers_to_contributions(Q, {"x": "Perth"})
    assert s[0].agent_id == "x" and s[0].raw_text == "Perth"


def test_arbitrate_answers() -> None:
    r = arbitrate_answers(Q, OUTPUTS)
    assert r.winner_text is not None and r.winner_agent is not None
    assert r.winner_agent in r.agreeing_agents
    assert r.decision.certificate == r.to_dict()["certificate"]


def test_arbitrate_answers_all_agree() -> None:
    r = arbitrate_answers(Q, {"a": "Canberra", "b": "canberra"})
    assert r.winner_text is not None and normalize(r.winner_text) == "canberra"


def test_node_is_order_free() -> None:
    node = arbiter_node()
    first = node({"question": Q, "agent_outputs": OUTPUTS})["arbitration"]
    rev = node({"question": Q, "agent_outputs": list(reversed(OUTPUTS))})["arbitration"]
    assert first["winner_text"] == rev["winner_text"]
    assert first["decision"]["slots"][0]["scores_q"] == rev["decision"]["slots"][0]["scores_q"]
    assert first["policy_hash"] == b.policy_hash(b.Policy.generic(order_free=True))


def test_node_artifact_verifies() -> None:
    out = arbiter_node(include_artifact=True, result_key="r")({"question": Q, "agent_outputs": OUTPUTS})
    assert b.verify(out["r"]["artifact"]).ok


class FakeStateGraph:
    """The slice of langgraph.StateGraph the adapter relies on: nodes are
    callables state -> partial update; list fields merge with `+`."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def add_node(self, name: str, fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self.nodes[name] = fn

    def run(self, state: Dict[str, Any], agents: List[str]) -> Dict[str, Any]:
        for a in agents:  # fan-out, in the given (arbitrary) completion order
            upd = self.nodes[a](state)
            state = {**state, "agent_outputs": operator.add(state.get("agent_outputs", []), upd["agent_outputs"])}
        return {**state, **self.nodes["arbiter"](state)}


def test_adapter_with_fake_graph() -> None:
    g = FakeStateGraph()
    for o in OUTPUTS:
        g.add_node(o["agent_id"], lambda s, o=o: {"agent_outputs": [o]})
    g.add_node("arbiter", arbiter_node())
    names = [o["agent_id"] for o in OUTPUTS]
    a = g.run({"question": Q}, names)["arbitration"]
    z = g.run({"question": Q}, list(reversed(names)))["arbitration"]
    assert a["winner_text"] == z["winner_text"] and a["winner_text"] is not None


def test_real_langgraph() -> None:
    pytest.importorskip("langgraph")
    from overturn_arbiter.adapters import build_debate_graph

    agents = {o["agent_id"]: (lambda q, o=o: {k: v for k, v in o.items() if k != "agent_id"}) for o in OUTPUTS}
    graph = build_debate_graph(agents, include_artifact=True)
    res = graph.invoke({"question": Q})
    arb = res["arbitration"]
    assert arb["winner_text"] == arbitrate_answers(Q, OUTPUTS).winner_text
    assert len(res["agent_outputs"]) == len(OUTPUTS)
    assert b.verify(arb["artifact"]).ok
