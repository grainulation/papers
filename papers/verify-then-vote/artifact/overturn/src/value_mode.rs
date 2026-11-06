//! Experimental candidate grouping by value (swarm-2 lane L2).
//!
//! In the default `member` mode every contribution in a conflict set is a
//! separate candidate: two agents asserting the same object compete with
//! each other exactly as they compete with an agent asserting a different
//! object, and the deadband / Schulze tie-break can fire between two
//! members that say the same thing.
//!
//! In `value` mode the candidates of a conflict set are its distinct
//! *values*: `(normalize_object(object), polarity)` pairs, the same key P4
//! already uses to decide that a slot is contradictory. Every member is
//! still scored exactly as in member mode (the per-member `ScoreBreakdown`
//! in the output is unchanged); the members of a value are then folded
//! into one value-level score vector by an aggregate:
//!
//! * `max` — the value scores as its best member. Adding agreeing members
//!   can never lower a value's score, and can raise it only by contributing
//!   a better member. Headcount alone buys nothing, so this is the most
//!   conservative choice: it removes intra-value competition (a value cannot
//!   lose because its own supporters split the deadband) without turning
//!   the reducer into a vote.
//! * `pooled` — evidence-pooled. Evidence is summed across the value's
//!   supporting agents and capped at 1, i.e. §6.6.1's per-claim rule
//!   `ev = min(1, Σ_e ...)` applied to the union of the supporters' evidence.
//!   Each agent contributes its best member's `ev` once, so an agent that
//!   repeats itself in several sentences is not counted twice (independent
//!   agents, not sentences, are the unit of corroboration). Confidence,
//!   critique survival, recency, constraint alignment and the lowering
//!   factor are *averaged* over the members, so headcount does not inflate
//!   self-reported confidence or the lowering factor; only evidence, which
//!   is the dimension that is meant to accumulate, pools. Final score is
//!   `mean(lf) · w·(ev_pool, conf_mean, cs_mean, rec_mean, ca_mean)`.
//!
//! Selection then runs at the value level with the member-mode rules
//! unchanged: argmax of the quantized value score; deadband if the top two
//! *values* are strictly within `deadband_threshold`; Schulze (when
//! `tiebreak = schulze`) over the values within the deadband, on their
//! quantized value vectors, with `schulze_dim_epsilon` and `schulze_dims`.
//! Remaining ties go to the earliest value in candidate order: by the
//! value's earliest member in canonical order (`tiebreak_order = seq`), or by
//! its representative's id (`tiebreak_order = id`). Proposition 1 and
//! Lemma 1 (§6.7) carry over verbatim with values in place of members,
//! because the value score is a deterministic function of the sealed set
//! and Schulze still only sees members of the (value-level) deadband.
//!
//! The selected value is admitted through one *representative*: its
//! highest-scoring member by quantized member score, ties by smallest id
//! (arrival-independent). P6 is unchanged: the representative is the
//! conflict set's `winner_idx`, every other member is rejected.

use crate::compiler::{quantize, schulze_scan, OverturnCompiler, TieBreak, TieOrder};
use crate::ir::*;
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::sync::OnceLock;

/// How the members of one value are folded into a value score.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ValueAggregate {
    /// Best member's score and dimension vector.
    #[default]
    Max,
    /// Capped per-agent evidence sum; other dimensions and lf averaged.
    Pooled,
}

/// Candidate granularity in P5 (policy field `candidate_mode`).
/// Serialized as `{"mode": "value", "aggregate": "max" | "pooled"}`;
/// the default `member` is never serialized, so the default policy hash
/// is unchanged.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "mode")]
pub enum CandidateMode {
    /// Each contribution is a candidate (original behaviour).
    #[default]
    Member,
    /// Each distinct (object, polarity) is a candidate.
    Value {
        #[serde(default)]
        aggregate: ValueAggregate,
    },
}

impl CandidateMode {
    pub fn is_member(&self) -> bool {
        *self == CandidateMode::Member
    }

    /// Parse the CLI form: `member`, `value` (= `value:max`), `value:max`,
    /// `value:pooled`.
    pub fn parse_cli(s: &str) -> Result<Self, String> {
        match s {
            "member" => Ok(CandidateMode::Member),
            "value" | "value:max" => Ok(CandidateMode::Value { aggregate: ValueAggregate::Max }),
            "value:pooled" => Ok(CandidateMode::Value { aggregate: ValueAggregate::Pooled }),
            _ => Err(format!("unknown candidate mode `{s}` (member | value | value:max | value:pooled)")),
        }
    }
}

