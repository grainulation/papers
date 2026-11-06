# History

## 2026-10-23: paper numbering

- The paper's statement numbering changed. `CATALOGUE.md`, `README.md` and the Lean comments follow the
  current paper: Section 3 has Definition 1, Proposition 1 and Corollary 1 (the gate); Appendix B.4 has
  Definition 2, Propositions 2 and 3, Corollary 2 and Lemma 1. Entries below keep the numbering in use
  when they were written. Theorem names are unchanged.

## 2026-10-21: initial formalisation

- Toolchain: elan installed user-local in `~/.elan`; Lean `leanprover/lean4:v4.35.0` (`lean-toolchain`);
  Mathlib `v4.35.0` (git tag, pinned in `lake-manifest.json`). Prebuilt oleans fetched with
  `lake exe cache get` (9031 files) in a few minutes. Mathlib is used for `convexHull`,
  `convex_halfSpace_gt`, `stdSimplex`, `Finset.inf'/sup'` and the `norm_num`/`linarith`/`nlinarith` tactics.
- Sources: the paper, `overturn/src/compiler.rs` (`quantize`, `SCORE_SCALE = 10_000`,
  `deadband_threshold = 500`, `deadband_candidates`, default weights), `overturn/src/ir.rs`
  (`LoweringConfidence::factor`: High 1.0, Medium 0.85, Low 0.5).
- Formalised Def 1 (pairwise and min/max forms), Prop 1 (i)/(ii) (real, strict and quantised), Lemma 1,
  Prop 2, the default-weights corollary, Cor 1 (both directions, any vertex set) and its full-simplex
  consequence, and the 0.815/0.830 counterexample over ℚ.
- Result: `lake build` succeeds with no `sorry`. The axiom audit shows only `propext`,
  `Classical.choice` and `Quot.sound`.

### Statement corrections found

1. Prop 1 (i) needs `δ ≥ 0`. It is false for negative `δ` (`prop1_i_needs_nonneg_delta`). The proof's
   `Score(c⁺) > Score(c*) + δ > Score(c*)` uses `δ > 0`; `δ ≥ 0` is enough.
2. Prop 1 and Lemma 1 need `S⁺ ≠ ∅`. The pairwise form of Def 1 is vacuous otherwise
   (`prop1_needs_nonempty_pos`). The notation paragraph assumes both classes non-empty, so Def 1 should
   restate this.
3. Lemma 1 implicitly needs `X ≠ ∅` and `T(X) ∈ X`. The implementation satisfies both, because the top
   member is always in its own strict deadband when the threshold is > 0.
4. Strict vs non-strict deadband. The paper's `D_δ` is non-strict (`≥ max − δ`), and the code's is strict
   (`top_q − q < 500`, on quantised scores). The strict set is a subset, so the paper's argument covers the
   code. Under ×10,000 rounding the strictness is required: real separation `> 0.05` only guarantees a
   rounded gap `≥ 500`, so a non-strict `≤ 500` deadband could admit an incorrect member
   (`quantized_nonstrict_fails`).
5. Mirror image (Scope paragraph). The mirror image is a correct example only if it **swaps the
   correctness labels** (correct = ev 0.80 / rec 1: Δ = 0.015 < δ). Swapping only recency gives scores
   0.865 vs 0.780, which is separated (margin 0.085).
6. Prop 2 needs `w ≥ 0`, which holds on `Δ⁴`. `γ` and `βᵢ` can be any valid bounds, not only the exact
   min/max.
7. Cor 1 holds for any generating set `V` with `W = conv V`, so `W ⊆ Δ⁴` is not used.

No other statement was found false. The default-weights arithmetic (`γ > 2.0`), the counterexample
scores (0.815 and 0.830) and `0.035 − 0.05 = −0.015` all check exactly.
