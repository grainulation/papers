# Verified-overturn gate ("verify, then vote"): rule, harm property, dev check

Status: implemented 2026-10-22 in `bran/src/gate.rs` (policy field `evidence.overturn_gate`), mirrored in
`real-agent-eval/v5/evaluate_v5.py` (`mirror`, `_select`). No model was called. The dev numbers in §5 are
**dev-informed** (FRAMING §3.4 disclosure applies). The Lean proof is not written yet; §4 is its statement.

## 1. Policy field

- `evidence.overturn_gate`: `"none"` (default) or `"verified"`. It is serialized and hashed only when it is
  non-default. The default policy hash `dd8d36e6def3a6d598765e82d461a473`, the generic preset hash
  `b905878f08e54d92b5a6f1e73f0682f2`, and every existing policy, root and certificate hash are unchanged.
  Unknown values are rejected (`deny_unknown_fields` plus a closed enum).
- The gate acts on CONTRADICTION slots only. Scoring is untouched: every member keeps its `ScoreBreakdown` and
  `scores_q`, so a gated and an ungated reduction of the same sealed set have identical `scores_q`.
- **NEI factor 0** was already expressible as `evidence.support_factor.not_enough_info = 0`, because the range
  check is `[0, 1]`. Under it, an NEI-labelled citation contributes exactly 0 evidence, like a `refutes` label.
  An unchecked or refused citation keeps `unchecked_factor` (0.5 in v5). This is tested in
  `gate::tests::nei_factor_zero`.
- Each gated contradiction slot carries a trace in the output, `selections[].gate`:
  `{stage, default_winner, plurality_agents, candidates, witnesses, overturned}`. The id lists are sorted by
  id. Ungated outputs carry no `gate` key, so they are byte-identical to before.

## 2. Rule (one contradiction slot)

**Definitions.**

- **Value:** `(normalize_object(object), polarity)`. This is the key that P4 and `value_mode` use.
- **n(v):** the number of distinct `agent_id`s among the members of v. An agent that repeats a value counts
  once.
- **P (plurality set):** the values with maximal n(v).
- **Witness:** a member that carries at least one evidence item whose *effective* label is `supports`. The
  effective label comes from `evidence::effective_label`: a sealed `bran-support/1` record for this
  contribution and this capture, with status `ok`, from a checker in `accepted_checkers`. Labels from any
  other checker, and refused or failed checks, never verify.
- **W (verified set):** the values with at least one witness member.
- **select(S):** the ordinary P5 selection run on the members of the values in S only. It is unchanged from
  the ungated reducer: candidate mode, quantized score, deadband, Schulze, and `tiebreak_order`.

**Decision.**

1. The default winner is **D = select(P)**. With a unique plurality value, D is that value. A tied plurality is
   broken by the policy itself, among the tied values only.
2. If **W = ∅**, the winner is D (`stage = "plurality"`).
3. If **W ≠ ∅**, the winner is **select(W)** (`stage = "verified"`). D keeps the slot iff D ∈ W and the policy
   prefers it among the verified values.

So a verified minority overturns an unverified majority whatever the scores are. When the majority is itself
verified, the policy score decides between it and the verified minority. This is FRAMING §3.4's BE-G:
"restricted to verified candidates, the policy score selects among them, MAJ if none is verified". The one
refinement is that "MAJ" is D, a deterministic, order-free plurality, because the evaluator's MAJ breaks ties
with a seeded `random.Random`, which a reducer cannot reproduce.

**Interaction with deadband and Schulze.**

- Inside each stage, the deadband test (the top-2 gap of quantized scores, at value level in value mode) and
  the Schulze candidate set are computed over **that stage's candidates only**.
- A non-candidate never enters the deadband or the Schulze vote, even when its score is higher than every
  candidate's or within the threshold of the top.
- `in_deadband` and `schulze_winner` in the output describe the deciding stage.
- A single verified value never enters the deadband (in value mode, or in member mode with one member).
- In member mode, a stage's candidates are all members of its values, so two members of the *same* value can
  still meet in the deadband. That never changes the decided value.
