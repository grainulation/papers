# Eval v4 power analysis

Script: `power.py` (numpy only, seed 20261021, no model calls). Output: `power_results.json`.
Run it with `python3 real-agent-eval/v4/power/power.py`, which takes about 10 min; add `--quick`
for fewer Monte Carlo reps. It reads the v3 `paired_decisions_*.csv` files only. (It is not run
with `-I`, because numpy lives in user site-packages and the script reads only repo-generated
CSVs.)

## Inputs from v3

| v3 table | decisive | questions with ≥ 1 | yield / question | ψ: Rust default vs majority (b/c) | ψ: recency-free (rec 0, no deadband) vs majority (b/c) | ψ: default vs recency-free |
|---|---|---|---|---|---|---|
| v3 A, original grader | 14 | 13/55 | 0.255 | 0.57 (2/6) | 0.21 (0/3) | 0.36 |
| v3 A, stricter | 9 | 8/55 | 0.164 | 0.44 (2/2) | 0.11 (0/1) | 0.33 |
| v3 B, original | 12 | 11/55 | 0.218 | 0.67 (2/6) | 0.25 (0/3) | 0.42 |
| v3 B, stricter | 8 | 7/55 | 0.145 | 0.50 (2/2) | 0.13 (0/1) | 0.38 |
| v1orig A, original | 15 | 12/55 | 0.273 | 0.67 (9/1) | 0.33 (4/1) | 0.33 |

- ψ is the discordant-pair rate (b+c)/N.
- Only 1 question in v3 A (q26) had more than one decisive set, so within-question clustering is
  negligible in v3.
- These ψ values were measured against a majority that equals first-member. Against a
  canonicalized, answer-constrained majority, ψ is unknown. The tables below therefore span ψ
  from 0.15 to 0.70, with 0.35 as the central value.

## Table 1: decisive conflicts for 80% power

The test is the two-sided exact McNemar test at α = 0.05. Power was computed by exact enumeration
and agrees with a 20,000-rep Monte Carlo check within ±0.01. N is the smallest value at which
power is ≥ 0.80 and stays there for the next 25 values of N, because exact-test power saw-tooths.

| Δ | ψ = 0.15 | 0.20 | 0.25 | 0.30 | 0.35 | 0.40 | 0.50 | 0.60 | 0.70 |
|---|---|---|---|---|---|---|---|---|---|
| 0.10 | 122 | 168 | 207 | 249 | **289** | 329 | 408 | 487 | 566 |
| 0.15 | n/a (boundary Δ = ψ: every discordant pair would favour one side) | 72 | 92 | 112 | **129** | 147 | 183 | 219 | 255 |

## Table 2: questions needed = N / yield

The yield is the number of decisive conflicts per question, with one run per question.

| target (ψ = 0.35) | 0.16 (v3 stricter) | 0.255 (v3 original) | 0.50 | 0.75 | 1.0 |
|---|---|---|---|---|---|
| Δ = 0.10 (N = 289) | 1,807 | 1,134 | 578 | 386 | 289 |
| Δ = 0.15 (N = 129) | 807 | 506 | 258 | 172 | 129 |

The full grid over ψ is in `power_results.json` → `independent_design[].questions_needed`.

**Reading.** At v3's yield, a 10-point effect needs more than 1,100 free-text questions. The
practical lever is yield, not question count: a one-slot ANSWER line per item over a small closed
answer space, on items where 5 small models split. A yield of 1.0 is the ceiling with one run,
because it means every item is decisive.

## Table 3: power of the actual v4 design

The design is 600 primary items, extendable to 1,000 by the stopping rule, with R = 1.

| items | yield | N decisive | ψ = 0.25: Δ = .10 / .15 | ψ = 0.35: Δ = .10 / .15 | ψ = 0.50: Δ = .10 / .15 |
|---|---|---|---|---|---|
| 600 | 0.16 | 96 | 0.42 / 0.82 | 0.32 / 0.65 | 0.24 / 0.50 |
| 600 | 0.255 | 153 | 0.65 / 0.96 | 0.51 / 0.87 | 0.37 / 0.72 |
| 600 | 0.35 | 210 | 0.81 / 0.99 | 0.65 / 0.96 | 0.50 / 0.86 |
| 600 | 0.50 | 300 | 0.93 / 1.00 | **0.82 / 0.99** | 0.66 / 0.95 |
| 600 | 0.75 | 450 | 0.99 / 1.00 | 0.94 / 1.00 | 0.84 / 0.99 |
| 1000 | 0.255 | 255 | 0.88 / 1.00 | 0.75 / 0.98 | 0.59 / 0.92 |
| 1000 | 0.35 | 350 | 0.96 / 1.00 | 0.87 / 1.00 | 0.73 / 0.98 |
| 1000 | 0.50 | 500 | 0.99 / 1.00 | 0.96 / 1.00 | 0.88 / 1.00 |

