# v6 wrapper build notes (prereg revision 3 and RUN_PLAN; nothing run against a model or a hosted API)

New files only. No v5 file touched (evaluate_v5 `9aa8fb2d`, collect_v5 `526bd20a`, post_collect_v5 `ff255e96`, make_results `bb0ef07d` unchanged).
Every wrapper loads its v5 module by path with `sys.dont_write_bytecode`, so no `__pycache__` appears in v5.

## Files
collect_v6, post_collect_v6, evaluate_v6, vdf_v6, futility_v6, make_results_v6, pooled_h3a_v6, qualify_v6,
local_checks_v6 (MiniCheck), build_alias_items_v6 (G-AK+A), pool_manifest.json, tests/{test_vdf_v6,test_pooled_h3a_v6,test_wrappers_v6}.py (26+16+10 tests).
Run a test file: `tools/corpus/.venv/bin/python -I real-agent-eval/v6/tests/<file>.py`.

## Gates (all pass)
1. vdf_v6 `--reproduce-v5` vs selector_study/results.json: 62 per-item and aggregate field checks, 0 mismatches
   (P VV/VDF .8726, 87/4, UB .0270; BE-G/VDF .8688, 87/6, c_D 4, UB .0344; T 6/1 and 9/1). Report: results/vdf_reproduction_v5.json.
2. `evaluate_v6.py --reproduce-v5` (frozen evaluator + binary on v5 conf data, output to a temporary directory): F2 blocks identical, paired_decisions_v5.csv
   byte-identical, items_v5.csv and overturns identical; the 54 other diffs are wall times and input paths. Report: results/evaluate_reproduction_v5.json.
3. collect_v6 / qualify_v6 / post_collect_v6 / local_checks_v6 dry runs: start-up checks and plan, no Ollama, exit 2 without `--run`.
   collect_v6 dev and conf plans reproduce v5's dispatch order and retriever for 160 and 1,100 items.
   qualify_v6 on v5 dev records gives yield .5375, m .3023, gemma2 60/160 citing, BEST mistral (v5's own values).
4. VDF branch tests: MAJ in W, MAJ not in W, W empty, tied verified plurality (v5-vv seed), D differs from MAJ on a tied majority, single value.
5. Extras: synthetic fixtures pass through evaluate_v6 (with and without the MiniCheck arm); G-AK+A on v5 data gives MAJ .7167, VV/VDF .8745 (README's numbers).

## Deviations from the plan text (all safety, none change a statistic)
- `--run` is also required by post_collect_v6 and local_checks_v6 (they make hosted/local calls). Plan commands for collect, qualify, post_collect need `--run` added.
- post_collect_v6 has an opt-in `seed` step (the APFS clones of plan section 3); not in the default step list.
- `--out` must be under v6/results for collect (also audit, judge-inputs), qualify, build_alias_items, local_checks.

## Spec ambiguities resolved
- BEST ties: plan says `max(sorted(agents), key=correct)` (alphabetical-first), prereg text says "ties by list order". Implemented v5's expression; qualification_v6.json also lists the tied agents and the list-order pick.
- Q4 yield: prereg says decisive/eligible, v5's dev gate divides by all items. Q4 decides on the prereg wording; both are reported.
- Q3 "valid citation": a label that maps to a shown passage (not just any label).
- "Agreement ... overall and on disagreement items" read as all eligible items of the set, and its >=2-distinct-values subset (decisive items are all disagreement items).
- Design-set hash is sha256 of the sorted ids joined by newline with a trailing newline.
- Checker_id 98751cc0 is recomputed offline from the on-disk files (Ollama 0.17.7 assumed); `--run` re-verifies it with /api/tags.

## Open items for the author
- BE-G-L policy_template_sha256 (offline): `c9ecf2fbcd964e15c782ec54a804997d5b575c3ca42de5bc76cd997c43a503c2` (use as `--expect-template BE-G-L=...`).
- Not edited (existing files): the `[[POOL: ...]]` slots in PREREGISTRATION.md, the `.gitignore` lines, FREEZE.json.
- Not implemented: prereg section 7 full-label cost and cache share (needs the v5 and v6 check_calls logs).
- exaone3.5:2.4b (replaced after failing qualification by exaone3.5:7.8b) reported 2.7B parameters; its licence is EXAONE NC 1.1; nemotron-mini carries the NVIDIA community licence.
