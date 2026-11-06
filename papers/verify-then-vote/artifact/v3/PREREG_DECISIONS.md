# v5 preregistration: decisions already made by the analysis team

These feed the v5 PREREGISTRATION.md, which must be frozen before the confirmatory run and before anyone reads v4's confirmatory accuracy.

## Items
- **SciFact allocation is proportional to the fresh pool:** 201 SUPPORTED and 49 REFUTED. All 54 REFUTED are not taken. Oversampling the regime where majority vote is expected to fail would look like tuning toward Bran. REFUTED is reported as a subgroup.
- **Extension split:** 160 / 133 / 107 (TruthfulQA, PopQA, FEVER), following the primary quotas.
- **TruthfulQA quota switch (design §2.2):** k is fixed in the prereg. Items are drawn from `reserve_order.json` in order.
- **The FEVER validation slice** excludes all 347 FEVER ids in the v5 dev and confirmatory sets.

## Corpus evidence
- `unchecked_factor` is always serialized. The default stays 1.0 and the v5 grounded policy uses 0.5.
- The xref key is `corpus:<corpus_id>/<encoded key>`.
- **The corpus pin is trusted from the manifest.** `--verify-passages` runs once before the freeze.
- **Corpus `ok` rule** is `corpus-nonempty/1`: a passage is `ok` if its text is non-empty. The web 200-character rule does not apply.

## Judge J and reader RS
1. **What J sees:** only parsed answers, which constrain its output. It sees each agent's stated confidence and cited passages, but not the agent's reasoning or model name.
2. **Single-value items** get `forced` with no call. BE's cost accounting counts them the same way.
3. **RS input:** the union of every passage shown to any agent, not just the cited ones. Using cited passages would leak the agents' answers.
4. **RS passage order:** a `Random("v5-rs:"+item_id)` shuffle.
5. **Null decisions** (refused, parse_error or model_mismatch) fall back to majority vote (MAJ) in the primary analysis, as a practitioner would. A sensitivity analysis scores them as wrong.
6. **J and RS may use outside knowledge.** This makes them the strongest practitioner baseline, unlike the passage-only checker.
7. **Option count:** TruthfulQA has up to 7 options (A–G). The answer schemas must allow this.
8. **Code freeze:** `judge.py` and its templates are frozen by hash before the dev judge run, since judge_id depends on them.

## Evaluation
- **Freeze `policy_template_sha256` per configuration, not `policy_hash`.** The policy hash varies per item because `incompatible_values` lists that item's observed objects.
- **One parse rule:** a response is parsed if its answer field is valid. A confidence outside the enum counts as "low". A citation to a passage label the agent was not shown becomes an `invalid_identifier` dead capture; it is not silently dropped.
- **Judge and reader failures:** a null J answer falls back to MAJ and is counted. A null RS answer is scored wrong, since RS answers without the agents.
- **EO** is B0 plus the selected candidate mode and NEI factor, with weights (1,0,0,0,0) and deadband 0. The grid's final tie-break is grid order.
- **B0** keeps citation items but has no evidence policy (legacy unverified scoring), so it isolates the effect of the policy.
- **Sealed support labels** are value-level (mapped). Raw checker labels can be recovered from the check cache, and each contribution's `raw_text` is its proposition.
- **The checks driver** emits `checks.jsonl` in the format given in the `evaluate_v5.py` docstring. It checks the gold value on every shown passage for the evidence-availability gate.

## Corrections to DESIGN.md
- **§6.1:** the correct minority is a single agent in 19 of 20 strict majority-wrong items, not 17.
- **§2.4 / §5.1 score arithmetic:** the per-citation score includes the CITATION type weight 0.8 and the cross-reference multiplier. One supported passage scores 0.459, not 0.638, and an NEI or unchecked one scores 0.230, not 0.319. Three pooled NEI citations score 0.689 against one supported at 0.459, so the failure mode still holds.
