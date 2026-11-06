# Selector study (post hoc, exploratory)

**Caveat.** Everything here was computed on the v5 **confirmatory** data after unblinding. No variant
below was preregistered, and the variants were designed after looking at the BE-G / VV harm cases. The
numbers are descriptive and biased towards the variants that look good. A variant can become confirmatory
only through a new preregistered run on fresh items, with the selector frozen beforehand.

Files: `selector_study.py` (the script), `results.json` (all numbers, per-item harm table, item lists).
Run: `python3 real-agent-eval/v5/selector_study/selector_study.py`. No model, hosted, or Rust-binary call.

## Method

- The script imports the frozen `evaluate_v5.py` without modifying it. Its sha256 matches `v5/FREEZE.json`.
  It rebuilds every eligible item with the evaluator's own `prepare_item`. It builds the BE-G
  (`member/nei0.5/gated`) reducer input exactly as `reduce_method` does and decides with `evaluate_v5.mirror`,
  which the confirmatory run verified equal to the frozen binary on all 7,910 slots. MAJ and VV come from
  `python_methods`. Inputs: `results/conf/raw`, `captures.jsonl`, `checks.jsonl`, accepted checker
  `f2a14bd8…`.
- `gate_parts` copies `mirror`'s scoring and gate code line for line, to expose the scores, W and D.
  Each item asserts that it gives the same D, winner, stage and deadband flag as `mirror`.
- **Reproduction gate (passed, exact).** Per item, MAJ, VV, BE-G and D (correctness and value), plus
  `BE-G_stage`, equal `eval/paired_decisions_v5.csv` on all 1,100 eligible items. Published aggregates are
  reproduced exactly:

  | set | n | MAJ | D | BE-G | VV | BE-G b/c vs MAJ | VV b/c vs MAJ | BE-G c_D | H3a (BE-G) |
  |---|---|---|---|---|---|---|---|---|---|
  | P | 526 | .7148 | .7338 | .8650 | .8650 | 91 / 12 | 88 / 9 | 10 (same 10 ids) | c=12, n_R=376, UB .0551, not rejected |
  | T | 69 | .4493 | .4928 | .5652 | .5217 | 9 / 1 | 6 / 1 | 0 | — |

  The "VV loses a correct default on 12" figure is **VV vs the scored default D** (12). VV's own default is
  MAJ, and against MAJ it loses 9.
- Definitions follow the evaluator: b/c vs MAJ = `overturn()`; c_D = D correct and winner wrong
  (`h4_block`); H3a = `cp_upper(c, n_R, 0.025) < 0.05` on P items with MAJ right (n_R = 376).
- **W** = values with ≥ 1 witness (a member with an accepted, status-ok `supports` label).
  **D** = scored `select(P)`, the reducer's default.
- **Trust weights (variant d)** were fit on the v5 **dev** split only (160 items, dev gold), as the posterior
  mean of Beta(1+correct, 1+incorrect): gemma2 .593, llama3.2 .636, mistral .667, phi3 .623, qwen2.5 .574.
  No confirmatory gold enters a weight. With these weights, k+1 votes always beat k votes (k ≤ 4). So TW
  differs from plurality only in how it breaks ties in agent count.

## Variants