static CLI_MODE: OnceLock<CandidateMode> = OnceLock::new();

/// Set by `--candidate-mode` before any policy is constructed. Affects only
/// `OverturnCompiler::default()` (and so every policy the CLI builds);
/// deserialized policies (`--replay-from`, `--reduce` overlays) keep the
/// mode they state, defaulting to `member`.
pub fn set_cli_mode(mode: CandidateMode) {
    let _ = CLI_MODE.set(mode);
}

/// `candidate_mode` of `OverturnCompiler::default()`.
pub fn default_mode() -> CandidateMode {
    CLI_MODE.get().copied().unwrap_or_default()
}

/// One value-level candidate.
#[derive(Debug, Clone)]
pub(crate) struct ValueCandidate {
    /// Representative member (index into `valid`).
    pub rep: usize,
    /// Earliest member in canonical order.
    pub first: usize,
    /// Quantized value-level dimension vector (ev, conf, cs, rec, ca).
    pub dims: [i64; 5],
    /// Quantized value-level final score.
    pub score_q: i64,
}

/// Group the scored members of `cs` by value and aggregate.
/// Returned in candidate order (see module docs).
pub(crate) fn value_candidates(
    policy: &OverturnCompiler,
    cs: &ConflictSet,
    valid: &[Contribution],
    aggregate: ValueAggregate,
) -> Vec<ValueCandidate> {
    // Key (object, is_negate): Polarity has no Ord.
    let mut groups: BTreeMap<(String, bool), Vec<usize>> = BTreeMap::new();
    for &idx in &cs.contribution_ids {
        let t = valid[idx].canonical_form.as_ref().expect("P4 members have a canonical form");
        groups.entry((normalize_object(&t.object), t.polarity == Polarity::Negate)).or_default().push(idx);
    }
    let w = &policy.weights;
    let mut out: Vec<ValueCandidate> = groups
        .into_values()
        .map(|members| {
            let rep = *members
                .iter()
                .max_by(|&&a, &&b| {
                    quantize(cs.scores[&a].final_score)
                        .cmp(&quantize(cs.scores[&b].final_score))
                        .then_with(|| valid[b].id.cmp(&valid[a].id))
                })
                .expect("non-empty value group");
            let first = *members.iter().min().expect("non-empty value group");
            let (dims, final_score) = match aggregate {
                ValueAggregate::Max => {
                    let s = &cs.scores[&rep];
                    ([s.ev, s.conf, s.cs, s.rec, s.ca], s.final_score)
                }
                ValueAggregate::Pooled => {
                    // Best ev per agent, then capped sum across agents.
                    let mut per_agent: BTreeMap<&str, f64> = BTreeMap::new();
                    for &m in &members {
                        let e = per_agent.entry(valid[m].agent_id.as_str()).or_insert(0.0);
                        *e = e.max(cs.scores[&m].ev);
                    }
                    let ev: f64 = per_agent.values().sum::<f64>().clamp(0.0, 1.0);
                    let k = members.len() as f64;
                    let mean = |f: fn(&ScoreBreakdown) -> f64| {
                        members.iter().map(|m| f(&cs.scores[m])).sum::<f64>() / k
                    };
                    let conf = mean(|s| s.conf);
                    let csv = mean(|s| s.cs);
                    let rec = mean(|s| s.rec);
                    let ca = mean(|s| s.ca);
                    let lf = mean(|s| s.lf);
                    let raw = w[0] * ev + w[1] * conf + w[2] * csv + w[3] * rec + w[4] * ca;
                    ([ev, conf, csv, rec, ca], raw * lf)
                }
            };
            ValueCandidate {
                rep,
                first,
                dims: dims.map(quantize),
                score_q: quantize(final_score),
            }
        })
        .collect();
    match policy.tiebreak_order {
        TieOrder::Seq => out.sort_by_key(|v| v.first),
        TieOrder::Id => out.sort_by(|a, b| valid[a.rep].id.cmp(&valid[b.rep].id)),
    }
    out
}

