# v5 checker controls: results (exploratory, not preregistered)

Run 2026-10-23. Design: `README.md`. Full numbers: `results.json`. Calls: `calls.jsonl`.

## Population and calls

- Reconstruction of BE-G (`member/nei0.5/gated`) on set P from the sealed conf inputs
  reproduces the reported decisions on all 1,000 eligible P items (0 mismatches against
  `paired_decisions_v5.csv`): 526 decisive, b = 91, c = 12 vs MAJ.
- 88 of those 103 b/c items are gated overturns (78 b, 10 c). The other 15 (13 b, 2 c)
  differ from MAJ through the plurality default (tie-break), not an overturn, and have no
  witness.
- W: 118 witness pairs (107 on b items, 11 on c items; FEVER 37, SciFact 47, PopQA 34).
- R: 118 comparison pairs (seed `v5-controls`) from a pool of 1,645 supports pairs on
  non-overturning values (FEVER 38, SciFact 19, PopQA 61).
- Calls: 435 (199 distinct masked prompts, one per proposition; 236 shuffled), all
  status ok, all reporting `claude-sonnet-5-5`, checker id
  `f2a14bd8988371bd231ca6ff137be13e`, pinned CLI 2.1.307. Total cost **$1.91**.
  Every original prompt was re-rendered and reproduced its sealed `internal_check_key`.
  All 236 shuffled donors are within +-30% of the original passage length.

## Labels (value-mapped; every original label is `supports`)

| group | n | M: supports | M: refutes | M: NEI | M supports rate (Wilson 95%) | S: supports | S: refutes | S: NEI | S supports rate (Wilson 95%) |
|---|---|---|---|---|---|---|---|---|---|
| W (all) | 118 | 0 | 0 | 118 | 0.000 [0.000, 0.032] | 0 | 0 | 118 | 0.000 [0.000, 0.032] |
| W, b overturns | 107 | 0 | 0 | 107 | 0.000 [0.000, 0.035] | 0 | 0 | 107 | 0.000 [0.000, 0.035] |
| W, c overturns | 11 | 0 | 0 | 11 | 0.000 [0.000, 0.259] | 0 | 0 | 11 | 0.000 [0.000, 0.259] |
| W, FEVER | 37 | 0 | 0 | 37 | 0.000 [0.000, 0.094] | 0 | 0 | 37 | 0.000 [0.000, 0.094] |
| W, SciFact | 47 | 0 | 0 | 47 | 0.000 [0.000, 0.076] | 0 | 0 | 47 | 0.000 [0.000, 0.076] |
| W, PopQA | 34 | 0 | 0 | 34 | 0.000 [0.000, 0.102] | 0 | 0 | 34 | 0.000 [0.000, 0.102] |
| R (all) | 118 | 0 | 0 | 118 | 0.000 [0.000, 0.032] | 0 | 0 | 118 | 0.000 [0.000, 0.032] |
| R, FEVER | 38 | 0 | 0 | 38 | 0.000 [0.000, 0.092] | 0 | 0 | 38 | 0.000 [0.000, 0.092] |
| R, SciFact | 19 | 0 | 0 | 19 | 0.000 [0.000, 0.168] | 0 | 0 | 19 | 0.000 [0.000, 0.168] |
| R, PopQA | 61 | 0 | 0 | 61 | 0.000 [0.000, 0.059] | 0 | 0 | 61 | 0.000 [0.000, 0.059] |

## Counterfactual BE-G decisions on decisive P (n = 526)

Control labels substituted for the 118 W pairs only; the 88 affected items re-decided
with the frozen binary (Python mirror cross-checked on each); all other labels unchanged.

| labels | BE-G accuracy | b | c | MAJ accuracy |
|---|---|---|---|---|
| original (sealed) | 0.865 | 91 | 12 | 0.715 |
| M substituted | 0.740 | 15 | 2 | 0.715 |
| S substituted | 0.740 | 15 | 2 | 0.715 |

Exploratory: the substituted labels come from a different checker input (masked or
shuffled passage) than the sealed records describe, so these are sensitivity numbers,
not preregistered tests.

## Interpretation

With the passage withheld or replaced by an unrelated same-source passage, the checker
never returned `supports` on any of the 118 pairs that licensed an overturn (upper 95%
bound 3.2%) or on the 118 comparison pairs, so its `supports` labels depend on the passage
content, not on prior knowledge of the answer. Substituting those labels removes 76 of 91
corrections and 10 of 12 harms, and BE-G falls back to roughly the plurality default
(74.0% vs MAJ 71.5%), which locates the gain in the verified passages.

Caveat: under S the checker's confidence field was often on a 0-100 scale (median 98 of
10,000) although every label was `not_enough_info`; the label is all the gate reads.
