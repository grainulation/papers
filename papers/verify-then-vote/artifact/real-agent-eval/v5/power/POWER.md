# Eval v5 power analysis

Script: `power_v5.py` (numpy only, seed 20261022, no model calls). Output: `power_results_v5.json`.
Run it with `python3 real-agent-eval/v5/power/power_v5.py` (about 80 s; `--quick` skips the
exact value of the one "> 1,500" cell). It exits non-zero if any number below drifts from the design.

The exact McNemar power code is v4's `real-agent-eval/v4/power/power.py`, imported unchanged (its
SHA-256 is recorded in the output). The only data the script reads is
`real-agent-eval/v4/results/dev/responses_v4.jsonl`. It refuses any path under `results/conf/`,
because v4 confirmatory data stay blinded.

## Anchor: v4 Table 1

With ψ = 0.25 and Δ = 0.10, the script gets **N = 207**, the same as v4 `POWER.md` Table 1. The
script asserts this value.

## §6.1 Stage A (v4 dev, closed-book): reproduced exactly

This uses majority only. On ties, a value's correctness is the expected result of the seeded-random
tie-break. Each object is graded on its member with the smallest contribution id, as in v4
`object_correct`.

| quantity | all | TQA | PopQA | FEVER | SciFact |
|---|---|---|---|---|---|
| decisive conflicts | 80 | 25 | 8 | 30 | 17 |
| majority correct (expected) | 51.9 | 15.0 | 4.9 | 25.5 | 6.5 |
| majority wrong, correct minority exists | 28.1 (m = 0.352) | 10.0 | 3.1 | 4.5 | 10.5 |
| majority strictly wrong | 20 | 8 | 2 | 2 | 8 |
| ties at the top | 16 | 4 | 2 | 5 | 5 |
| ≥ 3 agents on one wrong value | 14 | 6 | 0 | 0 | 8 |
| items where all agents are wrong | 29 / 160 | 8 | 17 | 0 | 4 |

**One correction to the design's §6.1 text.** The design says that in 17 of the 20 strict
majority-wrong items the correct minority is a single agent: qwen 10, phi3 6, mistral 2, llama 2,
gemma 1. Those per-model counts add up to 21, not 17.

The data say:

- the correct minority is a single agent in **19 of 20** items;
- one item has a two-agent minority on one value;
- the per-model counts above cover all 21 correct-minority agents.

If the counts are restricted to single-agent minorities, they are qwen 9, phi3 5, mistral 2,
llama 2, gemma 1. The figure "13 of 20 carried an evidence item" is reproduced. The analysis team
should change "17 of the 20" to "19 of the 20" and say that the model counts are over 21 agents.

## §6.2 table: decisive conflicts for 80% power (all cells reproduced)

The test is exact two-sided McNemar at α = 0.05. b/N = m·p_w and c/N = (1 − m)·q_r. N is the
smallest value with power ≥ 0.80 that stays there for 25 further values. Each finite cell was
checked with a 20,000-rep Monte Carlo (`mc_power_at_N` in the JSON).

| m | p_w | q_r = 0.05 | q_r = 0.10 | q_r = 0.15 |
|---|---|---|---|---|
| 0.35 | 0.3 | 221 | 872 | — |
| 0.35 | 0.4 | 123 | **302** | 1,070 |
| 0.35 | 0.5 | 83 | 165 | 374 |
| 0.25 | 0.4 | 293 | > 1,500 (exact: **2,266**) | — |
| 0.25 | 0.5 | 179 | 658 | — |

"—" means Δ ≤ 0.02. Those cells are (0.35, 0.3, 0.15) with Δ = 0.0075, (0.25, 0.4, 0.15) with
Δ = −0.0125, and (0.25, 0.5, 0.15) with Δ = 0.0125.

## Planning numbers (all reproduced)

| quantity | design | script |
|---|---|---|
| point m = 0.35, p_w = 0.4, q_r = 0.10 | Δ = 0.075, ψ ≈ 0.21, N = 302 | Δ = 0.075, ψ = 0.205, **N = 302** |
| N\* at Δ = 0.075, ψ = 0.25 (floor) | 368 | **368** (exact power at the planning point ψ = 0.205: 0.877) |
| N\* at ψ = 0.20 / 0.30 | 294 / 438 | **294 / 438** |
| items at yield 0.45 | ≈ 820 | ⌈368 / 0.45⌉ = **818** (736 at yield 0.50) |
| SciFact-only fallback | 129 at ψ = 0.35, Δ = 0.15; ≈ 120 decisive | **129**; 283 × 0.42 = 118.9 decisive |

## Stopping rule (§6.2)

`stopping_rule(psi_dev, y_dev)` takes ψ_dev = (b + c)/N for BE vs MAJ on dev, floored at 0.25.
It computes I = ⌈N\*(ψ) / y_dev⌉ with Δ = 0.075, clamped to [1,000, 1,400]. `evaluate_v5.py`
imports this function. Examples:

| ψ_dev | y_dev = 0.30 | 0.45 | 0.60 |
|---|---|---|---|
| ≤ 0.25 (N\* 368) | 1,227 | 1,000 (818) | 1,000 (614) |
| 0.30 (N\* 438) | 1,400 (1,460, cap) | 1,000 (974) | 1,000 (730) |
| 0.40 (N\* 580) | 1,400 (1,934, cap) | 1,289 | 1,000 (967) |

## H2 power: non-inferiority, margin −0.05, one-sided α = 0.025, true difference 0

| N | ψ(BE, J) = 0.15: normal / MC Wald | ψ(BE, J) = 0.10: normal / MC Wald |
|---|---|---|
| 368 | 0.70 / 0.70 | 0.86 / 0.86 |
| 450 | 0.78 / 0.78 | 0.92 / 0.91 |

"Normal" is the approximation d̂ ~ N(0, ψ/N), which the design quotes. "MC Wald" is v4's
`ni_power`: 20,000 reps with the paired Wald variance. Both reproduce the design's table. The
confirmatory test uses the Newcombe interval (`evaluate_v5.py`), which is slightly wider than Wald
at small ψ, so these numbers are a mild upper bound.