/// P5 selection for one conflict set in value mode. Member scores in
/// `cs.scores` must already be filled in. Sets `winner_idx`, `in_deadband`
/// and `schulze_winner` (to the representative of the Schulze value).
pub(crate) fn select(
    policy: &OverturnCompiler,
    cs: &mut ConflictSet,
    valid: &[Contribution],
    aggregate: ValueAggregate,
) {
    let vals = value_candidates(policy, cs, valid, aggregate);
    cs.in_deadband = false;
    cs.schulze_winner = None;
    // Argmax, first in candidate order on exact ties.
    let mut best = 0usize;
    for (i, v) in vals.iter().enumerate() {
        if v.score_q > vals[best].score_q {
            best = i;
        }
    }
    cs.winner_idx = vals.get(best).map(|v| v.rep);
    if vals.len() < 2 {
        return;
    }
    let top = vals[best].score_q;
    let mut sorted: Vec<i64> = vals.iter().map(|v| v.score_q).collect();
    sorted.sort_unstable_by(|a, b| b.cmp(a));
    if sorted[0] - sorted[1] >= policy.deadband_threshold {
        return;
    }
    cs.in_deadband = true;
    if policy.tiebreak != TieBreak::Schulze {
        return;
    }
    let cands: Vec<&ValueCandidate> = vals
        .iter()
        .filter(|v| top - v.score_q < policy.deadband_threshold)
        .collect();
    let dims: Vec<[i64; 5]> = cands.iter().map(|v| v.dims).collect();
    let w = schulze_scan(&dims, policy.schulze_dim_epsilon, policy.schulze_dims, None);
    cs.schulze_winner = Some(cands[w].rep);
    cs.winner_idx = Some(cands[w].rep);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn contrib(id: &str, agent: &str, seq: u64, object: &str, pol: Polarity, conf: f64, ev_w: f64) -> Contribution {
        let mut triple = CanonicalTriple::new("x", "has_capital", object);
        triple.polarity = pol;
        Contribution {
            id: id.to_string(),
            agent_id: agent.to_string(),
            agent_name: agent.to_string(),
            kind: ContributionKind::Assertion,
            canonical_form: Some(triple),
            confidence: conf,
            evidence: if ev_w > 0.0 {
                vec![EvidenceItem::new(EvidenceType::Citation, &format!("src-{id}"), ev_w, true)]
            } else {
                vec![]
            },
            raw_text: String::new(),
            lowering_confidence: LoweringConfidence::High,
            seq,
            timestamp: 0.0,
            is_correct: true,
        }
    }

    fn reduce_with(mode: CandidateMode, cs: Vec<Contribution>) -> (OverturnCompiler, CompilationResult) {
        let mut p = OverturnCompiler::default();
        p.candidate_mode = mode;
        let sealed = crate::compiler::seal_contributions("q", vec![], &Default::default(), &cs);
        let r = p.reduce(&sealed);
        (p, r)
    }

    fn winner_obj(r: &CompilationResult) -> (String, Polarity) {
        let cs = r.conflicts.iter().find(|c| c.typ == ConflictType::Contradiction).unwrap();
        let t = r.all_contributions[cs.winner_idx.unwrap()].canonical_form.clone().unwrap();
        (normalize_object(&t.object), t.polarity)
    }

    const MAX: CandidateMode = CandidateMode::Value { aggregate: ValueAggregate::Max };
    const POOLED: CandidateMode = CandidateMode::Value { aggregate: ValueAggregate::Pooled };

    #[test]
    fn default_is_member_and_not_serialized() {
        let p = OverturnCompiler::default();
        assert!(p.candidate_mode.is_member());
        let v = serde_json::to_value(&p).unwrap();
        assert!(v.get("candidate_mode").is_none());
        assert_eq!(p.policy_hash(), "dd8d36e6def3a6d598765e82d461a473");
    }

    #[test]
    fn value_modes_serialize_and_change_hash() {
        let d = OverturnCompiler::default();
        let mut hashes = vec![d.policy_hash()];
        for m in [MAX, POOLED] {
            let mut p = d.clone();
            p.candidate_mode = m;
            let j = serde_json::to_value(&p).unwrap();
            assert_eq!(j["candidate_mode"]["mode"], "value");
            let back: OverturnCompiler = serde_json::from_value(j).unwrap();
            assert_eq!(back.candidate_mode, m);
            hashes.push(p.policy_hash());
        }
        hashes.sort();
        hashes.dedup();
        assert_eq!(hashes.len(), 3);
        // aggregate defaults to max when omitted
        let m: CandidateMode = serde_json::from_str(r#"{"mode":"value"}"#).unwrap();
        assert_eq!(m, MAX);
        assert!(serde_json::from_str::<CandidateMode>(r#"{"mode":"vote"}"#).is_err());
    }

    #[test]
    fn cli_parse() {
        assert_eq!(CandidateMode::parse_cli("member").unwrap(), CandidateMode::Member);
        assert_eq!(CandidateMode::parse_cli("value").unwrap(), MAX);
        assert_eq!(CandidateMode::parse_cli("value:pooled").unwrap(), POOLED);
        assert!(CandidateMode::parse_cli("value:sum").is_err());
    }

    /// Many identical members: under `max` headcount buys nothing; under
    /// `pooled` the evidence of distinct agents accumulates (capped at 1),
    /// but repeated sentences from one agent count once.
    #[test]
    fn many_identical_members() {
        // One strong lone claim "b" vs ten weak agreeing agents on "a".
        let mut v = vec![contrib("zb", "solo", 0, "B", Polarity::Affirm, 0.9, 1.0)];
        for i in 0..10 {
            v.push(contrib(&format!("a{i}"), &format!("ag{i}"), 1 + i, "A", Polarity::Affirm, 0.9, 0.3));
        }
        let (_, r) = reduce_with(MAX, v.clone());
        assert_eq!(winner_obj(&r).0, "b");
        let (_, r) = reduce_with(POOLED, v.clone());
        assert_eq!(winner_obj(&r).0, "a", "ten independent weak citations pool past one strong one");
        // Same ten members but all from ONE agent: pooling counts the agent once.
        let mut v1 = vec![v[0].clone()];
        for i in 0..10 {
            v1.push(contrib(&format!("a{i}"), "one", 1 + i, "A", Polarity::Affirm, 0.9, 0.3));
        }
        let (_, r) = reduce_with(POOLED, v1);
        assert_eq!(winner_obj(&r).0, "b");
        // Exactly one admitted per slot in every mode; the rep is a member of the winning value.
        for m in [CandidateMode::Member, MAX, POOLED] {
            let (_, r) = reduce_with(m, v.clone());
            let cs = &r.conflicts[0];
            assert_eq!(r.admitted.iter().filter(|i| cs.contribution_ids.contains(i)).count(), 1);
        }
    }

    /// Pooled evidence is capped at 1 (no unbounded accumulation).
    #[test]
    fn pooled_evidence_capped() {
        let mut v = vec![];
        for i in 0..50 {
            v.push(contrib(&format!("a{i:02}"), &format!("ag{i}"), i, "A", Polarity::Affirm, 0.5, 1.0));
        }
        v.push(contrib("zz", "solo", 99, "B", Polarity::Affirm, 0.5, 0.0));
        let (p, r) = reduce_with(POOLED, v);
        let cs = &r.conflicts[0];
        let vals = value_candidates(&p, cs, &r.all_contributions, ValueAggregate::Pooled);
        assert!(vals.iter().all(|x| x.dims[0] <= 10_000));
    }

    /// Exact ties: the representative is the smallest id among the tied
    /// top members (arrival-independent), and value ties go to the earliest
    /// value in canonical order (seq) or by representative id (id).
    #[test]
    fn ties() {
        // Two identical-score members of "a" with ids m2 < m9; m9 arrives first.
        let a_late = contrib("m2", "p", 5, "A", Polarity::Affirm, 0.8, 0.5);
        let a_early = contrib("m9", "q", 1, "A", Polarity::Affirm, 0.8, 0.5);
        let b = contrib("m5", "r", 3, "B", Polarity::Affirm, 0.1, 0.0);
        let (_, r) = reduce_with(MAX, vec![a_late.clone(), a_early.clone(), b.clone()]);
        let cs = &r.conflicts[0];
        assert_eq!(r.all_contributions[cs.winner_idx.unwrap()].id, "m2");
        // Value-level exact tie between two single-member values with equal
        // vectors except recency; zero recency weight and deadband 0 so the
        // ordering rule alone decides.
        let x = contrib("k7", "p", 1, "X", Polarity::Affirm, 0.5, 0.5);
        let y = contrib("k3", "q", 2, "Y", Polarity::Affirm, 0.5, 0.5);
        for (order, want) in [(TieOrder::Seq, "k7"), (TieOrder::Id, "k3")] {
            let mut p = OverturnCompiler::default();
            p.candidate_mode = MAX;
            p.weights[3] = 0.0;
            p.deadband_threshold = 0;
            p.tiebreak_order = order;
            let sealed = crate::compiler::seal_contributions("q", vec![], &Default::default(), &[x.clone(), y.clone()]);
            let r = p.reduce(&sealed);
            assert_eq!(r.all_contributions[r.conflicts[0].winner_idx.unwrap()].id, want);
        }
    }

    /// Polarity: AFFIRM and NEGATE of the same object are distinct values,
    /// and normalization (case/whitespace) merges objects into one value.
    #[test]
    fn polarity_and_normalization() {
        let v = vec![
            contrib("n1", "a1", 0, "Sydney", Polarity::Negate, 0.9, 0.3),
            contrib("n2", "a2", 1, "sydney ", Polarity::Negate, 0.9, 0.3),
            contrib("n3", "a3", 2, "SYDNEY", Polarity::Negate, 0.9, 0.3),
            contrib("p1", "a4", 3, "Sydney", Polarity::Affirm, 0.9, 0.6),
        ];
        let (p, r) = reduce_with(POOLED, v.clone());
        let cs = r.conflicts.iter().find(|c| c.typ == ConflictType::Contradiction).unwrap();
        let vals = value_candidates(&p, cs, &r.all_contributions, ValueAggregate::Pooled);
        assert_eq!(vals.len(), 2, "three NEGATE spellings form one value, AFFIRM another");
        assert_eq!(winner_obj(&r), ("sydney".into(), Polarity::Negate));
        let (_, r) = reduce_with(MAX, v);
        assert_eq!(winner_obj(&r), ("sydney".into(), Polarity::Affirm));
    }

    /// A slot whose members all share one value is never in the deadband
    /// in value mode (no intra-value competition).
    #[test]
    fn single_value_never_deadband() {
        let v = vec![
            contrib("r1", "a1", 0, "A", Polarity::Affirm, 0.95, 0.3),
            contrib("r2", "a2", 1, "A", Polarity::Affirm, 0.5, 0.3),
        ];
        let (_, r) = reduce_with(MAX, v.clone());
        assert!(r.conflicts.iter().all(|c| !c.in_deadband));
        let (_, rm) = reduce_with(CandidateMode::Member, v);
        assert!(rm.conflicts.iter().any(|c| c.in_deadband));
    }

    /// `--reduce` policy overlays accept `candidate_mode`.
    #[test]
    fn reduce_overlay_accepts_candidate_mode() {
        let d = OverturnCompiler::default();
        let p = crate::overlay_policy(d.clone(), serde_json::json!({"candidate_mode": {"mode": "value", "aggregate": "pooled"}})).unwrap();
        assert_eq!(p.candidate_mode, POOLED);
        let p = crate::overlay_policy(d.clone(), serde_json::json!({"candidate_mode": {"mode": "member"}})).unwrap();
        assert_eq!(p.policy_hash(), d.policy_hash());
        assert!(crate::overlay_policy(d, serde_json::json!({"candidate_mode": "pooled"})).is_err());
    }

    /// Value-level Schulze stays inside the value deadband, and the winner
    /// is always the representative of its value.
    #[test]
    fn winner_is_rep_and_inside_value_deadband() {
        use rand::{Rng, SeedableRng};
        let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(7);
        for trial in 0..300 {
            let n = rng.gen_range(2..25);
            let v: Vec<Contribution> = (0..n)
                .map(|i| {
                    let obj = ["A", "B", "C", "D"][rng.gen_range(0..4)];
                    let pol = if rng.gen_bool(0.2) { Polarity::Negate } else { Polarity::Affirm };
                    contrib(&format!("t{trial}-{i:02}"), &format!("ag{}", rng.gen_range(0..6)),
                        rng.gen_range(0..1000), obj, pol, rng.gen_range(0.0..1.0), rng.gen_range(0.0..1.0))
                })
                .collect();
            for agg in [ValueAggregate::Max, ValueAggregate::Pooled] {
                let (p, r) = reduce_with(CandidateMode::Value { aggregate: agg }, v.clone());
                for cs in &r.conflicts {
                    let vals = value_candidates(&p, cs, &r.all_contributions, agg);
                    let w = cs.winner_idx.unwrap();
                    let wv = vals.iter().find(|x| x.rep == w).expect("winner is a representative");
                    let top = vals.iter().map(|x| x.score_q).max().unwrap();
                    assert!(top - wv.score_q < p.deadband_threshold.max(1));
                }
            }
        }
    }
}
