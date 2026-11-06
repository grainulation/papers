"""LangGraph adapter.

``arbiter_node`` needs no LangGraph import: it is a plain function from a
state mapping to a partial state update, which is what
``StateGraph.add_node`` expects. ``build_debate_graph`` wires a fan-out of
agent nodes into the arbiter and needs the ``[langgraph]`` extra.

Parallel fan-out makes arrival order nondeterministic, which is why the
node defaults to ``Policy.order_free()``: the winner then depends only on
what the agents said, not on which finished first.
"""
from __future__ import annotations

import operator
from typing import Any, Callable, Dict, List, Mapping, Optional

from ..api import seal
from ..backend import Backend
from ..policy import Policy
from .freetext import AnswerLike, answers_to_contributions, arbitrate_answers, summarize

State = Mapping[str, Any]


def arbiter_node(*, question_key: str = "question", outputs_key: str = "agent_outputs",
                 result_key: str = "arbitration", policy: Optional[Policy] = None,
                 include_artifact: bool = False, backend: Optional[Backend] = None,
                 ) -> Callable[[State], Dict[str, Any]]:
    """A node that arbitrates ``state[outputs_key]`` for ``state[question_key]``.

    ``state[outputs_key]`` is a list of dicts ``{"agent_id", "answer",
    "citations"?, "confidence"?}`` (or ``Answer``), or a mapping
    ``agent_id -> answer``. Returns ``{result_key: {...}}`` with the winner
    text and agent, agreeing agents, deadband flag, certificate, policy and
    root hashes, the full decision, and (``include_artifact``) the sealed
    artifact for later ``verify``.
    """

    def node(state: State) -> Dict[str, Any]:
        question = str(state[question_key])
        outputs: Any = state.get(outputs_key) or []
        if include_artifact:
            art = seal(answers_to_contributions(question, outputs), policy, intent=question,
                       backend=backend)
            assert art.decision is not None
            result = summarize(question, art.decision).to_dict()
            result["artifact"] = dict(art.data)
        else:
            result = arbitrate_answers(question, outputs, policy, backend=backend).to_dict()
        return {result_key: result}

    return node


AgentFn = Callable[[str], AnswerLike]


def build_debate_graph(agents: Mapping[str, AgentFn], *, policy: Optional[Policy] = None,
                       include_artifact: bool = False, backend: Optional[Backend] = None) -> Any:
    """Compile a LangGraph graph: START -> every agent (in parallel) ->
    arbiter -> END. Each agent function takes the question and returns an
    answer string, an ``Answer``, or a dict. Invoke with
    ``graph.invoke({"question": ...})``."""
    try:
        from typing import Annotated, TypedDict

        from langgraph.graph import END, START, StateGraph
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError("build_debate_graph needs `pip install overturn-arbiter[langgraph]`") from e

    # Functional form: the class form would be evaluated as strings
    # (`from __future__ import annotations`) outside this scope.
    DebateState = TypedDict("DebateState", {  # type: ignore[misc]
        "question": str,
        "agent_outputs": Annotated[List[Any], operator.add],
        "arbitration": Dict[str, Any],
    }, total=False)

    g = StateGraph(DebateState)

    def make(agent_id: str, fn: AgentFn) -> Callable[[State], Dict[str, Any]]:
        def run(state: State) -> Dict[str, Any]:
            out = fn(state["question"])
            if isinstance(out, str):
                out = {"agent_id": agent_id, "answer": out}
            elif isinstance(out, Mapping):
                out = {"agent_id": agent_id, **out}
            return {"agent_outputs": [out]}
        return run

    for name, fn in agents.items():
        g.add_node(name, make(name, fn))
        g.add_edge(START, name)
    g.add_node("arbiter", arbiter_node(policy=policy, include_artifact=include_artifact, backend=backend))
    g.add_edge(list(agents), "arbiter")
    g.add_edge("arbiter", END)
    return g.compile()
