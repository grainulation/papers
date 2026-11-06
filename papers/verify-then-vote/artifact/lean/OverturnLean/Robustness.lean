/-
Paper, Appendix B.4 — Corollary 2 (weight robustness over a polytope) and the
full-simplex consequence.
-/
import OverturnLean.Separation

namespace Overturn

variable {α : Type*}

theorem dot_isLinearMap (d : Fin 5 → ℝ) : IsLinearMap ℝ (fun w : Fin 5 → ℝ => dot w d) :=
  ⟨fun a b => by simp [dot, add_mul, Finset.sum_add_distrib],
   fun c a => by simp [dot, Finset.mul_sum, mul_assoc]⟩

/-- Separation of `Score_w` is, pairwise, the half-space condition `wᵀd > δ`. -/
theorem separated_score_iff (S : Finset α) (correct : α → Prop) (cand : α → Cand ℝ)
    (w : Fin 5 → ℝ) (δ : ℝ) :
    Separated S correct (fun a => score w (cand a)) δ ↔
      ∀ p ∈ S, ∀ m ∈ S, correct p → ¬ correct m → δ < dot w (dvec (cand p) (cand m)) := by
  simp only [Separated, score_sub_eq_dot]

/-- **Corollary 2 (Weight robustness over a polytope).**
For any set of weight vectors `V` (e.g. the vertex set of a polytope `W`,
with `W = conv V`), `S` is score-separated for every `w ∈ conv V`
iff it is score-separated for every `w ∈ V`. -/
theorem cor1 (V : Set (Fin 5 → ℝ)) (S : Finset α) (correct : α → Prop)
    (cand : α → Cand ℝ) (δ : ℝ) :
    (∀ w ∈ convexHull ℝ V, Separated S correct (fun a => score w (cand a)) δ) ↔
      (∀ w ∈ V, Separated S correct (fun a => score w (cand a)) δ) := by
  constructor
  · intro h w hw; exact h w (subset_convexHull ℝ V hw)
  · intro h w hw
    rw [separated_score_iff]
    intro p hp m hm hpc hmc
    have hsub : V ⊆ {u | δ < dot u (dvec (cand p) (cand m))} := by
      intro v hv
      exact (separated_score_iff S correct cand v δ).1 (h v hv) p hp m hm hpc hmc
    exact convexHull_min hsub (convex_halfSpace_gt (dot_isLinearMap _) δ) hw

/-- The standard basis vector `eᵢ` (a vertex of `Δ⁴`). -/
def basisVec (i : Fin 5) : Fin 5 → ℝ := fun j => if i = j then 1 else 0

theorem dot_basisVec (i : Fin 5) (d : Fin 5 → ℝ) : dot (basisVec i) d = d i := by
  simp [dot, basisVec]

set_option linter.deprecated false in
/-- **Full-simplex consequence of Corollary 2.** Separation for every `w` in the full
simplex `Δ⁴` holds iff every pair dominates by more than `δ` on every
dimension: `dᵢ(c⁺,c⁻) > δ` for all `i` and all pairs. -/
theorem simplex_robust_iff (S : Finset α) (correct : α → Prop) (cand : α → Cand ℝ) (δ : ℝ) :
    (∀ w ∈ stdSimplex ℝ (Fin 5), Separated S correct (fun a => score w (cand a)) δ) ↔
      ∀ p ∈ S, ∀ m ∈ S, correct p → ¬ correct m → ∀ i, δ < dvec (cand p) (cand m) i := by
  rw [← convexHull_basis_eq_stdSimplex, cor1]
  constructor
  · intro h p hp m hm hpc hmc i
    have := (separated_score_iff S correct cand _ δ).1 (h (basisVec i) ⟨i, rfl⟩) p hp m hm hpc hmc
    rwa [dot_basisVec] at this
  · rintro h _ ⟨i, rfl⟩
    rw [separated_score_iff]
    intro p hp m hm hpc hmc
    have := h p hp m hm hpc hmc i
    change δ < dot (basisVec i) _
    rwa [dot_basisVec]

end Overturn
