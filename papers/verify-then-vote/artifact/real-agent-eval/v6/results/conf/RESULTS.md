# Eval v6 results (confirmatory)

Pool: falcon3:3b, olmo2:7b, exaone3.5:7.8b, nemotron-mini:4b, granite3.3:2b (family-disjoint from v5). Items: 1100. Eligible: 1100. Decisive conflicts: **615** (yield 0.559). BE-G: `member/nei0.5/gated`. BE: `member/nei0.1`. BE-G-L: `not run`. BEST agent: `exaone3.5_7.8b`.

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
| P (SciFact, PopQA, FEVER) | 1000 | 1000 | 547 | 634 | 0.547 | fever 221, popqa 209, scifact 117 |
| T (TruthfulQA stratum) | 100 | 100 | 68 | 79 | 0.680 | truthfulqa 68 |
| pooled (descriptive only) | 1100 | 1100 | 615 | 713 | 0.559 | fever 221, popqa 209, scifact 117, truthfulqa 68 |

Set rule: tier primary -> P, tier tqa_stratum -> T (prereg §6.3); items without those tiers: TruthfulQA -> T, other sources -> P. P and T are never pooled for a test.

## 1. Preregistered analyses

### F1 (primary): VV/VDF, fixed sequence (H1a-VDF at α = 0.05, then H3a-VDF at one-sided 0.025 only if step 1 rejects with b > c)

> VDF was designed post hoc on v5 confirmatory data. This is its first confirmatory test, on a new pool (PREREGISTRATION.md §13).

| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |
|---|---|---|---|---|---|---|---|---|---|---|
| H1a-VDF | VV/VDF vs MAJ on P | 547 | 73 | 3 | 0.128 | [0.099, 0.158] | [0.099, 0.157] | 1.94e-18 | yes | better |

| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |
|---|---|---|---|---|---|---|---|---|
| H3a-VDF | VV/VDF | 400 | 3 | 0.007 | 0.0218 | < 0.05 | 11 | yes |

H3a-VDF reading: harm below 5% shown.

| | MAJ wrong | p̂_w = b / #wrong (Wilson 95%) | MAJ right | q̂_r = c / #right (Wilson 95%) |
|---|---|---|---|---|
| VV/VDF | 147 | 0.497 [0.417, 0.576] | 400 | 0.007 [0.003, 0.022] |

Sequence completed: **yes**.

**Pre-declared sensitivity: P without the 15 v5 design-set items** (sorted id list sha256 `b675a5e67267d695f3dd93fd18dae360e1d1491cf56b7c4835061b1930fe3832`; 14 of them are decisive P conflicts in this run; N = 533).

| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |
|---|---|---|---|---|---|---|---|---|---|---|
| H1a-VDF (no design set) | VV/VDF vs MAJ on P | 533 | 73 | 3 | 0.131 | [0.102, 0.162] | [0.101, 0.161] | 1.94e-18 | yes | better |

| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |
|---|---|---|---|---|---|---|---|---|
| H3a-VDF (no design set) | VV/VDF | 392 | 3 | 0.008 | 0.0222 | < 0.05 | 11 | yes |

H3a-VDF reading: harm below 5% shown.

Sequence completed without the design set: **yes**.

**H4 analogue for VDF** (c ≤ F; VV/VDF against MAJ, BE-G/VDF against D; a violation is an implementation defect)

| set | method | N | c_D | b_D | F | c_D items ⊆ F items | c vs MAJ | c vs MAJ not in F (tied) |
|---|---|---|---|---|---|---|---|---|
| P | BE-G/VDF | 547 | 3 | 63 | 46 | yes | 5 | 1 (1) |
| P | VV/VDF | 547 | 3 | 73 | 46 | yes | 3 | 0 (0) |
| T | BE-G/VDF | 68 | 2 | 1 | 3 | yes | 5 | 4 (4) |
| T | VV/VDF | 68 | 1 | 2 | 3 | yes | 1 | 0 (0) |

harm_bound_holds on P and T: **True**.

### F2 · H1-rep: BE-G and BE vs MAJ on P (exact two-sided McNemar, Holm, family-wise α = 0.05)

| | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | Holm threshold | Holm-adjusted p | reject | reading |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1a-rep | BE-G vs MAJ on P | 547 | 80 | 8 | 0.132 | [0.100, 0.164] | [0.101, 0.163] | 4.60e-16 | 0.025 | 9.20e-16 | yes | better |
| H1b-rep | BE vs MAJ on P | 547 | 92 | 23 | 0.126 | [0.089, 0.163] | [0.088, 0.163] | 5.79e-11 | 0.050 | 5.79e-11 | yes | better |

