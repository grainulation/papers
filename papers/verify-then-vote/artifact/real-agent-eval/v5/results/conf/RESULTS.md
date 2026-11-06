# Eval v5 results (confirmatory)

Items: 1100. Eligible: 1100. Decisive conflicts: **595** (yield 0.541). BE-G: `member/nei0.5/gated`. BE: `member/nei0.1`. BE-G-L: `not run`. BEST agent: `mistral`.

Binary `af420a5def1a6704`; evaluator `9aa8fb2d23dcf0e2`; propositions `1.0.0`; accepted checkers `f2a14bd8988371bd231ca6ff137be13e`.

| method | policy_template_sha256 |
|---|---|
| B0 | `e08f2ea6ad5c6fdeb36f8eeee2dce1555d6ba9450b25625945128bc06ad25f16` |
| BE | `084ecdbdcd06193beab228fc9ca21fcf1842f1fffd0326052c5b8908581dada0` |
| BE-G | `99c8b9c91c27d4fcf8cb33be2f342eb6dffa175f10802459df52a23ee2a0a245` |
| EO | `75ee3a54eb249c59a911bd75739f2ad06b6ba924e822e383a7f50f2ed6eb7ac7` |

Template check against the prereg: checked; mismatches: 0.

| analysis set | items | eligible | decisive | disagreement | yield | decisive by source |
|---|---|---|---|---|---|---|
| P (SciFact, PopQA, FEVER) | 1000 | 1000 | 526 | 622 | 0.526 | fever 199, popqa 173, scifact 154 |
| T (TruthfulQA stratum) | 100 | 100 | 69 | 80 | 0.690 | truthfulqa 69 |
| pooled (descriptive only) | 1100 | 1100 | 595 | 702 | 0.541 | fever 199, popqa 173, scifact 154, truthfulqa 69 |

Set rule: tier primary -> P, tier tqa_stratum -> T (prereg §6.3); items without those tiers: TruthfulQA -> T, other sources -> P. P and T are never pooled for a test.

## 1. Preregistered analyses

### H1: primary family on P (exact two-sided McNemar, Holm, family-wise α = 0.05)

| | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | Holm threshold | Holm-adjusted p | reject | reading |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1a | BE-G vs MAJ on P | 526 | 91 | 12 | 0.150 | [0.115, 0.186] | [0.114, 0.186] | 3.46e-16 | 0.025 | 6.92e-16 | yes | better |
| H1b | BE vs MAJ on P | 526 | 99 | 23 | 0.144 | [0.105, 0.184] | [0.106, 0.184] | 1.99e-12 | 0.050 | 1.99e-12 | yes | better |

| | MAJ wrong | p̂_w = b / #wrong (Wilson 95%) | MAJ right | q̂_r = c / #right (Wilson 95%) |
|---|---|---|---|---|
| H1a | 150 | 0.607 [0.527, 0.681] | 376 | 0.032 [0.018, 0.055] |
| H1b | 150 | 0.660 [0.581, 0.731] | 376 | 0.061 [0.041, 0.090] |

Holm order: H1a, H1b. A rejection reads as "better" only if b > c.

### H3: no harm (own α each, outside the H1 family)

| test | method | set | n_R | c | q̂_r | one-sided 97.5% Clopper–Pearson upper bound | bound | largest c that rejects | reject |
|---|---|---|---|---|---|---|---|---|---|
| H3a | BE-G | P | 376 | 12 | 0.032 | 0.0551 | < 0.05 | 10 | no |
| H3a (BE, descriptive) | BE | P | 376 | 23 | 0.061 | 0.0904 | < 0.05 | 10 | no |

| test | method | set | N | b | c | difference | Newcombe 95% CI | lower bound > −0.03 | reading |
|---|---|---|---|---|---|---|---|---|---|
| H3b | BE-G | T | 69 | 9 | 1 | 0.116 | [0.030, 0.197] | yes | non-inferior |
| H3b (BE, descriptive) | BE | T | 69 | 13 | 8 | 0.072 | [-0.055, 0.196] | no | not shown |

