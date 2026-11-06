# Validation-channel audit and human review preparation

**Status: prepared, not human-reviewed.** No human judgments are supplied. The JSONL answer fields are intentionally null. This packet does not validate the paper's model-based error attribution.

From the artifact directory, reproduce without model calls:

```sh
python3 reproduction/audit_validation.py --out /path/to/new-output-directory
```

The output directory must not exist; the runner refuses existing directories before writing any files.

`validation_channels.json` independently counts the raw frozen validation rows and records source-file SHA-256 digests. Raw supports errors are 18/350; raw refutes errors are 22/350. The latter can verify a REFUTED answer after the answer-relative label swap and are absent from the former statistic. These are direction-specific validation rates, not recalibrated deployment-harm estimates. Gold-incorrect answers are not necessarily non-entailing passage/answer pairs, so changing the rate alone cannot repair deployment calibration.

## Review procedure

1. Give separate copies of `review_first_pass.jsonl` to two independent human reviewers. This includes all 82 supported, dataset-incorrect pairs on 56 primary items, with the exact passage spans supplied to the checker. It omits checker labels, model attribution categories, model rationales, and dataset gold. Reviewers should not consult existing model annotations before completing this pass. The packet is selected for dataset disagreement, so selection itself is not blinded.
2. For each pair, assess passage relation to the **proposition** as supports, refutes, insufficient, or uncertain; assess entity match separately. Preserve the candidate answer distinction: a refutes relation may license a REFUTED candidate. Record a rationale and reviewer/date. Passage entailment is distinct from factual source correctness; mark source accuracy unknown unless independently checked.
3. After locking first-pass responses, supply `review_gold_second_pass.jsonl`. Review the dataset answer and aliases, distinguish a missing alias from a substantive factual disagreement, and record external evidence used. Do not automatically accept either the passage or the dataset as true.
4. Preserve both independent responses. An independent adjudicator resolves disagreements with a rationale; leave unresolved cases explicit. Report agreement and category counts without treating agreement itself as proof of correctness. A completed review needs a new, separately named output directory; do not overwrite these blank forms or frozen model annotations.

The source manifest binds each review ID to item, passage and frozen check IDs. Model classifications remain in the original artifact, not in these reviewer forms. This preparation covers all 82 pairs requested for attribution validation, including model-classified source/gold cases rather than only model-classified checker errors.

It does not cover every harmful decision: the tied-majority item `v5-popqa6297573` has no verified wrong witness and requires a separate decision/tie-default audit. Neither this packet nor a completed pair-level review establishes calibration for all 1,090 checked pairs on incorrect answers; that requires a broader, appropriately sampled passage-level review and dependence assumptions.