| | MAJ wrong | p̂_w = b / #wrong (Wilson 95%) | MAJ right | q̂_r = c / #right (Wilson 95%) |
|---|---|---|---|---|
| H1a-rep | 147 | 0.544 [0.464, 0.623] | 400 | 0.020 [0.010, 0.039] |
| H1b-rep | 147 | 0.626 [0.545, 0.700] | 400 | 0.058 [0.039, 0.085] |

Holm order: H1a-rep, H1b-rep. A rejection reads as "better" only if b > c.

### F2 · H3-rep: no harm (own α each, outside the H1 family)

| test | method | set | n_R | c | q̂_r | one-sided 97.5% Clopper–Pearson upper bound | bound | largest c that rejects | reject |
|---|---|---|---|---|---|---|---|---|---|
| H3a-rep | BE-G | P | 400 | 8 | 0.020 | 0.0390 | < 0.05 | 11 | yes |
| H3a-rep (BE, descriptive) | BE | P | 400 | 23 | 0.058 | 0.0850 | < 0.05 | 11 | no |

| test | method | set | N | b | c | difference | Newcombe 95% CI | lower bound > −0.03 | reading |
|---|---|---|---|---|---|---|---|---|---|
| H3b-rep | BE-G | T | 68 | 7 | 5 | 0.029 | [-0.068, 0.126] | no | not shown |
| H3b-rep (BE, descriptive) | BE | T | 68 | 10 | 19 | -0.132 | [-0.276, 0.020] | no | not shown; point estimate negative |

Power warning (pre-declared): power about 0.81 if BE-G and MAJ never disagree on T, 0.31 at b = c = 2%, 0.08 at dev's rate; a non-rejection is 'not shown', never harm, unless the estimate is negative.

### H2: local arm (fixed sequence, own α = 0.05)

not run: no local checks supplied. H2 is reported as "not run as confirmatory; local checker unvalidated".

### H4: gate soundness (c_D <= F (v3/GATE_SPEC.md §3))

F-hat rate: 0.0514 (18/350).

| set | method | N | c_D | b_D | F | c_D items ⊆ F items | F-hat | checked incorrect pairs | c vs MAJ | c vs MAJ not in F (tied) |
|---|---|---|---|---|---|---|---|---|---|---|
| P | BE-G | 547 | 6 | 66 | 46 | yes | 57.61 | 1184 | 8 | 1 (1) |
| T | BE-G | 68 | 2 | 1 | 3 | yes | 11.88 | 253 | 5 | 4 (4) |

harm_bound_holds on P and T: **True**. F items (P, BE-G): `v5-fever119298`, `v5-fever127363`, `v5-fever153147`, `v5-fever26317`, `v5-fever3019`, `v5-fever39855`, `v5-fever80417`, `v5-fever90151`, `v5-fever91498`, `v5-popqa1085503`, `v5-popqa1390922`, `v5-popqa145561`, `v5-popqa1613612`, `v5-popqa175943`, `v5-popqa1860287`, `v5-popqa1863504`, `v5-popqa2142166`, `v5-popqa2155468`, `v5-popqa2253188`, `v5-popqa2342806`, `v5-popqa255030`, `v5-popqa2785946`, `v5-popqa2839774`, `v5-popqa2941131`, `v5-popqa3146871`, `v5-popqa332734`, `v5-popqa3592879`, `v5-popqa4514247`, `v5-popqa4686489`, `v5-popqa486355`, `v5-popqa5724067`, `v5-popqa5781914`, `v5-popqa5815002`, `v5-popqa6278529`, `v5-popqa633894`, `v5-popqa6404382`, `v5-popqa6409098`, `v5-popqa645704`, `v5-popqa6493088`, `v5-popqa6503240`, `v5-popqa760352`, `v5-popqa996246`, `v5-scifactdev593`, `v5-scifactdev692`, `v5-scifactdev770`, `v5-scifactdev808`. c against MAJ not explained by F (tied pluralities, GATE_SPEC §3 caveat 1): `v5-popqa6117457`, `v5-tqa0051`, `v5-tqa0331`, `v5-tqa0395`, `v5-tqa0743`.

### §2.4 references and baselines (descriptive; Holm-adjusted p for the reference family vs MAJ)

