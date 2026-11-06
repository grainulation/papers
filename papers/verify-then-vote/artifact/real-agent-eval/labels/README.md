# Grader validation labels

This directory holds the material for checking the two automatic graders against human labels:

- `v1`: the original token-overlap grader, `evaluate_v1.claim_matches_gt`;
- `v2`: the stricter grader, `evaluate_v2.match_v2`.

Once labels exist, the same material re-scores the headline tables and adjudicates the low precision
of admitted claims.

Labels are never pre-filled. Every label column starts empty. The labeling page hides the grader
verdicts until all items are labeled.

## Files

| file | what it is |
|---|---|
| `sample.py` | Draws the stratified, seeded sample and builds `label.html` from `label_template.html`. It only reads `../v3/results` and `../results`, and it does not rerun the Rust binary. |
| `SAMPLE.md` | Stratum sizes, weights, and which decisive sets are covered. Generated. |
| `sample.json` | Items, grader verdicts, stratum weights, and every contradiction set with each method's output. Generated. **It contains the verdicts, so do not open it before labeling.** |
| `sample.csv` | A flat, blind item table with empty label columns. Use it to label in a spreadsheet instead of the page. Generated. |
| `label.html` | The labeling page. It is self-contained and works from `file://`. Generated. |
| `label_template.html` | The page template. Edit this file, not `label.html`. |
| `GUIDE.md` | Label definitions and decision rules, with examples from claims that are not in the sample. |
| `analyze.py` | Agreement, grader precision and recall, re-scored tables, and precision adjudication. It uses only the standard library. |

## Steps

1. **Read `GUIDE.md`.** Settle the open decisions listed below before labeling.
2. **Label.** Open `real-agent-eval/labels/label.html` in a browser by double-clicking it or with
   `open label.html`. Enter a labeler id, for example `aid`.
   - Keys:
     - `t`, `f`, `p`, `u` set `correct`.
     - `y` and `n` set `matches_gold`.
     - `g` and `b` set `well_formed_extraction` (good or bad).
     - `/` focuses the notes field and `Esc` leaves it.
     - `←` and `→` (or `j` and `k`, or `Enter`) move between items, and `x` jumps to the next unlabeled item.
   - Progress autosaves to this browser's localStorage, keyed by sample sha and labeler id. Export often
     anyway, because a private window or cleared site data loses localStorage.
   - Click **Export CSV**. It downloads `labels_<id>.csv`. Move the file into this directory.
   - To resume on another machine or browser, use **Import CSV**.
3. **Optional second labeler.** They work independently, under a different id and from the same
   `label.html`. They export `labels_<id2>.csv`.
4. **Analyze.** Run:

   ```sh
   cd real-agent-eval/labels
   python3 analyze.py labels_aid.csv                               # one labeler
   python3 analyze.py labels_aid.csv labels_bob.csv --primary aid  # adds human-vs-human kappa
   python3 analyze.py labels_aid.csv --boot 10000 --out analysis.md   # also writes analysis.json
   ```

   Partial label files work. Sections cover only the items that are labeled, and a headline set is
   re-scored only once all its members are labeled.
5. **Discuss.** After exporting, open the page's *Reveal grader verdicts* panel. It is enabled only when
   every item is labeled. `analysis.json` lists every item where the human and the stricter grader disagree
   (`v2_disagreements`).

To regenerate the sample (for example with other quotas), run `python3 sample.py --help`. Any change
produces a new sample sha. Labels exported against the old sha no longer line up, and `analyze.py` warns
about the mismatch.

## What the sample contains

Current defaults: 232 items with sample sha `64a3b043268ff2f1`. The full table is in `SAMPLE.md`.

The universe is the 972 v3 contributions plus the 1055 original v1 contributions. Deduplicating identical
claims, by question, raw sentence and triple, leaves 1956 distinct claims. Each claim goes in one primary
stratum, assigned by priority:

