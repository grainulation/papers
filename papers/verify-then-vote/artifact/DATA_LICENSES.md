# Data licenses

This artifact contains our own code and data, plus text derived from four public datasets and a
few web pages. Our own code is under Apache-2.0. Our own data and text (results, logs, design
documents, preregistrations) are under CC BY 4.0, except the model outputs listed under "Model outputs" below, which keep the terms stated there. The top-level license files give the full terms.
Third-party material keeps its own license, listed below. Where a file mixes sources, each line or
record carries the license of its source.

## Third-party datasets

| dataset | source | license | where the license is stated |
|---|---|---|---|
| FEVER 1.0 claims (`paper_dev`) and the FEVER 2017 Wikipedia pages (lead sections) | Thorne et al. 2018, fever.ai | **CC BY-SA 3.0** (Wikipedia text; share-alike applies to derived files) | fever.ai license page; recorded in `real-agent-eval/v5/benchmark/manifest.json` and `tools/corpus/corpus_manifest.json` |
| SciFact claims and evidence annotations | Wadden et al. 2020, `allenai/scifact` | **CC BY 4.0** | `LICENSE.md` in `allenai/scifact` (checked 2026-10-23) |
| SciFact corpus abstracts (`corpus.jsonl`) | from Semantic Scholar S2ORC, distributed with SciFact | **ODC-By 1.0** | `LICENSE.md` in `allenai/scifact` (checked 2026-10-23) |
| PopQA | Mallen et al. 2023, `AlexTMallen/adaptive-retrieval` | **MIT** (repository license; the Hugging Face card states none). The facts come from Wikidata, which is CC0. | repository license (checked 2026-10-23) |
| TruthfulQA (MC1) | Lin et al. 2022, `sylinrl/TruthfulQA` | **Apache-2.0** | repository license (checked 2026-10-23) |

Not included: the full FEVER Wikipedia dump, the full SciFact corpus and the retrieval indexes.
`tools/corpus/build.py` downloads them and checks them against `tools/corpus/corpus_manifest.json`;
`corpus-cache/` holds only `scifact_dense/dense_manifest.json`.

## Files with derived text

These files contain dataset questions, claims, gold answers or passages, either copied or quoted
inside prompts and model outputs:

- **Benchmark items** (all four datasets): `real-agent-eval/v4/benchmark/items_dev.jsonl`,
  `real-agent-eval/v4/benchmark/items_confirmatory.jsonl`, `real-agent-eval/v5/benchmark/items_dev.jsonl`,
  `real-agent-eval/v5/benchmark/items_confirmatory.jsonl`, and the archived
  `real-agent-eval/v5/benchmark/1.0.0/items_*.jsonl`. FEVER lines are CC BY-SA 3.0, SciFact claims
  CC BY 4.0, PopQA MIT, TruthfulQA Apache-2.0.
- **Retrieved passages: FEVER Wikipedia (CC BY-SA 3.0) and SciFact abstracts (ODC-By 1.0)**:
  - `real-agent-eval/v5/results/{dev,conf,conf_futility,dev_checker2}/captures.jsonl`;
  - `checks.jsonl`, `checks_plan.jsonl`, `check_calls.jsonl`, `judge.jsonl` and `judge_inputs*.jsonl`
    in those directories;
  - the per-item records in `real-agent-eval/v5/results/{dev,conf,pilot}/raw/`;
  - the reducer inputs under `real-agent-eval/v5/results/conf_futility/rust/`.
- **Second agent pool and post hoc analyses**, with the same FEVER Wikipedia passages (CC BY-SA 3.0),
  SciFact abstracts (ODC-By 1.0) and dataset questions:
  - `real-agent-eval/v6/results/{dev,dev_failed_exaone2.4b,conf,conf_futility}/`: `captures.jsonl`,
    `checks*.jsonl`, `check_calls.jsonl`, `judge*.jsonl`, `judge_inputs*.jsonl`, `raw/` and
    `items_first300.jsonl`; `real-agent-eval/v6/results/items_confirmatory_aliases.jsonl`;
  - `real-agent-eval/v5/local_checker/` (including `support-cache/`) and
    `real-agent-eval/v5/harm_attribution/` (including `stability/`);
  - `tools/evidence/support/validation/results/minicheck_*`.
- **Checker controls** (`real-agent-eval/v5/controls/`): `population.jsonl` holds the checker
  prompts with FEVER Wikipedia passages (CC BY-SA 3.0) and SciFact abstracts (ODC-By 1.0), and the
  propositions built from FEVER and SciFact claims and PopQA questions; `harm_reading.jsonl` holds
  propositions and annotator rationales that quote them. `calls.jsonl` and `results.json` refer to
  the same passages and propositions by key and hash, with labels and counts.
