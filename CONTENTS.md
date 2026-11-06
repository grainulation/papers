# Paper map

Each entry gives the paper's abstract and links to its manuscript, source and artifact.

---

### [Verify, Then Vote: Overturning Wrong Majorities in Multi-Agent LLMs](papers/verify-then-vote/paper.pdf)

Grainulation · November 2026 · [supporting material](papers/verify-then-vote/supplement.pdf) · [source](papers/verify-then-vote/tex/) · [artifact](papers/verify-then-vote/artifact/) · [citation](papers/verify-then-vote/README.md#citation)

Checking agents' cited passages improves majority vote, but an accurate aggregate can still overturn correct answers. We study *verify, then vote*: a fixed plurality default may be overturned only by an answer whose passage an accepted checker labels as supporting it. On OVERTURN's 1,000 primary questions, the pre-specified scored rule raises accuracy from 77.1% to 85.0%; on 526 decisive conflicts, from 71.5% to 86.5%. It nevertheless misses its pre-specified harm criterion: the upper confidence bound on overturns of correct majorities is 5.5%, above the 5% ceiling. *Verified default first*, which keeps a verified default, was developed after this analysis and specified before a second agent pool answered the same questions, partly reusing checker labels. It reaches 85.9% on that pool's decisive conflicts, with a harm-rate upper bound of 2.2%. This tests transfer across agent pools, not generalization to unseen questions. Matched-parameter ablations isolate the gate's reduction in harmful overturns, and withholding or replacing cited passages removes most corrections. The formal property identifies an inspectable failure condition: losing a correct default requires a verified wrong answer; it does not establish that such answers are rare. A strong model judge is more accurate and initially cheaper (93.9% versus 86.5%; $0.014 versus $0.021 per contested primary decision). The benefit of verify-then-vote is an explicit selection policy over reusable evidence: all 1,100 benchmark decisions replay byte-identically, and leave-one-agent-out decisions reuse sealed labels without a model call.

*Contents:* Rust reducer, Lean 4 proofs, Python package `overturn-arbiter`, the OVERTURN benchmark and its preregistration, a pre-specified second-agent-pool evaluation on the same questions, a companion memory-only benchmark, and the sealed agent responses, captures, checker labels and judge decisions.