| stratum | population | sampled |
|---|---|---|
| conflict_decisive: members of any set that is decisive under either grader (Tables A and B, both datasets) | 95 | 95 (census) |
| conflict_eligible: members of eligible sets that are not decisive | 44 | 44 (census) |
| precision_extra-but-true | 751 | 20 |
| precision_extraction-garbage | 660 | 17 |
| precision_grader-miss | 117 | 6 |
| precision_incorrect | 4 | 4 |
| grader_disagree: v1 and v2 disagree, and the claim is in no stratum above | 30 | 30 (census) |
| control_agree_yes / control_agree_no | 66 / 189 | 8 / 8 |

In the precision strata, the category is the heuristic from the adjudication sheets. It is used only for
stratifying.

Of the 257 distinct claims on which the two graders disagree, 79 are in the sample. Every disagreement in
the conflict strata and in `grader_disagree` is included. The rest sit in the precision strata and are
sampled at those strata's rates, mostly from `precision_grader-miss`. All 139 conflict members are
included, so every winner of every method in every decisive or eligible set is labeled.

Before sampling, `sample.py` checks itself: it reproduces every row of every `v3/results/paired_decisions_*.csv`
from the stored Rust outputs and aborts on any mismatch.

## What analyze.py reports

1. **Coverage**: labeled items by labeler and stratum.
2. **Cohen's kappa** for human `matches_gold` against v1 and against v2, and for human
   `well_formed_extraction = no` against the heuristic garbage flag. It repeats the grader comparisons on
   well-formed items only, and adds human-vs-human kappa on all three fields. It reports the sample kappa
   and a population-weighted kappa (weights N_h/n_h), each with a 95% CI from a bootstrap stratified by
   sampling stratum.
3. **Grader precision and recall** against human `matches_gold`, unweighted and weighted, plus a
   per-stratum table.
4. **Headline tables re-scored** for v3 and v1orig, Tables A and B. The variants are:
   - human `matches_gold`;
   - human `correct == true`, as a sensitivity check;
   - v1 and v2 grader rows over the same labeled sets, as a reproduction check.

   Each table gives eligible and decisive counts, the McNemar b/c and exact p against majority, and a
   question-cluster bootstrap of Rust minus majority. With the full sample labeled, the grader rows
   reproduce `v3/RESULTS.md` exactly. This was tested with synthetic labels that mirror the v2 grader.
5. **Precision adjudication** of the three sheets:
   - `precision_adjudication_v3.csv`;
   - `precision_adjudication_v1orig.csv`;
   - the older Python-reducer sheet `../results/precision_adjudication.csv`.

   For each it gives the heuristic category against the human category, estimated row counts
   post-stratified onto each sheet's heuristic counts, and an adjusted precision.

The human category is derived from the three labels in this order: `well_formed = no` gives
extraction-garbage; otherwise `matches_gold = yes` gives grader-miss; otherwise `correct` gives true
(extra-but-true), false (incorrect), partially or unclear.

## Decisions for the author

- **Pronoun subjects.** `GUIDE.md` resolves a pronoun or elided subject from the question when the
  reference is unambiguous, and judges content apart from extraction. v2 rejects bare-pronoun subjects
  by design, so this rule lowers human-v2 agreement on those items. The well-formed-only kappa
  separates out that effect. If you would rather judge the triple strictly as extracted, change the
  guide before labeling.
- **The bar for `well_formed_extraction`.** The guide counts any non-content prefix in the subject as
  malformed: bullets, bold markers, headings, `Claim:`, `Yes,`, `However,`. The reason is that the reducer
  keys slots on the exact subject string. This is strict, and many items will be `no`. Loosen it before
  labeling if you only care whether the content survives.
- **Which human field drives the headline re-score.** The primary variant uses `matches_gold`, which is
  what the graders approximate. `correct == true` is reported as a sensitivity check. Choose which one the
  paper cites.
- **Sample size.** The sample has 232 items, above the target of about 200, because the conflict census
  alone is 139 items. To shrink it, lower `--precision-total`, `--precision-min` or `--control-each`. The
  conflict census cannot be cut without losing complete re-scoring.
- **Coverage limit.** Contradiction sets in which neither grader found a correct member were not sampled
  in full (about 140 of 238 sets). Human labels could make some of them eligible. `analyze.py` reports a
  lower bound (`missed`), but the eligible counts for those sets are not re-scored.
