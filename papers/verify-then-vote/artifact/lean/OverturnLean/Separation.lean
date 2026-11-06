/-
Paper, Appendix B.4 — Definition 2 (score separation), Proposition 2
(deadband homogeneity), Lemma 1 (tie-breaker neutrality).

These are stated for an arbitrary score function `f : α → K`, so they apply to
`Score_w ∘ cand` (see `Overturn.score`) and to any other scoring.
-/
import OverturnLean.Basic

namespace Overturn

variable {K : Type*} [Field K] [LinearOrder K] [IsStrictOrderedRing K]
variable {α : Type*}

/-- **Definition 2 (Score separation), pairwise form.**
`S` is score-separated with margin `δ` if every correct member beats every
incorrect member by more than `δ`. -/
def Separated (S : Finset α) (correct : α → Prop) (f : α → K) (δ : K) : Prop :=
  ∀ p ∈ S, ∀ m ∈ S, correct p → ¬ correct m → δ < f p - f m

/-- `t` is a top-scoring member of `S`. -/
def IsTop (S : Finset α) (f : α → K) (t : α) : Prop := t ∈ S ∧ ∀ c ∈ S, f c ≤ f t

/-- The paper's deadband `D_δ = {c ∈ S : f c ≥ max f − δ}` (non-strict),
with the maximum taken at a top member `t`. -/
def InDeadband (S : Finset α) (f : α → K) (δ : K) (t c : α) : Prop :=
  c ∈ S ∧ f t - δ ≤ f c

/-- The implementation's deadband (`deadband_candidates`):
members *strictly* within `δ` of the top. -/
def InDeadbandStrict (S : Finset α) (f : α → K) (δ : K) (t c : α) : Prop :=
  c ∈ S ∧ f t - f c < δ

theorem inDeadbandStrict_imp (S : Finset α) (f : α → K) (δ : K) (t c : α) :
    InDeadbandStrict S f δ t c → InDeadband S f δ t c :=
  fun ⟨h, h'⟩ => ⟨h, by linarith⟩

/-- **Definition 2, min/max form.** With both correctness classes non-empty,
`min_{S⁺} f − max_{S⁻} f > δ` is equivalent to the pairwise form. -/
theorem separated_iff_min_sub_max (S : Finset α) (correct : α → Prop)
    [DecidablePred correct] (f : α → K) (δ : K)
    (hp : (S.filter correct).Nonempty) (hm : (S.filter (fun c => ¬ correct c)).Nonempty) :
    Separated S correct f δ ↔
      δ < (S.filter correct).inf' hp f - (S.filter (fun c => ¬ correct c)).sup' hm f := by
  constructor
  · intro h
    obtain ⟨p, hpS, hpe⟩ := Finset.exists_mem_eq_inf' hp f
    obtain ⟨m, hmS, hme⟩ := Finset.exists_mem_eq_sup' hm f
    rw [Finset.mem_filter] at hpS hmS
    rw [hpe, hme]; exact h p hpS.1 m hmS.1 hpS.2 hmS.2
  · intro h p hpS m hmS hpc hmc
    have h1 : (S.filter correct).inf' hp f ≤ f p :=
      Finset.inf'_le f (Finset.mem_filter.2 ⟨hpS, hpc⟩)
    have h2 : f m ≤ (S.filter (fun c => ¬ correct c)).sup' hm f :=
      Finset.le_sup' f (Finset.mem_filter.2 ⟨hmS, hmc⟩)
    linarith

/-- **Proposition 2 (i).** Every top-scoring member is correct.
Needs `S⁺ ≠ ∅` and `δ ≥ 0` (see `prop1_i_needs_nonneg_delta`). -/
theorem prop1_i {S : Finset α} {correct : α → Prop} {f : α → K} {δ : K}
    (hsep : Separated S correct f δ) (hδ : 0 ≤ δ) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : IsTop S f t) : correct t := by
  by_contra hc
  obtain ⟨p, hpS, hpc⟩ := hpos
  have h1 := hsep p hpS t ht.1 hpc hc
  have h2 := ht.2 p hpS
  linarith