Power warning (pre-declared): power about 0.81 if BE-G and MAJ never disagree on T, 0.31 at b = c = 2%, 0.08 at dev's rate; a non-rejection is 'not shown', never harm, unless the estimate is negative.

### H2: local arm (fixed sequence, own α = 0.05)

not run: no local checks supplied. H2 is reported as "not run as confirmatory; local checker unvalidated".

### H4: gate soundness (c_D <= F (v3/GATE_SPEC.md §3))

F-hat rate: 0.0514 (18/350).

| set | method | N | c_D | b_D | F | c_D items ⊆ F items | F-hat | checked incorrect pairs | c vs MAJ | c vs MAJ not in F (tied) |
|---|---|---|---|---|---|---|---|---|---|---|
| P | BE-G | 526 | 10 | 79 | 56 | yes | 52.75 | 1090 | 12 | 1 (1) |
| T | BE-G | 69 | 0 | 5 | 4 | yes | 9.90 | 210 | 1 | 0 (0) |

harm_bound_holds on P and T: **True**. F items (P, BE-G): `v5-fever119298`, `v5-fever127363`, `v5-fever153147`, `v5-fever80417`, `v5-fever90151`, `v5-fever91498`, `v5-popqa1165631`, `v5-popqa12488`, `v5-popqa1283560`, `v5-popqa1292419`, `v5-popqa145561`, `v5-popqa1613612`, `v5-popqa175943`, `v5-popqa1833420`, `v5-popqa1844051`, `v5-popqa2155468`, `v5-popqa2155469`, `v5-popqa2211064`, `v5-popqa2342806`, `v5-popqa276747`, `v5-popqa2785946`, `v5-popqa2791111`, `v5-popqa2797971`, `v5-popqa2925031`, `v5-popqa2940564`, `v5-popqa2941131`, `v5-popqa3031144`, `v5-popqa3102612`, `v5-popqa3114331`, `v5-popqa3148564`, `v5-popqa3207197`, `v5-popqa3592879`, `v5-popqa4514247`, `v5-popqa4663230`, `v5-popqa4686489`, `v5-popqa471864`, `v5-popqa486355`, `v5-popqa5308304`, `v5-popqa5489997`, `v5-popqa5724067`, `v5-popqa5781914`, `v5-popqa6278529`, `v5-popqa6297092`, `v5-popqa6297574`, `v5-popqa6341216`, `v5-popqa645704`, `v5-popqa6552986`, `v5-popqa695490`, `v5-popqa792070`, `v5-popqa7986`, `v5-popqa996246`, `v5-scifactdev208`, `v5-scifactdev593`, `v5-scifactdev692`, `v5-scifactdev770`, `v5-scifactdev808`. c against MAJ not explained by F (tied pluralities, GATE_SPEC §3 caveat 1): `v5-popqa6297573`.

### §2.4 references and baselines (descriptive; Holm-adjusted p for the reference family vs MAJ)

**P (SciFact, PopQA, FEVER).** Not run: none.

| method | role | accuracy | b / c vs MAJ | p | Holm p | BE-G vs method: b / c, p |
|---|---|---|---|---|---|---|
| BEST | best single model (mistral, fixed on dev) | 69.6% | 58 / 68 | 0.4228 | n/a | 113 / 24, 5.25e-15 |
| CB-S | closed-book Sonnet (memorisation reference) | 90.9% | 128 / 26 | 2.17e-17 | 6.52e-17 | 29 / 52, 0.0140 |
| CONF | confidence-weighted vote | 73.6% | 13 / 2 | 0.0074 | 0.0148 | 82 / 14, 7.24e-13 |
| CV | cite vote (unverified) | 69.0% | 29 / 42 | 0.1539 | 0.1539 | 106 / 14, 1.16e-18 |
| J | Sonnet judge (upper reference) | 93.9% | 131 / 13 | 1.05e-25 | 4.60e-25 | 11 / 50, 4.59e-07 |
| J_local | local judge (H2b) | 69.6% | 54 / 64 | 0.4075 | n/a | 110 / 21, 9.43e-16 |
| RS | Sonnet reader (upper reference) | 94.3% | 134 / 14 | 9.19e-26 | 4.60e-25 | 15 / 56, 1.04e-06 |
| VV | verified vote | 86.5% | 88 / 9 | 2.00e-17 | n/a | 9 / 9, 1.0000 |

