# Harm attribution (post hoc, exploratory)

**Caveat.** All of this was computed on the v5 **confirmatory** data after unblinding. None of it was
preregistered.
- The error classes come from a post hoc reading of the harm pairs (`../controls/harm_reading.jsonl`).
- The label replay in step 2 is a counterfactual edit of sealed labels, not a new measurement.
- The VDF variants were designed after looking at the harm cases (`../selector_study/README.md`).

Read every number as descriptive. None of them changes a preregistered result.

Files:
- `harm_attribution.py`: steps 1–3 and the step 4 population. It writes `results.json` and
  `stability_population.jsonl`.
- `stability/`: the prepared, **not run**, checker prompt-stability test: `SPEC.md`,
  `checker_stability.py`, `templates/paraphrase_{1,2,3}.txt` and `plan.json`.

Run with `python3 real-agent-eval/v5/harm_attribution/harm_attribution.py`, about 8 s. It makes no
model, hosted or Rust-binary call.

## Method

- **Reconstruction.** The script imports `../selector_study/selector_study.py` and uses its `decide`,
  `make_ctx` and dev trust weights. selector_study imports the frozen `evaluate_v5.py` unedited.
  - Every item is rebuilt with `prepare_item`.
  - BE-G is decided by `evaluate_v5.mirror`, and VV and MAJ by `python_methods`.
  - Before any analysis, the script checks two things:
    - MAJ, VV, BE-G and D (correctness and value) equal `paired_decisions_v5.csv` on all eligible
      items;
    - BE-G, VV, BE-G/VDF and VV/VDF reproduce selector_study's acc, b, c and c_D item lists on P
      and T.
- **Definitions.** These are the evaluator's:
  - b / c vs MAJ = `overturn()`;
  - c_D = the method's default right and the method wrong (D for BE-G and BE-G/VDF, MAJ for VV and
    VV/VDF);
  - overturn rate of right majorities = c / n_R, where n_R = items with MAJ right, with a Wilson
    95% CI and the one-sided 97.5% Clopper–Pearson upper bound `cp_upper(c, n_R, 0.025)`. This is
    H3a's statistic; its bound is 0.05.
- **Label replay (step 2).**
  - **What is flipped.** For each harm pair (item, passage, proposition) of class X, every accepted,
    status-ok `supports` label is set to `not_enough_info`, both on the citation audit (read by VV
    and W) and on the sealed support record (read by the reducer's scoring, xref eligibility and
    gate).
  - **Value level only.** A support record belongs to one contribution, so on FEVER and SciFact the
    other value, which shares the same check, keeps its label.
  - **Everything else is fixed:** captures, other labels, scores, policy and tie-break seeds.
  - **Re-decision.** BE-G, VV and the VDF variants are re-decided with the frozen logic.
  - **Checks.** Every one of the 82 pairs matched at least one support record, and every matched
    record belongs to a wrong value. T is unchanged in every scenario, as asserted.
- **Per-item split.** A baseline harm is attributed to class X when neutralizing X alone removes it.
  On P, BE-G has 12 harms vs MAJ, of which 10 are c_D. No harm was removed by more than one single
  class, and none needed a combination of classes. So the split is exact.

## Step 1: per-source harm breakdown (decisive items)

The columns from n_R to CP 97.5% UB describe the overturn of right majorities.

**BE-G** (published primary)

| set | source | n | MAJ acc | acc | b | c | c_D | n_R | c/n_R | Wilson 95% | CP 97.5% UB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | all | 526 | .7148 | .8650 | 91 | 12 | 10 | 376 | .0319 | [.0183, .0549] | .0551 |
| P | SciFact | 154 | .6883 | .8896 | 33 | 2 | 2 | 106 | .0189 | [.0052, .0662] | .0665 |
| P | PopQA | 173 | .6763 | .8035 | 30 | 8 | 6 | 117 | .0684 | [.0351, .1291] | .1303 |
| P | FEVER | 199 | .7688 | .8995 | 28 | 2 | 2 | 153 | .0131 | [.0036, .0464] | .0464 |
| T | TruthfulQA | 69 | .4493 | .5652 | 9 | 1 | 0 | 31 | .0323 | [.0057, .1619] | .1670 |

**VV**