/-- **Proposition 2 (ii).** Every member of the (non-strict) deadband is correct.
Needs `S⁺ ≠ ∅`; does not need `δ ≥ 0`. -/
theorem prop1_ii {S : Finset α} {correct : α → Prop} {f : α → K} {δ : K}
    (hsep : Separated S correct f δ) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : IsTop S f t) {c : α} (hc : InDeadband S f δ t c) : correct c := by
  by_contra hnc
  obtain ⟨p, hpS, hpc⟩ := hpos
  have h1 := hsep p hpS c hc.1 hpc hnc
  have h2 := ht.2 p hpS
  have h3 := hc.2
  linarith

/-- Proposition 2 (ii) for the implementation's strict deadband. -/
theorem prop1_ii_strict {S : Finset α} {correct : α → Prop} {f : α → K} {δ : K}
    (hsep : Separated S correct f δ) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : IsTop S f t) {c : α} (hc : InDeadbandStrict S f δ t c) : correct c :=
  prop1_ii hsep hpos ht (inDeadbandStrict_imp S f δ t c hc)

/-- Proposition 2 (i) is false without `δ ≥ 0`: a separated set (margin −2) whose top
member is incorrect. -/
theorem prop1_i_needs_nonneg_delta :
    ∃ (S : Finset Bool) (f : Bool → ℚ) (δ : ℚ) (t : Bool),
      Separated S (· = true) f δ ∧ (∃ p ∈ S, p = true) ∧ IsTop S f t ∧ ¬ t = true := by
  refine ⟨{true, false}, fun b => if b then 0 else 1, -2, false, ?_, ⟨true, by simp, rfl⟩, ?_, by simp⟩
  · intro p _ m _ hp hm
    subst hp; simp at hm; subst hm; norm_num
  · refine ⟨by simp, ?_⟩; intro c _; cases c <;> norm_num

/-- Proposition 2 is false without `S⁺ ≠ ∅`: separation is vacuous and the top is incorrect. -/
theorem prop1_needs_nonempty_pos :
    ∃ (S : Finset Bool) (f : Bool → ℚ) (t : Bool),
      Separated S (· = true) f 1 ∧ IsTop S f t ∧ InDeadband S f 1 t t ∧ ¬ t = true := by
  refine ⟨{false}, fun _ => 0, false, ?_, ⟨by simp, by simp⟩, ⟨by simp, by norm_num⟩, by simp⟩
  intro p hp _ _ hpc _; simp at hp; subst hp; simp at hpc

/-- **Lemma 1 (Tie-breaker neutrality, conditional).**
For any tie-breaker family `T ε` that returns a member of any non-empty
candidate set, if the candidate set `X` is a non-empty subset of `D_δ`
and `S` is separated, then `T ε X` has the same correctness as any top
member, for every indifference threshold `ε`. -/
theorem lemma1 {S : Finset α} {correct : α → Prop} {f : α → K} {δ : K}
    {E : Type*} (T : E → Finset α → α) (hT : ∀ ε X, X.Nonempty → T ε X ∈ X)
    (hsep : Separated S correct f δ) (hδ : 0 ≤ δ) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : IsTop S f t)
    (X : Finset α) (hXne : X.Nonempty) (hXD : ∀ c ∈ X, InDeadband S f δ t c) :
    ∀ ε, (correct (T ε X) ↔ correct t) := by
  intro ε
  have h1 : correct (T ε X) := prop1_ii hsep hpos ht (hXD _ (hT ε X hXne))
  have h2 : correct t := prop1_i hsep hδ hpos ht
  exact ⟨fun _ => h2, fun _ => h1⟩

/-- Lemma 1 for the implementation's candidate set `deadband_candidates()`
(strict deadband). -/
theorem lemma1_strict {S : Finset α} {correct : α → Prop} {f : α → K} {δ : K}
    {E : Type*} (T : E → Finset α → α) (hT : ∀ ε X, X.Nonempty → T ε X ∈ X)
    (hsep : Separated S correct f δ) (hδ : 0 ≤ δ) (hpos : ∃ p ∈ S, correct p)
    {t : α} (ht : IsTop S f t)
    (X : Finset α) (hXne : X.Nonempty) (hXD : ∀ c ∈ X, InDeadbandStrict S f δ t c) :
    ∀ ε, (correct (T ε X) ↔ correct t) :=
  lemma1 T hT hsep hδ hpos ht X hXne fun c hc => inDeadbandStrict_imp S f δ t c (hXD c hc)

end Overturn
