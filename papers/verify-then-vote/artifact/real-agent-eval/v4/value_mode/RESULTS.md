# Candidate grouping by value (experimental `candidate_mode`)

Implementation: `overturn/src/value_mode.rs`, plus small hunks in `compiler.rs` (one policy field, one dispatch in P5) and `main.rs` (module, `--candidate-mode` flag, overlay key). Binary SHA-256 `066a61ff314db4d962c637c0bcc62cc919cf2aba359a29451b0d8cafd4009d8f`.

**Result: do not change the default.** On the v3 real-agent data, value mode almost never changes a winner (0 to 2 of 54 to 64 contradiction slots per table) and leaves Table A accuracy unchanged, except for one extra correct pooled-mode conflict on v1 under the stricter grader. On the synthetic workload, it is the same as member mode or worse. The `max` aggregate loses 1 of 3 tcp conflicts at N=10K. The `pooled` aggregate loses all 3 tcp conflicts at N=1K and N=10K, because the capped evidence sum saturates.

## Definition

The policy field is `candidate_mode`:

- `{"mode": "member"}` is the default. It is never serialized, so the default policy hash stays `dd8d36e6def3a6d598765e82d461a473`.
- `{"mode": "value", "aggregate": "max" | "pooled"}` turns value mode on. `aggregate` defaults to `max`.
- The CLI form is `--candidate-mode member|value|value:max|value:pooled`, and the same setting can be given as a `--reduce` policy overlay key.

**How it works:**

- **Candidates.** In value mode, the candidates of a conflict set are its distinct values `(normalize_object(o), polarity)`. This is the same key P4 uses to decide that a slot is contradictory.
- **Member scoring.** Every member is scored exactly as in member mode. The per-member `scores_q` in the output are unchanged.
- **Aggregation.** A value's members are folded into one value-level vector (ev, conf, cs, rec, ca) and one final score:
  - **`max`**: the value scores as its best member, and uses that member's vector. Adding agreeing members cannot lower a value's score, and raises it only if the new member scores higher. Headcount alone buys nothing. This aggregate removes competition between members of the same value without turning P5 into a vote.
  - **`pooled`** (evidence-pooled):
    - `ev = min(1, Σ_agents max_{m ∈ agent} ev_m)`. This is §6.6.1's per-claim capped-sum rule extended to the union of the supporters' evidence. Each agent counts once, so repeated sentences are not extra corroboration.
    - conf, cs, rec, ca and the lowering factor are averaged, so headcount does not inflate self-reported confidence. Only evidence, the dimension meant to accumulate, is pooled.
    - Final score is `mean(lf) · w·(ev_pool, means…)`.
- **Selection.** The member-mode rules are applied at the value level:
  - the winner is the value with the highest quantized value score;
  - the deadband applies if the top two *values* differ by less than 500;
  - in that case, Schulze runs over the values strictly inside the deadband, using their quantized vectors with `schulze_dim_epsilon` and `schulze_dims`;
  - remaining ties go to the value whose earliest member comes first in canonical order (`tiebreak_order=seq`), or to the smallest representative id (`id`).

  Proposition 1 and Lemma 1 (§6.7) carry over with values in place of members.
- **Admission.** The selected value is admitted through its *representative*: the highest-scoring member by quantized member score, ties by smallest id. P6 is unchanged: one member is admitted per slot.

## Regression (default mode)

| Check | Result |
|---|---|
| `cargo test --release` | 59 passed, 1 ignored (10 new value-mode tests: default not serialized and hash `dd8d36e6…` unchanged; value modes round-trip and change the hash; CLI parsing; many identical members (max ignores headcount, pooled pools independent agents only, single-agent repeats count once); pooled cap; ties (representative by id; value ties by seq or id); polarity and normalization; single-value slot never in deadband; winner is a representative inside the value deadband (300 random sets × 2 aggregates); overlay accepts `candidate_mode`) |
| `--baselines`, `--ablation`, `--score-gaps` | byte-identical to `v2/evidence/stress/final-*.txt` |
| `--stress` | identical to `final-stress.txt` with the time column masked |
| `make replay-file` | all PASS. The five N=100 dumps are byte-identical to the pre-change binary (root/policy/cert e.g. tcp `a0a3b9e2…/dd8d36e6…/3acd534f21f3664b`). All three policy tampers exit 4 |
| `make test-quick` | properties OK, 500/500 replays identical |
| v3 stored inputs, member mode | 220/220 (`forced` and `native`, v3 and v1orig) re-reduce to exactly the stored `.out.json` |
| value-mode seal replay | `--dump-artifact … --candidate-mode value:{max,pooled}` then `--replay-from`: 6/6 PASS (`synthetic/value_mode_replay.txt`). Policy hashes are `c5768502aab9d42d30d4ebd93282704a` (max) and `f60a31da54edbc51b1cda08891afa24e` (pooled) |

