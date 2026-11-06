"""Five agents disagree on a fact; overturn picks a winner, seals the decision,
and anyone can replay it later.

    OVERTURN_BIN=/path/to/overturn python examples/quickstart.py   # or a platform wheel
"""
import copy

from overturn_arbiter import Policy, seal, verify
from overturn_arbiter.adapters import answers_to_contributions, summarize

question = "What is the capital of Australia?"
answers = {
    "llama":   {"answer": "Canberra", "citations": ["https://en.wikipedia.org/wiki/Canberra"], "confidence": 0.8},
    "mistral": {"answer": "Sydney", "confidence": 0.9},
    "gemma":   {"answer": "canberra.", "citations": ["https://www.aph.gov.au/About_Parliament"], "confidence": 0.7},
    "phi":     {"answer": "Melbourne", "confidence": 0.6},
    "qwen":    {"answer": "Sydney", "confidence": 0.5},
}

contributions = answers_to_contributions(question, answers)
artifact = seal(contributions, Policy.order_free(), intent=question)  # arbitrate + package for replay
decision = artifact.decision
result = summarize(question, decision)

print(f"winner:      {result.winner_text!r} (agent {result.winner_agent}; agreeing: {', '.join(result.agreeing_agents)})")
print(f"deadband:    {result.in_deadband}")
print(f"certificate: {decision.certificate}  policy={decision.policy_hash}  root={decision.root_hash}")
for cid, score in decision.slots[0].scores.items():
    c = decision.contributions[cid]
    print(f"  {score:.4f}  {c.agent_id:8s} {c.raw_text}")
for r in decision.rejected:
    print(f"  rejected {r.agent_id}: {r.reason}")

artifact.save("decision.overturn.json")
print("verify:", verify("decision.overturn.json").message)

tampered = copy.deepcopy(dict(artifact.data))
tampered["artifact"]["contributions"][0]["confidence"] = 0.99
bad = verify(tampered)
print(f"verify tampered: ok={bad.ok} reason={bad.reason}")