**P (SciFact, PopQA, FEVER).** Not run: J_local.

| method | role | accuracy | b / c vs MAJ | p | Holm p | BE-G vs method: b / c, p |
|---|---|---|---|---|---|---|
| BEST | best single model (exaone3.5_7.8b, fixed on dev) | 79.3% | 84 / 50 | 0.0042 | n/a | 71 / 33, 2.47e-04 |
| CB-S | closed-book Sonnet (memorisation reference) | 90.5% | 120 / 25 | 4.37e-16 | 1.31e-15 | 34 / 57, 0.0206 |
| CONF | confidence-weighted vote | 74.0% | 11 / 6 | 0.3323 | 0.3323 | 77 / 10, 5.92e-14 |
| CV | cite vote (unverified) | 70.4% | 35 / 50 | 0.1284 | 0.2568 | 100 / 13, 8.47e-18 |
| J | Sonnet judge (upper reference) | 93.6% | 122 / 10 | 1.25e-25 | 5.76e-25 | 11 / 51, 2.78e-07 |
| RS | Sonnet reader (upper reference) | 94.3% | 128 / 12 | 1.15e-25 | 5.76e-25 | 15 / 59, 2.55e-07 |
| VV | verified vote | 85.9% | 76 / 6 | 1.57e-16 | n/a | 5 / 3, 0.7266 |

**T (TruthfulQA stratum).** Not run: J_local.

| method | role | accuracy | b / c vs MAJ | p | Holm p | BE-G vs method: b / c, p |
|---|---|---|---|---|---|---|
| BEST | best single model (exaone3.5_7.8b, fixed on dev) | 58.8% | 14 / 7 | 0.1892 | n/a | 5 / 10, 0.3018 |
| CB-S | closed-book Sonnet (memorisation reference) | 98.5% | 35 / 1 | 1.08e-09 | 4.31e-09 | 1 / 33, 4.07e-09 |
| CONF | confidence-weighted vote | 50.0% | 5 / 4 | 1.0000 | 1.0000 | 6 / 5, 1.0000 |
| CV | cite vote (unverified) | 42.6% | 5 / 9 | 0.4240 | 0.8479 | 8 / 2, 0.1094 |
| J | Sonnet judge (upper reference) | 98.5% | 34 / 0 | 1.16e-10 | 5.82e-10 | 0 / 32, 4.66e-10 |
| RS | Sonnet reader (upper reference) | 97.1% | 34 / 1 | 2.10e-09 | 6.29e-09 | 1 / 32, 7.92e-09 |
| VV | verified vote | 50.0% | 2 / 1 | 1.0000 | n/a | 5 / 4, 1.0000 |

## 1b. Secondary analyses (pre-declared, unadjusted, no confirmatory claim)

### BE-G/VDF against MAJ on P (H1a form and H3a form), next to BE-G

| step | contrast | N | b | c | (b − c)/N | Newcombe 95% CI | bootstrap 95% CI | exact McNemar p | reject | reading |
|---|---|---|---|---|---|---|---|---|---|---|
| H1a-form | BE-G/VDF vs MAJ on P | 547 | 77 | 5 | 0.132 | [0.101, 0.163] | [0.101, 0.163] | 1.20e-17 | yes | better |

| step | method | n_R | c | q̂_r | one-sided 97.5% CP upper bound | bound | largest c that rejects | reject |
|---|---|---|---|---|---|---|---|---|
| H3a-form | BE-G/VDF | 400 | 5 | 0.013 | 0.0289 | < 0.05 | 11 | yes |

### VV/VDF on T (H3b form: Newcombe lower bound > −0.03)

| method | N | b | c | difference | Newcombe 95% CI | lower bound > −0.03 | reading |
|---|---|---|---|---|---|---|---|
| VV/VDF | 68 | 2 | 1 | 0.015 | [-0.034, 0.063] | no | not shown |
| BE-G/VDF | 68 | 7 | 5 | 0.029 | [-0.068, 0.126] | no | not shown |

### H3a-pool (BE-G only; declared after v5's H3a miss; the v5 half is fixed at c = 12, n_R = 376)