| set | source | n | MAJ acc | acc | b | c | c_D | n_R | c/n_R | Wilson 95% | CP 97.5% UB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | all | 526 | .7148 | .8650 | 88 | 9 | 9 | 376 | .0239 | [.0126, .0449] | .0450 |
| P | SciFact | 154 | .6883 | .8831 | 33 | 3 | 3 | 106 | .0283 | [.0097, .0799] | .0805 |
| P | PopQA | 173 | .6763 | .8092 | 27 | 4 | 4 | 117 | .0342 | [.0134, .0846] | .0852 |
| P | FEVER | 199 | .7688 | .8995 | 28 | 2 | 2 | 153 | .0131 | [.0036, .0464] | .0464 |
| T | TruthfulQA | 69 | .4493 | .5217 | 6 | 1 | 1 | 31 | .0323 | [.0057, .1619] | .1670 |

**BE-G/VDF** (post hoc)

| set | source | n | MAJ acc | acc | b | c | c_D | n_R | c/n_R | Wilson 95% | CP 97.5% UB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | all | 526 | .7148 | .8688 | 87 | 6 | 4 | 376 | .0160 | [.0073, .0344] | .0344 |
| P | SciFact | 154 | .6883 | .8961 | 33 | 1 | 1 | 106 | .0094 | [.0017, .0515] | .0514 |
| P | PopQA | 173 | .6763 | .8092 | 26 | 3 | 1 | 117 | .0256 | [.0088, .0727] | .0731 |
| P | FEVER | 199 | .7688 | .8995 | 28 | 2 | 2 | 153 | .0131 | [.0036, .0464] | .0464 |
| T | TruthfulQA | 69 | .4493 | .5652 | 9 | 1 | 0 | 31 | .0323 | [.0057, .1619] | .1670 |

**VV/VDF** (post hoc)

| set | source | n | MAJ acc | acc | b | c | c_D | n_R | c/n_R | Wilson 95% | CP 97.5% UB |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P | all | 526 | .7148 | .8726 | 87 | 4 | 4 | 376 | .0106 | [.0041, .0270] | .0270 |
| P | SciFact | 154 | .6883 | .8961 | 33 | 1 | 1 | 106 | .0094 | [.0017, .0515] | .0514 |
| P | PopQA | 173 | .6763 | .8208 | 26 | 1 | 1 | 117 | .0085 | [.0015, .0468] | .0467 |
| P | FEVER | 199 | .7688 | .8995 | 28 | 2 | 2 | 153 | .0131 | [.0036, .0464] | .0464 |
| T | TruthfulQA | 69 | .4493 | .5217 | 6 | 1 | 1 | 31 | .0323 | [.0057, .1619] | .1670 |

What the per-source tables show:
- **PopQA carries BE-G's harm.** It has 8 of 12 harms vs MAJ and 6 of 10 c_D. Its rate is .068, with
  a CP upper bound of .130.
- **FEVER is the same, two harms, under all four methods.** These are fever80417 and fever90151, both
  of class G. VDF does not touch them.
- **No source has a CP upper bound below .05 except FEVER**, and for PopQA under VV/VDF. Per-source
  n_R is 106–153, so even c = 1 gives an upper bound of about .05.

## Step 2: label replay by error class (P, 526 decisive items)

The class sizes are K 36, E 15, S 6 and G 25 pairs, 82 in all. G splits into alias 13, alternative
5 and disagreement 7. In the table, "pairs" = harm pairs neutralized and UB = the CP 97.5% upper
bound on c / 376.

**BE-G**

| scenario | pairs | acc | Δacc | b | c vs MAJ | c_D | UB | harms removed | corr. lost | new harms | new corr. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sealed | 0 | .8650 | — | 91 | 12 | 10 | .0551 | — | — | — | — |
| K | 36 | .8821 | +.0171 | 95 | 7 | 5 | .0380 | 5 | 0 | 0 | 4 |
| E | 15 | .8688 | +.0038 | 92 | 11 | 9 | .0517 | 1 | 0 | 0 | 1 |
| S | 6 | .8688 | +.0038 | 91 | 10 | 9 | .0484 | 2 | 0 | 0 | 0 |
| G | 25 | .8726 | +.0076 | 92 | 9 | 7 | .0450 | 3 | 0 | 0 | 1 |
| G: alias | 13 | .8650 | 0 | 91 | 12 | 10 | .0551 | 0 | 0 | 0 | 0 |
| G: alternative | 5 | .8650 | 0 | 91 | 12 | 10 | .0551 | 0 | 0 | 0 | 0 |
| G: disagreement | 7 | .8726 | +.0076 | 92 | 9 | 7 | .0450 | 3 | 0 | 0 | 1 |
| K + E | 51 | .8859 | +.0209 | 96 | 6 | 4 | .0344 | 6 | 0 | 0 | 5 |
| K + E + S | 57 | .8897 | +.0247 | 96 | 4 | 3 | .0270 | 8 | 0 | 0 | 5 |
| all four | 82 | .8992 | +.0342 | 98 | 1 | 0 | .0147 | 11 | 0 | 0 | 7 |