Scored family (sel = BE-G's scored P5 selector; default D = scored `select(P)` unless stated):

| name | rule |
|---|---|
| BE-G | published: sel(W) if W ≠ ∅ else D |
| VDF | verified default first: D if D ∈ W; else sel(W) if W ≠ ∅; else D |
| a2ag / a2cit | (a) the gate with W' = values with ≥ 2 witness **agents** / ≥ 2 distinct supporting **passages** |
| VDF+a2ag / VDF+a2cit | (b) D if D ∈ W (≥1 witness); else sel(W') if W' ≠ ∅; else D |
| esc | (c) if the gate would overturn D and sel(W) was decided in the deadband (the reducer's own `in_deadband` of the deciding stage), keep D and flag the item for review |
| esc-margin | (c') keep D if it would be overturned and score_q(winner) − score_q(D) < 500 (deadband threshold) |
| VDF+esc | VDF, then (c) on its overturns |
| twD | (d) gate with default D_tw = trust-weighted plurality, sel(W) scored |
| twD+VDF (+esc) | D_tw if D_tw ∈ W; else sel(W); else D_tw (then (c)) |

Plurality family (sel = VV's headcount among verified responses, seeded ties; default MAJ):
VV, VV/VDF, VV/a2ag, VV/a2cit, VV/VDF+a2ag, VV/VDF+a2cit, VV/esc-tie. VV/esc-tie keeps MAJ when VV would
overturn MAJ on a tied verified plurality, which is VV's analogue of the deadband. Trust-weighted
plurality: TW alone (no gate); TW-gate (weighted plurality among verified responses, else TW);
TW-gate/VDF.

## Results — P (526 decisive primary items, n_R = 376)

"harms removed" / "corrections lost" / "new corrections" compare the variant's c-vs-MAJ and b-vs-MAJ item
sets with its reference: BE-G for the scored and TW rows, VV for the VV rows. c_D is measured against the
variant's own default (D, D_tw, or MAJ). "BE-G c_D fixed" counts how many of the 10 published BE-G c_D
items the variant gets right.

| variant | acc | b vs MAJ | c vs MAJ | c_D (own D) | BE-G c_D fixed | harms removed | corr. lost | new corr. | escalated | H3a UB | H3a |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **BE-G** (pub.) | .8650 | 91 | 12 | 10 (D) | — | — | — | — | — | .0551 | not rej. |
| **BE-G/VDF** | **.8688** | 87 | **6** | **4** | 6 | 6 | 4 | 0 | — | .0344 | **rej.** |
| BE-G/a2ag | .7814 | 40 | 5 | 4 | 8 | 9 | 51 | 0 | — | .0308 | rej. |
| BE-G/a2cit | .7776 | 36 | 3 | 1 | 9 | 10 | 55 | 0 | — | .0231 | rej. |
| BE-G/VDF+a2ag | .7852 | 41 | 4 | 1 | 9 | 9 | 50 | 0 | — | .0270 | rej. |
| BE-G/VDF+a2cit | .7757 | 35 | 3 | 0 | 10 | 10 | 56 | 0 | — | .0231 | rej. |
| BE-G/esc | .8460 | 76 | 7 | 5 | 5 | 5 | 15 | 0 | 22 (4.2%) | .0380 | rej. |
| BE-G/esc-margin | .8441 | 75 | 7 | 4 | 6 | 6 | 16 | 0 | 24 (4.6%) | .0380 | rej. |
| BE-G/VDF+esc | .8479 | 76 | 6 | 4 | 6 | 6 | 15 | 0 | 12 (2.3%) | .0344 | rej. |
| TW (no gate) | .7262 | 12 | 6 | 6 (MAJ) | — | 11 | 83 | 4 | — | .0344 | rej. |
| TW-gate | .8574 | 88 | 13 | 11 (TW) | 1 | 2 | 7 | 4 | — | .0584 | not rej. |
| TW-gate/VDF | .8688 | 88 | 7 | 4 (TW) | 6 | 7 | 7 | 4 | — | .0380 | rej. |
| BE-G/twD | .8688 | 93 | 12 | 12 (TW) | 0 | 0 | 1 | 3 | — | .0551 | not rej. |
| **BE-G/twD+VDF** | **.8707** | 89 | 7 | 4 (TW) | 6 | 7 | 6 | 4 | — | .0380 | rej. |
| BE-G/twD+VDF+esc | .8479 | 77 | 7 | 4 (TW) | 6 | 7 | 18 | 4 | 13 (2.5%) | .0380 | rej. |
| **VV** (pub.) | .8650 | 88 | 9 | 9 (MAJ) | — | — | — | — | — | .0450 | rej. |
| **VV/VDF** | **.8726** | 87 | **4** | 4 | — | 5 | 1 | 0 | — | .0270 | rej. |
| VV/a2ag | .7681 | 31 | 3 | 3 | — | 6 | 57 | 0 | — | .0231 | rej. |
| VV/a2cit | .7605 | 24 | 0 | 0 | — | 9 | 65 | 1 | — | .0098 | rej. |
| VV/VDF+a2ag | .7719 | 31 | 1 | 1 | — | 8 | 57 | 0 | — | .0147 | rej. |
| VV/VDF+a2cit | .7586 | 23 | 0 | 0 | — | 9 | 65 | 0 | — | .0098 | rej. |
| VV/esc-tie | .8536 | 78 | 5 | 5 | — | 4 | 10 | 0 | 19 (3.6%) | .0308 | rej. |

Scored D alone: .7338 (b 13 / c 3 vs MAJ). Of the 22 BE-G/esc escalations, D was right on only 5. The other
17 were correct overturns that the rule withheld.

## Results — T (69 TruthfulQA items)

VDF, esc, VDF+esc, twD and twD+VDF leave T unchanged, or change it only slightly: BE-G-family acc .5652,
b/c vs MAJ 9 / 1, c_D 0. VV/VDF is identical to VV on T (.5217, 6 / 1). Every (a) variant gives up almost all
T gains: BE-G/a2* .4928 (4 / 1), VV/a2* .4493 (0 / 0). VV/esc-tie .5072 (5 / 1). TW-gate .5652.

## Harm cases (P)

The 10 BE-G c_D items (D correct, BE-G wrong):

| id | D ∈ W | W (value: witness agents / passages) | decided in gated deadband | ungated BE_in_deadband | score_q(win) − score_q(D) |
|---|---|---|---|---|---|
| popqa2342806 | yes | dervorguilla 1/1, matilda 1/1 | yes | 1 | 0 |
| scifactdev770 | yes | refuted 2/1, supported 2/1 | yes | 1 | 0 |
| popqa2211064 | yes | "based on provided passage…" 1/1, charles ii 1/1 | yes | 1 | 243 |
| popqa4686489 | yes | boone nc 1/2, nc 1/1, nc usa 1/2, united states 1/2 | yes | 1 | 0 |
| popqa695490 | yes | peter iii 3/1, saltykov 1/1 | yes | 1 | −275 |
| popqa2797971 | yes | "apollo … naxos" 1/1, zeus 1/1 | no | 1 | 1326 |
| scifactdev808 | no | refuted 1/1 | no (single verified value) | 0 | 2410 |
| fever90151 | no | refuted 2/1 | no | 1 | 2244 |
| popqa276747 | no | "states east of mississippi" 1/1 | no | 0 | 0 |
| fever80417 | no | supported 1/1 | no | 0 | 1607 |

- **D ∈ W in 6 of 10.** In each of these the selector picked a wrong verified value over a right verified
  default. VDF removes exactly these 6 and no others.
- **Deadband.** The "7 of 10" figure comes from the `BE_in_deadband` CSV column, which belongs to the
  *ungated* BE configuration (member/nei0.1). The gated decision's own deadband flag is set on **5 of 10**,
  all of them D ∈ W cases. In the 4 D ∉ W cases W holds a single wrong value, so no deadband or Schulze step
  is involved: the gate overturns because the minority is the only verified value. The ratio for VV is
  similar: harm vs MAJ in 9 cases, of which MAJ ∈ W in 5 (popqa2342806, popqa145561, scifactdev770,
  popqa175943, scifactdev692). VV/VDF removes exactly these 5.
- The other 2 BE-G harms vs MAJ (popqa6297574, popqa6297573) are tied-majority items where the scored D
  differs from MAJ's random tie-break. They are not c_D and are outside the theorem.
- The 4 harms no VDF variant removes (scifactdev808, fever90151, popqa276747, fever80417) need a verified
  wrong minority against an unverified right default. Only (a)-type rules reach them, at a cost of 50–65
  corrections. fever90151 has 2 witness agents and survives a2ag. It falls only to a2cit, because both
  agents cite the same passage.

Per-item detail for every harm kind (BE-G c_D, BE-G c_MAJ, VV c_MAJ, VV c vs scored D; P and T) is in
`results.json → harm_cases`.

## Does Proposition gate-harm still apply?

The Lean statement (`lean/BranLean/Gate.lean`, `gate_harm` / `gate_cD_le_F`) quantifies over any
`vals`, `n`, `verified` and `sel` with selection closure, and in the counting form these may vary per item.
So any rule of the form "D if W* = ∅, else a member of W*" is an instance, for any per-item default
D ∈ vals and verified set W*. Each variant's harm was checked empirically: c_D ⊆ F_W* held for every
variant in P and T (`harm_bound_holds` in results.json).

| variant | instance of the theorem? | verified set / selector | bound |
|---|---|---|---|
| VDF | yes, unchanged | W; sel'(S) = D if D ∈ S else sel(S) (closed; sel'(P) = D since D ∈ P) | c_D ≤ F |
| (a) a2ag / a2cit | yes, with W redefined | W' ⊆ W (≥ 2 agents / passages) | c_D ≤ F' ≤ F; harm now needs a wrong value with two supporting agents/passages (F' = 20 / 9 on P vs F = 56) |
| (b) VDF + (a) | yes | W'' = W' ∪ {D if D ∈ W}, sel' as VDF | harm needs a wrong value in W'' other than D, i.e. in W': c_D ≤ F' |
| (c) esc, esc-margin, VDF+esc | yes | W* = ∅ on escalated items, else W (a per-item `verified` that depends on scores; the proof does not care) | c_D ≤ F (and ≤ F on non-escalated items) |
| (d) TW-gate, twD, twD+VDF | yes, with D = D_tw | W; any default works (take n = weighted vote, or n = indicator of D_tw) | c_D ≤ F relative to D_tw, not relative to scored D or MAJ |
| VV family | yes (as in the paper) | plurality-among-verified selector, D = MAJ | relative to MAJ |
| TW alone, D alone | not a gate | — | no harm property |

As for the published gate, no variant bounds harm **vs MAJ** on tied-majority items where its default
differs from MAJ. Note that (c) does not satisfy plain selection closure as a selector on the original W,
because it can return D ∉ W. It is an instance only once escalation is modelled as emptying W* for that item.

## Verdict (post hoc)

- **Verified default first** is the only change that removes harm almost for free. On P it removes 6 of
  BE-G's 12 harms vs MAJ (6 of 10 c_D) and costs 4 of 91 corrections, so accuracy rises from .8650 to .8688.
  For VV it removes 5 of 9 and costs 1 of 88 (.8726). Both pass H3a (UB .0344 / .0270), where BE-G failed
  (.0551). T is unchanged.
- **(a) two-witness rules** remove 9–10 of the 12 BE-G harms but cost 50–65 corrections. P accuracy falls to
  about .78 and almost all of the T gain is lost. Not worth it.
- **(c) escalation** removes 5–6 harms, costs 15–16 corrections and flags 4–5% of P items. On top of VDF
  it removes nothing more, because VDF already takes out the deadband-decided harms, and it still costs 11
  more corrections.
- **(d) trust weights** (dev-fit) only break count ties. Alone, TW is worse than scored D (.7262 vs .7338).
  As the gate default it adds 3–4 corrections and some new harms. twD+VDF has the best scored-family
  accuracy (.8707, c 7), within noise of VDF (.8688, c 6).
- The best combination is VDF, optionally with D_tw. The 4 remaining c_D harms are unverified-right
  vs verified-wrong cases that no tested selector removes without large correction losses.