pooled across two pools (secondary; declared after v5's H3a miss)

| test | c | n | q̂_pool | one-sided 97.5% CP upper bound | < 0.05 | c₆ allowed |
|---|---|---|---|---|---|---|
| exact pooled (decides H3a-pool) | 20 | 776 | 0.0258 | 0.0395 | yes | 14 |

Dependence-robust sensitivity: U₅ = 0.0587, U₆ = 0.0421, U = 0.0501; holds robustly (U < 0.05): **no** (c₆ allowed 7). It does not decide H3a-pool.

Items that are c-events in both pools: 1 (v5 only 11, v6 only 7). Item-cluster bootstrap 95% interval of q_pool: [0.0150, 0.0385] (10000 resamples, seed 42).

### Cross-pool consistency (descriptive; v6 − v5 with Newcombe hybrid 95% intervals; no test of 'same effect in both pools')

| set | method | (b − c)/N v5 → v6 | difference | q̂_r v5 → v6 | difference | p̂_w v5 → v6 | difference |
|---|---|---|---|---|---|---|---|
| P | BE | 0.144 → 0.126 | -0.018 [-0.072, 0.036] | 0.061 → 0.058 | -0.004 [-0.038, 0.030] | 0.660 → 0.626 | -0.034 [-0.141, 0.074] |
| P | BE-G | 0.150 → 0.132 | -0.019 [-0.066, 0.029] | 0.032 → 0.020 | -0.012 [-0.037, 0.011] | 0.607 → 0.544 | -0.062 [-0.172, 0.049] |
| P | BE-G/VDF (v5 side post hoc) | 0.154 → 0.132 | -0.022 [-0.068, 0.023] | 0.016 → 0.013 | -0.003 [-0.023, 0.015] | 0.580 → 0.524 | -0.056 [-0.167, 0.056] |
| P | VV | 0.150 → 0.128 | -0.022 [-0.068, 0.024] | 0.024 → 0.015 | -0.009 [-0.031, 0.012] | 0.587 → 0.517 | -0.070 [-0.180, 0.043] |
| P | VV/VDF (v5 side post hoc) | 0.158 → 0.128 | -0.030 [-0.074, 0.014] | 0.011 → 0.007 | -0.003 [-0.020, 0.013] | 0.580 → 0.497 | -0.083 [-0.194, 0.030] |
| T | BE | 0.072 → -0.132 | -0.205 [-0.394, -0.006] | 0.258 → 0.576 | 0.318 [0.076, 0.512] | 0.342 → 0.286 | -0.056 [-0.257, 0.154] |
| T | BE-G | 0.116 → 0.029 | -0.087 [-0.213, 0.042] | 0.032 → 0.152 | 0.119 [-0.036, 0.279] | 0.237 → 0.200 | -0.037 [-0.221, 0.155] |
| T | BE-G/VDF (v5 side post hoc) | 0.116 → 0.029 | -0.087 [-0.213, 0.042] | 0.032 → 0.152 | 0.119 [-0.036, 0.279] | 0.237 → 0.200 | -0.037 [-0.221, 0.155] |
| T | VV | 0.072 → 0.015 | -0.058 [-0.143, 0.029] | 0.032 → 0.030 | -0.002 [-0.134, 0.124] | 0.158 → 0.057 | -0.101 [-0.253, 0.053] |
| T | VV/VDF (v5 side post hoc) | 0.072 → 0.015 | -0.058 [-0.143, 0.029] | 0.032 → 0.030 | -0.002 [-0.134, 0.124] | 0.158 → 0.057 | -0.101 [-0.253, 0.053] |

Cost with caching (prereg §7: marginal and full-label $ per decision, cache share) is not computed here; it needs the v5 and v6 `check_calls.jsonl` logs.

### Reading (v6 PREREGISTRATION.md §14)

**F1 (VV/VDF).**

- H1a-VDF and H3a-VDF both reject: verified default first beats majority and shows harm below 5% on a new, family-disjoint pool. This is its first confirmatory test; the rule was designed post hoc on v5.

**F2 (replication of v5).**

- H1a-rep rejects and H3a-rep holds: v5's BE-G result replicates, now with harm below 5% shown.

## 2. Deviations

- hosted check records on P carry no token counts (only $ and wall time are reported for checks)
- hosted check records on T carry no token counts (only $ and wall time are reported for checks)

## 3. Descriptive analyses (H5, sensitivity)

### Accuracy and overturn rates by set

**P (SciFact, PopQA, FEVER)** (547 decisive, 1000 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 73.1% | 75.9% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 86.3% | 83.1% | 80 | 8 | 0.544 [0.464, 0.623] | 0.020 [0.010, 0.039] |
| BE | ungated reducer member/nei0.1 (H1b) | 85.7% | 82.8% | 92 | 23 | 0.626 [0.545, 0.700] | 0.058 [0.039, 0.085] |
| B0 | order-free reducer, no evidence policy | 60.1% | 68.8% | 43 | 114 | 0.293 [0.225, 0.371] | 0.285 [0.243, 0.331] |
| EO | evidence-only weights at BE's mode / NEI | 84.6% | 82.2% | 93 | 30 | 0.633 [0.552, 0.706] | 0.075 [0.053, 0.105] |
| VV | verified vote | 85.9% | 82.9% | 76 | 6 | 0.517 [0.437, 0.596] | 0.015 [0.007, 0.032] |
| CV | cite vote (unverified) | 70.4% | 74.4% | 35 | 50 | 0.238 [0.176, 0.313] | 0.125 [0.096, 0.161] |
| CONF | confidence-weighted vote | 74.0% | 76.4% | 11 | 6 | 0.075 [0.042, 0.129] | 0.015 [0.007, 0.032] |
| BEST | best single model (exaone3.5_7.8b, fixed on dev) | 79.3% | 79.3% | 84 | 50 | 0.571 [0.491, 0.649] | 0.125 [0.096, 0.161] |
| D | reducer plurality default (H4) | 75.3% | 77.1% | 15 | 3 | 0.102 [0.063, 0.162] | 0.007 [0.003, 0.022] |
| ORC | oracle (any agent right) | 100.0% | 90.6% | 147 | 0 | 1.000 [0.975, 1.000] | 0.000 [0.000, 0.010] |
| J | Sonnet judge (upper reference) | 93.6% | 87.1% | 122 | 10 | 0.830 [0.761, 0.882] | 0.025 [0.014, 0.045] |
| RS | Sonnet reader (upper reference) | 94.3% | 57.4% | 128 | 12 | 0.871 [0.807, 0.916] | 0.030 [0.017, 0.052] |
| CB-S | closed-book Sonnet (memorisation reference) | 90.5% | 68.2% | 120 | 25 | 0.816 [0.746, 0.871] | 0.062 [0.043, 0.091] |

Against D: BE-G b_D 66, c_D 6, q_r(D) 0.015.

**T (TruthfulQA stratum)** (68 decisive, 100 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 48.5% | 50.0% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 51.5% | 52.0% | 7 | 5 | 0.200 [0.100, 0.359] | 0.152 [0.067, 0.309] |
| BE | ungated reducer member/nei0.1 (H1b) | 35.3% | 41.0% | 10 | 19 | 0.286 [0.163, 0.451] | 0.576 [0.408, 0.728] |
| B0 | order-free reducer, no evidence policy | 35.3% | 41.0% | 8 | 17 | 0.229 [0.121, 0.390] | 0.515 [0.352, 0.675] |
| EO | evidence-only weights at BE's mode / NEI | 41.2% | 45.0% | 10 | 15 | 0.286 [0.163, 0.451] | 0.455 [0.298, 0.620] |
| VV | verified vote | 50.0% | 51.0% | 2 | 1 | 0.057 [0.016, 0.186] | 0.030 [0.005, 0.153] |
| CV | cite vote (unverified) | 42.6% | 46.0% | 5 | 9 | 0.143 [0.063, 0.294] | 0.273 [0.151, 0.442] |
| CONF | confidence-weighted vote | 50.0% | 51.0% | 5 | 4 | 0.143 [0.063, 0.294] | 0.121 [0.048, 0.273] |
| BEST | best single model (exaone3.5_7.8b, fixed on dev) | 58.8% | 57.0% | 14 | 7 | 0.400 [0.256, 0.564] | 0.212 [0.107, 0.378] |
| D | reducer plurality default (H4) | 52.9% | 53.0% | 7 | 4 | 0.200 [0.100, 0.359] | 0.121 [0.048, 0.273] |
| ORC | oracle (any agent right) | 100.0% | 85.0% | 35 | 0 | 1.000 [0.901, 1.000] | 0.000 [0.000, 0.104] |
| J | Sonnet judge (upper reference) | 98.5% | 84.0% | 34 | 0 | 0.971 [0.855, 0.995] | 0.000 [0.000, 0.104] |
| RS | Sonnet reader (upper reference) | 97.1% | 76.0% | 34 | 1 | 0.971 [0.855, 0.995] | 0.030 [0.005, 0.153] |
| CB-S | closed-book Sonnet (memorisation reference) | 98.5% | 86.0% | 35 | 1 | 1.000 [0.901, 1.000] | 0.030 [0.005, 0.153] |

Against D: BE-G b_D 1, c_D 2, q_r(D) 0.056.

**pooled (descriptive only)** (615 decisive, 1100 eligible).

| method | role | decisive | eligible | b vs MAJ | c vs MAJ | p̂_w (Wilson 95%) | q̂_r (Wilson 95%) |
|---|---|---|---|---|---|---|---|
| MAJ | canonical majority (baseline) | 70.4% | 73.5% | — | — | — | — |
| BE-G | gated reducer member/nei0.5/gated (H1a) | 82.4% | 80.3% | 87 | 13 | 0.478 [0.407, 0.550] | 0.030 [0.018, 0.051] |
| BE | ungated reducer member/nei0.1 (H1b) | 80.2% | 79.0% | 102 | 42 | 0.560 [0.488, 0.631] | 0.097 [0.073, 0.129] |
| B0 | order-free reducer, no evidence policy | 57.4% | 66.3% | 51 | 131 | 0.280 [0.220, 0.349] | 0.303 [0.261, 0.347] |
| EO | evidence-only weights at BE's mode / NEI | 79.8% | 78.8% | 103 | 45 | 0.566 [0.493, 0.636] | 0.104 [0.079, 0.136] |
| VV | verified vote | 82.0% | 80.0% | 78 | 7 | 0.429 [0.359, 0.501] | 0.016 [0.008, 0.033] |
| CV | cite vote (unverified) | 67.3% | 71.8% | 40 | 59 | 0.220 [0.166, 0.285] | 0.136 [0.107, 0.172] |
| CONF | confidence-weighted vote | 71.4% | 74.1% | 16 | 10 | 0.088 [0.055, 0.138] | 0.023 [0.013, 0.042] |
| BEST | best single model (exaone3.5_7.8b, fixed on dev) | 77.1% | 77.3% | 98 | 57 | 0.538 [0.466, 0.609] | 0.132 [0.103, 0.167] |
| D | reducer plurality default (H4) | 72.8% | 74.9% | 22 | 7 | 0.121 [0.081, 0.176] | 0.016 [0.008, 0.033] |
| ORC | oracle (any agent right) | 100.0% | 90.1% | 182 | 0 | 1.000 [0.979, 1.000] | 0.000 [0.000, 0.009] |
| J | Sonnet judge (upper reference) | 94.1% | 86.8% | 156 | 10 | 0.857 [0.799, 0.901] | 0.023 [0.013, 0.042] |
| RS | Sonnet reader (upper reference) | 94.6% | 59.1% | 162 | 13 | 0.890 [0.836, 0.928] | 0.030 [0.018, 0.051] |
| CB-S | closed-book Sonnet (memorisation reference) | 91.4% | 69.8% | 155 | 26 | 0.852 [0.793, 0.896] | 0.060 [0.041, 0.087] |

Against D: BE-G b_D 67, c_D 8, q_r(D) 0.018.

### Gap-closed fraction G = (acc − acc_MAJ) / (acc_REF − acc_MAJ)

| set | method | REF | G | bootstrap 95% CI | undefined resamples |
|---|---|---|---|---|---|
| P | BE | J | 0.616 | [0.478, 0.742] | 0 |
| P | BE | ORC | 0.469 | [0.359, 0.568] | 0 |
| P | BE-G | J | 0.643 | [0.527, 0.756] | 0 |
| P | BE-G | ORC | 0.490 | [0.396, 0.578] | 0 |
| P | EO | J | 0.562 | [0.411, 0.695] | 0 |
| P | EO | ORC | 0.429 | [0.309, 0.535] | 0 |
| P | VV | J | 0.625 | [0.517, 0.732] | 0 |
| P | VV | ORC | 0.476 | [0.386, 0.563] | 0 |
| T | BE | J | -0.265 | [-0.690, 0.029] | 0 |
| T | BE | ORC | -0.257 | [-0.667, 0.027] | 0 |
| T | BE-G | J | 0.059 | [-0.156, 0.238] | 0 |
| T | BE-G | ORC | 0.057 | [-0.152, 0.234] | 0 |
| T | EO | J | -0.147 | [-0.517, 0.119] | 0 |
| T | EO | ORC | -0.143 | [-0.500, 0.114] | 0 |
| T | VV | J | 0.029 | [-0.069, 0.132] | 0 |
| T | VV | ORC | 0.029 | [-0.067, 0.128] | 0 |
| pooled | BE | J | 0.411 | [0.275, 0.533] | 0 |
| pooled | BE | ORC | 0.330 | [0.217, 0.430] | 0 |
| pooled | BE-G | J | 0.507 | [0.405, 0.605] | 0 |
| pooled | BE-G | ORC | 0.407 | [0.321, 0.488] | 0 |
| pooled | EO | J | 0.397 | [0.261, 0.523] | 0 |
| pooled | EO | ORC | 0.319 | [0.205, 0.422] | 0 |
| pooled | VV | J | 0.486 | [0.393, 0.577] | 0 |
| pooled | VV | ORC | 0.390 | [0.311, 0.466] | 0 |

### Cost (uniform basis: every disagreement item), latency, replay and audit

**P (SciFact, PopQA, FEVER)**: 634 decisions; 366 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0083 | 4.41 | n/a / n/a | n/a | — | critical path median 2.64 s, p95 3.98 s | 2795 checks, 0 missing |
| J | 0.0139 | 1.00 | 3598 / 117 | n/a | — | median 3058 ms, p95 9435 ms | 100.0% |
| RS | 0.0148 | 1.00 | 4201 / 92 | n/a | — | median 3150 ms, p95 5477 ms | 100.0% |
| CB-S | 0.0044 | 1.00 | 1510 / 123 | 768 | — | median 3068 ms, p95 4772 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 5.87 ms, p95 6.83 ms.

**T (TruthfulQA stratum)**: 79 decisions; 21 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0154 | 6.01 | n/a / n/a | n/a | — | critical path median 2.79 s, p95 3.63 s | 475 checks, 0 missing |
| J | 0.0129 | 1.00 | 3327 / 123 | n/a | — | median 2830 ms, p95 5519 ms | 100.0% |
| RS | 0.0188 | 1.00 | 5119 / 88 | n/a | — | median 3092 ms, p95 6050 ms | 100.0% |
| CB-S | 0.0046 | 1.00 | 1592 / 94 | 899 | — | median 3096 ms, p95 5579 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 5.91 ms, p95 8.09 ms.

**pooled (descriptive only)**: 713 decisions; 387 single-value items forced with no call.

| decider | $ / decision | calls / decision | input / output tokens per decision | cache-creation tokens | local wall s / decision | latency per decision | coverage |
|---|---|---|---|---|---|---|---|
| BE-G / BE / VV (hosted checks, shared labels) | 0.0091 | 4.59 | n/a / n/a | n/a | — | critical path median 2.66 s, p95 3.97 s | 3270 checks, 0 missing |
| J | 0.0138 | 1.00 | 3568 / 118 | n/a | — | median 3025 ms, p95 8217 ms | 100.0% |
| RS | 0.0153 | 1.00 | 4303 / 92 | n/a | — | median 3146 ms, p95 5695 ms | 100.0% |
| CB-S | 0.0044 | 1.00 | 1519 / 119 | 783 | — | median 3070 ms, p95 4788 ms | 100.0% |
| MAJ, CV, CONF, BEST, B0 | 0 | 0 | — | — | — | — | |

Reducer wall time (BE-G): median 5.87 ms, p95 6.94 ms.

Gold-shown diagnostic checks (excluded from $/decision): 2977 checks, $8.80.

| replay | result |
|---|---|
| BE identity (each reduction run twice) | byte-identical on 1100 / 1100 eligible items |
| BE-G identity (each reduction run twice) | byte-identical on 1100 / 1100 eligible items |
| J regeneration | agreement 96.0% on 200 items (planned set matched: True) |
| BE-G leave-one-agent-out | 3565 re-decisions on 713 items, 0 model calls, 23.81 s total; decision changed in 331 (9.3%) |
| J leave-one-agent-out | counterfactual 5 calls per item ≈ $0.069, 18.6 s per item; subsample rows 250, decision changed 11.2% |

| set | BE-G overturns | labelled passages per overturn (median, max) | characters (median, max) | J context tokens per decision (median) |
|---|---|---|---|---|
| P | 95 | 1, 5 | 859, 4901 | 3495 |
| T | 3 | 1, 1 | 921, 1020 | 3261 |
| pooled | 98 | 1, 5 | 878, 4901 | 3474 |

### Majority-following (agreement with MAJ on majority-wrong decisive items)

| set | majority-wrong items | J | RS | CB-S | J_local |
|---|---|---|---|---|---|
| P | 147 | 23 / 147 | 14 / 147 | 23 / 147 | not run |
| T | 35 | 1 / 35 | 0 / 35 | 0 / 35 | not run |
| pooled | 182 | 24 / 182 | 14 / 182 | 23 / 182 | not run |

### Close pairs and subgroups

| set | pair | N | b | c | p |
|---|---|---|---|---|---|
| P | BE-G vs VV | 547 | 5 | 3 | 0.7266 |
| P | BE vs EO | 547 | 10 | 4 | 0.1796 |
| T | BE-G vs VV | 68 | 5 | 4 | 1.0000 |
| T | BE vs EO | 68 | 3 | 7 | 0.3438 |
| pooled | BE-G vs VV | 615 | 10 | 7 | 0.6291 |
| pooled | BE vs EO | 615 | 13 | 11 | 0.8388 |

| subgroup | N | MAJ | BE-G | BE | J | BE-G vs MAJ b / c, p |
|---|---|---|---|---|---|---|
| P:fever | 221 | 78.7% | 88.2% | 87.8% | 93.7% | 23 / 2, 1.94e-05 |
| P:popqa | 209 | 68.4% | 82.3% | 82.3% | 93.8% | 35 / 6, 4.87e-06 |
| P:scifact | 117 | 70.9% | 89.7% | 88.0% | 93.2% | 22 / 0, 4.77e-07 |
| T:truthfulqa | 68 | 48.5% | 51.5% | 35.3% | 98.5% | 7 / 5, 0.7744 |
| popqa pop_1e3_1e4 | 73 | 67.1% | 87.7% | 89.0% | 93.2% | 16 / 1, 2.75e-04 |
| popqa pop_1e4_1e5 | 77 | 62.3% | 75.3% | 75.3% | 90.9% | 12 / 2, 0.0129 |
| popqa pop_ge_1e5 | 59 | 78.0% | 84.7% | 83.1% | 98.3% | 7 / 3, 0.3438 |
| SciFact REFUTED | 34 | 47.1% | 82.4% | 73.5% | 97.1% | 12 / 0, 4.88e-04 |

### Sensitivity analyses (pre-declared, descriptive)

| analysis | contrast | N | b | c | p |
|---|---|---|---|---|---|
| PopQA excluded | H1a: BE-G vs MAJ on P | 338 | 45 | 2 | 1.60e-11 |
| MAJ with earliest-arrival ties | H1a: BE-G vs MAJ_early on P | 547 | 77 | 10 | 5.92e-14 |
| PopQA excluded | H1b: BE vs MAJ on P | 338 | 53 | 13 | 7.24e-07 |
| MAJ with earliest-arrival ties | H1b: BE vs MAJ_early on P | 547 | 89 | 25 | 1.32e-09 |
| c and q_r against D | BE-G vs D on P | 547 | 66 | 6 (q_r 0.015) | |
| null J decisions scored wrong (0 nulls) | BE-G vs J on P | 547 | 11 | 51 | 2.78e-07 |
| null J decisions scored wrong (0 nulls) | BE-G vs J on T | 68 | 0 | 32 | 4.66e-10 |

Witness sample for blinded labelling: 83 BE-G overturn witnesses in `witness_sample_v5.jsonl` (labels and κ against G-AK are added outside the evaluator).

### Also reported

- Gate stages (BE-G, decisive): P {"plurality": 101, "verified": 446}; T {"plurality": 59, "verified": 9}; pooled {"plurality": 160, "verified": 455}.
- S4 separation (δ = 0.05): BE-G 204 / 615; BE 203 / 615.
- Hosted checks cited: 4979; status {"ok": 4975, "refused": 4}; mapped labels on citations {"not_enough_info": 3672, "parse_error": 4, "refutes": 688, "supports": 3896}.
- Evidence availability (decisive, diagnostic): fever 82.4%; popqa 85.2%; scifact 85.5%; truthfulqa 13.2%.
- Fallbacks on decisive conflicts: P {"BEST_fallback": 0, "CB-S_missing": 1, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 547, "RS_missing": 0, "VV_fallback": 101}; T {"BEST_fallback": 0, "CB-S_missing": 0, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 68, "RS_missing": 0, "VV_fallback": 59}; pooled {"BEST_fallback": 0, "CB-S_missing": 1, "CV_fallback": 0, "J_fallback": 0, "J_local_fallback": 615, "RS_missing": 0, "VV_fallback": 160}.
- Mirror check: 7965 slots, 0 mismatches. Counts: {"mirror_checked": 7965, "support_records": 8260}.

