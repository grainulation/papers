# Checker prompt-stability test (prepared, NOT run)

Status: **post hoc, exploratory, not preregistered. No hosted call has been made.** `run` refuses to
start without `--i-approve-hosted-cost`.

## Question

Are the `supports` labels that drove BE-G and VV decisions on the v5 confirmatory data stable under
meaning-preserving rewording of the checker prompt? Or do some depend on the exact wording of the
0.2.0 template?

## Population (`../stability_population.jsonl`, 227 pairs = 227 distinct checks)

These pairs come from `../harm_attribution.py` and the selector_study reconstruction. A pair is (item,
passage, proposition). Each is an accepted (`f2a14bd8…`), status-ok citation whose value-mapped
label is `supports`.

- **Licensing pairs (145):** on decisive P and T items where BE-G's value differs from MAJ or from
  its scored default D, or VV's value differs from MAJ: every supports pair of the decided value. By
  kind: BE-G b 127, BE-G c 13, BE-G same-correctness 18; VV b 123, VV c 10, VV same-correctness 8.
  The kinds overlap.
- **Supported-wrong pairs (82):** every pair in `../../controls/harm_reading.jsonl`.
- By set: P 219, T 8. By source: popqa 127, scifact 50, fever 42, truthfulqa 8.

Every sealed label in the population is `supports`.

## Conditions

k = 3 paraphrases of `tools/evidence/support/prompt_template.txt`:
`templates/paraphrase_{1,2,3}.txt`. Each one rewords the SYSTEM rules and the one-line USER framing.
Each keeps every rule, example and label definition, the `<<<CLAIM … CLAIM>>>` and
`<<<PASSAGE … PASSAGE>>>` delimiters, and the `{claim}` / `{passage}` placeholders. The original
template is not edited.

Everything else stays as sealed:
- model `claude-sonnet-5-5` with `effort low`;
- the CLI flags, so `flags_sha256` is asserted equal;
- the response schema;
- CLI version 2.1.307 on `PATH` (or selected with `BRAN_CLAUDE_BIN`), with `DISABLE_AUTOUPDATER=1`; the runner rejects a mismatched checker identity;
- the same span texts from `checks.jsonl`, with the original prompt re-rendered and its
  `internal_check_key` verified first.

A paraphrased template has a different checker id (the template hash is part of it), and each call
row logs that id. The support cache is bypassed and no record is written to it.

Optional `--include-original` re-runs the unchanged template once per check. This gives a baseline
for sampling noise, so a paraphrase flip rate can be compared with the plain re-query flip rate.

## Outputs (`analyze`)

- **Per paraphrase:**
  - label distribution;
  - flip rate (value-mapped label ≠ `supports`) with Wilson 95% CI, overall and by group (licensing
    vs supported-wrong, correct vs wrong value);
  - exact McNemar against the sealed label on the supports / not-supports scale. Every sealed
    label is `supports`, so the not→supports cell is 0 by construction. The test then reduces to a
    sign test on the flips.
- **Decisions:** BE-G, VV, BE-G/VDF and VV/VDF on P and T, re-decided with the frozen logic. A pair
  keeps `supports` only if it is `supports` under all k paraphrases ("supports under all k").
  Otherwise its label is set to `not_enough_info`, the same value-level replay as step 2 of the
  README. The same is done for each paraphrase alone. Reported against the sealed decisions:
  - accuracy;
  - b and c vs MAJ;
  - c_D;
  - the CP 97.5% upper bound;
  - harms removed and corrections lost.

  If a pair has no ok answer after 3 attempts, it keeps its sealed label, and the number of such
  pairs is reported.
- The analysis path was exercised on two synthetic call files in a scratch directory, not here:
  - all paraphrases return the sealed label: the published decisions came back exactly;
  - one paraphrase returns NEI on the 82 supported-wrong pairs: this equals the README's "all four
    classes" replay (BE-G .8992, c 1, c_D 0).

## Cost

- 227 checks × 3 paraphrases = **681 calls**. At the mean of $0.0048 per cited check
  (`results/conf/RUN_NOTES.md` item 9) that is **≈ $3.27**.
- With `--include-original`: 908 calls, ≈ $4.36.
- The paraphrased system prompts are 2,528–2,603 characters against 2,377, so expect a few percent
  more per call.
- `run` aborts if the projected cost exceeds `--max-usd` (default $6).

## Commands

```
python3 -I real-agent-eval/v5/harm_attribution/stability/checker_stability.py plan      # no hosted call
DISABLE_AUTOUPDATER=1 python3 -I real-agent-eval/v5/harm_attribution/stability/checker_stability.py run --i-approve-hosted-cost [--include-original]
python3 -I real-agent-eval/v5/harm_attribution/stability/checker_stability.py analyze   # no hosted call
```
