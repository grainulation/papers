# Supports cutoff T for hosted checker 0.2.0 (f2a14bd8988371bd231ca6ff137be13e)

**Chosen T: none.** No candidate meets the pre-fixed rule (smallest T with supports precision >= 0.95 on every
slice and recall within 10 points of "any"). Per the rule, the v5 exploratory check (step 4) is not run.
Script: `validation_table.py` (reads cached labels only; no model or hosted calls). Validation data only.

## Data used
- FEVER fresh2 (300; 100 gold supports): `results/fresh2_fever-f2a14bd8...jsonl`
- SciFact fresh2 (150, all NEI gold, so zero gold supports): `results/fresh2_scifact-f2a14bd8...jsonl`
- **SciFact-300 (`slice.jsonl`) has no 0.2.0 labels.** Its cached results are checker 76d44ce2 (0.1.0) and a local
  checker 41b9f3ec, neither of which is 0.2.0. It is excluded; fresh labels would need a hosted run.

## Validation table (n_sup / precision / recall)
| T | FEVER n_sup | FEVER prec | FEVER recall | SciFact n_sup (all false) | SciFact prec |
|---|---|---|---|---|---|
| any | 108 | .898 | .970 | 7 | 0 |
| 5000 | 106 | .896 | .950 | 3 | 0 |
| 6000 | 106 | .896 | .950 | 3 | 0 |
| 7000 | 106 | .896 | .950 | 2 | 0 |
| 8000 | 106 | .896 | .950 | 1 | 0 |
| 9000 | 100 | .910 | .910 | 0 | n/a |
| 9500 | 83 | .964 | .800 | 0 | n/a |
| 9700 | 77 | .961 | .740 | 0 | n/a |
| 9900 | 12 | 1.000 | .120 | 0 | n/a |

SciFact fresh2 has no gold supports, so recall is undefined and precision is 0 whenever any supports is emitted.

## score_q distribution of predicted supports
- FEVER: 72:1, 88:1, 8000:1, 8200:3, 8300:1, 8500:1, 9000:8, 9200:7, 9400:2, 9500:5, 9600:1, 9700:21, 9800:44, 9900:12.
  Coarse and top-heavy (71% at 9700-9900); there is no value above 9900. The 72 and 88 values look like a different scale.
- SciFact: 58, 62, 80, 88, 6500, 7000, 8000 (one each).

## Rule outcome
- FEVER first reaches precision >= .95 at T=9500, where recall is .80 (-17 points vs any). Fails the 10-point limit.
- T=9000 keeps recall (.91) but precision is .91. T=9700/9900 lose 23 / 85 points of recall.
- Verdict: no T satisfies both conditions, so none is chosen. Supports labels stay uncut.