**VV**

| scenario | pairs | acc | Δacc | b | c vs MAJ | c_D | UB | harms removed | corr. lost | new harms | new corr. |
|---|---|---|---|---|---|---|---|---|---|---|---|
| sealed | 0 | .8650 | — | 88 | 9 | 9 | .0450 | — | — | — | — |
| K | 36 | .8764 | +.0114 | 91 | 6 | 6 | .0344 | 3 | 0 | 0 | 3 |
| E | 15 | .8726 | +.0076 | 89 | 6 | 6 | .0344 | 3 | 0 | 0 | 1 |
| S | 6 | .8650 | 0 | 88 | 9 | 9 | .0450 | 0 | 0 | 0 | 0 |
| G | 25 | .8802 | +.0152 | 93 | 6 | 6 | .0344 | 3 | 0 | 0 | 5 |
| G: alias | 13 | .8707 | +.0057 | 91 | 9 | 9 | .0450 | 0 | 0 | 0 | 3 |
| G: alternative | 5 | .8669 | +.0019 | 89 | 9 | 9 | .0450 | 0 | 0 | 0 | 1 |
| G: disagreement | 7 | .8726 | +.0076 | 89 | 6 | 6 | .0344 | 3 | 0 | 0 | 1 |
| K + E | 51 | .8840 | +.0190 | 92 | 3 | 3 | .0231 | 6 | 0 | 0 | 4 |
| K + E + S | 57 | .8859 | +.0209 | 93 | 3 | 3 | .0231 | 6 | 0 | 0 | 5 |
| all four | 82 | .8992 | +.0342 | 97 | 0 | 0 | .0098 | 9 | 0 | 0 | 9 |

**VDF variants**

| scenario | BE-G/VDF acc | b | c | c_D | UB | VV/VDF acc | b | c | c_D | UB |
|---|---|---|---|---|---|---|---|---|---|---|
| sealed | .8688 | 87 | 6 | 4 | .0344 | .8726 | 87 | 4 | 4 | .0270 |
| K | .8821 | 93 | 5 | 3 | .0308 | .8821 | 91 | 3 | 3 | .0231 |
| E | .8707 | 88 | 6 | 4 | .0344 | .8745 | 88 | 4 | 4 | .0270 |
| S | .8707 | 87 | 5 | 4 | .0308 | .8726 | 87 | 4 | 4 | .0270 |
| G | .8802 | 90 | 3 | 1 | .0231 | .8859 | 91 | 1 | 1 | .0147 |
| K + E | .8840 | 94 | 5 | 3 | .0308 | .8840 | 92 | 3 | 3 | .0231 |
| all four | .8992 | 98 | 1 | 0 | .0147 | .8992 | 97 | 0 | 0 | .0098 |

**No corrections are lost in any scenario.** The concern was that neutralizing a class could also
remove a correction elsewhere. That cannot happen here, because every flipped label belongs to a
wrong value. Removing a wrong value's witness does not take away a right value's witness.

What does change is how the gate decides. Neutralizing a class adds 0–11 **new corrections**: with
the false witness gone, W often holds only the right value, or the right value wins sel(W). The
accuracy gains in the table come from these new corrections as well as from the removed harms.

**Exact split of the sealed harms.** Each harm is fixed by exactly one single class, or by none.
Per-item detail is in `results.json → step2_label_replay.harm_split`.

| method | K | E | S | G | unattributable | total |
|---|---|---|---|---|---|---|
| BE-G c_D | 5 | 1 | 1 | 3 | 0 | 10 |
| BE-G c vs MAJ | 5 | 1 | 2 | 3 | 1 | 12 |
| VV c_D = c vs MAJ | 3 | 3 | 0 | 3 | 0 | 9 |
| BE-G/VDF c_D / c vs MAJ | 1 / 1 | 0 / 0 | 0 / 1 | 3 / 3 | 0 / 1 | 4 / 6 |
| VV/VDF | 1 | 0 | 0 | 3 | 0 | 4 |

