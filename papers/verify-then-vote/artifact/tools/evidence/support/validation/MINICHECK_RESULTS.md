# MiniCheck local checker: exploratory validation

Checker `98751cc07911d57a1586848dfb8c4e7b`: `bespoke-minicheck:7b` on Ollama 0.17.7. Manifest digest
`66607904c165445540331c2f005bb5120edd939008ba1fe1e75151ed827a7a00` (InternLM2, 7.7B, Q4_K_M). Run 2026-10-24.
Full report: `validation/98751cc07911d57a1586848dfb8c4e7b.json`. Code: `minicheck_check.py`, `minicheck_pin.json`,
`minicheck_template.txt`, `validation/minicheck_validate.py`. Raw rows: `validation/results/minicheck_*-98751cc0….jsonl`.
Support cache: `validation/cache_minicheck/`. This run is exploratory (PREREGISTRATION §2.3, MiniCheck bullet). It made
no hosted calls.

## Setup

- **What the checker sees.** It sees the same claim string, bm25/1 spans, neutralizer and `[...]` span join as
  Claude 0.2.0 and mistral, and the same caching and sealing. Only the wrapper differs. It is MiniCheck's own format:
  USER `Document: {passage}\nClaim: {claim}`. No `system` is sent, so the Modelfile's MiniCheck system prompt applies.
  No structured-output `format` is sent.
- **Decoding.** Temperature 0, seed 42, num_ctx 8192, top_k 40, top_p 0.9, num_predict 8.
- **Output mapping.** `Yes` → `supports` and `No` → `not_enough_info`. Anything else is a `parse_error`, which never
  happened. MiniCheck is binary: "No" means *not supported*, never *contradicted*. So the checker never emits `refutes`.
- **Effect on the reducers.** The gate opens only on `supports`, so the gated decision does not depend on this
  mapping. Under an NEI factor above 0 (BE-G's scored form, nei0.5), a "No" passage gets 0.5 rather than the 0 a true
  `refutes` would get.
- **score_q.** The probability of the answer token, from Ollama logprobs. No frozen policy uses it.
- **How macro-F1 was computed (criterion unchanged).** `validate.metrics` takes the three-way mean of F1 over supports,
  refutes and NEI, exactly as for 0.2.0 and mistral. Because `refutes` is never predicted, refutes F1 = 0. So macro-F1
  is at most 2/3 = 0.667 < 0.70 for **any** binary checker under **any** binary-to-three-way mapping. The criterion is
  structurally unattainable, not narrowly missed.
- **Binary macro-F1 (descriptive only).** Supports vs not, mean of the two F1s. It is reported beside the binding
  number and is not binding.

## Binding criteria (FRAMING §3.2, PREREGISTRATION §2.3)

| criterion | threshold | MiniCheck | pass | Claude 0.2.0 (`f2a14bd8…`) | mistral (`41b9f3ec…`) |
|---|---|---|---|---|---|
| supports precision, FEVER fresh2 (n = 300) | ≥ 0.85 | **0.857** (96/112; bootstrap 0.792–0.919) | yes (point); CI lower < 0.85 | 0.898 (97/108; 0.837–0.952) | 0.774, fail |
| supports precision, SciFact-300 | ≥ 0.85 | **0.918** (78/85; bootstrap 0.852–0.973) | yes, CI lower too | not run on this slice (0.1.0, same model: 0.923) | 0.569, fail |
| macro-F1 (three-way, FEVER fresh2) | ≥ 0.70 | **0.499** (0.468–0.526) | **no**: structural ceiling 0.667 | 0.899, pass | 0.548, fail |
| regeneration stability (n = 50) | ≥ 0.95 | **50/50 = 1.00** (Wilson 0.929–1.00) | yes | 0.96, pass | 1.00, pass |
| **all binding** | | | **FAIL** (only on macro-F1) | pass | fail |

## Other measurements (not binding)

| measure | MiniCheck | Claude 0.2.0 | mistral |
|---|---|---|---|
| injection success (50) | 0/50 (Wilson 0–7.1%). Supports-target attacks: 0/30. The 20 refutes-target attacks cannot succeed. | 0/50 | 21/50 = 0.42 |
| SciFact fresh2, NEI only (150): false supports | 2 (148 NEI) | 7 (+10 refutes, 2 unchecked) | 22 (+12 refutes) |
| binary macro-F1, FEVER / SciFact-300 | 0.927 / 0.887 | — | — |
| three-way macro-F1, SciFact-300 | 0.491 (ceiling 0.667) | — | 0.571 |
| byte-identity rerun, reverse order | 510/510 | n/a (hosted) | 510/510 |
| latency per call (sequential, M3 Pro) | mean 1.59 s, p50 1.50 s, p90 2.48 s (n = 798). FEVER mean 1.16 s. | median 3.1 s (FEVER) | mean 2.29 s, p50 2.13 s |
| $ per check | 0 hosted | ≈ $0.0048 (RUN_NOTES item 9) | 0 hosted |

FEVER fresh2 confusion, rows gold, columns predicted (`supports` / `refutes` / `not_enough_info`):

| gold | supports | refutes | not_enough_info |
|---|---|---|---|
| supports | 96 | 0 | 4 |
| refutes | 1 | 0 | 99 |
| not_enough_info | 15 | 0 | 85 |

Its 16 false supports are 15 NEI pairs and 1 refutes pair. Claude 0.2.0 had 11: 10 NEI and 1 refutes.

## Verdict

As defined, MiniCheck **fails** the binding validation. The failure is only on three-way macro-F1 (0.499 against
0.70), and that criterion cannot be met by a binary checker: its ceiling is 0.667. On the quantities the verified gate
actually uses, MiniCheck meets every threshold:

- supports precision 0.857 on FEVER and 0.918 on SciFact-300;
- stability 1.00, and the 510-prompt rerun is byte-identical;
- 0/50 injection success;
- about 1.6 s per call, with no hosted cost.

Its FEVER supports precision is 4 points below Claude 0.2.0's. Its bootstrap lower bound (0.792) does not clear 0.85,
so the margin is thin. Under the task's rule the confirmatory-item analysis (step 5) was **not run**.

Using MiniCheck for BE-G-L would require a criterion that fits a binary checker, for example dropping three-way
macro-F1 or replacing it with the binary macro-F1. That is a change to the validation criteria and needs the author's
decision, disclosed as such. It cannot be applied silently.
