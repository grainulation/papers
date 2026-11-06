/-
Paper, Appendix B.4 — Proposition 3 (evidence with bounded side-channels) and
the default-weights consequence.
-/
import OverturnLean.Separation

namespace Overturn

variable {K : Type*} [Field K] [LinearOrder K] [IsStrictOrderedRing K]
variable {α : Type*}

/-- **Proposition 3 (Evidence with bounded side-channels).**
`γ` is any lower bound on the lowering-weighted evidence gap `d₀` over all
(correct, incorrect) pairs, and `β i` (i = 1..4) any upper bound on `−dᵢ`.
(The paper's `γ = min d₀` and `βᵢ = max (max 0 (−dᵢ))` are such bounds.)
If `w ≥ 0` and `w₀γ − Σᵢ₌₁⁴ wᵢβᵢ > δ`, then `S` is score-separated. -/
theorem prop2 (S : Finset α) (correct : α → Prop) (cand : α → Cand K)
    (w : Fin 5 → K) (hw : ∀ i, 0 ≤ w i) (γ δ : K) (β : Fin 5 → K)
    (hγ : ∀ p ∈ S, ∀ m ∈ S, correct p → ¬ correct m → γ ≤ dvec (cand p) (cand m) 0)
    (hβ : ∀ p ∈ S, ∀ m ∈ S, correct p → ¬ correct m →
      ∀ i, i ≠ 0 → -β i ≤ dvec (cand p) (cand m) i)
    (h : δ < w 0 * γ - (w 1 * β 1 + w 2 * β 2 + w 3 * β 3 + w 4 * β 4)) :
    Separated S correct (fun a => score w (cand a)) δ := by
  intro p hp m hm hpc hmc
  rw [score_sub_eq_dot, dot_five]
  have b := hβ p hp m hm hpc hmc
  have e0 := mul_le_mul_of_nonneg_left (hγ p hp m hm hpc hmc) (hw 0)
  have e1 := mul_le_mul_of_nonneg_left (b 1 (by decide)) (hw 1)
  have e2 := mul_le_mul_of_nonneg_left (b 2 (by decide)) (hw 2)
  have e3 := mul_le_mul_of_nonneg_left (b 3 (by decide)) (hw 3)
  have e4 := mul_le_mul_of_nonneg_left (b 4 (by decide)) (hw 4)
  nlinarith

/-- With no knowledge of the side channels (`βᵢ = 1`) and `Σ w = 1`,
the Proposition 3 condition reads `w₀γ − (1 − w₀) > δ`. -/
theorem prop2_condition_unit_beta (w : Fin 5 → K) (hsum : dot w (fun _ => 1) = 1) (γ δ : K) :
    (δ < w 0 * γ - (w 1 * 1 + w 2 * 1 + w 3 * 1 + w 4 * 1)) ↔ (δ < w 0 * γ - (1 - w 0)) := by
  rw [dot_five] at hsum
  constructor <;> intro h <;> linarith

/-- Under the default weights with `βᵢ = 1` and `δ = 0.05`, the condition
is equivalent to `γ > 2`. -/
theorem default_condition_iff_gamma_gt_two (γ : K) :
    ((5 : K) / 100 < wdef 0 * γ - (wdef 1 * 1 + wdef 2 * 1 + wdef 3 * 1 + wdef 4 * 1)) ↔
      2 < γ := by
  simp only [wdef]
  norm_num
  constructor <;> intro h <;> linarith

/-- **Default-weights consequence of Proposition 3.** With `βᵢ = 1`, `w = wdef` and any `δ ≥ 0`,
no `γ ≤ 1` satisfies the Proposition 3 condition. -/
theorem default_weights_no_gamma (γ δ : K) (hγ : γ ≤ 1) (hδ : 0 ≤ δ) :
    ¬ (δ < wdef 0 * γ - (wdef 1 * 1 + wdef 2 * 1 + wdef 3 * 1 + wdef 4 * 1)) := by
  simp only [wdef]
  norm_num
  linarith

/-- Stronger: under the default weights even the maximal evidence gap `d₀ = 1`
does not give separation for any `δ ≥ 0` — the incorrect candidate wins
on all four side channels. -/
theorem default_max_evidence_gap_not_separated (δ : K) (hδ : 0 ≤ δ) :
    let cp : Cand K := ⟨![1, 0, 0, 0, 0], 1⟩
    let cm : Cand K := ⟨![0, 1, 1, 1, 1], 1⟩
    dvec cp cm 0 = 1 ∧ ¬ (δ < score wdef cp - score wdef cm) := by
  simp only [dvec, score, dot_five, wdef]
  norm_num
  linarith

end Overturn
