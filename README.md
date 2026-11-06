<p align="center">
  <img src="assets/papers-logo.png" width="180" alt="Grainulation Papers glitch logo">
</p>

<h1 align="center">Papers</h1>

<p align="center"><strong>Papers you can read. Results you can check.</strong></p>

<p align="center">
  Research on evidence and verification in multi-agent systems.<br>
  Manuscripts, formal proofs, code, and the recorded data behind the results.
</p>

<p align="center">
  <a href="papers/verify-then-vote/paper.pdf"><img src="https://img.shields.io/badge/read_the_paper-Verify%2C_Then_Vote-98f3ef?style=for-the-badge" alt="Read Verify, Then Vote"></a>
</p>

<p align="center">
  <a href="https://github.com/grainulation/papers/actions/workflows/papers.yml"><img src="https://github.com/grainulation/papers/actions/workflows/papers.yml/badge.svg?branch=main" alt="Paper and catalogue checks"></a>
  <a href="https://github.com/grainulation/papers/actions/workflows/verify-then-vote.yml"><img src="https://github.com/grainulation/papers/actions/workflows/verify-then-vote.yml/badge.svg?branch=main" alt="Artifact verification"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/code-Apache_2.0-blue" alt="Code license: Apache 2.0"></a>
  <a href="LICENSE-CC-BY-4.0"><img src="https://img.shields.io/badge/papers-CC_BY_4.0-476b46" alt="Manuscript and figure license: CC BY 4.0"></a>
</p>

<p align="center">
  <a href="CONTENTS.md">Paper map</a> ·
  <a href="papers/verify-then-vote/supplement.pdf">Supplement</a> ·
  <a href="papers/verify-then-vote/artifact/README.md">Reproduce the results</a> ·
  <a href="papers/verify-then-vote/README.md#citation">Cite</a> ·
  <a href="CONTRIBUTING.md">Contribute</a>
</p>

---

## Verify, Then Vote

**Overturning Wrong Majorities in Multi-Agent LLMs** · November 2026

When agents share a mistake, their majority can be wrong. This paper studies a rule that lets checked passage evidence overturn the vote, while recording which evidence licensed each change.

Verification improves accuracy on the evaluated benchmark, but the original scored rule misses its pre-specified harm criterion. The formal result identifies an inspectable failure condition; it does not guarantee a low error rate. The paper reports the gains, failures, and tradeoff against a stronger model judge together.

| Start here | What you get |
| --- | --- |
| **[Read the paper](papers/verify-then-vote/paper.pdf)** | The rule, main results, controls, and limitations. |
| [Supporting material](papers/verify-then-vote/supplement.pdf) | Methods, proofs, pooled-bound construction, and full replay tests. |
| [Reproduce the results](papers/verify-then-vote/artifact/README.md) | Commands and pinned toolchains for the code, analyses, and formal proofs. |
| [Source and citation](papers/verify-then-vote/README.md) | LaTeX build instructions, artifact map, and BibTeX. |

## Follow a result back to its evidence

Each paper lives alongside the material needed to inspect its claims:

- **Read** the argument in the main paper and the supporting methods in its supplement.
- **Inspect** the study protocols, recorded inputs, checker labels, and reported outputs.
- **Reproduce** the analyses and run the implementation and proof checks using the artifact guide.

The [paper map](CONTENTS.md) collects abstracts and links. [`catalogue.yaml`](catalogue.yaml) provides the machine-readable index.

## Build the documents

With [Tectonic](https://tectonic-typesetting.github.io/) installed, or `latexmk` with pdfLaTeX, run from the repository root:

```sh
make -C papers/verify-then-vote/tex
```

This builds the main paper and supplement. Add the `arxiv` target to create a source bundle containing both standalone documents. Code, data, and proof checks have separate requirements; follow the [artifact guide](papers/verify-then-vote/artifact/README.md).

## Release status and corrections

The collection is being prepared for its **first public release**. Study freezes record when analyses were specified; they are not earlier publications. After publication, tagged releases and the [history](history.md) will record corrections and revisions.

For a correction or reproduction report, [open an issue](https://github.com/grainulation/papers/issues) with the paper, section, claim, and supporting evidence or commands. See [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution and release process.

## Licensing

| Material | Terms |
| --- | --- |
| Code | [Apache License 2.0](LICENSE) |
| Manuscripts and figures | [CC BY 4.0](LICENSE-CC-BY-4.0) |
| Data we produced | CC BY 4.0 unless the artifact's `DATA_LICENSES.md` states otherwise |
| Third-party data and model outputs | Their own dataset or provider terms; EXAONE outputs are **not** under CC BY 4.0 |

The artifact's [data and component licenses](papers/verify-then-vote/artifact/DATA_LICENSES.md) take precedence over this summary.
