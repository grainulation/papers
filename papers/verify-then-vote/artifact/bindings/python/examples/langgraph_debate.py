"""A LangGraph fan-out: five agents answer in parallel, an overturn node arbitrates.

    pip install 'overturn-arbiter[langgraph]'
    python examples/langgraph_debate.py

The agents here are stubs; swap in LLM calls that return an answer string or
{"answer": ..., "citations": [...], "confidence": ...}. Parallel branches
finish in any order, so the node uses the order-free policy by default.
"""
from overturn_arbiter import verify
from overturn_arbiter.adapters import arbiter_node

AGENTS = {
    "llama":   lambda q: {"answer": "Canberra", "citations": ["https://en.wikipedia.org/wiki/Canberra"], "confidence": 0.8},
    "mistral": lambda q: {"answer": "Sydney", "confidence": 0.9},
    "gemma":   lambda q: {"answer": "Canberra", "citations": ["https://www.aph.gov.au/About_Parliament"], "confidence": 0.7},
    "phi":     lambda q: "Melbourne",
    "qwen":    lambda q: "Sydney",
}
QUESTION = "What is the capital of Australia?"

try:
    from overturn_arbiter.adapters import build_debate_graph

    graph = build_debate_graph(AGENTS, include_artifact=True)
    state = graph.invoke({"question": QUESTION})
except ImportError:
    # No LangGraph installed: run the same node on a hand-built state.
    outputs = []
    for name, fn in AGENTS.items():
        out = fn(QUESTION)
        outputs.append({"agent_id": name, **(out if isinstance(out, dict) else {"answer": out})})
    state = {"question": QUESTION, "agent_outputs": outputs}
    state.update(arbiter_node(include_artifact=True)(state))

arb = state["arbitration"]
print(f"winner: {arb['winner_text']!r} from {arb['winner_agent']} (agreeing: {arb['agreeing_agents']})")
print(f"certificate: {arb['certificate']}  policy: {arb['policy_hash']}  deadband: {arb['in_deadband']}")
print("replay:", "PASS" if verify(arb["artifact"]) else "FAIL")