- **Order-freeness** follows the base policy. With the v5 / `order_free` settings (recency weight 0,
  recency-free Schulze, `tiebreak_order = id`), the decision and the trace do not depend on input order or on
  arrival `seq` (`gate::tests::permutation_invariance`: 120 permutations × 3 modes × 2 NEI factors).

## 3. Harm property

Fix one slot. Let `correct : Value → Bool` be gold correctness, as a function of the value.

**Theorem (harm ⊆ checker false positives on wrong answers).** If D is correct and the gated winner is not,
then some incorrect value carries an accepted `supports` label.

*Proof.* Let w be the gated winner.

1. Suppose w = D. Then w is correct, which contradicts the assumption. So w ≠ D.
2. If W = ∅, then w = D by rule 2. So W ≠ ∅, and w = select(W).
3. select(S) returns a member of S. This holds because every step only picks among S's members:
   - argmax over S's members;
   - Schulze over a subset of them;
   - in value mode, a representative of one of S's values.

   Hence w ∈ W, so w has a witness member: its value carries an accepted `supports` label.
4. w is incorrect, so that label is a false positive on a wrong answer. ∎

**Corollary 1 (c ≤ F).** Over a set of items, let:

- c_D = #{D correct, gated wrong};
- F = #{some incorrect value carries an accepted `supports` label}.

Then every c_D item is an F item, so c_D ≤ F.

**Corollary 2 (no-loss when the checker makes no false positive).** On an item where no incorrect value is
verified:

- the gated winner is correct iff (some correct value is verified) or (W = ∅ and D is correct);
- in particular, it is correct whenever D is.

*Proof.* If W ≠ ∅, then W holds only correct values, so w ∈ W is correct. If W = ∅, then w = D. ∎

**What the property does not cover (stated so the Lean lemma matches the code).**

1. **D is not the evaluator's MAJ** on tied-plurality items. MAJ breaks ties at random and D by policy score.
   The bound is exact for c_D. Against MAJ, a tied item can add to c without a false support (§5: 0–2 such
   items on dev).
2. **Correctness is assumed to be value-level.** The v5 grader can grade two raw answers with the same
   canonical value differently (`objects_with_mixed_member_correctness`). Such an item is outside the
   theorem's hypothesis.
3. **An agent that asserts two different values in one slot** counts toward n of both. v5 has one answer per
   agent, so this case does not arise there.

## 4. Statement for the Lean proof (later; do not rebuild Lean now)

```lean
variable {V : Type} [DecidableEq V]
-- slot data
variable (vals : Finset V) (n : V → ℕ) (verified : V → Prop) [DecidablePred verified]
         (correct : V → Prop) (sel : Finset V → V)
-- the only property of P5 that the proof needs: selection closure
variable (hsel : ∀ S : Finset V, S.Nonempty → sel S ∈ S)

def P := vals.filter (fun v => ∀ u ∈ vals, n u ≤ n v)
def W := vals.filter verified
def D := sel (P vals n)
def gated := if (W vals verified) = ∅ then D vals n sel else sel (W vals verified)

theorem gate_harm (hne : vals.Nonempty) :
    correct (D vals n sel) → ¬ correct (gated vals n verified sel) →
    ∃ v ∈ vals, verified v ∧ ¬ correct v

theorem gate_no_loss (hne : vals.Nonempty) (hF : ∀ v ∈ vals, verified v → correct v) :
    correct (D vals n sel) → correct (gated vals n verified sel)
```

- The proof is case analysis on `W = ∅` plus `hsel` (P is non-empty because `vals` is finite and non-empty).
- The counting corollary c_D ≤ F is `Finset.card_le_card` on the item filter.
- The proof needs no fact about scores, the deadband or Schulze, only `hsel`. Bran's `select_slot` satisfies
  `hsel` by construction (§3, proof step 3), and the Rust tests check it on every gated overturn:
  `winner ∈ witnesses`, also asserted over every stored dev output by `test_gated_configs`.