## Synthetic workload (seed 42, `--stress`)

Files: `synthetic/stress_<mode>_run{1..5}.txt` and `synthetic/stress_summary.json`. Time is the median of 5 runs, in ms, with the range in brackets. The machine was shared during these runs (load average about 5), so the times are indicative only.

| Topic | N | mode | Slots | Prec | FP | Time ms |
|---|---:|---|---:|---:|---:|---|
| australia | 100 | member / max / pooled | 4 / 4 / 4 | 100% / 100% / 100% | 0 / 0 / 0 | 2.3 / 2.2 / 2.2 |
| australia | 1,000 | member / max / pooled | 4 / 4 / 4 | 100% / 100% / 100% | 0 / 0 / 0 | 20.8 / 19.8 / 20.0 |
| australia | 10,000 | member / max / pooled | 4 / 4 / 4 | 100% / 100% / 100% | 0 / 0 / 0 | 236.7 [229–257] / 199.8 [193–243] / 208.9 [201–229] |
| tcp | 100 | member / max / pooled | 14 / 14 / 14 | 79% / 79% / 79% | 3 / 3 / 3 | 2.4 / 2.2 / 2.4 |
| tcp | 1,000 | member / max / pooled | 14 / 14 / 14 | 79% / 79% / **57%** | 3 / 3 / **6** | 25.0 / 23.7 / 24.8 |
| tcp | 10,000 | member / max / pooled | 14 / 14 / 14 | 79% / **71%** / **57%** | 3 / **4** / **6** | 251.7 [246–266] / 222.2 [212–252] / 231.0 [217–240] |
| nutrition | 100 | member / max / pooled | 15 / 15 / 15 | 67% / 67% / 67% | 5 / 5 / 5 | 2.5 / 2.4 / 2.5 |
| nutrition | 1,000 | member / max / pooled | 15 / 15 / 15 | 67% / 67% / 67% | 5 / 5 / 5 | 22.0 / 21.6 / 22.1 |
| nutrition | 10,000 | member / max / pooled | 15 / 15 / 15 | 67% / 67% / 67% | 5 / 5 / 5 | 268.0 [256–294] / 231.5 [226–260] / 240.4 [229–255] |

"Slots" is the number of output slots (`Output` column; it equals `Conflicts` in every row). Value mode never changes slot structure.

The per-slot breakdown is in `synthetic_slots.py`, `synthetic_slots.{json,csv}`, and in the dumps under `synthetic/dump_*.json`. The full 10K dumps were regenerated in scratch and are not committed.

| Topic | N | contradiction slots | correct winners (member / max / pooled) | in deadband (member / max / pooled) | winning value changed (max, pooled) |
|---|---:|---:|---|---|---|
| australia | 100 / 1K / 10K | 1 | 1 / 1 / 1 at every N | 1 / 0 / 0 | 0, 0 |
| tcp | 100 | 3 | 3 / 3 / 3 | 3 / 0 / 0 | 0, 0 |
| tcp | 1,000 | 3 | 3 / 3 / **0** | 3 / 1 / 0 | 0, 3 |
| tcp | 10,000 | 3 | 3 / **2** / **0** | 3 / 2 / 0 | 1, 3 |
| nutrition | 100 / 1K / 10K | 1 | 1 / 1 / 1 at every N | 1 / 0 / 0 | 0, 0 |

**Why value mode is worse on tcp.** In the three tcp contradiction slots:

- The correct value is heavily critiqued (about 100 to 130 NEGATE critiques at N=10K), so its critique survival is 0. The incorrect value is uncritiqued, so its critique survival is 1, and it also arrives later.
- As a result, the incorrect value's mean member score exceeds the correct value's in all three slots (for example 3054 vs 2329 for `<tcp_integrity_check>` at N=10K). In `<tcp_integrity_check>`, the top incorrect member even outscores the top correct member (3515 vs 3092).
- Member mode still gets all three right. Every slot falls in the deadband, and Schulze over the hundreds of deadband *members* recovers the correct value.

The two aggregates fail for different reasons:

- **`max`** reduces each slot to two representative vectors. A two-candidate Schulze is a plain count of dimensions won: the correct representative wins on ev and conf, the incorrect one on cs and rec. It flips `<tcp_handshake>` at N=10K.
- **`pooled`** saturates. With hundreds of supporting agents, both values reach `ev = 1`. Evidence then stops discriminating, and the averaged critique-survival and recency dimensions decide, in favour of the misconception. It flips all three tcp slots at N≥1K. At N=100 the sums do not saturate, and every slot is correct.

Value mode is 8 to 16% faster at N=10K, because the deadband never runs Schulze over hundreds of members.

