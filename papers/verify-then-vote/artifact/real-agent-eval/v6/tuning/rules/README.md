# Rules screen (post hoc, exploratory; v5 P=526 decisive, T=69)

Run: `python3 rules_screen.py` (writes `rules_results.json`, incl. per-item rows). Imports
`v5/selector_study/selector_study.py` unmodified (exact v5 reconstruction). No model, hosted or binary call.
Not preregistered; numbers are descriptive and tuned on confirmatory data.

## A. Discriminative support
Rule: a verified value may overturn the default only if one of its witnessing passages is not labelled
"supports" for the default's proposition (label = sealed check in checks.jsonl, accepted checker, status ok,
mapped with the default's label_map). Values failing the rule are dropped from W' before the vote
(VV/VDF) or before sel (BE-G/VDF); empty W' keeps the default. Unchecked (proposition, passage) = "unknown".

| P | acc | b/c vs MAJ | c_D | H3a UB | corr. lost | harms removed |
|---|---|---|---|---|---|---|
| VV/VDF | .8726 | 87/4 | 7 | .0270 | - | - |
| VV/VDF+A unknown=not-supports | .8726 | 87/4 | 7 | .0270 | 0 | 0 |
| VV/VDF+A unknown=supports | .8441 | 71/3 | 12 | .0231 | 16 | 1 |
| BE-G/VDF | .8688 | 87/6 | 4 | .0344 | - | - |
| BE-G/VDF+A unknown=not-supports | .8688 | 87/6 | 4 | .0344 | 0 | 0 |
| BE-G/VDF+A unknown=supports | .8536 | 79/6 | 3 | .0344 | 8 | 1 |

(c_D = scored D right, output wrong. VV/VDF c_D 7 here vs 4 in selector_study README, which is c vs MAJ.)
New checks to fill unknowns: 26 distinct (proposition, passage) pairs on P (3 more on T), counting only pairs
whose outcome could flip an overturn; 27 on P if every unknown pair on overturning items is counted.
Conclusion: checks barely discriminate on known labels; the rule costs 16 of 87 corrections for 1 harm removed.

## B. Deterministic tie rule (VV/VDF with a changed default)
34 P items have a seeded majority tie (11 on T). (ii) and (iii) give identical decisions: D is always among
the tied values, and an unverified default is replaced by the verified vote anyway. 18 P items change.

| P | acc | b/c vs MAJ | c_D | H3a UB | corr. lost / new corr. vs VV/VDF | harms removed / added vs VV/VDF | harm vs own default |
|---|---|---|---|---|---|---|---|
| (i) seeded tie (VV/VDF) | .8726 | 87/4 | 7 | .0270 | - | - | 4 (MAJ) |
| (ii) verified, then D | .8707 | 88/6 | 4 | .0344 | 2 / 3 | 0 / 2 | 4 (D) |
| (iii) D | .8707 | 88/6 | 4 | .0344 | 2 / 3 | 0 / 2 | 4 (D) |

Harm vs MAJ changes meaning: MAJ is still the published reference, but the default is D for (ii)/(iii). T:
(ii)/(iii) acc .5797 vs .5217 (b/c 10/1), 5 items change; T is TruthfulQA, no H3a rejection either way.

## Lean gate theorem
Literal form (sel returns a member of W, or D when W is empty) holds for VDF and B(ii)/(iii) only if D is the
default of record. It does not hold literally for A: when W is non-empty but all values are filtered, the
output is D, not in W. The weaker form (output in W' or D, W' subset of W) holds, so the harm bound
(output wrong while default right implies a wrong member of W) still applies. B changes only the default
passed to the gate, so the theorem holds with that default.
