/-
Paper, Appendix B.4 — basic objects (scoring and notation).

A candidate `c` has a feature vector `x(c) = (ev, conf, cs, rec, ca)` and a
lowering factor `λ(c)`.  For a weight vector `w`,
`Score_w(c) = λ(c) * wᵀ x(c)` (compiler.rs: `raw * lf`).
Indices: 0 = ev, 1 = conf, 2 = cs, 3 = rec, 4 = ca.
-/
import Mathlib

namespace Overturn

variable {K : Type*} [Field K] [LinearOrder K] [IsStrictOrderedRing K]

/-- A candidate: feature vector and lowering factor. -/
structure Cand (K : Type*) where
  x : Fin 5 → K
  lam : K

/-- Inner product `wᵀ v` on `K⁵`. -/
def dot (w v : Fin 5 → K) : K := ∑ i, w i * v i

/-- `Score_w(c) = λ(c) · wᵀ x(c)`. -/
def score (w : Fin 5 → K) (c : Cand K) : K := c.lam * dot w c.x

/-- Per-dimension weighted difference `d(c⁺,c⁻) = λ⁺ x⁺ − λ⁻ x⁻`. -/
def dvec (cp cm : Cand K) : Fin 5 → K := fun i => cp.lam * cp.x i - cm.lam * cm.x i

/-- The implementation's default weights `[0.35, 0.20, 0.25, 0.05, 0.15]`. -/
def wdef : Fin 5 → K := ![35/100, 20/100, 25/100, 5/100, 15/100]

omit [LinearOrder K] [IsStrictOrderedRing K] in
theorem dot_five (w v : Fin 5 → K) :
    dot w v = w 0 * v 0 + w 1 * v 1 + w 2 * v 2 + w 3 * v 3 + w 4 * v 4 := by
  simp [dot, Fin.sum_univ_five]

omit [LinearOrder K] [IsStrictOrderedRing K] in
/-- `Score_w(c⁺) − Score_w(c⁻) = wᵀ d(c⁺,c⁻)`. -/
theorem score_sub_eq_dot (w : Fin 5 → K) (cp cm : Cand K) :
    score w cp - score w cm = dot w (dvec cp cm) := by
  simp only [score, dot, dvec, Finset.mul_sum, ← Finset.sum_sub_distrib]
  exact Finset.sum_congr rfl fun i _ => by ring

/-- If features and lowering factors lie in `[0,1]`, then `d ∈ [-1,1]⁵`
(so `γ ≤ 1` and `β_i ≤ 1`). -/
theorem dvec_mem_Icc (cp cm : Cand K)
    (hp : ∀ i, 0 ≤ cp.x i ∧ cp.x i ≤ 1) (hm : ∀ i, 0 ≤ cm.x i ∧ cm.x i ≤ 1)
    (hlp : 0 ≤ cp.lam ∧ cp.lam ≤ 1) (hlm : 0 ≤ cm.lam ∧ cm.lam ≤ 1) (i : Fin 5) :
    -1 ≤ dvec cp cm i ∧ dvec cp cm i ≤ 1 := by
  obtain ⟨a0, a1⟩ := hp i; obtain ⟨b0, b1⟩ := hm i
  obtain ⟨l0, l1⟩ := hlp; obtain ⟨m0, m1⟩ := hlm
  have h1 : cp.lam * cp.x i ≤ 1 := by nlinarith
  have h2 : cm.lam * cm.x i ≤ 1 := by nlinarith
  have h3 : 0 ≤ cp.lam * cp.x i := mul_nonneg l0 a0
  have h4 : 0 ≤ cm.lam * cm.x i := mul_nonneg m0 b0
  simp only [dvec]; constructor <;> linarith

end Overturn
