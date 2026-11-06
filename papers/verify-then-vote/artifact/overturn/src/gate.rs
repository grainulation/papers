//! Verified-overturn gate ("verify, then vote"; `v3/GATE_SPEC.md`).
//!
//! Policy field `evidence.overturn_gate = "verified"` (default `"none"`,
//! never serialized, so every existing policy hash is unchanged). It acts
//! on CONTRADICTION slots only; redundancy sets hold one value and are
//! unaffected. Scoring is untouched: every member keeps its
//! `ScoreBreakdown` and `scores_q`; the gate only restricts which members
//! the ordinary P5 selection may choose from.
//!
//! Definitions, for one contradiction slot:
//!
//! * **value** — `(normalize_object(object), polarity)`, the key P4 and
//!   `value_mode` use.
//! * **n(v)** — the number of distinct `agent_id`s among the members of v
//!   (an agent that repeats a value counts once).
//! * **plurality set P** — the values with maximal n(v).
//! * **witness** — a member carrying at least one evidence item whose
//!   *effective* support label (`evidence::effective_label`: support record
//!   for this contribution and capture, status `ok`, checker in
//!   `accepted_checkers`) is `supports`.
//! * **verified set W** — the values with at least one witness member.
//!
//! Rule:
//!
//! 1. **Default winner D** = the ordinary P5 selection (candidate mode,
//!    score, deadband, Schulze, `tiebreak_order`) run on the members of the
//!    values in P only. With a unique plurality value this is that value;
//!    a tied plurality is broken by the policy itself.
//! 2. If W is empty, the winner is D (stage `plurality`).
//! 3. Otherwise the winner is the ordinary P5 selection run on the members
//!    of the values in W only (stage `verified`). D keeps the slot iff D is
//!    verified and the policy prefers it among the verified values; any
//!    other winner is verified by construction.
//!
//! Hence a winner whose value differs from D's always carries an accepted
//! `supports` label (the harm property, `GATE_SPEC.md` §3).
//!
//! Interaction with deadband and Schulze: inside each stage, the deadband
//! test (top-2 gap of quantized scores, at value level in value mode) and
//! the Schulze candidate set are computed over that stage's candidates
//! only. A non-candidate never enters the deadband or the Schulze vote,
//! even if its score is higher or within the threshold of the top. The
//! output's `in_deadband` / `schulze_winner` describe the stage that
//! decided (`gate.stage`). In member mode, a stage's candidates are all
//! members of its values, so members of the same value may still meet in
//! the deadband; that never changes the decided value.

use crate::compiler::OverturnCompiler;
use crate::evidence::{self, EvidencePolicy, EvidenceStore, SupportLabel};
use crate::ir::*;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

/// Gate trace of one slot (member indices into the valid contributions).
#[derive(Debug, Clone, PartialEq)]
pub struct GateTrace {
    /// True when W was non-empty and the verified stage decided.
    pub verified_stage: bool,
    /// The default (plurality-stage) winner D.
    pub default_winner: Option<usize>,
    /// max n(v): distinct agents behind each plurality value.
    pub plurality_agents: usize,
    /// Members the deciding stage chose from.
    pub candidates: Vec<usize>,
    /// Members carrying an accepted `supports` label.
    pub witnesses: Vec<usize>,
    /// The winner's value differs from D's.
    pub overturned: bool,
}

/// `GateTrace` keyed by contribution ids (in `Selection::gate`). Id lists
/// are sorted by id, so the trace does not depend on arrival order.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct GateOutput {
    /// `verified` | `plurality`.
    pub stage: String,
    pub default_winner: Option<String>,
    pub plurality_agents: usize,
    pub candidates: Vec<String>,
    pub witnesses: Vec<String>,
    pub overturned: bool,
}

impl GateOutput {
    pub fn from_trace(t: &GateTrace, valid: &[Contribution]) -> Self {
        let ids = |v: &[usize]| {
            let mut out: Vec<String> = v.iter().map(|&i| valid[i].id.clone()).collect();
            out.sort();
            out
        };
        GateOutput {
            stage: if t.verified_stage { "verified" } else { "plurality" }.into(),
            default_winner: t.default_winner.map(|i| valid[i].id.clone()),
            plurality_agents: t.plurality_agents,
            candidates: ids(&t.candidates),
            witnesses: ids(&t.witnesses),
            overturned: t.overturned,
        }
    }
}

