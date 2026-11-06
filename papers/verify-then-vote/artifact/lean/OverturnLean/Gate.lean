/-
Verified-overturn gate ("verify, then vote") — harm property.

Paper, Section 3 — Proposition 1 (harm requires a verified wrong answer) is `gate_harm`;
Corollary 1 (counting form `c_D ≤ F` and no-loss) is `gate_cD_le_F` and `gate_no_loss`.

Source: `v3/GATE_SPEC.md` §3 (harm property, its Corollaries 1 and 2) and §4 (Lean statement);
implementation `overturn/src/gate.rs`.

One contradiction slot is modelled by:
* `vals : Finset V` — the distinct values asserted in the slot;
* `n : V → ℕ` — the number of distinct agents asserting each value;
* `verified : V → Prop` — the value has a witness member (an accepted `supports` label);
* `correct : V → Prop` — gold correctness, as a function of the value;
* `sel : Finset V → V` — the ordinary P5 selection (score, deadband, Schulze, tie-break).

The only property of `sel` used anywhere is selection closure,
`hsel : ∀ S, S.Nonempty → sel S ∈ S`. No fact about scores, the deadband or Schulze is needed.
-/
import Mathlib

namespace Overturn.Gate

variable {V : Type*} [DecidableEq V]

/-- The plurality set `P`: the values of maximal agent count `n`. -/
def P (vals : Finset V) (n : V → ℕ) : Finset V :=
  vals.filter (fun v => ∀ u ∈ vals, n u ≤ n v)

/-- The verified set `W`: the values with at least one witness member. -/
def W (vals : Finset V) (verified : V → Prop) [DecidablePred verified] : Finset V :=
  vals.filter verified

/-- The default winner `D = sel(P)`. -/
def D (vals : Finset V) (n : V → ℕ) (sel : Finset V → V) : V :=
  sel (P vals n)

/-- The gated winner: `D` if `W = ∅`, otherwise `sel(W)`. -/
def gated (vals : Finset V) (n : V → ℕ) (verified : V → Prop) [DecidablePred verified]
    (sel : Finset V → V) : V :=
  if W vals verified = ∅ then D vals n sel else sel (W vals verified)

section Slot

variable (vals : Finset V) (n : V → ℕ) (verified : V → Prop) [DecidablePred verified]
  (correct : V → Prop) (sel : Finset V → V)

omit [DecidableEq V] in
/-- `P` is non-empty when `vals` is: a finite non-empty set has an `n`-maximal member. -/
theorem P_nonempty (hne : vals.Nonempty) : (P vals n).Nonempty := by
  obtain ⟨v, hv, hmax⟩ := Finset.exists_max_image vals n hne
  exact ⟨v, Finset.mem_filter.2 ⟨hv, hmax⟩⟩

omit [DecidableEq V] in
/-- The default winner is a plurality value. -/
theorem D_mem_P (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S) (hne : vals.Nonempty) :
    D vals n sel ∈ P vals n :=
  hsel _ (P_nonempty vals n hne)

omit [DecidableEq V] in
/-- The default winner is one of the slot's values. -/
theorem D_mem_vals (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S) (hne : vals.Nonempty) :
    D vals n sel ∈ vals :=
  (Finset.mem_filter.1 (D_mem_P vals n sel hsel hne)).1

/-- Rule 2: with no verified value, the gated winner is `D`. -/
theorem gated_eq_D (hW : W vals verified = ∅) : gated vals n verified sel = D vals n sel := by
  simp [gated, hW]

/-- Rule 3 + selection closure: if `W` is non-empty, the gated winner is in `W` (verified). -/
theorem gate_winner_verified (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S)
    (hW : (W vals verified).Nonempty) :
    gated vals n verified sel ∈ W vals verified := by
  unfold gated
  split_ifs with h
  · exact absurd h hW.ne_empty
  · exact hsel _ hW

/-- The gated winner is one of the slot's values. -/
theorem gated_mem_vals (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S) (hne : vals.Nonempty) :
    gated vals n verified sel ∈ vals := by
  by_cases hW : W vals verified = ∅
  · rw [gated_eq_D vals n verified sel hW]
    exact D_mem_vals vals n sel hsel hne
  · exact (Finset.mem_filter.1
      (gate_winner_verified vals n verified sel hsel (Finset.nonempty_iff_ne_empty.2 hW))).1