Which items fall in each class:
- **BE-G K (5):** popqa2211064, popqa276747, popqa2797971, popqa4686489 and scifactdev770.
- **BE-G E (1):** popqa2342806.
- **BE-G S (2):** popqa695490, which is c_D, and popqa6297574, a tied-majority harm that is not c_D.
- **G (3), for every method:** fever80417, fever90151 and scifactdev808. All three are in the
  `disagreement` subclass, where the passage contradicts the gold label. Alias and alternative gold
  issues cause no harm vs MAJ. They only block a few corrections: neutralizing them adds 3 + 1 to VV
  and 2 to BE-G/VDF.
- **Unattributable (1):** popqa6297573, a tied-majority item where D differs from MAJ's random
  tie-break. No verified label is involved.
- **The 4 harms that VDF does not remove** are K popqa276747 plus the 3 G items.

## Step 3: judge errors vs verified-wrong items (P, n = 526)

F = items with at least one verified wrong value: the 56 items in `harm_reading.jsonl`. This was
recomputed with `f_and_pairs` and matches exactly. J is the published Sonnet judge column. J has 0
null fallbacks on P, so `J_nullwrong` gives the same table.

| | F (56) | not F (470) | total |
|---|---|---|---|
| J wrong | 17 | 15 | 32 |
| J right | 39 | 455 | 494 |

The two kinds of error are strongly associated:
- 53% of J's errors fall on F items, against 7.9% of its right answers. Under independence about
  3.4 of J's 32 errors would be F items; the table has 17.
- The odds ratio is 13.2. Fisher's exact p = 4.5e-10, the same for the two-sided and the one-sided
  (greater) test.
- By the F item's class (first of K, E, S, G):
  - K: 5 of 24 items J-wrong;
  - E: 3 of 8;
  - S: 0 of 5;
  - G: 9 of 19.

So the judge and the checker fail on the same hard items, above all on the gold and grading items,
where the "error" may lie in the gold label.

## Step 4: checker prompt-stability test, prepared and not run

See `stability/SPEC.md`.
- **Population:** 227 pairs, which are 227 distinct checks.
  - 145 licensing pairs: BE-G or VV overturns and corrections on P and T. P has 219 pairs and T 8.
  - 82 supported-wrong pairs.
- **Calls:** 3 paraphrases × 227 = **681 hosted checker calls, ≈ $3.27** at $0.0048 per check.
  Adding a re-run of the original template as a noise baseline gives 908 calls, ≈ $4.36.
- **Gate:** `run` refuses to start without `--i-approve-hosted-cost`. `plan` and `analyze` make no
  hosted call.

## Verdict (post hoc)

The published H3a statistic for BE-G is c = 12 of n_R = 376, which is 3.19%, with a CP upper bound
of 5.51%. The bound misses .05 by two harms: c = 10 gives .0484.

By exact label replay, the 12 harms split as follows:

| cause | harms | share | UB with it removed |
|---|---|---|---|
| checker false support (K) | 5 | 42% | .0380 |
| entity mismatch (E) | 1 | 8% | — |
| false or outdated source (S) | 2 | 17% | — |
| gold / grading (G), all of them passages that contradict the gold label | 3 | 25% | .0450 |
| tie-break artefact (no verified label) | 1 | 8% | — |

- **Neutralizing K alone** brings the bound to .0380, and **G alone** to .0450. Either one on its own
  is enough to pass.
- **All checker-side and source-side errors together (K+E+S)** account for 8 of the 12 harms. With
  them removed the bound is .0270.
- **Neutralizing all four classes** leaves only the tie-break item, at .0147.

**In short:** about two thirds of BE-G's overturn harm is pipeline error, mainly checker error (6 of
12 if entity mismatch counts with the checker, 8 of 12 with false sources added). About a quarter is
a disputed gold label, and one harm is a tie-break artefact.

For VV the split is K 3, E 3, G 3, which is one third gold and two thirds checker. Both VDF variants
already remove most of the checker-caused harm. What remains for them is mostly G: 3 of 4 c_D.

These attributions rest on a post hoc, two-annotator reading of the pairs, and on a counterfactual
that assumes a corrected label would have been `not_enough_info`. They describe this run only.
