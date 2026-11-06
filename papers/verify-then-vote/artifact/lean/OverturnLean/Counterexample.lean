/-
Paper, Appendix B.4 — the counterexample ("Why the margin must cover the total
score", Figure 2): an evidence gap > δ does not imply separation. Computed
exactly over ℚ.
Default weights, lowering factor HIGH = 1.0, conf 0.5, cs 1, ca 1.
-/
import OverturnLean.SufficientCondition

namespace Overturn

/-- Correct candidate `c⁺`: ev 0.90, rec 0. -/
def cPlus : Cand ℚ := ⟨![9/10, 1/2, 1, 0, 1], 1⟩
/-- Incorrect candidate `c⁻`: ev 0.80, rec 1. -/
def cMinus : Cand ℚ := ⟨![8/10, 1/2, 1, 1, 1], 1⟩

/-- `δ = 0.05`. -/
def δ₀ : ℚ := 5/100

theorem score_cPlus : score wdef cPlus = 815/1000 := by
  norm_num [score, dot_five, wdef, cPlus]

theorem score_cMinus : score wdef cMinus = 830/1000 := by
  norm_num [score, dot_five, wdef, cMinus]

/-- The earlier condition holds: evidence gap `0.10 > δ`. -/
theorem old_condition_holds : δ₀ < cPlus.x 0 - cMinus.x 0 := by
  norm_num [δ₀, cPlus, cMinus]

/-- Yet the incorrect candidate scores strictly higher. -/
theorem incorrect_wins : score wdef cPlus < score wdef cMinus := by
  rw [score_cPlus, score_cMinus]; norm_num

/-- The two are within the deadband of each other (`|Δ| = 0.015 < δ`). -/
theorem within_deadband : score wdef cMinus - score wdef cPlus < δ₀ := by
  rw [score_cPlus, score_cMinus]; norm_num [δ₀]

/-- The conflict set `{c⁺, c⁻}` (indexed by `Bool`, `true` = correct). -/
def cands : Bool → Cand ℚ := fun b => if b then cPlus else cMinus

/-- It is not score-separated with margin `δ`. -/
theorem not_separated :
    ¬ Separated ({true, false} : Finset Bool) (· = true) (fun b => score wdef (cands b)) δ₀ := by
  intro h
  have := h true (by simp) false (by simp) rfl (by simp)
  simp only [cands, ite_true, Bool.false_eq_true, ite_false] at this
  rw [score_cPlus, score_cMinus] at this; norm_num [δ₀] at this

/-- The evidence-gap condition ("evidence gap > δ for every pair ⇒ separation")
is false. -/
theorem old_prop1_false :
    ¬ ∀ (S : Finset Bool) (cand : Bool → Cand ℚ),
      (∀ p ∈ S, ∀ m ∈ S, p = true → ¬ m = true → δ₀ < (cand p).x 0 - (cand m).x 0) →
      Separated S (· = true) (fun b => score wdef (cand b)) δ₀ := by
  intro h
  apply not_separated
  apply h
  intro p _ m _ hp hm
  subst hp; simp at hm; subst hm
  exact old_condition_holds

/-- The Proposition 3 quantities for the counterexample: `γ = 0.10`, `β_rec = 1`,
other `β = 0`; `w₀γ − w_rec β_rec = 0.035 − 0.05 = −0.015`, exactly the
observed score difference, and the Proposition 3 condition fails. -/
theorem prop2_quantities :
    dvec cPlus cMinus 0 = 1/10 ∧ dvec cPlus cMinus 1 = 0 ∧ dvec cPlus cMinus 2 = 0 ∧
    dvec cPlus cMinus 3 = -1 ∧ dvec cPlus cMinus 4 = 0 ∧
    wdef 0 * (1/10 : ℚ) - (wdef 1 * 0 + wdef 2 * 0 + wdef 3 * 1 + wdef 4 * 0) = -15/1000 ∧
    score wdef cPlus - score wdef cMinus = -15/1000 ∧
    ¬ (δ₀ < wdef 0 * (1/10 : ℚ) - (wdef 1 * 0 + wdef 2 * 0 + wdef 3 * 1 + wdef 4 * 0)) := by
  refine ⟨?_, ?_, ?_, ?_, ?_, ?_, ?_, ?_⟩ <;>
    norm_num [dvec, cPlus, cMinus, wdef, score, dot_five, δ₀]

/-- The "mirror image" (swap the correctness labels, so recency favours the
correct claim): selection is correct but `Δ_w = 0.015 < δ`, so correct
selection does not imply separation. -/
theorem mirror_correct_but_not_separated :
    score wdef cPlus < score wdef cMinus ∧
    ¬ (δ₀ < score wdef cMinus - score wdef cPlus) := by
  rw [score_cPlus, score_cMinus]; norm_num [δ₀]

/-- Note: swapping only the *recency* values (keeping labels) is NOT a
non-separated example: scores 0.865 vs 0.780, margin 0.085 > δ. -/
theorem recency_swap_is_separated :
    let cP : Cand ℚ := ⟨![9/10, 1/2, 1, 1, 1], 1⟩
    let cM : Cand ℚ := ⟨![8/10, 1/2, 1, 0, 1], 1⟩
    score wdef cP = 865/1000 ∧ score wdef cM = 780/1000 ∧ δ₀ < score wdef cP - score wdef cM := by
  norm_num [score, dot_five, wdef, δ₀]

end Overturn