## 5. Dev check (86 decisive conflicts; dev-informed)

**Inputs.** The run reused the sealed dev checks in `results/dev/checks.jsonl`, all made by the **old checker
`76d44ce22b1ea2f476539e36daacc81a`**. That is the only checker id in that file, and it is the accepted
checker. The checker 0.2.0 run (`results/dev_checker2/`) was not used, and no checker was called. Output is
in `real-agent-eval/v5/results/dev/eval_gate/` (summaries only).

**Reproduce.** The command regenerates the 6,400 reducer files under `<out>/rust/`:

```
python3 real-agent-eval/v5/evaluate_v5.py --split dev --bin bran/target/release/bran \
  --items real-agent-eval/v5/benchmark/items_dev.jsonl --raw-dir real-agent-eval/v5/results/dev/raw \
  --captures real-agent-eval/v5/results/dev/captures.jsonl --checks real-agent-eval/v5/results/dev/checks.jsonl \
  --judge real-agent-eval/v5/results/dev/judge.jsonl --accepted-checker 76d44ce22b1ea2f476539e36daacc81a --out <out>
```

**Integrity.**

- The Python mirror equals the binary on all 3,200 slots (160 items × 20 reductions), including the gate
  trace.
- The 2,560 stored reducer files of the original run (`results/dev/eval/rust/`) are reproduced byte for byte.
- `overturns_v5.jsonl`, `dev_gate_v5.json`, every original CSV column, and every original grid row are
  identical. BE is still `member/nei0.1` (b 17, c 8).

**Ungated grid** (the §5.1 six, plus NEI 0; acc on decisive items):

| config | dev-informed | changed | b | c | b − c | acc | template sha256 |
|---|---|---|---|---|---|---|---|
| `member/nei0.5` | no | 0 | 15 | 8 | 7 | 0.779 | `e405bc91…` |
| `member/nei0.1` (BE) | no | 1 | 17 | 8 | 9 | 0.802 | `d135c367…` |
| `member/nei0` | yes | 1 | 16 | 8 | 8 | 0.791 | `49e7bc33…` |
| `value:max/nei0.5` | no | 1 | 15 | 8 | 7 | 0.779 | `ded77eb8…` |
| `value:max/nei0.1` | no | 2 | 17 | 9 | 8 | 0.791 | `8547d78f…` |
| `value:max/nei0` | yes | 2 | 16 | 8 | 8 | 0.791 | `9eb94c15…` |
| `value:pooled/nei0.5` | no | 1 | 14 | 8 | 6 | 0.767 | `eb5ae5f6…` |
| `value:pooled/nei0.1` | no | 2 | 15 | 10 | 5 | 0.756 | `d517ada7…` |
| `value:pooled/nei0` | yes | 2 | 16 | 10 | 6 | 0.767 | `a5a331d4…` |

**Gated grid** (all dev-informed):

- b and c are against MAJ; b_D and c_D are against D.
- The VV column counts items that agree with VV on correctness, on the 77 decisive items with a unique
  plurality.
- **F = 2** (`v5-popqa601478`, `v5-tqa0202`). Nine decisive items have a tied plurality.
- Every configuration has `stage` = verified on 53 items and plurality on 33. This is exactly VV's 33
  fallbacks, so the gate's verified set equals VV's on every item.