**T (TruthfulQA stratum).** Not run: none.

| method | role | accuracy | b / c vs MAJ | p | Holm p | BE-G vs method: b / c, p |
|---|---|---|---|---|---|---|
| BEST | best single model (mistral, fixed on dev) | 49.3% | 14 / 11 | 0.6900 | n/a | 16 / 11, 0.4421 |
| CB-S | closed-book Sonnet (memorisation reference) | 95.7% | 36 / 1 | 5.53e-10 | 2.21e-09 | 1 / 28, 1.12e-07 |
| CONF | confidence-weighted vote | 42.0% | 1 / 3 | 0.6250 | 0.7754 | 10 / 0, 0.0020 |
| CV | cite vote (unverified) | 39.1% | 4 / 8 | 0.3877 | 0.7754 | 13 / 1, 0.0018 |
| J | Sonnet judge (upper reference) | 100.0% | 38 / 0 | 7.28e-12 | 3.64e-11 | 0 / 30, 1.86e-09 |
| J_local | local judge (H2b) | 42.0% | 6 / 8 | 0.7905 | n/a | 16 / 6, 0.0525 |
| RS | Sonnet reader (upper reference) | 94.2% | 35 / 1 | 1.08e-09 | 3.23e-09 | 1 / 27, 2.16e-07 |
| VV | verified vote | 52.2% | 6 / 1 | 0.1250 | n/a | 4 / 1, 0.3750 |

### Reading (PREREGISTRATION.md §14)

- H2 "not run as confirmatory; checker unvalidated". Headline H1a + H3 with the hosted checker. Cost is framed as "per-label, reusable, auditable", never "cheaper than J".
- "Harm equals checker false supports, as the bound predicts." H4 (c_D <= F, F against F-hat) leads.

## 2. Deviations

- hosted check records on P carry no token counts (only $ and wall time are reported for checks)
- hosted check records on T carry no token counts (only $ and wall time are reported for checks)

## 3. Descriptive analyses (H5, sensitivity)

### Accuracy and overturn rates by set

