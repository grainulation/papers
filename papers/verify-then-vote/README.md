# [Verify, Then Vote: Overturning Wrong Majorities in Multi-Agent LLMs](paper.pdf)

**Author:** Grainulation

**Manuscript date:** November 2026

**Status:** first public release in preparation.

## Abstract

Checking agents' cited passages improves majority vote, but an accurate aggregate can still overturn correct answers. We study *verify, then vote*: a fixed plurality default may be overturned only by an answer whose passage an accepted checker labels as supporting it. On OVERTURN's 1,000 primary questions, the pre-specified scored rule raises accuracy from 77.1% to 85.0%; on 526 decisive conflicts, from 71.5% to 86.5%. It nevertheless misses its pre-specified harm criterion: the upper confidence bound on overturns of correct majorities is 5.5%, above the 5% ceiling. *Verified default first*, which keeps a verified default, was developed after this analysis and specified before a second agent pool answered the same questions, partly reusing checker labels. It reaches 85.9% on that pool's decisive conflicts, with a harm-rate upper bound of 2.2%. This tests transfer across agent pools, not generalization to unseen questions. Matched-parameter ablations isolate the gate's reduction in harmful overturns, and withholding or replacing cited passages removes most corrections. The formal property identifies an inspectable failure condition: losing a correct default requires a verified wrong answer; it does not establish that such answers are rare. A strong model judge is more accurate and initially cheaper (93.9% versus 86.5%; $0.014 versus $0.021 per contested primary decision). The benefit of verify-then-vote is an explicit selection policy over reusable evidence: all 1,100 benchmark decisions replay byte-identically, and leave-one-agent-out decisions reuse sealed labels without a model call.

## Contents

| Path | What it holds |
|---|---|
| [`paper.pdf`](paper.pdf) | the main paper and references |
| [`supplement.pdf`](supplement.pdf) | supporting methods, proofs, diagnostics, and reproduction details |
| [`tex/`](tex/) | LaTeX source: `make` builds `main.pdf` and `supplement.pdf`, `make arxiv` writes the arXiv bundle |
| [`artifact/`](artifact/) | code, proofs, preregistrations and sealed data; [`artifact/README.md`](artifact/README.md) maps every result to a command |
| [`artifact/overturn/`](artifact/overturn/) | the reducer (Rust crate and CLI `overturn`) |
| [`artifact/lean/`](artifact/lean/) | Lean 4 proofs of the selection guarantees and the gate's harm bound |
| [`artifact/bindings/python/`](artifact/bindings/python/) | the Python package `overturn-arbiter` |
| [`artifact/real-agent-eval/v5/`](artifact/real-agent-eval/v5/) | OVERTURN: benchmark, preregistration, frozen evaluator, sealed responses, captures, checker labels and judge rows |
| [`artifact/real-agent-eval/v6/`](artifact/real-agent-eval/v6/) | the second agent pool: preregistration, freeze record, pool manifest, sealed responses, captures, checker labels, judge rows and results |
| [`artifact/real-agent-eval/v4/`](artifact/real-agent-eval/v4/) | the companion memory-only benchmark and its preregistration |
| [`artifact/real-agent-eval/v3/`](artifact/real-agent-eval/v3/) | the free-text measurements |
| [`artifact/tools/`](artifact/tools/) | evidence capture, the support checker and its validation, the judges, the retrieval corpus builder |

## Build instructions

From `papers/verify-then-vote/tex/`, run `make` to build the main paper (`main.pdf`) and supporting material (`supplement.pdf`), or `make arxiv` to produce a source bundle containing both standalone documents. The build uses Tectonic when available, otherwise `latexmk` with pdfLaTeX.

For code, data and formal-proof verification, follow the commands and toolchain pins in [the artifact instructions](artifact/README.md).

## Citation

```bibtex
@misc{grainulation2026verify,
  author       = {{Grainulation}},
  title        = {Verify, Then Vote: Overturning Wrong Majorities in Multi-Agent {LLMs}},
  year         = {2026},
  howpublished = {\url{https://github.com/grainulation/papers/tree/main/papers/verify-then-vote}}
}
```

## Release status

This is preparation for the first public release. The study protocols and freeze records document when analyses were specified; they do not represent earlier publications.

Editorial revision, 2026-11-05: clarified the main paper and supporting methods with worked examples and explicit population and baseline distinctions. Research results, formal statements, and proofs are unchanged.
