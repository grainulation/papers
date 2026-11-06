# MiniCheck re-decision of the v5 confirmatory items (EXPLORATORY)

**MiniCheck fails the preregistered three-way macro-F1 criterion by construction (binary checker) and meets every
supports criterion; this re-decision is outside the preregistration.**

- **Checks.** `run_minicheck_checks.py` ran `bespoke-minicheck:7b` (checker `98751cc0…`, validated in
  `tools/evidence/support/validation/MINICHECK_RESULTS.md`) on the 4,742 cited (proposition, passage) pairs. It used
  the same sealed captures, sequentially, and made no hosted calls. Output is `checks_minicheck.jsonl`: 4,742 ok, 1,671
  `supports` and 3,071 `not_enough_info`. The run took 86 min, which is 4.7 s of local checking per eligible decision
  and $0 hosted.
- **Decisions.** `minicheck_redecide.py` uses the frozen `evaluate_v5.py` (read-only) and `selector_study.decide`. It
  first recomputes the hosted run through the same code and must reproduce the published numbers, else it aborts.
  Output is `results.json`.

## P (526 decisive primary items, n_R = 376)

| method | hosted acc | MiniCheck acc | b/c vs MAJ, hosted → MiniCheck | c_D | H3a UB | F (verified-wrong items) |
|---|---|---|---|---|---|---|
| BE-G | .8650 | .7757 | 91/12 → 43/11 | 10 → 10 | .0551 → .0517 (not rej.) | 56 → 73 |
| VV | .8650 | .7738 | 88/9 → 40/9 | 9 → 9 | .0450 → .0450 (rej.) | 56 → 73 |
| BE-G/VDF | .8688 | .7776 | 87/6 → 40/7 | 4 → 5 | .0344 → .0380 (rej.) | 56 → 73 |
| VV/VDF | .8726 | .7776 | 87/4 → 38/5 | 4 → 5 | .0270 → .0308 (rej.) | 56 → 73 |

The MAJ baseline is .7148. Each line on T (69 items) reads hosted → MiniCheck:

- BE-G: .5652 → .5507, b/c 9/1 → 10/3.
- VV: .5217 → .4928, b/c 6/1 → 6/3.
- F: 4 → 14.

## Why corrections fall

- **Licensing labels.** They differ on 1,171 of 8,155 citations: 784 are licensed by the hosted checker only, 387 by
  MiniCheck only.
- **Per check.** The hosted checker's 507 `refutes` labels become 475 `not_enough_info` and 32 `supports` under
  MiniCheck.
- **Lost corrections.** Of the 48 BE-G corrections on P that are lost, 36 are correct REFUTED answers on binary
  FEVER/SciFact items. Such an answer is licensed only by a `refutes` label, and a binary checker never emits one. This
  is the same structural gap the macro-F1 criterion measures.