- **Checker validation slices and results**:
  - FEVER: `tools/evidence/support/validation/fever_slice.jsonl`, `fever_slice_fresh2.jsonl`;
  - SciFact: `slice.jsonl`, `scifact_slice_fresh2.jsonl`, `pilot.jsonl`, `injection.jsonl`;
  - the matching per-call files in `tools/evidence/support/validation/results/`;
  - the checker cache `tools/evidence/support/validation/cache/` holds labels, scores and hashes
    keyed by check, with no passage or claim text.
- **v4 study** (questions and gold answers from all four datasets, inside prompts and grading
  sheets): `real-agent-eval/v4/results/{dev,conf}/responses_v4.jsonl`, `raw/`, `items_v4_blind.csv`,
  `popqa_label_sheet.csv`, and `real-agent-eval/v4/results/dev/popqa_sim/`.

## Web text captured by the evidence tool

`tools/evidence/support/smoke/` (the support records in `reduce-input*.json`, `reduce-output*.json`
and `cache/`) holds short sealed excerpts: at most three spans of at most 1,000 characters per
capture. They come from:

- `en.wikipedia.org` (Acceleration due to gravity; Newton's law of universal gravitation): CC BY-SA 4.0;
- `git-scm.com/docs/git-merge`: Git documentation, GPL-2.0;
- RFC 793 (`rfc-editor.org`): IETF RFC; reproduction is allowed under the IETF Trust's terms for
  RFCs.

Records of the identifiers recovered from v3 responses (`tools/evidence/results/`) hold URLs and
DOIs only, with no page text.

## Model outputs

The free-text study (`real-agent-eval/results/`, `real-agent-eval/v3/`, `real-agent-eval/labels/`),
the v4, v5 and v6 raw records and the judge and checker records contain text generated by models.
Except as stated below, we release this text as part of our data, under CC BY 4.0, subject to any
terms the model providers place on outputs. The questions in `real-agent-eval/questions.json` are our
own.

| model | where its output appears | terms on outputs |
|---|---|---|
| llama3.2:3b, mistral, gemma2:2b, phi3:mini, qwen2.5:3b (first pool, via Ollama) | v3, v4, v5 records | released under CC BY 4.0 as above, subject to each provider's terms |
| Claude Sonnet 5.5 (checker, judges, reader, closed-book reference) | checker and judge records of v5 and v6 | released under CC BY 4.0 as above, subject to Anthropic's terms |
| **EXAONE 3.5 7.8B Instruct** (`exaone3.5:7.8b`), and EXAONE 3.5 2.4B Instruct (`exaone3.5:2.4b`, failed qualification, no answers) | `real-agent-eval/v6/results/{dev,dev_failed_exaone2.4b,conf,conf_futility}/` raw records and the judge inputs that quote them | **Not under CC BY 4.0.** Under the EXAONE AI Model License Agreement 1.1 - NC, the output belongs to LG AI Research and is shared here for research purposes only; any commercial use is prohibited. Output of EXAONE 3.5 (LG AI Research); license: <https://huggingface.co/LGAI-EXAONE/EXAONE-3.5-7.8B-Instruct/blob/main/LICENSE> |
| Nemotron-Mini 4B Instruct (`nemotron-mini:4b`) | v6 raw records and judge inputs | released under CC BY 4.0 as above; the NVIDIA AI Foundation Models Community License does not allow using its outputs to develop or improve another large language model, and downstream users should observe that term |
| Falcon 3 3B Instruct (`falcon3:3b`) | v6 raw records and judge inputs | released under CC BY 4.0 as above; use must follow the TII Falcon License and TII's Acceptable Use Policy (<https://falconllm.tii.ae/falcon-terms-and-conditions.html>) |
| OLMo 2 7B (`olmo2:7b`), Granite 3.3 2B (`granite3.3:2b`), nomic-embed-text | v6 raw records; dense retrieval | Apache-2.0 models; outputs released under CC BY 4.0 as above |
| Bespoke-MiniCheck-7B (`bespoke-minicheck:7b`, two-way checker comparison) | `real-agent-eval/v5/local_checker/`, `tools/evidence/support/validation/results/minicheck_*` | labels only (supported or unsupported); the model is offered for non-commercial use (license file in `bespokelabs/Bespoke-MiniCheck-7B` on Hugging Face; commercial licensing through Bespoke Labs) |

Where a record mixes outputs, each output keeps the terms of the model that produced it.