## v3 real-agent inputs (`--reduce`, value-mode policy overlay)

The inputs are the stored `real-agent-eval/v3/results/rust/<ds>/<q>/{forced,native}.in.json`, with only `policy.candidate_mode` overlaid. The I/O is written to `rust/` (git-ignored; regenerate with `python3 run_value_mode.py --bin overturn/target/release/overturn`). Scoring imports `real-agent-eval/v3/evaluate_v3.py` (unmodified): the same rows, graders, outcome rule, McNemar and bootstrap. Files: `results.json`, `paired_*.csv`, `winner_changes_*.csv`.

**Winner changes vs member mode, over all Rust contradiction slots.** Each cell gives "id changed / value changed".

| Dataset | Slots | slots where a value repeats | forced: max | forced: pooled | native: max | native: pooled |
|---|---:|---:|---|---|---|---|
| v3 | 64 forced / 54 native | 6 / 6 | 1 / 0 | 2 / 1 | 1 / 0 | 2 / 1 |
| v1orig | 62 forced / 55 native | 7 / 6 | 0 / 0 | 2 / 2 | 0 / 0 | 1 / 1 |

The few changes are:

- **v3 q01 (both aggregates):** a different Canberra member is chosen (the representative rule picks by smallest id rather than by member-level Schulze), and the winning value is the same.
- **v3 q28 (pooled):** the winner changes from "high" to "low" in the extraction artefact "(the confidence level for this claim, is)".
- **v1orig q23 (pooled):** goldfish memory "up to 12 hours" becomes "up to one month".
- **v1orig q44 (pooled):** a climate-consensus paraphrase changes.

Value mode can matter only where an object string repeats in a slot, and that happens in about 10% of slots, because extracted objects rarely repeat verbatim (§9.2.1 point 3).

**Table A (Python-structured slots, `forced` policy).** Each cell gives "correct over eligible · correct over decisive". The "vs maj." columns give b/c and exact McNemar *p* against majority vote.

| Method | v3 orig (26/14) | vs maj. | v3 strict (16/9) | v1 orig (24/15) | vs maj. | v1 strict (17/9) | vs maj. |
|---|---|---|---|---|---|---|---|
| Rust, member (default) | 18 · 6 | 2/6, 0.289 | 12 · 5 | 20 · 11 | 9/1, 0.0215 | 12 · 4 | 3/2, 1.0 |
| Rust, value:max | 18 · 6 | 2/6, 0.289 | 12 · 5 | 20 · 11 | 9/1, 0.0215 | 12 · 4 | 3/2, 1.0 |
| Rust, value:pooled | 18 · 6 | 2/6, 0.289 | 12 · 5 | 20 · 11 | 9/1, 0.0215 | **13 · 5** | 4/2, 0.688 |
| Majority vote | 22 · 10 | — | 12 · 5 | 12 · 3 | — | 11 · 3 | — |
| First member | 22 · 10 | — | 12 · 5 | 13 · 4 | — | 11 · 3 | — |
| Last member | 16 · 4 | — | 11 · 4 | 16 · 7 | — | 11 · 3 | — |

The member-mode row reproduces Table 9.2.1 exactly. Against member mode, value:max is 0/0 discordant in every column. Value:pooled is 0/0 in every column except v1 strict, where it is 1/0 (*p* = 1.0).

Table B (Rust-native slots) has the same pattern, with value = member in all four cells (v3 15·5 and 9·4; v1 16·9 and 10·4). See `results.json`.

## Recommendation

1. **Keep `member` as the default.** Value mode has no measurable benefit on real data: it is inert in about 90% of slots, and it gains at most one conflict out of 17. It is harmful on the one synthetic topic where values repeat at scale and their side-channels disagree.
2. **Do not adopt `pooled` with a hard cap.** A capped sum is headcount-insensitive once every value saturates, and that happens at modest N. The decision then falls to the averaged side-channels: critique survival and recency, the dimensions §6.7 already identifies as the problem. A non-saturating pool (for example a mean over the top-k agents, or noisy-OR on a log scale) would be needed. That pool would be a different, headcount-sensitive policy that needs its own preregistered test.
3. **`max` is the safe variant if grouping is wanted for presentation.** One value means one candidate, and the deadband no longer fires between members of the same value. But it exposes the same flaw as member mode: per-dimension Schulze with two candidates is a dimension count in which recency and critique survival each get a full vote. Any further work should go with the tie-break redesign (`tiebreak=score_then_canonical` or `schulze_dims` without recency), not ship alone.
4. **For the paper:** value grouping does not explain the v3 gap to majority vote. The baseline's advantage comes from first-arrival order and from objects that are never canonicalized, not from members of one value splitting the vote. Object canonicalization, not value-level candidates, is the lever: value mode can act only on objects that already match after normalization.
