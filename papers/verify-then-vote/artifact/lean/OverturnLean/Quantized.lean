/-
Paper, Appendix B.4 — Proposition 2 for the ×10,000 integer-quantized
implementation (compiler.rs: `quantize`, `deadband_candidates`).

Model: `q a` is any integer with `|q a − 10000·f a| ≤ 1/2`
(true of `(score * 10000.0).round()` for exact real scores; floating-point
error in computing `f` itself is not modelled).  The integer threshold `Q`
corresponds to `δ = Q / 10000` (implementation: `Q = 500`, `δ = 0.05`).
-/
import OverturnLean.Separation

namespace Overturn

variable {α : Type*}

/-- Real separation `> Q/10000` gives an integer gap `≥ Q` after rounding. -/
theorem quantized_gap {fp fm : ℝ} {qp qm Q : ℤ}
    (hp : |(qp : ℝ) - 10000 * fp| ≤ 1 / 2) (hm : |(qm : ℝ) - 10000 * fm| ≤ 1 / 2)
    (h : (Q : ℝ) / 10000 < fp - fm) : Q ≤ qp - qm := by
  rw [abs_le] at hp hm
  have : ((Q : ℝ) - 1) < (qp : ℝ) - qm := by
    have : (Q : ℝ) < 10000 * (fp - fm) := by
      have := mul_lt_mul_of_pos_left h (by norm_num : (0:ℝ) < 10000); linarith [this,
        show (10000 : ℝ) * ((Q : ℝ) / 10000) = Q by ring]
    linarith [hp.1, hp.2, hm.1, hm.2]
  have h' : Q - 1 < qp - qm := by exact_mod_cast this
  omega

/-- **Proposition 2 (i), quantized.** Every member with maximal quantized score is
correct (so the implementation's first-maximum winner is correct). -/
theorem prop1_i_quantized {S : Finset α} {correct : α → Prop} {f : α → ℝ} {q : α → ℤ}
    (hq : ∀ a ∈ S, |(q a : ℝ) - 10000 * f a| ≤ 1 / 2) {Q : ℤ} (hQ : 0 < Q)
    (hsep : Separated S correct f ((Q : ℝ) / 10000)) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : t ∈ S ∧ ∀ c ∈ S, q c ≤ q t) : correct t := by
  by_contra hc
  obtain ⟨p, hpS, hpc⟩ := hpos
  have := quantized_gap (hq p hpS) (hq t ht.1) (hsep p hpS t ht.1 hpc hc)
  have := ht.2 p hpS
  omega

/-- **Proposition 2 (ii), quantized, strict (as implemented).** Every member of
`deadband_candidates()` — `top_q − q c < Q` — is correct. -/
theorem prop1_ii_quantized {S : Finset α} {correct : α → Prop} {f : α → ℝ} {q : α → ℤ}
    (hq : ∀ a ∈ S, |(q a : ℝ) - 10000 * f a| ≤ 1 / 2) {Q : ℤ}
    (hsep : Separated S correct f ((Q : ℝ) / 10000)) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : t ∈ S ∧ ∀ c ∈ S, q c ≤ q t) {c : α} (hcS : c ∈ S) (hc : q t - q c < Q) :
    correct c := by
  by_contra hnc
  obtain ⟨p, hpS, hpc⟩ := hpos
  have := quantized_gap (hq p hpS) (hq c hcS) (hsep p hpS c hcS hpc hnc)
  have := ht.2 p hpS
  omega

/-- The **non-strict** quantized deadband `top_q − q c ≤ Q` is *not* safe:
real margin `0.05004 > 0.05`, but after rounding the gap is exactly 500,
so the incorrect member would enter a `≤ 500` deadband.  The strict `<` in
`deadband_candidates()` is load-bearing. -/
theorem quantized_nonstrict_fails :
    ∃ (S : Finset Bool) (f : Bool → ℝ) (q : Bool → ℤ),
      (∀ a ∈ S, |(q a : ℝ) - 10000 * f a| ≤ 1 / 2) ∧
      Separated S (· = true) f ((500 : ℤ) / 10000 : ℝ) ∧
      (true ∈ S ∧ ∀ c ∈ S, q c ≤ q true) ∧
      false ∈ S ∧ q true - q false ≤ 500 ∧ ¬ (false = true) := by
  refine ⟨{true, false}, fun b => if b then 5004 / 100000 else 0,
    fun b => if b then 500 else 0, ?_, ?_, ?_, by simp, by norm_num, by simp⟩
  · intro a _; cases a <;> norm_num [abs_le]
  · intro p _ m _ hp hm
    subst hp; simp at hm; subst hm; norm_num
  · refine ⟨by simp, ?_⟩; intro c _; cases c <;> norm_num

end Overturn