| config | b | c | b_D | c_D | acc | McNemar p | VV agree (untied) | template sha256 |
|---|---|---|---|---|---|---|---|---|
| `member/nei0.5/gated` (**selected**) | 13 | 1 | 10 | 0 | 0.837 | 0.0018 | 77/77 | `fd9819cc330684b0…` |
| `member/nei0.1/gated` | 13 | 2 | 10 | 0 | 0.826 | 0.0074 | 77/77 | `c140f4bf…` |
| `member/nei0/gated` | 13 | 4 | 10 | 1 | 0.802 | 0.049 | 76/77 | `a0efd153…` |
| `value:max/nei0.5/gated` | 13 | 1 | 10 | 0 | 0.837 | 0.0018 | 77/77 | `8f29ce02…` |
| `value:max/nei0.1/gated` | 13 | 2 | 10 | 0 | 0.826 | 0.0074 | 77/77 | `afc79659…` |
| `value:max/nei0/gated` | 13 | 4 | 10 | 1 | 0.802 | 0.049 | 76/77 | `8e133738…` |
| `value:pooled/nei0.5/gated` | 13 | 2 | 10 | 0 | 0.826 | 0.0074 | 77/77 | `0112841f…` |
| `value:pooled/nei0.1/gated` | 13 | 4 | 10 | 1 | 0.802 | 0.049 | 76/77 | `329f7d43…` |
| `value:pooled/nei0/gated` | 13 | 4 | 10 | 1 | 0.802 | 0.049 | 76/77 | `ce5ce506…` |

- **Selection** (FRAMING §3.4: largest b − c, then smaller c, then fewer changed fields, then full-grid order)
  picks `member/nei0.5/gated`. It ties `value:max/nei0.5/gated` on b − c and c, and wins on changed fields.
- **Harm bound.** c_D ≤ F holds in every configuration, with every c_D item an F item (`harm_bound_holds`).
  The only c_D item is `v5-popqa601478`, at NEI 0 and in pooled/NEI 0.1:
  - D = "jacob" (correct) and is verified;
  - the minority "heli" (incorrect) also carries an accepted `supports` label, a checker false positive;
  - once NEI evidence stops counting, the policy score prefers "heli" among the verified values.

  This is exactly the harm the theorem allows.
- **VV equivalence.** FRAMING §0 says "restrict to verified candidates, else MAJ reproduces VV: b = 11,
  c = 0". On the 77 untied decisive items, the gated reducer reproduces VV exactly in every configuration
  with c_D = 0: b = 10, c = 0 for both. VV's remaining b = 1 comes from the 9 tied items. The differences
  from VV's 11 / 0 overall are all of one kind:
  - **Tied plurality, both fall back.** D (policy tie-break) differs from MAJ (random tie-break).
    - In the selected configuration, the tied items give b = 3, c = 1 against MAJ, against VV's 1 / 0 there.
      The three b items are VV's one plus `v5-popqa6268676` and `v5-popqa6269689`; the c item is
      `v5-tqa0731`.
    - `v5-tqa0007` is also lost in every configuration except member and value:max at NEI 0.5.
    - `v5-popqa1763729` is also lost in the four c_D = 1 configurations.
    - None of these involve a false support; they are the "D is not MAJ" caveat of §3.
  - **Both verified, score versus headcount.** This occurs only at NEI 0 and pooled/NEI 0.1, on
    `v5-popqa601478` above. There VV's verified headcount tie fell to "jacob" at random.
- **By source** (selected configuration; MAJ / gated / VV / BE correct):

  | source | items | MAJ | gated | VV | BE |
  |---|---|---|---|---|---|
  | FEVER | 19 | 16 | 18 | 18 | 17 |
  | PopQA | 16 | 9 | 13 | 11 | 13 |
  | SciFact | 29 | 20 | 27 | 27 | 28 |
  | TruthfulQA | 22 | 15 | 14 | 15 | 11 |

  The TQA "do no harm" stratum: gated loses 1 item against MAJ, while ungated BE loses 4.

**Hashes.**

- bran binary `af420a5def1a67043706f9d232d198b9244dae55b495c68f63de11e99d65045e`. The old binary `8f883e3e…`
  and the new one give byte-identical outputs on the 1,280 stored dev reductions (re-reduced) and on the five
  `--dump-artifact` topic dumps (N = 100, seed 42).
- `evaluate_v5.py` `cbd3eea09170d0bd1e50637b4eaf0295c70b5c1aff224fc16e67220d0af84774`.
- Policy hashes vary per item (the `incompatible_values` objects), so the templates above are the frozen
  identifiers, as PREREG_DECISIONS specifies.
