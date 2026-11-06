# v5 confirmatory run: operational notes

Facts for the deviations section of `RESULTS.md`. None of them changes an input to a preregistered
test.

1. **CLI pin.** The installed Claude Code CLI auto-updated from 2.1.307 to 2.1.308 during
   collection. `run_checks_v5.py --expect-checker` refused the new `checker_id`
   (`304a97b6…`). Every hosted call (checks, J, RS, CB-S, regeneration, LOAO) then ran on the pinned
   2.1.307 binary with `DISABLE_AUTOUPDATER=1`. Every check carries `checker_id`
   `f2a14bd8988371bd231ca6ff137be13e`, and every judge record carries `runtime_version`
   `claude-code/2.1.307`.
2. **Futility look (§8).** Run on the first 300 items in frozen order, with BE-G vs MAJ on 144
   decisive P conflicts: b = 25, c = 4, so collection continued (`../conf_futility/futility_look.json`).
   Its checks share the canonical evidence cache, so the final checks reuse them.
3. **Collection latency.** Item 1023 took 369.5 s (median ≈ 25 s). Evidence capture ran
   concurrently on the same machine and loaded the 6.35M-passage FEVER index. Agent latency is
   descriptive only.
4. **Refusals.** One support check, one RS call and one CB-S call ended `refused`. They are kept
   as recorded: the check scores as unchecked, RS and CB-S score as missing (wrong).
5. **J regeneration and J LOAO.** `judge.py --regenerate` logs fresh answers without exporting
   them as rows. The 200 regeneration items and the 50 LOAO items × 5 dropped agents therefore ran
   in fresh stores (`judge-store-jregen`, `judge-store-loao-<agent>`), exported as run 1 and as
   `dropped_agent` rows. Same pin and same judge_id.
6. **J_local drift** (`num_thread` 4 and 8, Ollama restart) was not run: `local_judge.py` has no
   thread control. J_local is exploratory (§2.3).
7. **J_local interruption.** The J_local store was moved out of place by an operator error after
   242 of 702 items and the run was stopped. Two items written in the meantime were merged back
   (no overlap), and the run resumed from the store cache: the 244 finished items were cache hits
   with no new calls. Cache-hit log lines are excluded from cost rows.
8. **Local checker arm.** Not run: the mistral checker failed validation before the freeze, and
   MiniCheck was not validated. BE-G-L and VV-L are not reported.
9. **Check cost in `RESULTS.md` is understated (correction).** 4,398 of 7,248 checks were first
   called in the futility look and in a pre-run on collected items. The final `check` step read
   them from the shared cache, so their `cost_usd` in `checks.jsonl` is empty, and the evaluator's
   "$ / decision" for BE-G / BE / VV ($0.0015 on P) counts only the 2,850 calls made in the final
   step. Corrected from the live call logs of all three runs (`check_calls.jsonl` here, in `../conf_futility/` and in `../conf_prerun/`) (7,249 calls, $34.09): cited checks
   4,742, $22.74, mean $0.0048 per check. At the evaluator's calls per decision, that gives
   **P $0.0211 per decision (1.48× J), T $0.0264 (2.0× J), pooled $0.0217 (1.53× J)**. The
   gold-shown diagnostic total ($11.35, 2,506 checks) is unaffected and matches the evaluator. No
   other cost or accuracy figure depends on `cost_usd`.