/// Whether `c` carries an evidence item with an effective `supports` label.
pub fn is_witness(c: &Contribution, store: &EvidenceStore, pol: &EvidencePolicy) -> bool {
    c.evidence.iter().any(|e| matches!(evidence::effective_label(e, c, store, pol), Some((SupportLabel::Supports, _))))
}

fn value_key(c: &Contribution) -> (String, bool) {
    let t = c.canonical_form.as_ref().expect("P4 members have a canonical form");
    (normalize_object(&t.object), t.polarity == Polarity::Negate)
}

/// Ordinary P5 selection on the members `members` of `cs` only.
fn select_among(policy: &OverturnCompiler, cs: &ConflictSet, valid: &[Contribution], members: &[usize]) -> ConflictSet {
    let mut sub = cs.clone();
    sub.contribution_ids = members.to_vec();
    sub.scores.retain(|k, _| members.contains(k));
    sub.winner_idx = None;
    sub.gate = None;
    policy.select_slot(&mut sub, valid);
    sub
}

/// Gated P5 selection for one contradiction slot whose member scores are
/// filled in. Sets `winner_idx`, `in_deadband`, `schulze_winner`, `gate`.
pub(crate) fn gated_select(
    policy: &OverturnCompiler,
    cs: &mut ConflictSet,
    valid: &[Contribution],
    store: &EvidenceStore,
    pol: &EvidencePolicy,
) {
    let mut groups: BTreeMap<(String, bool), Vec<usize>> = BTreeMap::new();
    for &idx in &cs.contribution_ids {
        groups.entry(value_key(&valid[idx])).or_default().push(idx);
    }
    let n_agents = |m: &[usize]| m.iter().map(|&i| valid[i].agent_id.as_str()).collect::<BTreeSet<_>>().len();
    let top = groups.values().map(|m| n_agents(m)).max().unwrap_or(0);
    let witnesses: Vec<usize> = cs.contribution_ids.iter().copied()
        .filter(|&i| is_witness(&valid[i], store, pol))
        .collect();
    let members_of = |keep: &dyn Fn(&[usize]) -> bool| {
        let mut v: Vec<usize> = groups.values().filter(|m| keep(m)).flatten().copied().collect();
        v.sort_unstable();
        v
    };
    let plurality = members_of(&|m| n_agents(m) == top);
    let verified = members_of(&|m| m.iter().any(|i| witnesses.contains(i)));

    let default = select_among(policy, cs, valid, &plurality);
    let (verified_stage, candidates) = if verified.is_empty() { (false, plurality) } else { (true, verified) };
    let decided = if verified_stage { select_among(policy, cs, valid, &candidates) } else { default.clone() };

    cs.winner_idx = decided.winner_idx;
    cs.in_deadband = decided.in_deadband;
    cs.schulze_winner = decided.schulze_winner;
    let overturned = match (decided.winner_idx, default.winner_idx) {
        (Some(w), Some(d)) => value_key(&valid[w]) != value_key(&valid[d]),
        _ => false,
    };
    cs.gate = Some(GateTrace {
        verified_stage,
        default_winner: default.winner_idx,
        plurality_agents: top,
        candidates,
        witnesses,
        overturned,
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::compiler::{seal_contributions_with_evidence, ReductionOutput, TieOrder, SCHULZE_DIMS_NO_RECENCY};
    use crate::evidence::fixtures::{capture, checker, support};
    use crate::evidence::{CaptureOutcome, EvidencePolicy, OverturnGate, SupportFactors};
    use crate::ir::{make_id, ContributionKind, LoweringConfidence};
    use crate::value_mode::{CandidateMode, ValueAggregate};
    use std::collections::BTreeMap;

    /// One parsed answer: agent, value, confidence, arrival, citations
    /// as (passage, label) with `None` = cited, unchecked.
    struct A<'a> {
        agent: &'a str,
        obj: &'a str,
        conf: f64,
        seq: u64,
        cites: Vec<(&'a str, Option<SupportLabel>)>,
    }

    fn a<'a>(agent: &'a str, obj: &'a str, conf: f64, seq: u64, cites: Vec<(&'a str, Option<SupportLabel>)>) -> A<'a> {
        A { agent, obj, conf, seq, cites }
    }

    fn gated(mode: CandidateMode, nei: f64, gate: OverturnGate, accepted: &str) -> OverturnCompiler {
        let mut w = OverturnCompiler::default().weights;
        w[3] = 0.0;
        OverturnCompiler {
            weights: w,
            schulze_dims: SCHULZE_DIMS_NO_RECENCY,
            tiebreak_order: TieOrder::Id,
            candidate_mode: mode,
            values: Default::default(),
            functional_predicates: vec!["answer".into()],
            evidence: Some(EvidencePolicy {
                unchecked_factor: 0.5,
                support_factor: SupportFactors { supports: 1.0, not_enough_info: nei, refutes: 0.0 },
                accepted_checkers: vec![accepted.to_string()],
                overturn_gate: gate,
                ..EvidencePolicy::default()
            }),
            ..OverturnCompiler::default()
        }
    }

    /// Build contributions + store; `rogue` labels come from an unaccepted checker.
    fn build(answers: &[A], rogue_agents: &[&str]) -> (Vec<Contribution>, EvidenceStore, String) {
        let ok = checker("judge-accepted");
        let rogue = checker("judge-unvalidated");
        let mut store = EvidenceStore::default();
        let mut out = Vec::new();
        for x in answers {
            let mut c = Contribution {
                id: make_id(&format!("{}|{}", x.agent, x.obj)),
                agent_id: x.agent.into(),
                agent_name: x.agent.into(),
                kind: ContributionKind::Assertion,
                canonical_form: Some(CanonicalTriple::new("q1", "answer", x.obj)),
                confidence: x.conf,
                evidence: vec![],
                raw_text: format!("The answer is {}.", x.obj),
                lowering_confidence: LoweringConfidence::High,
                seq: x.seq,
                timestamp: 0.0,
                is_correct: true,
            };
            for (p, lab) in &x.cites {
                let url = format!("https://example.org/{p}");
                let cid = store.add_capture(capture(&url, CaptureOutcome::Ok));
                let mut e = EvidenceItem::new(EvidenceType::Citation, &url, 1.0, true);
                e.capture_ref = Some(cid.clone());
                if let Some(l) = lab {
                    let ch = if rogue_agents.contains(&x.agent) { &rogue } else { &ok };
                    e.support_ref = Some(store.add_support(support(&c, &cid, *l, ch)));
                }
                c.evidence.push(e);
            }
            out.push(c);
        }
        (out, store, ok.checker_id)
    }

    fn reduce(p: &OverturnCompiler, cs: &[Contribution], store: &EvidenceStore) -> ReductionOutput {
        let cal: BTreeMap<String, f64> = cs.iter().map(|c| (c.agent_id.clone(), 0.7)).collect();
        let sealed = seal_contributions_with_evidence("q1?", vec![], &cal, cs, Some(store)).unwrap();
        ReductionOutput::from_result(&p.reduce(&sealed))
    }

    fn slot(o: &ReductionOutput) -> &crate::compiler::Selection {
        let v: Vec<_> = o.selections.iter().filter(|s| s.typ == "CONTRADICTION").collect();
        assert_eq!(v.len(), 1);
        v[0]
    }

    fn winner_obj(o: &ReductionOutput, cs: &[Contribution]) -> String {
        let w = slot(o).winner.clone().unwrap();
        cs.iter().find(|c| c.id == w).unwrap().canonical_form.as_ref().unwrap().object.clone()
    }

    const MODES: [CandidateMode; 3] = [
        CandidateMode::Member,
        CandidateMode::Value { aggregate: ValueAggregate::Max },
        CandidateMode::Value { aggregate: ValueAggregate::Pooled },
    ];

    use SupportLabel::{NotEnoughInfo as N, Refutes as R, Supports as S};

    /// The dev c-case mechanism: a minority wins ungated on NEI-citation
    /// volume. Gated, an unverified minority can never overturn.
    #[test]
    fn unverified_minority_never_overturns() {
        let ans = [
            a("a1", "Paris", 0.45, 1000, vec![]),
            a("a2", "Paris", 0.45, 2000, vec![]),
            a("a3", "Paris", 0.45, 3000, vec![]),
            a("a4", "Lyon", 0.85, 4000, vec![("p1", Some(N)), ("p2", Some(N)), ("p3", None)]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            for nei in [0.5, 0.1, 0.0] {
                let ungated = reduce(&gated(m, nei, OverturnGate::None, &acc), &cs, &st);
                let g = reduce(&gated(m, nei, OverturnGate::Verified, &acc), &cs, &st);
                if nei == 0.5 {
                    assert_eq!(winner_obj(&ungated, &cs), "Lyon", "{m:?}: fixture must overturn ungated");
                }
                assert!(slot(&ungated).gate.is_none());
                assert_eq!(winner_obj(&g, &cs), "Paris", "{m:?} nei {nei}");
                let t = slot(&g).gate.as_ref().unwrap();
                assert_eq!((t.stage.as_str(), t.overturned, t.plurality_agents), ("plurality", false, 3));
                assert!(t.witnesses.is_empty());
                // scores are not touched by the gate
                assert_eq!(slot(&g).scores_q, slot(&ungated).scores_q);
            }
        }
        // a `supports` label from an unaccepted checker does not verify
        let ans2 = [
            a("a1", "Paris", 0.45, 1000, vec![]),
            a("a2", "Paris", 0.45, 2000, vec![]),
            a("a4", "Lyon", 0.85, 4000, vec![("p1", Some(S))]),
        ];
        let (cs2, st2, acc2) = build(&ans2, &["a4"]);
        for m in MODES {
            let g = reduce(&gated(m, 0.0, OverturnGate::Verified, &acc2), &cs2, &st2);
            assert_eq!(winner_obj(&g, &cs2), "Paris", "{m:?}");
        }
    }

    /// A verified minority overturns an unverified majority, whatever its score.
    #[test]
    fn verified_minority_overturns() {
        let ans = [
            a("a1", "Paris", 0.85, 1000, vec![("p1", Some(N)), ("p2", Some(N)), ("p3", Some(N))]),
            a("a2", "Paris", 0.85, 2000, vec![("p4", Some(N)), ("p5", Some(N)), ("p6", Some(N))]),
            a("a3", "Paris", 0.85, 3000, vec![("p7", Some(N))]),
            a("a4", "Lyon", 0.45, 4000, vec![("p8", Some(S))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            for nei in [0.5, 0.1, 0.0] {
                let g = reduce(&gated(m, nei, OverturnGate::Verified, &acc), &cs, &st);
                assert_eq!(winner_obj(&g, &cs), "Lyon", "{m:?} nei {nei}");
                let t = slot(&g).gate.as_ref().unwrap();
                assert_eq!((t.stage.as_str(), t.overturned), ("verified", true));
                let lyon = cs.iter().find(|c| c.agent_id == "a4").unwrap().id.clone();
                assert_eq!(t.witnesses, vec![lyon.clone()]);
                assert_eq!(t.candidates, vec![lyon]);
                // D is the plurality value
                let d = t.default_winner.clone().unwrap();
                assert_eq!(cs.iter().find(|c| c.id == d).unwrap().canonical_form.as_ref().unwrap().object, "Paris");
                assert!(!slot(&g).in_deadband, "a single candidate never enters the deadband");
            }
        }
    }

    /// Both the majority and a minority are verified: the policy score
    /// decides among the verified values (FRAMING §3.4 BE-G). The minority
    /// can win only on a higher verified-stage score, never on unverified
    /// members' scores.
    #[test]
    fn verified_majority_vs_verified_minority() {
        // (1) majority verified with stronger evidence: majority keeps the slot
        let ans = [
            a("a1", "Paris", 0.65, 1000, vec![("p1", Some(S)), ("p2", Some(S))]),
            a("a2", "Paris", 0.65, 2000, vec![]),
            a("a3", "Paris", 0.65, 3000, vec![]),
            a("a4", "Lyon", 0.65, 4000, vec![("p8", Some(S))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            let g = reduce(&gated(m, 0.0, OverturnGate::Verified, &acc), &cs, &st);
            assert_eq!(winner_obj(&g, &cs), "Paris", "{m:?}");
            let t = slot(&g).gate.as_ref().unwrap();
            assert_eq!((t.stage.as_str(), t.overturned, t.candidates.len()), ("verified", false, 4));
        }
        // (2) verified minority with the higher score among verified values wins
        let ans = [
            a("a1", "Paris", 0.45, 1000, vec![("p1", Some(S))]),
            a("a2", "Paris", 0.45, 2000, vec![]),
            a("a3", "Paris", 0.45, 3000, vec![]),
            a("a4", "Lyon", 0.85, 4000, vec![("p8", Some(S)), ("p9", Some(S)), ("p10", Some(S))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            let g = reduce(&gated(m, 0.0, OverturnGate::Verified, &acc), &cs, &st);
            assert_eq!(winner_obj(&g, &cs), "Lyon", "{m:?}");
            assert!(slot(&g).gate.as_ref().unwrap().overturned);
        }
        // (3) an unverified third value with the top score cannot win the verified stage
        let ans = [
            a("a1", "Paris", 0.45, 1000, vec![("p1", Some(S))]),
            a("a2", "Paris", 0.45, 2000, vec![]),
            a("a3", "Marseille", 0.85, 3000, vec![("p3", Some(N)), ("p4", Some(N)), ("p5", None)]),
            a("a4", "Lyon", 0.45, 4000, vec![("p8", Some(S))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            let ungated = reduce(&gated(m, 0.5, OverturnGate::None, &acc), &cs, &st);
            assert_eq!(winner_obj(&ungated, &cs), "Marseille", "{m:?}");
            let g = reduce(&gated(m, 0.5, OverturnGate::Verified, &acc), &cs, &st);
            assert_ne!(winner_obj(&g, &cs), "Marseille", "{m:?}");
            let marseille = cs.iter().find(|c| c.agent_id == "a3").unwrap().id.clone();
            assert!(!slot(&g).gate.as_ref().unwrap().candidates.contains(&marseille));
        }
    }

    /// Refutes and NEI labels never verify; a tied plurality is broken by
    /// the policy among the tied values only.
    #[test]
    fn only_supports_verifies_and_tied_plurality() {
        let ans = [
            a("a1", "Paris", 0.45, 1000, vec![("p1", Some(R))]),
            a("a2", "Paris", 0.45, 2000, vec![]),
            a("a3", "Lyon", 0.85, 3000, vec![("p3", Some(N))]),
            a("a4", "Lyon", 0.45, 4000, vec![]),
            a("a5", "Nice", 0.85, 5000, vec![("p5", Some(N)), ("p6", Some(N)), ("p7", Some(N))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        for m in MODES {
            let g = reduce(&gated(m, 0.5, OverturnGate::Verified, &acc), &cs, &st);
            let t = slot(&g).gate.as_ref().unwrap();
            assert_eq!((t.stage.as_str(), t.plurality_agents, t.candidates.len()), ("plurality", 2, 4), "{m:?}");
            // Nice (1 agent) is excluded even though it scores highest
            assert_eq!(winner_obj(&g, &cs), "Lyon", "{m:?}");
        }
    }

    /// The gated decision (winner, trace, outputs) is invariant under
    /// every permutation of input order and every relabelling of arrival
    /// `seq` (order-free policy: recency 0, recency-free Schulze, id order).
    #[test]
    fn permutation_invariance() {
        let ans = [
            a("a1", "Paris", 0.85, 1000, vec![("p1", Some(N))]),
            a("a2", "Paris", 0.65, 2000, vec![("p2", Some(N))]),
            a("a3", "Paris", 0.45, 3000, vec![]),
            a("a4", "Lyon", 0.45, 4000, vec![("p8", Some(S))]),
            a("a5", "Nice", 0.65, 5000, vec![("p9", Some(S)), ("p10", Some(N))]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        let perms = permutations(cs.len());
        for m in MODES {
            for nei in [0.5, 0.0] {
                let p = gated(m, nei, OverturnGate::Verified, &acc);
                let base = reduce(&p, &cs, &st);
                let mut n = 0;
                for perm in &perms {
                    // permute both the input order and the arrival seq
                    let seqs: Vec<u64> = perm.iter().map(|&i| cs[i].seq).collect();
                    let mut shuffled: Vec<Contribution> = perm.iter().map(|&i| cs[i].clone()).collect();
                    for (k, c) in shuffled.iter_mut().enumerate() {
                        c.seq = seqs[(k + 1) % seqs.len()];
                    }
                    let o = reduce(&p, &shuffled, &st);
                    let (s, b) = (slot(&o), slot(&base));
                    assert_eq!((&s.winner, &s.gate, &s.scores_q, s.in_deadband), (&b.winner, &b.gate, &b.scores_q, b.in_deadband),
                               "{m:?} nei {nei} perm {perm:?}");
                    // `seq` is sealed, so the root hash and the canonical order of the
                    // id lists move with it; the admitted / rejected sets do not
                    let sorted = |v: &[String]| { let mut v = v.to_vec(); v.sort(); v };
                    assert_eq!((sorted(&o.admitted), sorted(&o.rejected)), (sorted(&base.admitted), sorted(&base.rejected)));
                    n += 1;
                }
                assert_eq!(n, 120);
            }
        }
    }

    /// `overturn_gate` is hashed only when non-default: explicit `"none"`
    /// hashes as absent; `"verified"` changes the hash; unknown values are
    /// rejected.
    #[test]
    fn gate_field_serialization_and_hash() {
        let base = gated(CandidateMode::Member, 0.1, OverturnGate::None, "ck");
        let mut j: serde_json::Value = serde_json::to_value(&base).unwrap();
        assert!(j["evidence"].get("overturn_gate").is_none());
        j["evidence"]["overturn_gate"] = "none".into();
        let explicit: OverturnCompiler = serde_json::from_value(j.clone()).unwrap();
        assert_eq!(explicit.policy_hash(), base.policy_hash());
        j["evidence"]["overturn_gate"] = "verified".into();
        let v: OverturnCompiler = serde_json::from_value(j.clone()).unwrap();
        assert_eq!(v.evidence.as_ref().unwrap().overturn_gate, OverturnGate::Verified);
        assert_ne!(v.policy_hash(), base.policy_hash());
        assert!(v.canonical_policy_json().contains("\"overturn_gate\":\"verified\""));
        j["evidence"]["overturn_gate"] = "majority".into();
        assert!(serde_json::from_value::<OverturnCompiler>(j).is_err());
        // default and generic presets are untouched
        assert_eq!(OverturnCompiler::default().policy_hash(), "dd8d36e6def3a6d598765e82d461a473");
    }

    /// NEI factor 0 is expressible (`support_factor.not_enough_info = 0`):
    /// an NEI-labelled citation then contributes exactly 0 evidence, as a
    /// refutes label does; an unchecked citation keeps `unchecked_factor`.
    #[test]
    fn nei_factor_zero() {
        let j = serde_json::json!({"format": "bran-evidence-policy/1", "unchecked_factor": 0.5, "accepted_checkers": ["x"],
            "support_factor": {"supports": 1.0, "not_enough_info": 0.0, "refutes": 0.0}});
        let pol: EvidencePolicy = serde_json::from_value(j).unwrap();
        assert_eq!(pol.support_factor.not_enough_info, 0.0);
        let ans = [
            a("a1", "Paris", 0.65, 1000, vec![]),
            a("a2", "Lyon", 0.65, 2000, vec![("p1", Some(N)), ("p2", Some(N)), ("p3", Some(R))]),
            a("a3", "Nice", 0.65, 3000, vec![("p4", None)]),
        ];
        let (cs, st, acc) = build(&ans, &[]);
        let p0 = gated(CandidateMode::Member, 0.0, OverturnGate::None, &acc);
        let p1 = gated(CandidateMode::Member, 0.1, OverturnGate::None, &acc);
        let (o0, o1) = (reduce(&p0, &cs, &st), reduce(&p1, &cs, &st));
        let sc = |o: &ReductionOutput, ag: &str| slot(o).scores_q[&cs.iter().find(|c| c.agent_id == ag).unwrap().id];
        assert_eq!(sc(&o0, "a2"), sc(&o0, "a1"), "NEI/refutes-only evidence scores as no evidence");
        assert!(sc(&o1, "a2") > sc(&o1, "a1"));
        assert!(sc(&o0, "a3") > sc(&o0, "a1"), "unchecked keeps unchecked_factor 0.5");
        assert!(p0.canonical_policy_json().contains("\"not_enough_info\":0.0"));
    }

    fn permutations(n: usize) -> Vec<Vec<usize>> {
        if n == 0 {
            return vec![vec![]];
        }
        let mut out = Vec::new();
        for p in permutations(n - 1) {
            for k in 0..=p.len() {
                let mut q = p.clone();
                q.insert(k, n - 1);
                out.push(q);
            }
        }
        out
    }
}