/-- **Harm property (paper Proposition 1; GATE_SPEC §3).** If the default winner `D` is correct and the gated winner
is not, then some value in `vals` is verified and incorrect (a checker false positive on a wrong
answer). Holds for every `vals`, including the empty one. -/
theorem gate_harm (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S) :
    correct (D vals n sel) → ¬ correct (gated vals n verified sel) →
    ∃ v ∈ vals, verified v ∧ ¬ correct v := by
  intro hD hG
  by_cases hW : W vals verified = ∅
  · rw [gated_eq_D vals n verified sel hW] at hG
    exact absurd hD hG
  · obtain ⟨hmem, hver⟩ := Finset.mem_filter.1
      (gate_winner_verified vals n verified sel hsel (Finset.nonempty_iff_ne_empty.2 hW))
    exact ⟨_, hmem, hver, hG⟩

/-- **No-loss (paper Corollary 1; GATE_SPEC §3, Corollary 2).** If every verified value is correct, then `D` correct
implies the gated winner correct. -/
theorem gate_no_loss (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S)
    (hF : ∀ v ∈ vals, verified v → correct v) :
    correct (D vals n sel) → correct (gated vals n verified sel) := by
  intro hD
  by_contra hG
  obtain ⟨v, hv, hver, hnc⟩ := gate_harm vals n verified correct sel hsel hD hG
  exact hnc (hF v hv hver)

/-- **No-loss, exact characterization (paper Corollary 1; GATE_SPEC Corollary 2, full form).** With no verified incorrect value, the gated winner is correct iff
some correct value is verified, or `W = ∅` and `D` is correct. -/
theorem gate_correct_iff (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S)
    (hF : ∀ v ∈ vals, verified v → correct v) :
    correct (gated vals n verified sel) ↔
      (∃ v ∈ vals, verified v ∧ correct v) ∨ (W vals verified = ∅ ∧ correct (D vals n sel)) := by
  by_cases hW : W vals verified = ∅
  · rw [gated_eq_D vals n verified sel hW]
    constructor
    · exact fun h => Or.inr ⟨hW, h⟩
    · rintro (⟨v, hv, hver, -⟩ | ⟨-, h⟩)
      · have hvW : v ∈ W vals verified := Finset.mem_filter.2 ⟨hv, hver⟩
        rw [hW] at hvW
        exact absurd hvW (Finset.notMem_empty v)
      · exact h
  · obtain ⟨hmem, hver⟩ := Finset.mem_filter.1
      (gate_winner_verified vals n verified sel hsel (Finset.nonempty_iff_ne_empty.2 hW))
    have hc := hF _ hmem hver
    exact ⟨fun _ => Or.inl ⟨_, hmem, hver, hc⟩, fun _ => hc⟩

end Slot

section Count

/-! Counting over items. Every slot ingredient may vary by item `i`. -/

variable {ι : Type*} (items : Finset ι) (vals : ι → Finset V) (n : ι → V → ℕ)
  (verified : ι → V → Prop) [∀ i, DecidablePred (verified i)]
  (correct : ι → V → Prop) [∀ i, DecidablePred (correct i)] (sel : ι → Finset V → V)

/-- **Counting form `c_D ≤ F` (paper Corollary 1; GATE_SPEC Corollary 1).** The number of items where `D` is correct and the gated winner is
wrong is at most the number of items where some incorrect value is verified. -/
theorem gate_cD_le_F (hsel : ∀ i, ∀ S : Finset V, S.Nonempty → sel i S ∈ S) :
    (items.filter (fun i => correct i (D (vals i) (n i) (sel i)) ∧
        ¬ correct i (gated (vals i) (n i) (verified i) (sel i)))).card ≤
      (items.filter (fun i => ∃ v ∈ vals i, verified i v ∧ ¬ correct i v)).card := by
  apply Finset.card_le_card
  intro i hi
  obtain ⟨hi, hD, hG⟩ := Finset.mem_filter.1 hi
  exact Finset.mem_filter.2
    ⟨hi, gate_harm (vals i) (n i) (verified i) (correct i) (sel i) (hsel i) hD hG⟩

end Count

end Overturn.Gate
