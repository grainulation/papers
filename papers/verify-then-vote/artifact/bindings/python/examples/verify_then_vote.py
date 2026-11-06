"""Offline gate demonstration with explicitly synthetic passage/checker records.

These records illustrate the wire format, not a validated factual checker.
Production applications must obtain and validate their own capture/support labels.
"""
import hashlib
import json
from dataclasses import replace
from overturn_arbiter import Claim, Contribution, Evidence, EvidenceType, Policy, SubprocessBackend, seal, verify


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()[:32]


def run(accepted=True):
    text = 'The capital of Australia is Canberra.'
    sha = hashlib.sha256(text.encode()).hexdigest()
    url = 'corpus://demo/capital'
    capture = dict(format='bran-capture/1', requested=url, identifier_kind='corpus', request_url=url,
                   redirects=[], resolved_url=url, canonical_url=url, http_status=None,
                   content_type='text/plain', content_length=len(text.encode()), truncated=False,
                   content_sha256=sha, extraction=dict(method='corpus/1', method_version='1',
                   text_sha256=sha, text_chars=len(text)), outcome='ok',
                   robots=dict(checked=False, allowed=None, robots_sha256=None),
                   license_note='Synthetic example text, CC0', capture_tool_version='demo/1')
    cid = digest(capture)
    checker = dict(model='synthetic-demo-not-a-model', model_digest='demo/1',
                   prompt_template_sha256=sha, decoding=dict(temperature_x1000=0, top_k=1,
                   top_p_x1000=1000, num_ctx=1024, num_predict=64, seed=0),
                   checker_tool_version='demo/1')
    checker['checker_id'] = digest(checker)
    checker['ollama_version'] = 'not-used'
    contributions = [Contribution(agent, Claim('Australia', 'has_capital', answer), confidence=0.5,
                                  raw_text=f'The capital of Australia is {answer}.')
                     for agent, answer in [('a', 'Sydney'), ('b', 'Sydney'), ('c', 'Canberra')]]
    evidence = Evidence(EvidenceType.CITATION, url, 1.0, capture_ref=cid)
    contributions[2] = replace(contributions[2], evidence=(evidence,))
    # Support records name content IDs; support_ref itself is excluded from those IDs.
    request = SubprocessBackend().assign_ids({'contributions': [c.to_wire(i) for i, c in enumerate(contributions)]})
    claim = dict(subject='Australia', predicate='has_capital', object='Canberra', polarity='AFFIRM', raw_text=text)
    support = dict(format='bran-support/1', contribution_id=request['contributions'][2]['id'],
                   claim=claim, capture_id=cid, spans=[dict(start=0, end=len(text), text=text)],
                   span_selector=dict(method='bm25/1', version='1', params=dict(k1_x1000=1200,
                   b_x1000=750, chunk_chars=800, overlap_chars=200)), checker=checker,
                   status='ok', label='supports', score_q=10000, raw_output_sha256=sha)
    sid = digest(support)
    contributions[2] = replace(contributions[2], evidence=(replace(evidence, support_ref=sid),))
    policy = Policy.verify_then_vote([checker['checker_id']] if accepted else ['unaccepted-checker'])
    artifact = seal(contributions, policy, intent='What is the capital of Australia?',
                    evidence_store={'captures': {cid: capture}, 'support': {sid: support}})
    assert verify(artifact).ok  # Integrity/replay, not a guarantee of factual truth.
    slot = next(s for s in artifact.decision.slots if s.type == 'CONTRADICTION')
    winner = artifact.decision.contributions[slot.winner].claim.object
    assert winner == ('Canberra' if accepted else 'Sydney')
    assert bool(slot.gate['overturned']) == accepted
    return artifact


if __name__ == '__main__':
    run()
    run(accepted=False)
    print('PASS accepted support overturns; unaccepted support preserves majority; both replay')