**P (SciFact, PopQA, FEVER)** (526 decisive, 1000 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 71.5% | 77.1% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 86.5% | 85.0% | 91 | 12 | 0.607 [0.527, 0.681] | 0.032 [0.018, 0.055] |
| BE | ungated reducer member/nei0.1 (H1b) | 85.9% | 84.7% | 99 | 23 | 0.660 [0.581, 0.731] | 0.061 [0.041, 0.090] |
| B0 | order-free reducer, no evidence policy | 63.7% | 73.0% | 47 | 88 | 0.313 [0.245, 0.391] | 0.234 [0.194, 0.279] |
| EO | evidence-only weights at BE's mode / NEI | 85.7% | 84.6% | 100 | 25 | 0.667 [0.588, 0.737] | 0.066 [0.045, 0.096] |
| VV | verified vote | 86.5% | 85.0% | 88 | 9 | 0.587 [0.507, 0.662] | 0.024 [0.013, 0.045] |
| CV | cite vote (unverified) | 69.0% | 75.8% | 29 | 42 | 0.193 [0.138, 0.264] | 0.112 [0.084, 0.148] |
| CONF | confidence-weighted vote | 73.6% | 78.2% | 13 | 2 | 0.087 [0.051, 0.143] | 0.005 [0.001, 0.019] |
| BEST | best single model (mistral, fixed on dev) | 69.6% | 76.1% | 58 | 68 | 0.387 [0.312, 0.467] | 0.181 [0.145, 0.223] |
| D | reducer plurality default (H4) | 73.4% | 78.1% | 13 | 3 | 0.087 [0.051, 0.143] | 0.008 [0.003, 0.023] |
| ORC | oracle (any agent right) | 100.0% | 92.1% | 150 | 0 | 1.000 [0.975, 1.000] | 0.000 [0.000, 0.010] |
| J | Sonnet judge (upper reference) | 93.9% | 88.9% | 131 | 13 | 0.873 [0.811, 0.917] | 0.035 [0.020, 0.058] |
| RS | Sonnet reader (upper reference) | 94.3% | 57.1% | 134 | 14 | 0.893 [0.834, 0.933] | 0.037 [0.022, 0.062] |
| CB-S | closed-book Sonnet (memorisation reference) | 90.9% | 55.4% | 128 | 26 | 0.853 [0.788, 0.901] | 0.069 [0.048, 0.099] |
| J_local | local judge (H2b) | 69.6% | 76.1% | 54 | 64 | 0.360 [0.288, 0.439] | 0.170 [0.136, 0.211] |

Against D: BE-G b_D 79, c_D 10, q_r(D) 0.026.

**T (TruthfulQA stratum)** (69 decisive, 100 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 44.9% | 51.0% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 56.5% | 59.0% | 9 | 1 | 0.237 [0.130, 0.392] | 0.032 [0.006, 0.162] |
| BE | ungated reducer member/nei0.1 (H1b) | 52.2% | 56.0% | 13 | 8 | 0.342 [0.212, 0.501] | 0.258 [0.137, 0.432] |
| B0 | order-free reducer, no evidence policy | 43.5% | 50.0% | 7 | 8 | 0.184 [0.092, 0.334] | 0.258 [0.137, 0.432] |
| EO | evidence-only weights at BE's mode / NEI | 52.2% | 56.0% | 13 | 8 | 0.342 [0.212, 0.501] | 0.258 [0.137, 0.432] |
| VV | verified vote | 52.2% | 56.0% | 6 | 1 | 0.158 [0.074, 0.304] | 0.032 [0.006, 0.162] |
| CV | cite vote (unverified) | 39.1% | 47.0% | 4 | 8 | 0.105 [0.042, 0.241] | 0.258 [0.137, 0.432] |
| CONF | confidence-weighted vote | 42.0% | 49.0% | 1 | 3 | 0.026 [0.005, 0.135] | 0.097 [0.033, 0.249] |
| BEST | best single model (mistral, fixed on dev) | 49.3% | 54.0% | 14 | 11 | 0.368 [0.234, 0.527] | 0.355 [0.211, 0.531] |
| D | reducer plurality default (H4) | 49.3% | 54.0% | 4 | 1 | 0.105 [0.042, 0.241] | 0.032 [0.006, 0.162] |
| ORC | oracle (any agent right) | 100.0% | 89.0% | 38 | 0 | 1.000 [0.908, 1.000] | 0.000 [0.000, 0.110] |
| J | Sonnet judge (upper reference) | 100.0% | 89.0% | 38 | 0 | 1.000 [0.908, 1.000] | 0.000 [0.000, 0.110] |
| RS | Sonnet reader (upper reference) | 94.2% | 75.0% | 35 | 1 | 0.921 [0.792, 0.973] | 0.032 [0.006, 0.162] |
| CB-S | closed-book Sonnet (memorisation reference) | 95.7% | 77.0% | 36 | 1 | 0.947 [0.827, 0.985] | 0.032 [0.006, 0.162] |
| J_local | local judge (H2b) | 42.0% | 49.0% | 6 | 8 | 0.158 [0.074, 0.304] | 0.258 [0.137, 0.432] |

Against D: BE-G b_D 5, c_D 0, q_r(D) 0.000.

**pooled (descriptive only)** (595 decisive, 1100 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 68.4% | 74.7% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 83.0% | 82.6% | 100 | 13 | 0.532 [0.461, 0.602] | 0.032 [0.019, 0.054] |
| BE | ungated reducer member/nei0.1 (H1b) | 82.0% | 82.1% | 112 | 31 | 0.596 [0.524, 0.663] | 0.076 [0.054, 0.106] |
| B0 | order-free reducer, no evidence policy | 61.3% | 70.9% | 54 | 96 | 0.287 [0.227, 0.356] | 0.236 [0.197, 0.279] |
| EO | evidence-only weights at BE's mode / NEI | 81.8% | 82.0% | 113 | 33 | 0.601 [0.530, 0.668] | 0.081 [0.058, 0.112] |
| VV | verified vote | 82.5% | 82.4% | 94 | 10 | 0.500 [0.429, 0.571] | 0.025 [0.013, 0.045] |
| CV | cite vote (unverified) | 65.5% | 73.2% | 33 | 50 | 0.176 [0.128, 0.236] | 0.123 [0.094, 0.158] |
| CONF | confidence-weighted vote | 69.9% | 75.5% | 14 | 5 | 0.074 [0.045, 0.121] | 0.012 [0.005, 0.028] |
| BEST | best single model (mistral, fixed on dev) | 67.2% | 74.1% | 72 | 79 | 0.383 [0.316, 0.454] | 0.194 [0.159, 0.235] |
| D | reducer plurality default (H4) | 70.6% | 75.9% | 17 | 4 | 0.090 [0.057, 0.140] | 0.010 [0.004, 0.025] |
| ORC | oracle (any agent right) | 100.0% | 91.8% | 188 | 0 | 1.000 [0.980, 1.000] | 0.000 [0.000, 0.009] |
| J | Sonnet judge (upper reference) | 94.6% | 88.9% | 169 | 13 | 0.899 [0.848, 0.934] | 0.032 [0.019, 0.054] |
| RS | Sonnet reader (upper reference) | 94.3% | 58.7% | 169 | 15 | 0.899 [0.848, 0.934] | 0.037 [0.022, 0.060] |
| CB-S | closed-book Sonnet (memorisation reference) | 91.4% | 57.4% | 164 | 27 | 0.872 [0.817, 0.913] | 0.066 [0.046, 0.095] |
| J_local | local judge (H2b) | 66.4% | 73.6% | 60 | 72 | 0.319 [0.257, 0.389] | 0.177 [0.143, 0.217] |

Against D: BE-G b_D 84, c_D 10, q_r(D) 0.024.

### Gap-closed fraction G = (acc − acc_MAJ) / (acc_REF − acc_MAJ)

| set | method | REF | G | bootstrap 95% CI | undefined resamples |
|---|---|---|---|---|---|
| P | BE | J | 0.644 | [0.517, 0.765] | 0 |
| P | BE | ORC | 0.507 | [0.399, 0.604] | 0 |
| P | BE-G | J | 0.669 | [0.558, 0.779] | 0 |
| P | BE-G | ORC | 0.527 | [0.432, 0.616] | 0 |
| P | EO | J | 0.636 | [0.505, 0.752] | 0 |
| P | EO | ORC | 0.500 | [0.390, 0.601] | 0 |
| P | VV | J | 0.669 | [0.566, 0.771] | 0 |
| P | VV | ORC | 0.527 | [0.436, 0.616] | 0 |
| T | BE | J | 0.132 | [-0.116, 0.333] | 0 |
| T | BE | ORC | 0.132 | [-0.116, 0.333] | 0 |
| T | BE-G | J | 0.211 | [0.061, 0.359] | 0 |
| T | BE-G | ORC | 0.211 | [0.061, 0.359] | 0 |
| T | EO | J | 0.132 | [-0.121, 0.333] | 0 |
| T | EO | ORC | 0.132 | [-0.121, 0.333] | 0 |
| T | VV | J | 0.132 | [0.000, 0.263] | 0 |
| T | VV | ORC | 0.132 | [0.000, 0.263] | 0 |
| pooled | BE | J | 0.519 | [0.404, 0.624] | 0 |
| pooled | BE | ORC | 0.431 | [0.331, 0.522] | 0 |
| pooled | BE-G | J | 0.558 | [0.460, 0.649] | 0 |
| pooled | BE-G | ORC | 0.463 | [0.377, 0.541] | 0 |
| pooled | EO | J | 0.513 | [0.395, 0.617] | 0 |
| pooled | EO | ORC | 0.426 | [0.323, 0.517] | 0 |
| pooled | VV | J | 0.538 | [0.446, 0.628] | 0 |
| pooled | VV | ORC | 0.447 | [0.366, 0.525] | 0 |

### Cost (uniform basis: every disagreement item), latency, replay and audit

**P (SciFact, PopQA, FEVER)**: 622 decisions; 378 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0015 | 4.40 | n/a / n/a | n/a | — | critical path median 0.01 s, p95 3.37 s | 2739 checks, 0 missing |
| J | 0.0143 | 1.00 | 3740 / 117 | n/a | — | median 3327 ms, p95 5905 ms | 100.0% |
| RS | 0.0147 | 1.00 | 4175 / 93 | n/a | — | median 3208 ms, p95 5709 ms | 100.0% |
| CB-S | 0.0044 | 1.00 | 1512 / 123 | 767 | — | median 3117 ms, p95 4752 ms | 100.0% |
| J_local | 0.0000 | 1.00 | 1824 / 21 | n/a | 6.94 | median 6250 ms, p95 12700 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 6.03 ms, p95 12.56 ms.

**T (TruthfulQA stratum)**: 80 decisions; 20 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0020 | 5.50 | n/a / n/a | n/a | — | critical path median 0.01 s, p95 3.40 s | 440 checks, 0 missing |
| J | 0.0132 | 1.00 | 3379 / 115 | n/a | — | median 3361 ms, p95 10174 ms | 100.0% |
| RS | 0.0185 | 1.00 | 5007 / 97 | n/a | — | median 2932 ms, p95 3963 ms | 100.0% |
| CB-S | 0.0046 | 1.00 | 1593 / 94 | 886 | — | median 3094 ms, p95 5472 ms | 100.0% |
| J_local | 0.0000 | 1.00 | 1572 / 20 | n/a | 5.80 | median 5374 ms, p95 9780 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 5.92 ms, p95 13.32 ms.

**pooled (descriptive only)**: 702 decisions; 398 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0015 | 4.53 | n/a / n/a | n/a | — | critical path median 0.01 s, p95 3.37 s | 3179 checks, 0 missing |
| J | 0.0142 | 1.00 | 3699 / 117 | n/a | — | median 3332 ms, p95 6268 ms | 100.0% |
| RS | 0.0152 | 1.00 | 4270 / 94 | n/a | — | median 3180 ms, p95 5666 ms | 100.0% |
| CB-S | 0.0044 | 1.00 | 1521 / 119 | 781 | — | median 3112 ms, p95 4756 ms | 100.0% |
| J_local | 0.0000 | 1.00 | 1796 / 20 | n/a | 6.81 | median 6176 ms, p95 12502 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 6.02 ms, p95 12.56 ms.

Gold-shown diagnostic checks (excluded from $/decision): 2506 checks, $11.35.

| replay | result |
|---|---|
| BE identity (each reduction run twice) | byte-identical on 1100 / 1100 eligible items |
| BE-G identity (each reduction run twice) | byte-identical on 1100 / 1100 eligible items |
| J regeneration | agreement 97.5% on 200 items (planned set matched: True) |
| BE-G leave-one-agent-out | 3510 re-decisions on 702 items, 0 model calls, 23.32 s total; decision changed in 330 (9.4%) |
| J leave-one-agent-out | counterfactual 5 calls per item ≈ $0.071, 19.0 s per item; subsample rows 250, decision changed 5.6% |

| set | BE-G overturns | labelled passages per overturn (median, max) | characters (median, max) | J context tokens per decision (median) |
|---|---|---|---|---|
| P | 104 | 1, 4 | 950, 2796 | 3649 |
| T | 6 | 1, 1 | 922, 992 | 3402 |
| pooled | 110 | 1, 4 | 938, 2796 | 3630 |

### Majority-following (agreement with MAJ on majority-wrong decisive items)

| set | majority-wrong items | J | RS | CB-S | J_local |
|---|---|---|---|---|---|
| P | 150 | 17 / 150 | 15 / 150 | 17 / 150 | 87 / 150 |
| T | 38 | 0 / 38 | 0 / 38 | 0 / 38 | 27 / 38 |
| pooled | 188 | 17 / 188 | 15 / 188 | 17 / 188 | 114 / 188 |

### Close pairs and subgroups

| set | pair | N | b | c | p |
|---|---|---|---|---|---|
| P | BE-G vs VV | 526 | 9 | 9 | 1.0000 |
| P | BE vs EO | 526 | 6 | 5 | 1.0000 |
| T | BE-G vs VV | 69 | 4 | 1 | 0.3750 |
| T | BE vs EO | 69 | 2 | 2 | 1.0000 |
| pooled | BE-G vs VV | 595 | 13 | 10 | 0.6776 |
| pooled | BE vs EO | 595 | 8 | 7 | 1.0000 |

| subgroup | N | MAJ | BE-G | BE | J | BE-G vs MAJ b / c, p |
|---|---|---|---|---|---|---|
| P:fever | 199 | 76.9% | 89.9% | 89.4% | 93.0% | 28 / 2, 8.68e-07 |
| P:popqa | 173 | 67.6% | 80.3% | 77.5% | 95.4% | 30 / 8, 4.72e-04 |
| P:scifact | 154 | 68.8% | 89.0% | 90.9% | 93.5% | 33 / 2, 3.67e-08 |
| T:truthfulqa | 69 | 44.9% | 56.5% | 52.2% | 100.0% | 9 / 1, 0.0215 |
| popqa pop_1e3_1e4 | 60 | 55.0% | 80.0% | 80.0% | 95.0% | 16 / 1, 2.75e-04 |
| popqa pop_1e4_1e5 | 64 | 70.3% | 73.4% | 71.9% | 93.8% | 8 / 6, 0.7905 |
| popqa pop_ge_1e5 | 49 | 79.6% | 89.8% | 81.6% | 98.0% | 6 / 1, 0.1250 |
| SciFact REFUTED | 43 | 39.5% | 83.7% | 88.4% | 95.3% | 19 / 0, 3.81e-06 |

### Sensitivity analyses (pre-declared, descriptive)

| analysis | contrast | N | b | c | p |
|---|---|---|---|---|---|
| PopQA excluded | H1a: BE-G vs MAJ on P | 353 | 61 | 4 | 3.92e-14 |
| MAJ with earliest-arrival ties | H1a: BE-G vs MAJ_early on P | 526 | 90 | 11 | 1.42e-16 |
| PopQA excluded | H1b: BE vs MAJ on P | 353 | 70 | 11 | 1.18e-11 |
| MAJ with earliest-arrival ties | H1b: BE vs MAJ_early on P | 526 | 98 | 22 | 1.22e-12 |
| c and q_r against D | BE-G vs D on P | 526 | 79 | 10 (q_r 0.026) | |
| null J decisions scored wrong (0 nulls) | BE-G vs J on P | 526 | 11 | 50 | 4.59e-07 |
| null J_local decisions scored wrong (0 nulls) | BE-G vs J_local on P | 526 | 110 | 21 | 9.43e-16 |
| null J decisions scored wrong (0 nulls) | BE-G vs J on T | 69 | 0 | 30 | 1.86e-09 |
| null J_local decisions scored wrong (0 nulls) | BE-G vs J_local on T | 69 | 16 | 6 | 0.0525 |

Witness sample for blinded labelling: 100 BE-G overturn witnesses in `witness_sample_v5.jsonl` (labels and κ against G-AK are added outside the evaluator).

### Also reported

- Gate stages (BE-G, decisive): P {"plurality": 99, "verified": 427}; T {"plurality": 56, "verified": 13}; pooled {"plurality": 155, "verified": 440}.
- S4 separation (δ = 0.05): BE-G 229 / 595; BE 215 / 595.
- Hosted checks cited: 4742; status {"ok": 4741, "refused": 1}; mapped labels on citations {"not_enough_info": 3388, "parse_error": 1, "refutes": 666, "supports": 4100}.
- Evidence availability (decisive, diagnostic): fever 83.9%; popqa 84.4%; scifact 84.4%; truthfulqa 20.3%.
- Fallbacks on decisive conflicts: P {"BEST_fallback": 0, "CB-S_missing": 1, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 0, "RS_missing": 1, "VV_fallback": 99}; T {"BEST_fallback": 0, "CB-S_missing": 0, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 0, "RS_missing": 0, "VV_fallback": 56}; pooled {"BEST_fallback": 0, "CB-S_missing": 1, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 0, "RS_missing": 1, "VV_fallback": 155}.
- Mirror check: 7910 slots, 0 mismatches. Counts: {"mirror_checked": 7910, "support_records": 8155}.

## 4. Dev gate (§6.2) and the selections (PREREGISTRATION.md §5.2)

| check | value | threshold | pass | if it fails |
|---|---|---|---|---|
| yield y_dev | 0.537 | ≥ 0.3 | True | mixed-fleet arm (§3.2) |
| majority-wrong share m_dev | 0.302 (expected tie-break 0.306) | ≥ 0.2 | True | mixed-fleet arm (§3.2) |
| evidence availability per source | fever 89.5% (lower bound); popqa 56.2%; scifact 86.2% (lower bound); truthfulqa 18.2% | ≥ 0.3 | False | §2.2 TQA switch (TruthfulQA quota -> PopQA and FEVER) |
| parse failure, worst agent | 0.0% | < 0.05 | True | one schema fix |

All four pass: **False**. Stopping rule: ψ_dev = 0.279 (used 0.279), N\* = 409, I = **1000** items (unclamped 761).

| configuration | gated | changed fields | b | c | b − c | ψ | policy template sha256 |
|---|---|---|---|---|---|---|---|
| `member/nei0.5` | no | 0 | 14 | 9 | 5 | 0.267 | `154f50b024b90b2b` |
| `member/nei0.1` **(BE)** | no | 1 | 15 | 9 | 6 | 0.279 | `084ecdbdcd06193b` |
| `member/nei0` | no | 1 | 14 | 9 | 5 | 0.267 | `554da1a336c77a62` |
| `value:max/nei0.5` | no | 1 | 14 | 9 | 5 | 0.267 | `b3060b352bb9509f` |
| `value:max/nei0.1` | no | 2 | 15 | 10 | 5 | 0.291 | `dacc8b542dac2c25` |
| `value:max/nei0` | no | 2 | 14 | 9 | 5 | 0.267 | `a6d3ead0359192b9` |
| `value:pooled/nei0.5` | no | 1 | 13 | 9 | 4 | 0.256 | `bb5dbf64dee2a8c4` |
| `value:pooled/nei0.1` | no | 2 | 13 | 11 | 2 | 0.279 | `204115d5e683e77a` |
| `value:pooled/nei0` | no | 2 | 13 | 11 | 2 | 0.279 | `38e265a9757c0b5a` |
| `member/nei0.5/gated` **(BE-G)** | yes | 1 | 11 | 1 | 10 | 0.140 | `99c8b9c91c27d4fc` |
| `member/nei0.1/gated` | yes | 2 | 11 | 2 | 9 | 0.151 | `7d6990cf56cab1b8` |
| `member/nei0/gated` | yes | 2 | 10 | 4 | 6 | 0.163 | `badf42547b61f1f6` |
| `value:max/nei0.5/gated` | yes | 2 | 11 | 1 | 10 | 0.140 | `79036cb50d1ac9e8` |
| `value:max/nei0.1/gated` | yes | 3 | 11 | 2 | 9 | 0.151 | `b5bc92b192c787e8` |
| `value:max/nei0/gated` | yes | 3 | 10 | 4 | 6 | 0.163 | `04d36e5d6c643966` |
| `value:pooled/nei0.5/gated` | yes | 2 | 11 | 2 | 9 | 0.151 | `99443fedad15860d` |
| `value:pooled/nei0.1/gated` | yes | 3 | 11 | 4 | 7 | 0.174 | `9d3320caf2f92050` |
| `value:pooled/nei0/gated` | yes | 3 | 10 | 4 | 6 | 0.163 | `44f01d13622a1c72` |

