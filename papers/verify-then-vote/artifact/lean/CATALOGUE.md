# Catalogue: paper Section 3 and Appendix B.4 → Lean

The selection guarantees of Appendix B.4 and the gate of Section 3 (summarised in Appendix D).
Namespace `Overturn`. Every theorem below is proved; the build contains no `sorry` (checked by `OverturnLean/Audit.lean`).

Modelling conventions: features are indexed 0 = ev, 1 = conf, 2 = cs, 3 = rec, 4 = ca. A conflict set is a
`Finset α` with a predicate `correct`. Results stated for an arbitrary score `f : α → K` apply to
`Score_w ∘ cand` in particular. `K` is any linear ordered field. Corollary 2 is stated over ℝ, and the
counterexample is computed over ℚ.

| Paper statement | Lean theorem | File | Status |
|---|---|---|---|
| Notation: `Score_w(c⁺) − Score_w(c⁻) = wᵀd(c⁺,c⁻)` | `score_sub_eq_dot` | Basic | proved |
| Notation: `d ∈ [−1,1]⁵` (so `γ ≤ 1`, `βᵢ ≤ 1`) | `dvec_mem_Icc` | Basic | proved, assuming `x, λ ∈ [0,1]` |
| **Definition 2** Score separation, pairwise form `wᵀd > δ` for every pair | `Separated` (def) | Separation | definition |
| **Definition 2** "equivalently" `min_{S⁺} − max_{S⁻} > δ` | `separated_iff_min_sub_max` | Separation | proved; needs both classes non-empty (as in the paper's notation) |
| **Proposition 2 (i)** the argmax lies in `S⁺` | `prop1_i` | Separation | proved for *every* maximiser, so ties at the top are covered. **Differs:** needs `δ ≥ 0` and `S⁺ ≠ ∅`; see `prop1_i_needs_nonneg_delta` and `prop1_needs_nonempty_pos` |
| **Proposition 2 (ii)** `D_δ ⊆ S⁺` (non-strict `≥ max − δ`) | `prop1_ii` | Separation | proved; needs `S⁺ ≠ ∅`, does not need `δ ≥ 0` |
| Proposition 2 (ii), implementation's strict deadband (`max − f < δ`) | `prop1_ii_strict`, `inDeadbandStrict_imp` | Separation | proved (the strict set ⊆ `D_δ`) |
| Necessity of `δ ≥ 0` in Proposition 2 (i) | `prop1_i_needs_nonneg_delta` | Separation | proved (counterexample with `δ = −2`) |
| Necessity of `S⁺ ≠ ∅` | `prop1_needs_nonempty_pos` | Separation | proved (counterexample) |
| **Lemma 1** tie-breaker neutrality for `X ⊆ D_δ`, every `ε` | `lemma1` | Separation | proved. **Differs:** also needs `X ≠ ∅`, `T(X) ∈ X`, `δ ≥ 0`, `S⁺ ≠ ∅` (all implicit in the paper) |
| Lemma 1 with `X = deadband_candidates()` (strict) | `lemma1_strict` | Separation | proved |
| **Proposition 3** `w₁γ − Σᵢ₌₂⁵ wᵢβᵢ > δ ⇒` separation | `prop2` | SufficientCondition | proved for any lower bound `γ` on `d₁` and any upper bounds `βᵢ` on `−dᵢ` (the paper's min/max choices are special cases); needs `w ≥ 0` |
| With `βᵢ = 1`, `Σw = 1`: condition is `w₁γ − (1 − w₁) > δ` | `prop2_condition_unit_beta` | SufficientCondition | proved |
| Default `w₁ = 0.35`, `δ = 0.05`: requires `γ > 2.0` | `default_condition_iff_gamma_gt_two` | SufficientCondition | proved (iff) |
| **Default-weights consequence of Proposition 3**: with `βᵢ = 1`, no `γ ≤ 1` works | `default_weights_no_gamma` | SufficientCondition | proved for every `δ ≥ 0` |
| Stronger: under default weights even `d_ev = 1` does not separate | `default_max_evidence_gap_not_separated` | SufficientCondition | proved (extra, not in paper) |
| **Corollary 2** separation on all of `W = conv V(W)` ⇔ separation on `V(W)` | `cor1` | Robustness | proved, both directions, for an arbitrary set `V` (finite or not, inside `Δ⁴` or not); proof by half-space convexity |
| Full-simplex consequence of Corollary 2: robustness ⇔ `dᵢ > δ` on every dimension for every pair | `simplex_robust_iff` | Robustness | proved |
| Implementation: Proposition 2 (i) on ×10,000 quantised scores | `prop1_i_quantized` | Quantized | proved for `|q − 10000·f| ≤ ½`, threshold `Q > 0`, `δ = Q/10000` |
| Implementation: `deadband_candidates()` (`top_q − q < 500`) ⊆ `S⁺` | `prop1_ii_quantized` | Quantized | proved |
| Implementation: non-strict `top_q − q ≤ 500` is unsafe | `quantized_nonstrict_fails` | Quantized | proved (counterexample: real margin 0.05004, rounded gap exactly 500) |
| Real separation `> Q/10000` ⇒ rounded gap `≥ Q` | `quantized_gap` | Quantized | proved |
| **Counterexample** scores 0.815 / 0.830 | `score_cPlus`, `score_cMinus` | Counterexample | proved (`norm_num`, ℚ) |
| Counterexample: old condition holds (ev gap 0.10 > 0.05) | `old_condition_holds` | Counterexample | proved |
| Counterexample: incorrect wins, both in deadband, not separated | `incorrect_wins`, `within_deadband`, `not_separated` | Counterexample | proved |
| The evidence-gap condition ("evidence gap > δ ⇒ separation") is false | `old_prop1_false` | Counterexample | proved |
| `γ = 0.10`, `β_rec = 1`, `0.035 − 0.05 = −0.015` equals the score difference | `prop2_quantities` | Counterexample | proved |
| "Mirror image selects correctly with `Δ_w < δ`" | `mirror_correct_but_not_separated` | Counterexample | proved when the mirror **swaps the correctness labels**. **Differs:** swapping only the recency values gives margin 0.085 > δ (`recency_swap_is_separated`) |

## Verify, then vote: paper Section 3 and `v3/GATE_SPEC.md` §3–§4 → Lean

Namespace `Overturn.Gate`, file `OverturnLean/Gate.lean`. One contradiction slot is `vals : Finset V` with agent
counts `n`, predicates `verified` (has a witness member) and `correct` (value-level gold), and a selector
`sel : Finset V → V`. The only assumption on `sel` is selection closure `hsel : ∀ S, S.Nonempty → sel S ∈ S`;
no fact about scores, the deadband or Schulze is used.

Statement numbers follow the paper's Section 3: Definition 1 (verify, then vote), Proposition 1 (harm
requires a verified wrong answer), Corollary 1 (counting form `c_D ≤ F` and no-loss). `v3/GATE_SPEC.md`
numbers the same results as its Corollary 1 (`c_D ≤ F`) and Corollary 2 (no-loss).

| Paper statement | Lean theorem | File | Status |
|---|---|---|---|
| **Definition 1** `P`, `W`, `D = sel(P)`, gated winner (`W = ∅ ⇒ D`, else `sel(W)`) | `P`, `W`, `D`, `gated` (defs) | Gate | definition, matches §4 verbatim |
| `P` non-empty when `vals` is (finite argmax of `n`) | `P_nonempty` | Gate | proved |
| `D ∈ P`, `D ∈ vals` | `D_mem_P`, `D_mem_vals` | Gate | proved; need `vals ≠ ∅` and `hsel` |
| Rule 2: `W = ∅ ⇒` gated winner is `D` | `gated_eq_D` | Gate | proved |
| Proof step 3: `W ≠ ∅ ⇒` gated winner `∈ W` | `gate_winner_verified` | Gate | proved |
| Gated winner `∈ vals` | `gated_mem_vals` | Gate | proved; needs `vals ≠ ∅` |
| **Proposition 1** (harm): `D` correct ∧ gated wrong ⇒ some verified incorrect value | `gate_harm` | Gate | proved. **Differs:** §4's `hne : vals.Nonempty` is not needed (the statement holds for empty `vals` too) |
| **Corollary 1** no-loss: no verified incorrect value ⇒ (`D` correct ⇒ gated correct) | `gate_no_loss` | Gate | proved; §4's `hne` not needed |
| Corollary 1, exact characterization: gated correct ⇔ (some correct value verified) ∨ (`W = ∅` ∧ `D` correct) | `gate_correct_iff` | Gate | proved |
| **Corollary 1** counting form `c_D ≤ F` over a finite item set | `gate_cD_le_F` | Gate | proved via `Finset.card_le_card`; slot data and `sel` may vary per item |

Not covered, as §3 states: `D` versus the evaluator's random-tie MAJ, member-level (mixed) correctness, and
agents asserting two values in one slot. These are outside the hypotheses, not counterexamples.

## Not formalised

- Floating-point error in computing `raw * lf` in `f64`. The model uses exact field arithmetic, and the
  quantisation model assumes `|q − 10000·f| ≤ ½` for the exact score.
- Schulze itself. Lemma 1 holds for *any* selector `T ε` with `T ε X ∈ X`, which covers dimension-level
  Schulze at every indifference threshold `ε`.
- The remark that false-positive counts are not linear in `w` (after Corollary 2) is prose about an
  empirical statistic.
