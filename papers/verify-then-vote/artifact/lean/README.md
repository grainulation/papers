# Selection and gate guarantees in Lean 4

Machine-checked versions of the selection guarantees of Appendix B.4 ("Selection and its guarantees")
and the verify-then-vote harm bound of Section 3 ("Verify, Then Vote") of the paper.
Appendix D of the paper lists the statements and their theorem names.

The layout follows github.com/openai/math only in its structure: a Lean library, a catalogue that
maps each paper statement to a theorem name, and a history log. None of its content is used.

## Build

```sh
# one-time: install elan (user-local, no sudo)
curl -sSfL https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh | sh -s -- -y --default-toolchain none
export PATH="$HOME/.elan/bin:$PATH"

cd lean
lake exe cache get   # fetch prebuilt Mathlib oleans (~9k files); skip and lake builds Mathlib from source (hours)
lake build
```

The toolchain is pinned in `lean-toolchain` (Lean `v4.35.0`) and Mathlib is pinned to `v4.35.0` in
`lakefile.toml` / `lake-manifest.json`. `OverturnLean/Audit.lean` runs `#print axioms` on every catalogued
theorem. The build log should show only `propext`, `Classical.choice` and `Quot.sound`, and no `sorryAx`.

## Layout

| File | Contents |
|---|---|
| `OverturnLean/Basic.lean` | candidates, `score = λ·wᵀx`, `dvec`, default weights, `Score⁺−Score⁻ = wᵀd` |
| `OverturnLean/Separation.lean` | Definition 2, Proposition 2 (i)/(ii), Lemma 1, necessity examples |
| `OverturnLean/SufficientCondition.lean` | Proposition 3, default-weights consequence |
| `OverturnLean/Robustness.lean` | Corollary 2 (both directions), full-simplex consequence |
| `OverturnLean/Quantized.lean` | Proposition 2 for the ×10,000 integer implementation; strict-vs-non-strict |
| `OverturnLean/Counterexample.lean` | 0.815 vs 0.830 counterexample over ℚ, mirror image |
| `OverturnLean/Gate.lean` | verify, then vote (Section 3; `v3/GATE_SPEC.md` §3–§4): Proposition 1 (harm), Corollary 1 (`c_D ≤ F`, no-loss) |
| `OverturnLean/Audit.lean` | axiom audit |

See `CATALOGUE.md` for the statement → theorem map and `HISTORY.md` for the log.