The proposed size is 600 primary items (150 per source) plus a 400-item extension. If the
dev-stage yield is at least 0.5, this has ≥ 80% power at Δ = 0.10 for ψ ≤ 0.35, and ≥ 95% at
Δ = 0.15 for ψ ≤ 0.5. If the yield is as low as v3's (0.255), the 1,000-item cap still gives
0.75 at Δ = 0.10 and 0.98 at Δ = 0.15 (ψ = 0.35).

## Table 4: clustered designs

These simulations add replicate runs per question and use 1,500 reps per point, ψ = 0.35 and
target power 80%.

- **Design.** Each question is run R times, and its decisive count is K_i ~ Binom(R, y/R).
- **Heterogeneity.** A question's discordance direction varies through
  (p_b, p_c, p_0) ~ Dirichlet(κ · mean). κ = ∞ means no heterogeneity; smaller κ means stronger
  within-question correlation.
- **Tests.**
  - Naive: the exact McNemar test on pooled conflicts.
  - Durkalski et al. (2003) clustered McNemar: X² = (Σ_i(b_i − c_i))² / Σ_i(b_i − c_i)², referred
    to χ²(1).

| R | yield / question | κ | Δ | questions for 80% (Durkalski) | type-I naive | type-I Durkalski |
|---|---|---|---|---|---|---|
| 1 | 0.5 | — | 0.10 / 0.15 | 545 / 243 | 0.042 / 0.037 | 0.058 / 0.058 |
| 1 | 1.0 | — | 0.10 / 0.15 | 275 / 123 | 0.034 / 0.036 | 0.043 / 0.049 |
| 3 | 0.75 | ∞ / 10 / 2 | 0.10 | 364 / 383 / 446 | 0.037 / 0.034 / 0.061 | 0.048 / 0.040 / 0.055 |
| 3 | 1.5 | ∞ / 10 / 2 | 0.10 | 183 / 193 / 249 | 0.036 / 0.051 / 0.076 | 0.049 / 0.051 / 0.048 |
| 3 | 3.0 | ∞ / 10 / 2 | 0.10 | 93 / 109 / 158 | 0.032 / 0.053 / **0.119** | 0.045 / 0.045 / 0.045 |
| 3 | 1.5 | ∞ / 10 / 2 | 0.15 | 83 / 88 / 103 | 0.036 / 0.047 / 0.065 | 0.052 / 0.049 / 0.045 |

Type-I error was measured at the Q found. Monte Carlo SE is about 0.006 at α = 0.05.

**Reading.**

- With R = 1, the naive exact test is valid; at about 0.035–0.042 it is conservative, as an
  exact test should be. The Durkalski χ² is near nominal. The two tests reach the same Q.
- With replicates and strong heterogeneity (κ = 2), the naive exact test **inflates type-I error
  to 0.08–0.12**, while Durkalski holds about 0.05. Replicates buy fewer questions only if
  heterogeneity is mild: at κ = 2 and R = 3, Q = 446 versus 545 for R = 1 at a per-question yield
  of 0.75 versus 0.5, and the total model calls rise 3×.
- The prereg therefore uses **R = 1 and the exact McNemar test as the primary**, extending item
  count rather than replicates. If R > 1 is ever adopted, the primary test must be the Durkalski
  test.

## Table 5: H2 non-inferiority (recency-free vs default)

The test is one-sided α = 0.025 with a Wald CI on the paired difference. The true difference is
0, and each cell uses 10,000 reps.

| margin | N decisive | ψ = 0.10 | ψ = 0.20 | ψ = 0.35 |
|---|---|---|---|---|
| −0.05 | 300 | 0.78 | 0.50 | 0.32 |
| −0.05 | 800 | 1.00 | 0.89 | 0.67 |
| −0.10 | 150 | 0.97 | 0.79 | 0.55 |
| −0.10 | 300 | 1.00 | 0.97 | 0.83 |
| −0.10 | 500 | 1.00 | 1.00 | 0.97 |

In v3, ψ between the default and recency-free reducers was 0.33–0.42 on decisive sets. A −0.05
margin is not reachable at a realistic N, so the prereg proposes −0.10.

## Caveats

- **ψ and yield are guesses until Stage A.** The stopping rule (PREREGISTRATION §7.4) sets the
  item count from the dev-stage yield and pooled ψ only (b+c, never b−c).
- **Discreteness.** Exact-test power is not monotone in N. Table 1 reports a stable threshold.
- **The Durkalski test is asymptotic.** At small Q it ran slightly liberal (up to about 0.06).
- **v3 ψ is measured against a degenerate majority.** Its range (0.11–0.67) is wide, and Table 3
  is the more useful planning table.
