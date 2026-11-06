# Matched gate ablation

This post hoc analysis isolates the gate on the first agent pool's sealed inputs.
It does not amend the pre-specified comparison or its hypotheses. The original
comparison used an NEI factor of 0.1 without the gate and 0.5 with it; it therefore
changed two settings.

From the artifact directory, with a native reducer built from this source:

```sh
python3 reproduction/matched_gate.py --bin /path/to/overturn --out /path/to/new-output-directory
```

The runner imports the archived evaluator after verifying the documented freeze
hashes, reconstructs all 1,100 items, and executes the reducer with the gate off
and on at both NEI factors. It asserts that paired policies differ only in the
gate field and that all other inputs are identical. Every Rust decision is
checked against the archived independent Python mirror. The two original
configurations, majority baseline and published default must exactly match the
archived answer and correctness for every item. No model call is made. Outputs
include per-item decisions, full reducer inputs/outputs and an aggregate receipt.
`matched_gate_results.json` records the executed analysis (4,400 mirror checks).

## Primary decisive conflicts

All rows use the same 526 items. Corrections/losses compare with the majority
baseline (376 correct). Accuracy is correct answers divided by 526.

| NEI factor | Gate | Correct | Accuracy | Corrections | Losses |
|---|---|---:|---:|---:|---:|
| 0.1 | off | 452 | 85.9% | 99 | 23 |
| 0.1 | on | 453 | 86.1% | 89 | 12 |
| 0.5 | off | 439 | 83.5% | 96 | 33 |
| 0.5 | on | 455 | 86.5% | 91 | 12 |

Thus the matched gate reduces losses from 23 to 12 at 0.1, and from 33 to 12 at
0.5, while retaining respectively 89/99 (89.9%) and 91/96 (94.8%) of corrections.
Directly comparing gate on with gate off, it repairs 11 and loses 10 correct
ungated decisions at 0.1; at 0.5 it repairs 27 and loses 11. These direct paired
changes differ from corrections/losses against majority.

The deterministic plurality default is policy-specific: scoring breaks a tied
plurality. Both defaults are correct on 386 primary decisive items, but do not
select the same answer on every item. Against each factor's own default,
corrections/losses are 87/21 (0.1 off), 77/10 (0.1 on), 83/30 (0.5 off), and
79/10 (0.5 on). The JSON also includes all rows against the common published
0.5 default (`D`) and TruthfulQA results. No inferential tests were selected for
these post hoc comparisons.
