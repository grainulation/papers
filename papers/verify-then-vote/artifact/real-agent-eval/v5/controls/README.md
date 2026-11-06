# v5 checker controls: passage content vs checker prior knowledge (exploratory)

Status: **exploratory, not preregistered.** Added 2026-10-23 for a reviewer question:
do verify-then-vote's gains on set P come from the passage content, or from the strong
checker's (claude-sonnet-5-5) prior knowledge of the answer?

Nothing here changes a frozen file (`../FREEZE.json`), the real support store, or
`../results/conf/checks.jsonl`. All model calls are new, uncached, and logged in
`calls.jsonl` in this directory.

## Design (fixed before any control call was made)

Population (set P, BE-G = `member/nei0.5/gated`, conf split, real checker
`f2a14bd8988371bd231ca6ff137be13e`):

- **W (witness pairs):** every (proposition, passage) pair that licensed a BE-G gated
  overturn whose decision differs from MAJ on a decisive P item — the correct overturns
  (b: BE-G right, MAJ wrong) and the harmful ones (c: BE-G wrong, MAJ right). A licensing
  pair is an accepted, status-ok check whose label, mapped to the winning value, is
  `supports`, on a citation by an agent that proposed the winning value (the same
  definition as `evaluate_v5._witnesses`). Pairs are de-duplicated by check key.
- **R (comparison):** an equal-size random sample (seed `"v5-controls"`) of checked
  pairs on P items whose mapped label is `supports`, cited by an agent, for a value that
  was *not* a BE-G overturn winner on its item, and not in W.

All originals are `supports` (after the value's label map; for FEVER/SciFact REFUTED
answers the raw label on the claim is `refutes`). Labels below are reported on the same
value-mapped scale.

Conditions (same prompt template, same system prompt, same CLI flags, pinned client
version 2.1.307 on `PATH` or selected by `BRAN_CLAUDE_BIN`,
`DISABLE_AUTOUPDATER=1`, checker id verified):

- **M (masked):** the passage block is replaced by the fixed placeholder
  `[passage withheld]`. A `supports` here can only come from prior knowledge (or the
  proposition itself). The masked prompt depends only on the proposition, so it is
  queried once per distinct proposition and the label applies to all its pairs.
- **S (shuffled):** the passage is replaced by the span text of a passage drawn
  (seeded, `"v5-controls:S:<check_key>"`) from a different item of the same source,
  with: no passage shown to the target item; donor title not in the proposition and the
  target title not in the donor text; for PopQA the proposed value and subject not in the
  donor text; length within +-30% of the original passage (closest available otherwise).

Implementation reuses `tools/evidence/support/check.py` (`Checker`, `render_user`,
`Checker.call`) with a modified passage list; the support cache is bypassed (calls go
straight to `Checker.call`, nothing is written to any `SupportCache`). The original
prompt is re-rendered and must reproduce each check's `internal_check_key` (sanity
check that the control prompts differ only in the passage block).

Measures:

1. Label distribution per condition (M, S) vs the original label, for W and R; the
   `supports` rate with Wilson 95% CIs, split by b vs c and by source.
2. Counterfactual decisions: re-run BE-G on every P item with the control label
   substituted for each W pair (all other check labels unchanged), with the frozen
   binary (`../frozen-bin/bran`, cross-checked by the Python mirror), and report
   accuracy on decisive P and b/c vs MAJ, against the original. The substituted labels
   come from a different checker input than the sealed records describe, so these are
   exploratory sensitivity numbers, not preregistered tests.

Budget: at most $10 of hosted calls; a cost estimate (about $0.005/call) is made first
and the run stops if the projection exceeds $10.

## Files

- `controls_v5.py` — `build` (population + prompts), `run` (calls), `analyze`.
- `population.jsonl` — W and R pairs with condition prompts' hashes and donor keys.
- `calls.jsonl` — one row per hosted call: condition, check key, prompt sha256, label,
  status, cost.
- `results.json`, `RESULTS.md` — tables and counterfactuals.

## Verified wrong answers on P (`harm_reading.jsonl`)

There are 82 (incorrect answer, passage) pairs with an accepted, mapped supports label, spread over the 56 decisive P items counted in F. Two annotators, both Claude Opus 5.5 instances and each blind to the other's labels, assigned every pair to one of four classes:

- **K**: checker false support. The passage does not support the proposition as written.
- **E**: entity mismatch. The passage is accurate about a different, same-named entity.
- **S**: false or outdated source. The passage states something false or outdated about the intended entity.
- **G**: gold or grading. The field `gold_subclass` splits it three ways: `alias` (spelling or alias missing from gold), `alternative` (coarser or alternative answer the passage supports) and `disagreement` (the passage contradicts the gold label; a suspected gold issue).

Agreement: 79 of 82 pairs, Cohen's kappa 0.95. Kappa measures agreement between the two annotations. A third Claude Opus 5.5 pass adjudicated the three disagreements (pairs 25, 67, 76) against the definitions; they are marked `adjudicated`.

An item's class is the first of K, E, S, G that any of its pairs has.

| | K | E | S | G |
|---|---|---|---|---|
| Items (56) | 24 | 8 | 5 | 19 |
| Lost defaults (10, `lost_default`) | 5 | 1 | 1 | 3 |

Each row gives the item, value, proposition, passage key, both annotators' labels, the second annotator's rationale and the final class. Every reading can be checked against `captures.jsonl`.

Gold items (19) by subclass: 9 alias, 3 alternative, 7 disagreement. The 3 gold-class lost defaults are all disagreements.
