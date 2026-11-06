use crate::ir::*;
use crate::topics::Topic;
use crate::agents::AgentPersonality;
use crate::evidence::{self, EvidencePolicy, EvidenceStore};
use std::collections::{BTreeMap, HashMap, HashSet};
use sha2::{Digest, Sha256};
use serde::{Deserialize, Serialize};
use rand_chacha::ChaCha8Rng;
use rand::SeedableRng;
use crate::value_mode::CandidateMode;

// ── Functional predicates (unique-valued) ───────────────────

const UNIQUE_PREDICATES: &[&str] = &[
    "has_capital",
    "is_classified_as",
    "are_caused_by",
    "became_capital_in",
    "was_reclassified_in",
    "is_located_in",
    "was_temporary_capital_until",
    "contributes",
    "is",
    "has",
    "raises",
    "recommends",
    "is_causal_for",
];

/// Arity of a predicate: FUNCTIONAL iff listed in `UNIQUE_PREDICATES`.
pub fn predicate_arity(predicate: &str) -> PredicateArity {
    predicate_arity_ext(predicate, &[])
}

/// Arity of a predicate under a policy that extends `UNIQUE_PREDICATES`
/// with `extra` (`OverturnCompiler::functional_predicates`; compared
/// case-insensitively, like the built-in list).
pub fn predicate_arity_ext(predicate: &str, extra: &[String]) -> PredicateArity {
    let p = predicate.to_lowercase();
    if UNIQUE_PREDICATES.iter().any(|&u| u == p) || extra.iter().any(|u| u.to_lowercase() == p) {
        PredicateArity::Functional
    } else {
        PredicateArity::NonFunctional
    }
}

/// The built-in functional predicates (sorted).
pub fn builtin_functional_predicates() -> Vec<&'static str> {
    let mut v = UNIQUE_PREDICATES.to_vec();
    v.sort_unstable();
    v.dedup();
    v
}

// ── Value incompatibility seed table (B1b) ──────────────────

/// Exclusive alternatives among NON_FUNCTIONAL values, seeded from the
/// TCP topic in topics.rs: each misconception that is the exclusive
/// alternative of a correct fact under the same predicate is grouped
/// with it. Not grouped, because no same-predicate exclusive counterpart
/// exists: (TCP, guarantees, zero data loss) and (TCP, implements, fixed
/// timeout retransmission) — the latter's alternative, exponential
/// backoff, is asserted under `handles_loss_via`, not `implements`.
const INCOMPATIBLE_VALUES: &[(&str, &str, &[&str])] = &[
    // Connection setup is exactly one handshake protocol.
    ("uses", "tcp_handshake", &["three-way handshake (SYN, SYN-ACK, ACK)", "two-way handshake"]),
    // Loss recovery: ARQ retransmission vs FEC.
    ("handles_loss_via", "tcp_loss_recovery", &["retransmission with exponential backoff", "forward error correction (FEC)"]),
    // The segment integrity check is one algorithm.
    ("detects_corruption_via", "tcp_integrity_check", &["16-bit checksum", "CRC-32"]),
];

/// Default value policy: the seeded `INCOMPATIBLE_VALUES` table.
pub fn default_value_policy() -> ValuePolicy {
    ValuePolicy::from_table(INCOMPATIBLE_VALUES)
}

static DEFAULT_VALUE_POLICY: once_cell::sync::Lazy<ValuePolicy> =
    once_cell::sync::Lazy::new(default_value_policy);

/// Arity-aware slot key under the default value policy.
pub fn slot_key(triple: &CanonicalTriple) -> SlotKey {
    slot_key_with(triple, &DEFAULT_VALUE_POLICY)
}

/// Arity-aware slot key for a triple.
///   FUNCTIONAL               → (subject, predicate)
///   NON_FUNCTIONAL, grouped  → (subject, predicate, group id)
///   NON_FUNCTIONAL, ungrouped→ (subject, predicate, normalized object)
/// Polarity is excluded in all cases.
pub fn slot_key_with(triple: &CanonicalTriple, policy: &ValuePolicy) -> SlotKey {
    slot_key_ext(triple, policy, &[])
}

/// `slot_key_with` with extra functional predicates (see `predicate_arity_ext`).
pub fn slot_key_ext(triple: &CanonicalTriple, policy: &ValuePolicy, extra_functional: &[String]) -> SlotKey {
    let (subject, predicate) = triple.key();
    match predicate_arity_ext(&predicate, extra_functional) {
        PredicateArity::Functional => SlotKey { subject, predicate, object: None, group: None },
        PredicateArity::NonFunctional => {
            let obj = normalize_object(&triple.object);
            match policy.group_of(&predicate, &obj) {
                Some(g) => {
                    let group = Some(g.to_string());
                    SlotKey { subject, predicate, object: None, group }
                }
                None => SlotKey { subject, predicate, object: Some(obj), group: None },
            }
        }
    }
}

/// Object-level key used to target critiques: like `slot_key` but never
/// grouped, so negating one exclusive value does not penalize its
/// alternatives.
pub fn critique_key(triple: &CanonicalTriple) -> SlotKey {
    slot_key_with(triple, &ValuePolicy::default())
}

// ── Compiler ────────────────────────────────────────────────

/// Integer scale factor for score quantization (§6.1 purity constraint #5).
/// All scores are multiplied by this factor and rounded to the nearest
/// integer before comparison, ensuring platform-independent determinism.
pub const SCORE_SCALE: f64 = 10_000.0;

/// The reduction policy. Serializable so a dumped artifact can be
/// replayed under exactly the policy that produced it.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OverturnCompiler {
    pub weights: [f64; 5], // ev, conf, cs, rec, ca
    pub max_severity_budget: f64,
    /// Score gap below which a conflict enters the deadband
    /// and the Election Leader should be consulted.
    /// Expressed in integer-scaled units (i.e. 500 = 0.05 in f64 scale).
    /// The deadband is ABSOLUTE on the 10,000-point quantized scale: it is
    /// not relative to the score range of the conflict set. It also bounds
    /// the Schulze candidate set (members within it of the top score).
    pub deadband_threshold: i64,
    /// Dimension-level indifference threshold for Schulze pairwise
    /// comparisons. Candidate i beats j on dimension k only if
    /// d_k(i) > d_k(j) + schulze_dim_epsilon.
    /// Expressed in integer-scaled units (i.e. 100 = 0.01 in f64 scale).
    pub schulze_dim_epsilon: i64,
    /// Hardening policy for anti-adversarial measures.
    pub hardening: HardeningPolicy,
    /// Value-incompatibility policy for non-functional predicates.
    pub values: ValuePolicy,
    /// Dimensions that vote in the Schulze tie-break, as a bitmask over
    /// (ev, conf, cs, rec, ca): bit 0 = ev, ..., bit 3 = rec, bit 4 = ca.
    /// Default `0b11111` (all five, the original behaviour). Schulze
    /// dimensions are unweighted, so a zero scoring weight does NOT remove
    /// a dimension from the tie-break; clear its bit here instead
    /// (recency-free: `0b10111` = 23, see `SCHULZE_DIMS_NO_RECENCY`).
    /// Bits above 4 are ignored. Serialized (and hashed) only when
    /// non-default, so the default policy hash is unchanged.
    #[serde(default = "default_schulze_dims", skip_serializing_if = "is_default_schulze_dims")]
    pub schulze_dims: u8,
    /// How a deadband conflict is resolved. Default `schulze`. Serialized
    /// (and hashed) only when non-default.
    #[serde(default, skip_serializing_if = "TieBreak::is_default")]
    pub tiebreak: TieBreak,
    /// Order used to break remaining ties: the Schulze scan order over the
    /// deadband candidates, and the choice among members sharing the top
    /// quantized score. Default `seq` (canonical member order = ascending
    /// arrival `seq`, then id; the original behaviour, arrival-dependent).
    /// `id` orders by contribution id only (a content hash), so it is
    /// independent of arrival order. Serialized (and hashed) only when
    /// non-default.
    #[serde(default, skip_serializing_if = "TieOrder::is_default")]
    pub tiebreak_order: TieOrder,
    /// Experimental: candidates are members (default) or distinct
    /// values; see `value_mode`. Serialized (and hashed) only when
    /// non-default.
    #[serde(default, skip_serializing_if = "CandidateMode::is_member")]
    pub candidate_mode: CandidateMode,
    /// Evidence capture/support scoring (`bran-evidence-policy/1`, spec
    /// §3.4). `None` = today's evidence scoring. Serialized (and hashed)
    /// only when set, so the default policy hash is unchanged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence: Option<EvidencePolicy>,
    /// Predicates treated as FUNCTIONAL (one slot per (subject,
    /// predicate)) in addition to the built-in `UNIQUE_PREDICATES`,
    /// compared case-insensitively. Applies to conflict slots and to
    /// critique targeting, exactly like a built-in functional predicate.
    /// Serialized (and hashed) only when non-empty, so every existing
    /// policy hash is unchanged; hashed as a set (lowercased, sorted,
    /// deduplicated, built-in entries dropped).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub functional_predicates: Vec<String>,
}

/// Tie-resolution order (see `OverturnCompiler::tiebreak_order`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TieOrder {
    /// Canonical member order: ascending (seq, id). Arrival-dependent.
    #[default]
    Seq,
    /// Ascending contribution id only. Arrival-independent.
    Id,
}

impl TieOrder {
    fn is_default(&self) -> bool { *self == TieOrder::Seq }
}

/// All five Schulze dimensions (ev, conf, cs, rec, ca).
pub const SCHULZE_DIMS_ALL: u8 = 0b11111;
/// All Schulze dimensions except recency (bit 3).
pub const SCHULZE_DIMS_NO_RECENCY: u8 = SCHULZE_DIMS_ALL & !(1 << 3);

fn default_schulze_dims() -> u8 { SCHULZE_DIMS_ALL }
fn is_default_schulze_dims(m: &u8) -> bool { *m == SCHULZE_DIMS_ALL }

/// Deadband tie-break mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TieBreak {
    /// Per-dimension Schulze over the deadband candidates (original).
    #[default]
    Schulze,
    /// Keep the raw-score leader: highest quantized final score, exact
    /// ties broken by `tiebreak_order` (default: canonical member order,
    /// which is arrival `seq`; use `id` for an arrival-free result).
    /// No dimension votes, so a zero weight fully removes a dimension.
    ScoreThenCanonical,
}

impl TieBreak {
    fn is_default(&self) -> bool { *self == TieBreak::Schulze }
}

/// Format tag of the canonical policy serialization (hashed).
pub const POLICY_FORMAT: &str = "bran-policy/1";

/// serde_json maps non-finite floats to `null`; the policy has no
/// optional fields, so any `null` means a NaN/inf slipped in.
fn no_null_floats(v: &serde_json::Value) -> bool {
    match v {
        serde_json::Value::Null => false,
        serde_json::Value::Array(a) => a.iter().all(no_null_floats),
        serde_json::Value::Object(o) => o.values().all(no_null_floats),
        _ => true,
    }
}

/// Quantize a floating-point score to integer-scaled representation.
#[inline]
pub fn quantize(score: f64) -> i64 {
    (score * SCORE_SCALE).round() as i64
}

impl Default for OverturnCompiler {
    fn default() -> Self {
        Self {
            weights: [0.35, 0.20, 0.25, 0.05, 0.15],
            max_severity_budget: 5.0,
            deadband_threshold: 500,      // 0.05 × 10,000
            schulze_dim_epsilon: 100,      // 0.01 × 10,000
            hardening: HardeningPolicy::default(),
            values: default_value_policy(),
            schulze_dims: SCHULZE_DIMS_ALL,
            tiebreak: TieBreak::Schulze,
            tiebreak_order: TieOrder::Seq,
            candidate_mode: crate::value_mode::default_mode(),
            evidence: None,
            functional_predicates: Vec::new(),
        }
    }
}

impl OverturnCompiler {
    pub fn new(weights: [f64; 5], max_severity_budget: f64) -> Self {
        Self { weights, max_severity_budget, ..Self::default() }
    }

    pub fn with_weights(weights: [f64; 5]) -> Self {
        Self::new(weights, 5.0)
    }

    // ── Policy hash ─────────────────────────────────────────

    /// Canonical serialization of the full reduction policy
    /// (`bran-policy/1`). Two sections:
    ///   `config`    — every serialized field of `OverturnCompiler` (weights,
    ///                 severity budget, deadband, Schulze epsilon,
    ///                 hardening, incompatible_values table);
    ///   `constants` — reducer constants compiled into the binary
    ///                 (score scale, lowering factors, evidence-type
    ///                 weights, verification quality, functional
    ///                 predicates), so a binary built with different
    ///                 constants produces a different policy hash.
    /// Canonicalization rules:
    ///   * object keys sorted (serde_json `Value` maps are BTreeMaps;
    ///     the `preserve_order` feature is not enabled);
    ///   * compact output, no whitespace;
    ///   * floats as serde_json/ryu shortest round-trip decimal, which is
    ///     a pure integer algorithm over the IEEE-754 bits: exact (two
    ///     distinct f64 never print the same) and platform-independent.
    ///     Non-finite floats are rejected (they have no JSON form);
    ///   * set-valued data is sorted and deduplicated: the objects of each
    ///     incompatible_values group and the functional predicates.
    ///     Map key order (predicates, groups) is irrelevant by construction.
    pub fn canonical_policy_json(&self) -> String {
        let mut config = serde_json::to_value(self).expect("policy serialization");
        if let Some(table) = config
            .pointer_mut("/values/incompatible_values")
            .and_then(|t| t.as_object_mut())
        {
            for groups in table.values_mut() {
                if let Some(groups) = groups.as_object_mut() {
                    for objs in groups.values_mut() {
                        if let Some(arr) = objs.as_array_mut() {
                            let mut v: Vec<String> = arr.iter()
                                .map(|o| o.as_str().unwrap_or_default().to_string())
                                .collect();
                            v.sort();
                            v.dedup();
                            *arr = v.into_iter().map(serde_json::Value::String).collect();
                        }
                    }
                }
            }
        }
        // accepted_checkers is a set: order and duplicates are irrelevant.
        if let Some(arr) = config.pointer_mut("/evidence/accepted_checkers").and_then(|a| a.as_array_mut()) {
            let mut v: Vec<String> = arr.iter().map(|o| o.as_str().unwrap_or_default().to_string()).collect();
            v.sort();
            v.dedup();
            *arr = v.into_iter().map(serde_json::Value::String).collect();
        }
        // functional_predicates is a set extending the built-in list:
        // lowercase, drop built-ins, sort, dedup; absent when empty, so a
        // policy listing only built-ins hashes as the default does.
        if let Some(obj) = config.as_object_mut()
            && let Some(serde_json::Value::Array(arr)) = obj.get("functional_predicates") {
            let builtin = builtin_functional_predicates();
            let mut v: Vec<String> = arr.iter()
                .map(|o| o.as_str().unwrap_or_default().to_lowercase())
                .filter(|p| !builtin.contains(&p.as_str()))
                .collect();
            v.sort();
            v.dedup();
            if v.is_empty() {
                obj.remove("functional_predicates");
            } else {
                obj.insert("functional_predicates".into(), v.into_iter().map(serde_json::Value::String).collect());
            }
        }
        let doc = serde_json::json!({
            "format": POLICY_FORMAT,
            "config": config,
            "constants": reducer_constants(),
        });
        assert!(no_null_floats(&doc), "policy contains a non-finite float");
        serde_json::to_string(&doc).expect("policy serialization")
    }

    /// SHA-256 of `canonical_policy_json()`, truncated to 128 bits (hex),
    /// the same width as the sealed set's root hash.
    pub fn policy_hash(&self) -> String {
        let h = Sha256::digest(self.canonical_policy_json().as_bytes());
        h.iter().take(16).map(|b| format!("{b:02x}")).collect()
    }

    /// Named base policy. `default` is the reducer default (hash
    /// `dd8d36e6def3a6d598765e82d461a473`; it carries the TCP demo's
    /// `values.incompatible_values` groups). `generic` is the default
    /// without any value-incompatibility groups: the recommended base for
    /// external use, where the demo's TCP groupings mean nothing. It is
    /// equivalent to the overlay `{"values": {"incompatible_values": {}}}`.
    pub fn preset(name: &str) -> Option<Self> {
        match name {
            "default" => Some(Self::default()),
            "generic" => Some(Self { values: ValuePolicy::default(), ..Self::default() }),
            _ => None,
        }
    }

    /// Conflict slot key of a triple under this policy.
    pub fn slot_key_of(&self, triple: &CanonicalTriple) -> SlotKey {
        slot_key_ext(triple, &self.values, &self.functional_predicates)
    }

    /// Critique-targeting key under this policy (never grouped).
    pub fn critique_key_of(&self, triple: &CanonicalTriple) -> SlotKey {
        if self.functional_predicates.is_empty() {
            critique_key(triple)
        } else {
            slot_key_ext(triple, &ValuePolicy::default(), &self.functional_predicates)
        }
    }
}

/// Names accepted by `OverturnCompiler::preset`.
pub const POLICY_PRESETS: &[&str] = &["default", "generic"];

/// The `constants` block of `canonical_policy_json`: reducer constants
/// compiled into the binary.
pub fn reducer_constants() -> serde_json::Value {
    let functional = builtin_functional_predicates();
    serde_json::json!({
                "score_scale": SCORE_SCALE,
                "lowering_factors": {
                    "HIGH": LoweringConfidence::High.factor(),
                    "MEDIUM": LoweringConfidence::Medium.factor(),
                    "LOW": LoweringConfidence::Low.factor(),
                },
                "evidence_type_weights": {
                    "TOOL_RESULT": EvidenceType::ToolResult.weight(),
                    "EMPIRICAL": EvidenceType::Empirical.weight(),
                    "CITATION": EvidenceType::Citation.weight(),
                    "AUTHORITY": EvidenceType::Authority.weight(),
                    "REASONING": EvidenceType::Reasoning.weight(),
                },
                "verification_quality": {
                    "UNVERIFIED": EvidenceVerification::Unverified.quality_score(),
                    "REACHABILITY_CHECKED": EvidenceVerification::ReachabilityChecked.quality_score(),
                    "CONTENT_HASHED": EvidenceVerification::ContentHashed.quality_score(),
                    "CROSS_REFERENCED": EvidenceVerification::CrossReferenced.quality_score(),
                    "STALE": EvidenceVerification::Stale.quality_score(),
                },
                "functional_predicates": functional,
    })
}

/// Reducer-constants id: SHA-256 of the compact JSON of
/// `reducer_constants()`, truncated to 128 bits (hex). Two binaries with
/// the same id hash every policy identically.
pub fn reducer_constants_id() -> String {
    let h = Sha256::digest(serde_json::to_string(&reducer_constants()).expect("constants").as_bytes());
    h.iter().take(16).map(|b| format!("{b:02x}")).collect()
}

impl OverturnCompiler {

    // ── Main entry point ────────────────────────────────────

    /// Ingest (P1–P2), seal (P3 + hash), then reduce the sealed set (P4–P6).
    pub fn compile(
        &self,
        topic: &Topic,
        roster: &[AgentPersonality],
        seed: u64,
    ) -> CompilationResult {
        self.compile_with_injected(topic, roster, seed, Vec::new())
    }

    /// Compile with additional injected claims (e.g., sybil attacks).
    /// Injected claims are ingested alongside lowered ones, so `seq` is
    /// assigned over the combined arrival order.
    pub fn compile_with_injected(
        &self,
        topic: &Topic,
        roster: &[AgentPersonality],
        seed: u64,
        injected: Vec<Contribution>,
    ) -> CompilationResult {
        let t0 = std::time::Instant::now();
        let mut rng = ChaCha8Rng::seed_from_u64(seed);

        // P1: Normalize (extract goal/constraints/criteria — structural no-op)
        let (goal, _constraints, _criteria) = self.p1_normalize(topic);

        // P2: Lower — generate claims from every agent, record arrival seq
        // (P2 assigns content ids; injected claims get theirs here.)
        let mut contributions = self.p2_lower(roster, topic, &mut rng);
        if !injected.is_empty() {
            let mut injected = injected;
            assign_content_ids(&mut injected);
            contributions.extend(injected);
            assign_arrival_seq(&mut contributions);
        }

        // Seal: P3 validate + canonical order, then hash. Nothing below
        // reads anything outside the sealed set. Every id is already a
        // content id (seq is not part of it), so none is recomputed.
        let sealed = seal_inner(
            goal,
            topic.criteria.iter().map(|c| c.to_string()).collect(),
            &roster_calibration(roster),
            &contributions,
            Some(CONTRIBUTION_ID_SCHEME),
        );
        debug_assert!(sealed.content_id_violations().is_empty());

        // P4–P6 on the sealed set
        let mut result = self.reduce(&sealed);
        result.ees = compute_ees(roster);
        result.time_us = t0.elapsed().as_micros() as u64;
        result
    }

    /// Seal step: validate, canonically order, and hash the inputs to
    /// reduction. `calibration` is restricted to contributing agents,
    /// with the reducer's 0.5 default written in explicitly.
    pub fn seal(
        &self,
        intent: &str,
        criteria: &[&str],
        roster: &[AgentPersonality],
        contributions: &[Contribution],
    ) -> SealedArtifactSet {
        // The compiler is the ingesting party for its own lowered (and
        // in-process injected) contributions, so it assigns content ids
        // here; externally supplied ids are checked, never rewritten
        // (`seal_contributions_content`).
        let mut owned = contributions.to_vec();
        assign_content_ids(&mut owned);
        seal_inner(
            intent,
            criteria.iter().map(|c| c.to_string()).collect(),
            &roster_calibration(roster),
            &owned,
            Some(CONTRIBUTION_ID_SCHEME),
        )
    }

    /// Legacy seal (generator-seed ids, `bran-artifact/2`): no id check,
    /// no `id_scheme`. Kept so pre-v4 artifacts can be reproduced.
    pub fn seal_legacy(
        &self,
        intent: &str,
        criteria: &[&str],
        roster: &[AgentPersonality],
        contributions: &[Contribution],
    ) -> SealedArtifactSet {
        seal_contributions(
            intent,
            criteria.iter().map(|c| c.to_string()).collect(),
            &roster_calibration(roster),
            contributions,
        )
    }

    /// Reduce a sealed artifact set: P4 detect, P5 score/select, P6
    /// partition + certificate. A pure function of (`self`, `sealed`).
    /// `ees` is a roster diagnostic and is left at 0.0 here.
    pub fn reduce(&self, sealed: &SealedArtifactSet) -> CompilationResult {
        let valid = &sealed.contributions;
        let mut conflicts = self.p4_detect(valid, &sealed.intent);
        self.p5_select(&mut conflicts, valid, &sealed.calibration, &sealed.criteria, sealed.evidence_store.as_ref());
        self.p6_partition(sealed, conflicts)
    }

    // ── Public per-pass accessors (for timing instrumentation) ──

    pub fn p2_lower_pub(&self, roster: &[AgentPersonality], topic: &Topic, rng: &mut ChaCha8Rng) -> Vec<Contribution> {
        self.p2_lower(roster, topic, rng)
    }

    /// P2 with the legacy generator-seed ids (`make_id(seed)`), for
    /// reproducing `bran-artifact/2` dumps (`--legacy-ids`).
    pub fn p2_lower_legacy_ids_pub(&self, roster: &[AgentPersonality], topic: &Topic, rng: &mut ChaCha8Rng) -> Vec<Contribution> {
        let mut all_claims: Vec<Contribution> = Vec::new();
        for agent in roster {
            let claims = agent.generate_claims(topic, &all_claims, rng);
            all_claims.extend(claims);
        }
        assign_arrival_seq(&mut all_claims);
        all_claims
    }

    pub fn p3_validate_pub(&self, contributions: &[Contribution]) -> Vec<Contribution> {
        p3_validate(contributions)
    }

    pub fn p4_detect_pub(&self, valid: &[Contribution], intent: &str) -> Vec<ConflictSet> {
        self.p4_detect(valid, intent)
    }

    pub fn p5_select_pub(&self, conflicts: &mut [ConflictSet], valid: &[Contribution], roster: &[AgentPersonality], topic: &Topic) {
        let cal = calibration_map(roster, valid);
        let criteria: Vec<String> = topic.criteria.iter().map(|c| c.to_string()).collect();
        self.p5_select(conflicts, valid, &cal, &criteria, None)
    }

    /// P6 for instrumentation paths that ran P4/P5 by hand: seals
    /// `valid` (already canonical from `p3_validate_pub`) so the
    /// certificate references the same root hash `compile()` would.
    pub fn p6_commit_pub(&self, valid: Vec<Contribution>, conflicts: Vec<ConflictSet>, roster: &[AgentPersonality], time_us: u64, topic: &Topic) -> CompilationResult {
        let sealed = self.seal(topic.goal, &topic.criteria, roster, &valid);
        let mut r = self.p6_partition(&sealed, conflicts);
        r.ees = compute_ees(roster);
        r.time_us = time_us;
        r
    }

    // ── P1: Intent Normalization ────────────────────────────

    fn p1_normalize<'a>(&self, topic: &'a Topic) -> (&'a str, &'a [&'a str], &'a [&'a str]) {
        (topic.goal, &topic.constraints, &topic.criteria)
    }

    // ── P2: Lowering ────────────────────────────────────────

    fn p2_lower(
        &self,
        roster: &[AgentPersonality],
        topic: &Topic,
        rng: &mut ChaCha8Rng,
    ) -> Vec<Contribution> {
        let mut all_claims = self.p2_lower_legacy_ids_pub(roster, topic, rng);
        assign_content_ids(&mut all_claims);
        all_claims
    }

    // ── P4: Conflict Detection ──────────────────────────────

    fn p4_detect(&self, valid: &[Contribution], intent: &str) -> Vec<ConflictSet> {
        // Group non-CRITIQUE contributions by value_key() for redundancy
        let mut exact_groups: HashMap<(String, String, String, Polarity), Vec<usize>> =
            HashMap::new();
        // Group non-CRITIQUE by arity-aware slot key for contradictions:
        //   FUNCTIONAL     → (s, p):    distinct objects compete
        //   NON_FUNCTIONAL → (s, p, o): only AFFIRM vs NEGATE competes,
        //   unless o is in an exclusivity group → (s, p, g): group members compete
        let mut sp_groups: HashMap<SlotKey, Vec<usize>> = HashMap::new();

        for (idx, c) in valid.iter().enumerate() {
            if c.kind == ContributionKind::Critique {
                continue;
            }
            // §6.4: Only contributions with lowering_confidence ≥ MEDIUM
            // participate in triple-based contradiction detection.
            if c.lowering_confidence == LoweringConfidence::Low {
                continue;
            }
            let triple = c.canonical_form.as_ref().unwrap();
            let vk = triple.value_key();
            exact_groups.entry(vk).or_default().push(idx);
            sp_groups.entry(self.slot_key_of(triple)).or_default().push(idx);
        }

        let mut conflicts = Vec::new();
        let mut seen_in_contradiction: HashSet<usize> = HashSet::new();

        // Contradictions: same slot but different (object, polarity) tuples.
        // For non-functional slots the object is fixed by the key, so this
        // only fires on AFFIRM vs NEGATE of the same (s, p, o).
        // Sort keys for deterministic ordering
        let mut sp_keys: Vec<SlotKey> = sp_groups.keys().cloned().collect();
        sp_keys.sort();

        for skey in &sp_keys {
            let members = &sp_groups[skey];
            let key = (skey.subject.clone(), skey.predicate.clone());
            // Collect distinct (object, polarity) pairs
            let mut obj_pol: HashMap<(String, Polarity), Vec<usize>> = HashMap::new();
            for &idx in members {
                let triple = valid[idx].canonical_form.as_ref().unwrap();
                let op = (normalize_object(&triple.object), triple.polarity);
                obj_pol.entry(op).or_default().push(idx);
            }

            if obj_pol.len() > 1 {
                {
                    let mut scores = HashMap::new();
                    for &idx in members {
                        scores.insert(idx, ScoreBreakdown {
                            ev: 0.0, conf: 0.0, cs: 0.0,
                            rec: 0.0, ca: 0.0, raw: 0.0,
                            lf: 0.0, final_score: 0.0,
                        });
                    }
                    conflicts.push(ConflictSet {
                        typ: ConflictType::Contradiction,
                        triple_key: key.clone(),
                        slot_key: skey.clone(),
                        slot_id: Some(ClaimSlotId::from_slot_key(skey, intent)),
                        contribution_ids: members.clone(),
                        winner_idx: None,
                        scores,
                        in_deadband: false,
                        schulze_winner: None,
                        gate: None,
                    });
                    for &idx in members {
                        seen_in_contradiction.insert(idx);
                    }
                }
            }
        }

        // Redundancies: exact same triple from multiple agents
        let mut exact_keys: Vec<_> = exact_groups.keys().cloned().collect();
        exact_keys.sort_by(|a, b| {
            a.0.cmp(&b.0)
                .then(a.1.cmp(&b.1))
                .then(a.2.cmp(&b.2))
        });

        for key in &exact_keys {
            let members = &exact_groups[key];
            if members.len() > 1 {
                // Skip if any member is already in a contradiction
                if members.iter().any(|idx| seen_in_contradiction.contains(idx)) {
                    continue;
                }
                let mut scores = HashMap::new();
                for &idx in members {
                    scores.insert(idx, ScoreBreakdown {
                        ev: 0.0, conf: 0.0, cs: 0.0,
                        rec: 0.0, ca: 0.0, raw: 0.0,
                        lf: 0.0, final_score: 0.0,
                    });
                }
                let tk = (key.0.clone(), key.1.clone());
                let skey = self.slot_key_of(valid[members[0]].canonical_form.as_ref().unwrap());
                let sid = ClaimSlotId::from_slot_key(&skey, intent);
                conflicts.push(ConflictSet {
                    typ: ConflictType::Redundancy,
                    triple_key: tk,
                    slot_key: skey,
                    slot_id: Some(sid),
                    contribution_ids: members.clone(),
                    winner_idx: None,
                    scores,
                    in_deadband: false,
                    schulze_winner: None,
                    gate: None,
                });
            }
        }

        conflicts
    }

    // ── P5: Score and Select ────────────────────────────────

    fn p5_select(
        &self,
        conflicts: &mut [ConflictSet],
        valid: &[Contribution],
        agent_map: &BTreeMap<String, f64>,
        criteria: &[String],
        store: Option<&EvidenceStore>,
    ) {
        // Evidence policy context: (policy, sealed store or empty).
        let empty_store = EvidenceStore::default();
        let ev_ctx = self.evidence.as_ref().map(|p| (p, store.unwrap_or(&empty_store)));

        // ── 1c: Cross-reference bonus ──────────────────────────
        // Map evidence sources → set of citing agent_ids (under the
        // evidence policy: xref keys of eligible citers, spec §3.2)
        let mut source_citers: HashMap<String, HashSet<String>> = HashMap::new();
        if let Some((pol, st)) = ev_ctx {
            source_citers = evidence::citer_map(valid, st, pol);
        } else {
            for c in valid.iter() {
                for e in &c.evidence {
                    source_citers
                        .entry(e.source.to_lowercase())
                        .or_default()
                        .insert(c.agent_id.clone());
                }
            }
        }

        // ── 1e: Critique rate limiting & authentication ────────
        // Build set of agents that have at least one assertion
        let agent_has_assertion: HashSet<String> = valid
            .iter()
            .filter(|c| c.kind == ContributionKind::Assertion)
            .map(|c| c.agent_id.clone())
            .collect();

        // Build critique severity index with rate limiting
        // Keyed by object-level slot: a critique of (s, p, o) on a non-functional
        // predicate only affects that object, not sibling or exclusive values.
        let mut critique_severity: HashMap<SlotKey, f64> = HashMap::new();
        // Track per-agent per-key critique counts for rate limiting
        let mut agent_critique_count: HashMap<(String, SlotKey), usize> = HashMap::new();

        for c in valid.iter() {
            if c.kind == ContributionKind::Critique {
                if let Some(ref triple) = c.canonical_form {
                    if triple.polarity == Polarity::Negate {
                        // Skip critiques from agents with zero assertions
                        if !agent_has_assertion.contains(&c.agent_id) {
                            continue;
                        }

                        let key = self.critique_key_of(triple);
                        let agent_key = (c.agent_id.clone(), key.clone());
                        let count = agent_critique_count.entry(agent_key).or_insert(0);

                        // Rate limit: cap critiques per agent per key
                        if *count >= self.hardening.max_critiques_per_agent {
                            continue;
                        }
                        *count += 1;

                        // Halve severity of critiques with only Reasoning evidence
                        let has_substantive_evidence = c.evidence.iter().any(|e| {
                            e.typ != EvidenceType::Reasoning
                        });
                        let severity = if has_substantive_evidence { 1.0 } else { 0.5 };

                        *critique_severity.entry(key).or_insert(0.0) += severity;
                    }
                }
            }
        }

        let w = &self.weights;

        for cs in conflicts.iter_mut() {
            // Pre-compute recency ranks once per conflict set: O(M log M) instead of O(M²).
            // Ranked by recorded arrival `seq` (ties by canonical index).
            let mut seq_pairs: Vec<(usize, u64)> = cs
                .contribution_ids
                .iter()
                .map(|&idx| (idx, valid[idx].seq))
                .collect();
            seq_pairs.sort_by_key(|&(idx, seq)| (seq, idx));
            let denom = (seq_pairs.len() as isize - 1).max(1) as f64;
            let recency_map: HashMap<usize, f64> = seq_pairs
                .iter()
                .enumerate()
                .map(|(rank, &(idx, _))| (idx, rank as f64 / denom))
                .collect();

            for &idx in &cs.contribution_ids {
                let c = &valid[idx];
                let cal = agent_map.get(&c.agent_id).copied().unwrap_or(0.5);

                let ev = self.score_evidence_with_xref(c, &source_citers, ev_ctx);
                let conf = self.score_confidence(c, cal);
                let cs_score = self.score_critique_survival_indexed(c, &critique_severity);
                let rec = recency_map.get(&idx).copied().unwrap_or(0.0);
                let ca = self.score_constraint_alignment(c, criteria);

                let raw = w[0] * ev + w[1] * conf + w[2] * cs_score + w[3] * rec + w[4] * ca;
                let lf = c.lowering_factor();
                let final_score = raw * lf;

                cs.scores.insert(
                    idx,
                    ScoreBreakdown { ev, conf, cs: cs_score, rec, ca, raw, lf, final_score },
                );
            }

            // Verified-overturn gate (contradiction slots only; `gate`).
            if cs.typ == ConflictType::Contradiction
                && let Some((pol, st)) = ev_ctx
                && pol.overturn_gate == evidence::OverturnGate::Verified {
                crate::gate::gated_select(self, cs, valid, st, pol);
                continue;
            }
            self.select_slot(cs, valid);
        }
    }

    /// P5 selection over the members of `cs` (scores already filled in):
    /// argmax of the quantized score, deadband on the top-2 gap, Schulze
    /// over the deadband candidates (when `tiebreak = schulze`), residual
    /// ties by `tiebreak_order`; at value level in value mode. Sets
    /// `winner_idx`, `in_deadband`, `schulze_winner`. Only the members in
    /// `cs.contribution_ids` / `cs.scores` take part, so the gate can run
    /// it on a restricted copy of the slot.
    pub(crate) fn select_slot(&self, cs: &mut ConflictSet, valid: &[Contribution]) {
        cs.in_deadband = false;
        cs.schulze_winner = None;
        if let CandidateMode::Value { aggregate } = self.candidate_mode {
            crate::value_mode::select(self, cs, valid, aggregate);
            return;
        }
        // §6.1 purity constraint #5: integer-scaled comparison; first max
        // in canonical member order.
        let mut best_idx: Option<usize> = None;
        let mut best_score_q: i64 = i64::MIN;
        for &idx in &cs.contribution_ids {
            let score_q = quantize(cs.scores[&idx].final_score);
            if score_q > best_score_q {
                best_score_q = score_q;
                best_idx = Some(idx);
            }
        }
        if self.tiebreak_order == TieOrder::Id {
            // Top quantized score; exact ties by smallest id (ids are
            // unique after P3 dedup), independent of `seq`.
            best_idx = cs.contribution_ids.iter().copied().max_by(|&a, &b| {
                quantize(cs.scores[&a].final_score).cmp(&quantize(cs.scores[&b].final_score))
                    .then_with(|| valid[b].id.cmp(&valid[a].id))
            });
        }
        cs.winner_idx = best_idx;

        // Deadband detection: if top-2 gap < threshold (integer-scaled),
        // flag for Election Leader escalation (Schulze path).
        let mut all_scores_q: Vec<i64> = cs.scores.values().map(|s| quantize(s.final_score)).collect();
        all_scores_q.sort_by(|a, b| b.cmp(a));
        if all_scores_q.len() >= 2 {
            let gap = all_scores_q[0] - all_scores_q[1];
            if gap < self.deadband_threshold {
                cs.in_deadband = true;
                // 2a: Schulze voting among the deadband candidates only.
                // Under `score_then_canonical` the raw-score leader
                // (first max in canonical order, computed above) stays.
                if self.tiebreak == TieBreak::Schulze
                    && let Some(schulze_idx) = self.schulze_select_in(cs, valid) {
                    cs.schulze_winner = Some(schulze_idx);
                    cs.winner_idx = Some(schulze_idx);
                }
            }
        }
    }

    // ── Scoring helpers ─────────────────────────────────────

    /// Evidence scoring with cross-reference bonus (1c).
    /// Sources cited by multiple independent agents get a multiplier.
    fn score_evidence_with_xref(
        &self,
        c: &Contribution,
        source_citers: &HashMap<String, HashSet<String>>,
        ev_ctx: Option<(&EvidencePolicy, &EvidenceStore)>,
    ) -> f64 {
        if c.evidence.is_empty() {
            return 0.0;
        }
        if let Some((pol, store)) = ev_ctx {
            // Evidence policy (spec §3.2): ev = min(1, Σ w·t·q'·r'·s·x').
            let mut total = 0.0;
            for e in &c.evidence {
                let f = evidence::factors(e, c, store, pol);
                let base = e.weight * e.type_weight() * f.q * f.r * f.s;
                total += base * evidence::xref_multiplier(&f, source_citers);
            }
            return total.clamp(0.0, 1.0);
        }
        let mut total = 0.0;
        for e in &c.evidence {
            let sr = match e.typ {
                EvidenceType::Citation | EvidenceType::ToolResult | EvidenceType::Empirical => {
                    if e.reachable { 0.75 } else { 0.45 }
                }
                EvidenceType::Authority => 0.5,
                EvidenceType::Reasoning => 0.3,
            };
            let base = e.weight * e.type_weight() * e.source_quality() * sr;

            // Cross-reference multiplier: reward sources cited by multiple agents
            let n_citers = source_citers
                .get(&e.source.to_lowercase())
                .map(|s| s.len())
                .unwrap_or(1);
            let xref_mult = if n_citers >= 3 {
                1.2
            } else if n_citers >= 2 {
                1.1
            } else {
                0.9 // single-source penalty
            };

            total += base * xref_mult;
        }
        total.clamp(0.0, 1.0)
    }

    /// Legacy evidence scoring (without cross-reference), for use in contexts
    /// where the source_citers map is not available.
    fn score_evidence(&self, c: &Contribution) -> f64 {
        if c.evidence.is_empty() {
            return 0.0;
        }
        let mut total = 0.0;
        for e in &c.evidence {
            let sr = match e.typ {
                EvidenceType::Citation | EvidenceType::ToolResult | EvidenceType::Empirical => {
                    if e.reachable { 0.75 } else { 0.45 }
                }
                EvidenceType::Authority => 0.5,
                EvidenceType::Reasoning => 0.3,
            };
            total += e.weight * e.type_weight() * e.source_quality() * sr;
        }
        total.clamp(0.0, 1.0)
    }

    fn score_confidence(&self, c: &Contribution, calibration: f64) -> f64 {
        (c.confidence * calibration).min(1.0)
    }

    fn score_critique_survival_indexed(
        &self,
        c: &Contribution,
        critique_severity: &HashMap<SlotKey, f64>,
    ) -> f64 {
        let c_key = match &c.canonical_form {
            Some(t) => self.critique_key_of(t),
            None => return 1.0,
        };
        let severity_sum = critique_severity.get(&c_key).copied().unwrap_or(0.0);
        (1.0 - severity_sum / self.max_severity_budget).max(0.0)
    }

    /// 2b: Hardened constraint alignment scoring.
    /// Requires bigram matches (2+ consecutive words) instead of single-word
    /// matches, and uses canonical triple text instead of raw_text.
    fn score_constraint_alignment(&self, c: &Contribution, criteria: &[String]) -> f64 {
        if criteria.is_empty() {
            return 1.0;
        }

        // Use canonical triple text if available, falling back to raw_text
        let text = if let Some(ref triple) = c.canonical_form {
            format!("{} {} {}", triple.subject, triple.predicate, triple.object).to_lowercase()
        } else {
            c.raw_text.to_lowercase()
        };
        // Also check raw_text for broader coverage
        let raw_lower = c.raw_text.to_lowercase();

        let matched = criteria
            .iter()
            .filter(|cr| {
                let words: Vec<&str> = cr.split_whitespace().collect();
                if words.len() >= 2 {
                    // Require at least one bigram match (2 consecutive words)
                    let has_bigram = words.windows(2).any(|pair| {
                        let bigram = format!("{} {}", pair[0].to_lowercase(), pair[1].to_lowercase());
                        text.contains(&bigram) || raw_lower.contains(&bigram)
                    });
                    // Also accept if a single significant word (>4 chars) matches
                    let has_long_word = words.iter().any(|w| {
                        let wl = w.to_lowercase();
                        wl.len() > 4 && (text.contains(&wl) || raw_lower.contains(&wl))
                    });
                    has_bigram || has_long_word
                } else {
                    // Single-word criterion: require exact match of the word
                    words.iter().any(|w| {
                        let wl = w.to_lowercase();
                        text.contains(&wl) || raw_lower.contains(&wl)
                    })
                }
            })
            .count();
        matched as f64 / criteria.len() as f64
    }

    // ── 2a: Schulze voting for deadband conflicts ──────────

    /// Schulze candidate set: members whose quantized final score is
    /// strictly within `deadband_threshold` (absolute, integer-scaled) of
    /// the top score, in canonical member order. A member outside the
    /// deadband can never be returned by `schulze_select`.
    pub fn deadband_candidates(&self, cs: &ConflictSet) -> Vec<usize> {
        let top = cs.scores.values().map(|s| quantize(s.final_score)).max();
        let Some(top) = top else { return Vec::new() };
        cs.contribution_ids
            .iter()
            .copied()
            .filter(|idx| {
                cs.scores.get(idx)
                    .map(|s| top - quantize(s.final_score) < self.deadband_threshold)
                    .unwrap_or(false)
            })
            .collect()
    }

    /// Schulze winner over the deadband candidates of `cs`, scanned in
    /// canonical member order.
    #[cfg(test)]
    fn schulze_select(&self, cs: &ConflictSet) -> Option<usize> {
        self.schulze_over(cs, &self.deadband_candidates(cs))
    }

    /// Schulze winner over the deadband candidates of `cs`, scanned in
    /// `tiebreak_order` (canonical member order, or by id).
    fn schulze_select_in(&self, cs: &ConflictSet, valid: &[Contribution]) -> Option<usize> {
        let mut cands = self.deadband_candidates(cs);
        if self.tiebreak_order == TieOrder::Id {
            cands.sort_by(|&a, &b| valid[a].id.cmp(&valid[b].id));
        }
        self.schulze_over(cs, &cands)
    }

    /// Compute Schulze winner among `candidates` from the scoring
    /// dimensions selected by `schulze_dims`. Returns the index of the
    /// Schulze winner within the conflict set. Exact replacement of the
    /// original Floyd–Warshall implementation (`schulze_over_reference`,
    /// identical winner including ties); see `schulze_scan`.
    fn schulze_over(&self, cs: &ConflictSet, candidates: &[usize]) -> Option<usize> {
        if candidates.len() < 2 {
            return candidates.first().copied();
        }
        // Quantize once per candidate (not once per pair).
        let dims: Vec<[i64; 5]> = candidates
            .iter()
            .map(|c| {
                let s = &cs.scores[c];
                [quantize(s.ev), quantize(s.conf), quantize(s.cs), quantize(s.rec), quantize(s.ca)]
            })
            .collect();
        let best = schulze_scan(&dims, self.schulze_dim_epsilon, self.schulze_dims, None);
        Some(candidates[best])
    }

    /// Original O(n³) Floyd–Warshall implementation, kept verbatim as the
    /// test oracle for `schulze_over` (all five dimensions; see
    /// `schulze_equivalence_tests`).
    #[cfg(test)]
    fn schulze_over_reference(&self, cs: &ConflictSet, candidates: &[usize]) -> Option<usize> {
        let n = candidates.len();
        if n < 2 {
            return candidates.first().copied();
        }

        // Build pairwise preference matrix from the 5 scoring dimensions.
        // d[i][j] = number of dimensions where candidate i beats candidate j.
        let mut d = vec![vec![0i64; n]; n];

        for i in 0..n {
            for j in 0..n {
                if i == j { continue; }
                let si = &cs.scores[&candidates[i]];
                let sj = &cs.scores[&candidates[j]];

                let dims_i: [i64; 5] = [quantize(si.ev), quantize(si.conf), quantize(si.cs), quantize(si.rec), quantize(si.ca)];
                let dims_j: [i64; 5] = [quantize(sj.ev), quantize(sj.conf), quantize(sj.cs), quantize(sj.rec), quantize(sj.ca)];

                let mut wins = 0i64;
                for k in 0..5 {
                    if dims_i[k] > dims_j[k] + self.schulze_dim_epsilon {
                        wins += 1;
                    }
                }
                d[i][j] = wins;
            }
        }

        // Schulze widest-path: p[i][j] = strength of strongest path from i to j
        let mut p = vec![vec![0i64; n]; n];
        for i in 0..n {
            for j in 0..n {
                if i != j {
                    p[i][j] = d[i][j];
                }
            }
        }

        for k in 0..n {
            for i in 0..n {
                if i == k { continue; }
                for j in 0..n {
                    if j == i || j == k { continue; }
                    let through_k = p[i][k].min(p[k][j]);
                    if through_k > p[i][j] {
                        p[i][j] = through_k;
                    }
                }
            }
        }

        // Find the candidate that beats all others via widest path
        let mut best = 0;
        for i in 1..n {
            if p[i][best] > p[best][i] {
                best = i;
            }
        }

        Some(candidates[best])
    }

    // ── 3c: Behavioral EES ─────────────────────────────────

    /// Compute pairwise output similarity (Jaccard over triple sets)
    /// for behavioral EES estimation. Returns (behavioral_ees, warnings).
    pub fn behavioral_ees(
        &self,
        valid: &[Contribution],
        roster: &[AgentPersonality],
    ) -> (f64, Vec<String>) {
        let n = roster.len();
        if n <= 1 {
            return (n as f64, vec![]);
        }

        // Build per-agent triple sets
        let mut agent_triples: HashMap<String, HashSet<(String, String, String)>> = HashMap::new();
        for c in valid.iter() {
            if let Some(ref triple) = c.canonical_form {
                agent_triples
                    .entry(c.agent_id.clone())
                    .or_default()
                    .insert((
                        triple.subject.to_lowercase(),
                        triple.predicate.to_lowercase(),
                        triple.object.to_lowercase(),
                    ));
            }
        }

        let agent_ids: Vec<String> = roster
            .iter()
            .map(|a| a.name.to_lowercase().replace(' ', "_"))
            .collect();

        // Compute pairwise Jaccard similarity
        let mut total_sim = 0.0;
        let mut pair_count = 0usize;
        let empty = HashSet::new();

        for i in 0..n {
            for j in (i + 1)..n {
                let ti = agent_triples.get(&agent_ids[i]).unwrap_or(&empty);
                let tj = agent_triples.get(&agent_ids[j]).unwrap_or(&empty);
                let inter = ti.intersection(tj).count();
                let union = ti.union(tj).count();
                let sim = if union > 0 { inter as f64 / union as f64 } else { 0.0 };
                total_sim += sim;
                pair_count += 1;
            }
        }

        let avg_sim = if pair_count > 0 { total_sim / pair_count as f64 } else { 0.0 };
        let behavioral_ees = n as f64 / (1.0 + (n as f64 - 1.0) * avg_sim);

        // Compare with family-based EES and warn if divergent
        let family_ees = compute_ees(roster);
        let mut warnings = vec![];
        if behavioral_ees < family_ees * 0.7 {
            warnings.push(format!(
                "Behavioral EES ({:.1}) << Family EES ({:.1}): agents from different families may be correlated",
                behavioral_ees, family_ees
            ));
        }

        (behavioral_ees, warnings)
    }

    // ── P6: Commit ──────────────────────────────────────────

    fn p6_partition(
        &self,
        sealed: &SealedArtifactSet,
        conflicts: Vec<ConflictSet>,
    ) -> CompilationResult {
        let valid = &sealed.contributions;
        let mut admitted: Vec<usize> = Vec::new();
        let mut rejected: Vec<usize> = Vec::new();

        // Collect all indices that belong to any conflict set
        let mut conflicting: HashSet<usize> = HashSet::new();

        for cs in &conflicts {
            for &idx in &cs.contribution_ids {
                conflicting.insert(idx);
            }
            if let Some(winner) = cs.winner_idx {
                admitted.push(winner);
                for &idx in &cs.contribution_ids {
                    if idx != winner {
                        rejected.push(idx);
                    }
                }
            }
        }

        // Non-conflicting, non-critique assertions are admitted,
        // but LOW-confidence contributions are rejected: their triples
        // are too unreliable for either conflict detection or admission.
        for (idx, c) in valid.iter().enumerate() {
            if !conflicting.contains(&idx) && c.kind != ContributionKind::Critique {
                if c.lowering_confidence == LoweringConfidence::Low {
                    rejected.push(idx);
                } else {
                    admitted.push(idx);
                }
            }
        }

        // Deduplicate (shouldn't be needed but defensive)
        admitted.sort_unstable();
        admitted.dedup();
        rejected.sort_unstable();
        rejected.dedup();

        // ── 1d: Singleton corroboration warnings ───────────────
        // Build map: (subject, predicate) → set of asserting agent_ids
        let mut sp_agents: HashMap<(String, String), HashSet<String>> = HashMap::new();
        for c in valid.iter() {
            if c.kind == ContributionKind::Critique {
                continue;
            }
            if let Some(ref triple) = c.canonical_form {
                sp_agents
                    .entry(triple.key())
                    .or_default()
                    .insert(c.agent_id.clone());
            }
        }

        let mut singleton_warnings: Vec<usize> = Vec::new();
        for &idx in &admitted {
            let c = &valid[idx];
            if let Some(ref triple) = c.canonical_form {
                let key = triple.key();
                let n_agents = sp_agents.get(&key).map(|s| s.len()).unwrap_or(0);
                if n_agents < self.hardening.min_corroboration {
                    singleton_warnings.push(idx);
                }
            }
        }
        singleton_warnings.sort_unstable();

        // Certificate: sha256(sealed root hash ‖ policy hash ‖ admitted
        // contribution ids), each as its hex/id string bytes, truncated
        // to 64 bits. Binds the outcome to both the inputs and the policy.
        let mut hasher = Sha256::new();
        let policy_hash = self.policy_hash();
        hasher.update(sealed.root_hash.as_bytes());
        hasher.update(policy_hash.as_bytes());
        for &idx in &admitted {
            hasher.update(valid[idx].id.as_bytes());
        }
        let hash = hasher.finalize();
        let certificate = hash
            .iter()
            .take(8)
            .map(|b| format!("{b:02x}"))
            .collect::<String>();

        CompilationResult {
            admitted,
            rejected,
            conflicts,
            ees: 0.0,
            time_us: 0,
            certificate,
            policy_hash,
            artifact_set: sealed.header(),
            all_contributions: valid.clone(),
            singleton_warnings,
        }
    }
}

// ── Ingestion & P3 ──────────────────────────────────────────

// ── Schulze winner: exact bounded-strength algorithm ──────

/// Pairwise strengths over the active Schulze dimensions, without an
/// n×n matrix: `d(i, j)` = number of active dimensions k with
/// `v_k(i) > v_k(j) + epsilon` (the original comparison, verbatim).
struct SchulzeDims {
    n: usize,
    /// Active dimensions only, row-major `n × a`.
    vals: Vec<i64>,
    a: usize,
    eps: i64,
}

impl SchulzeDims {
    fn new(dims: &[[i64; 5]], eps: i64, mask: u8) -> Self {
        let n = dims.len();
        // A dimension is active iff it is selected by `mask` and some pair
        // i != j satisfies v(i) > v(j) + eps. With n >= 2 that is exactly
        // max - min > eps (if max and min are attained only by one member,
        // all values are equal and then 0 > eps makes any pair qualify).
        let active: Vec<usize> = (0..5)
            .filter(|&k| mask & (1 << k) != 0)
            .filter(|&k| {
                let (lo, hi) = dims.iter().fold((i64::MAX, i64::MIN), |(lo, hi), v| (lo.min(v[k]), hi.max(v[k])));
                n >= 2 && (hi as i128) - (lo as i128) > eps as i128
            })
            .collect();
        let a = active.len();
        let mut vals = Vec::with_capacity(n * a);
        for v in dims {
            for &k in &active {
                vals.push(v[k]);
            }
        }
        Self { n, vals, a, eps }
    }

    /// Maximum possible pairwise strength.
    fn max_strength(&self) -> u8 {
        self.a as u8
    }

    #[inline]
    fn d(&self, i: usize, j: usize) -> u8 {
        let a = self.a;
        let (vi, vj) = (&self.vals[i * a..i * a + a], &self.vals[j * a..j * a + a]);
        let mut w = 0u8;
        for t in 0..a {
            if vi[t] > vj[t] + self.eps {
                w += 1;
            }
        }
        w
    }

    /// Single-source (forward: p[src][·]) or single-sink (backward:
    /// p[·][src]) widest-path strengths, written into `out` (`out[src]` is
    /// unspecified). Bucket-queue Dijkstra over strengths 0..=D: every
    /// node is settled once at its final label, in non-increasing label
    /// order, and its row (or column) is scanned once: O(n² · a).
    fn widest(&self, src: usize, forward: bool, out: &mut [u8], settled: &mut [bool], buckets: &mut [Vec<u32>]) {
        let top = self.max_strength() as usize + 1; // sentinel label of src
        out.iter_mut().for_each(|x| *x = 0);
        settled.iter_mut().for_each(|x| *x = false);
        buckets.iter_mut().for_each(|b| b.clear());
        out[src] = top as u8;
        buckets[top].push(src as u32);
        for level in (1..=top).rev() {
            while let Some(v) = buckets[level].pop() {
                let v = v as usize;
                if settled[v] || out[v] as usize != level {
                    continue;
                }
                settled[v] = true;
                let a = self.a;
                let vv = &self.vals[v * a..v * a + a];
                for (w, vw) in self.vals.chunks_exact(a).enumerate() {
                    if settled[w] {
                        continue;
                    }
                    // d(v, w) forward, d(w, v) backward; same comparison as `d`.
                    let mut s = 0u8;
                    for t in 0..a {
                        let beats = if forward { vv[t] > vw[t] + self.eps } else { vw[t] > vv[t] + self.eps };
                        s += beats as u8;
                    }
                    let cand = s.min(level as u8);
                    if cand > out[w] {
                        out[w] = cand;
                        buckets[cand as usize].push(w as u32);
                    }
                }
            }
        }
    }

    /// All-pairs closure, one reachability bitset matrix per strength
    /// level k = 1..=D (edges with d >= k), by bitset Warshall:
    /// O(n² · a + D · n³ / 64). `p(i, j)` = number of levels at which j is
    /// reachable from i (levels are nested, so this is the widest path).
    fn closure(&self) -> SchulzeClosure {
        let n = self.n;
        let words = n.div_ceil(64);
        let levels = self.max_strength() as usize;
        let mut reach = vec![vec![0u64; n * words]; levels];
        for i in 0..n {
            for j in 0..n {
                if i == j {
                    continue;
                }
                let s = self.d(i, j) as usize;
                for r in reach.iter_mut().take(s) {
                    r[i * words + j / 64] |= 1u64 << (j % 64);
                }
            }
        }
        for r in reach.iter_mut() {
            for m in 0..n {
                let (mw, mb) = (m / 64, 1u64 << (m % 64));
                let row_m: Vec<u64> = r[m * words..(m + 1) * words].to_vec();
                for i in 0..n {
                    if i != m && r[i * words + mw] & mb != 0 {
                        let row_i = &mut r[i * words..(i + 1) * words];
                        for (x, y) in row_i.iter_mut().zip(&row_m) {
                            *x |= *y;
                        }
                    }
                }
            }
        }
        SchulzeClosure { words, reach }
    }
}

struct SchulzeClosure {
    words: usize,
    reach: Vec<Vec<u64>>,
}

impl SchulzeClosure {
    fn p(&self, i: usize, j: usize) -> u8 {
        let (w, b) = (i * self.words + j / 64, 1u64 << (j % 64));
        self.reach.iter().filter(|r| r[w] & b != 0).count() as u8
    }
}

/// Index (into `dims`) of the Schulze winner the original implementation
/// returns: widest-path strengths p over pairwise strengths d (number of
/// selected dimensions on which i beats j by more than `eps`), then the
/// sequential scan `best = 0; for i in 1..n { if p[i][best] > p[best][i]
/// { best = i } }` in the given (canonical) order.
///
/// Exactness: d is an integer in 0..=D (D = number of active
/// dimensions, <= 5), so p[i][j] >= k iff j is reachable from i using
/// edges with d >= k; widest paths are computed exactly, either per
/// source (lazy) or for all pairs (bitset closure). The scan only reads
/// p[i][best] and p[best][i], so the lazy path computes one forward and
/// one backward widest-path tree per distinct leader.
///
/// Complexity (a = active dimensions, c = leader changes in the scan):
/// lazy O((c + 1) · n² · a) time, O(n) memory. If c reaches the switch
/// limit (default max(4, n/128) leaders, or `lazy_limit`), the scan restarts
/// on the all-pairs bitset closure: O(n² · a + D · n³ / 64) time and
/// O(D · n² / 64) words. Worst case is therefore bounded by
/// O(n² · a · n/128 + D · n³ / 64), i.e. still cubic but with a constant
/// ~10–70x below the original Floyd–Warshall (measured: adversarial
/// leader chain n = 2000, 0.15 s vs 10.5 s; `schulze_timing` test).
pub(crate) fn schulze_scan(dims: &[[i64; 5]], eps: i64, mask: u8, lazy_limit: Option<usize>) -> usize {
    let n = dims.len();
    if n < 2 {
        return 0;
    }
    let sd = SchulzeDims::new(dims, eps, mask);
    if sd.a == 0 {
        return 0; // all strengths are 0: the scan never moves
    }
    // One lazy step (two trees) costs ~2·n²·a comparisons; the closure
    // ~D·n³/64 word operations with D = a, so switch after ~n/128 steps.
    let limit = lazy_limit.unwrap_or_else(|| (n / 128).max(4));
    let mut fwd = vec![0u8; n]; // p[best][·]
    let mut bwd = vec![0u8; n]; // p[·][best]
    let mut settled = vec![false; n];
    let mut buckets: Vec<Vec<u32>> = vec![Vec::new(); sd.max_strength() as usize + 2];
    let mut best = 0usize;
    let mut computed_for = usize::MAX;
    let mut trees = 0usize;
    for i in 1..n {
        if computed_for != best {
            if trees >= limit {
                return schulze_scan_closure(&sd);
            }
            sd.widest(best, true, &mut fwd, &mut settled, &mut buckets);
            sd.widest(best, false, &mut bwd, &mut settled, &mut buckets);
            computed_for = best;
            trees += 1;
        }
        if bwd[i] > fwd[i] {
            best = i;
        }
    }
    best
}

fn schulze_scan_closure(sd: &SchulzeDims) -> usize {
    let c = sd.closure();
    let mut best = 0;
    for i in 1..sd.n {
        if c.p(i, best) > c.p(best, i) {
            best = i;
        }
    }
    best
}

/// Record arrival sequence numbers. For the synthetic agents, arrival
/// order is the existing seed-deterministic timestamp order (ties broken
/// by generation order), so recency ranks are unchanged from the
/// timestamp-based scoring this replaces. After this point scoring reads
/// only `seq`.
pub fn assign_arrival_seq(contributions: &mut [Contribution]) {
    let mut order: Vec<usize> = (0..contributions.len()).collect();
    order.sort_by(|&a, &b| {
        contributions[a].timestamp
            .partial_cmp(&contributions[b].timestamp)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(a.cmp(&b))
    });
    for (rank, idx) in order.into_iter().enumerate() {
        contributions[idx].seq = rank as u64;
    }
}

/// Why P3 dropped a contribution (audit record; not sealed).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct P3Rejection {
    pub id: String,
    pub agent_id: String,
    pub seq: u64,
    /// `synthesis_out_of_scope` | `no_canonical_form` | `duplicate_id`.
    pub reason: String,
}

pub const P3_SYNTHESIS: &str = "synthesis_out_of_scope";
pub const P3_NO_CANONICAL_FORM: &str = "no_canonical_form";
pub const P3_DUPLICATE_ID: &str = "duplicate_id";

/// P3: drop contributions without a canonical form, put the rest in
/// canonical order (ascending seq, then id), and dedup by id keeping the
/// earliest arrival. The output is independent of input vector order.
pub fn p3_validate(contributions: &[Contribution]) -> Vec<Contribution> {
    p3_validate_audited(contributions).0
}

/// P3 with its audit record. SYNTHESIS contributions are rejected with
/// reason `synthesis_out_of_scope`: the reducer selects among asserted
/// claims and has no semantics for a synthesis, so none reaches the
/// sealed set and P6 can only admit ASSERTION ids (P6 never admits
/// CRITIQUEs). Rejections are sorted, so the audit record is also
/// independent of input order.
pub fn p3_validate_audited(contributions: &[Contribution]) -> (Vec<Contribution>, Vec<P3Rejection>) {
    let rej = |c: &Contribution, reason: &str| P3Rejection {
        id: c.id.clone(), agent_id: c.agent_id.clone(), seq: c.seq, reason: reason.to_string(),
    };
    let mut rejected = Vec::new();
    let mut valid: Vec<Contribution> = Vec::new();
    for c in contributions {
        if c.kind == ContributionKind::Synthesis {
            rejected.push(rej(c, P3_SYNTHESIS));
        } else if c.canonical_form.is_none() {
            rejected.push(rej(c, P3_NO_CANONICAL_FORM));
        } else {
            valid.push(c.clone());
        }
    }
    valid.sort_by(|a, b| a.seq.cmp(&b.seq).then_with(|| a.id.cmp(&b.id)));
    let mut seen_ids: HashSet<String> = HashSet::new();
    valid.retain(|c| {
        let first = seen_ids.insert(c.id.clone());
        if !first { rejected.push(rej(c, P3_DUPLICATE_ID)); }
        first
    });
    rejected.sort();
    (valid, rejected)
}

/// agent_id → calibration for every roster agent.
pub fn roster_calibration(roster: &[AgentPersonality]) -> BTreeMap<String, f64> {
    roster
        .iter()
        .map(|a| (a.name.to_lowercase().replace(' ', "_"), a.calibration))
        .collect()
}

/// Calibration restricted to the agents of `valid`, with the reducer's
/// 0.5 default for agents outside the roster written in explicitly.
pub fn calibration_map(roster: &[AgentPersonality], valid: &[Contribution]) -> BTreeMap<String, f64> {
    restrict_calibration(&roster_calibration(roster), valid)
}

fn restrict_calibration(calibration: &BTreeMap<String, f64>, valid: &[Contribution]) -> BTreeMap<String, f64> {
    valid
        .iter()
        .map(|c| (c.agent_id.clone(), calibration.get(&c.agent_id).copied().unwrap_or(0.5)))
        .collect()
}

/// Validate and seal arbitrary contributions (used by `compile()` and by
/// `--reduce` for externally supplied claims).
pub fn seal_contributions(
    intent: &str,
    criteria: Vec<String>,
    calibration: &BTreeMap<String, f64>,
    contributions: &[Contribution],
) -> SealedArtifactSet {
    seal_inner(intent, criteria, calibration, contributions, None)
}

/// P3 + seal with an optional id scheme (hashed once). Does not check ids.
fn seal_inner(
    intent: &str,
    criteria: Vec<String>,
    calibration: &BTreeMap<String, f64>,
    contributions: &[Contribution],
    id_scheme: Option<&str>,
) -> SealedArtifactSet {
    let valid = p3_validate(contributions);
    let cal = restrict_calibration(calibration, &valid);
    SealedArtifactSet::new_with_id_scheme(intent, criteria, cal, valid, id_scheme)
}

/// `seal_contributions` plus evidence records (spec §3.3 hunk 5): after
/// P3, validate `store` against the valid contributions (ids, refs,
/// claims; dangling refs are an error, never silently unchecked) and
/// seal the store restricted to referenced records. With no store and no
/// refs, or no referenced records, the result is byte-identical to
/// `seal_contributions`.
pub fn seal_contributions_with_evidence(
    intent: &str,
    criteria: Vec<String>,
    calibration: &BTreeMap<String, f64>,
    contributions: &[Contribution],
    store: Option<&EvidenceStore>,
) -> Result<SealedArtifactSet, evidence::SealError> {
    let valid = p3_validate(contributions);
    let empty = EvidenceStore::default();
    let restricted = evidence::validate_store(&valid, store.unwrap_or(&empty))?;
    let cal = restrict_calibration(calibration, &valid);
    Ok(SealedArtifactSet::new(intent, criteria, cal, valid).with_evidence_store(Some(restricted)))
}

/// Why sealing externally supplied contributions failed.
#[derive(Debug, Clone, PartialEq)]
pub enum SealInputError {
    /// Content-addressed mode: a supplied id is not the content id of its
    /// payload (edited after the id was computed, or a foreign id scheme).
    ContentId { id: String, agent_id: String, expected: String },
    /// Evidence record validation failed (see `evidence::validate_store`).
    Evidence(evidence::SealError),
}

impl std::fmt::Display for SealInputError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SealInputError::ContentId { id, agent_id, expected } => write!(f,
                "contribution {id} (agent {agent_id}): supplied id is not its {} content id {expected}",
                crate::ir::CONTRIBUTION_ID_SCHEME),
            SealInputError::Evidence(e) => write!(f, "{e}"),
        }
    }
}

/// Seal with content-addressed ids (`bran-contribution-id/1`,
/// `bran-artifact/4`). Every supplied contribution, including ones P3
/// would drop, must carry `id == content_id(c)`; the first mismatch (in
/// canonical (seq, id) order) rejects the whole input. Ids are never
/// recomputed here. Otherwise as `seal_contributions_with_evidence`,
/// with `id_scheme` set (and root-hashed).
pub fn seal_contributions_content(
    intent: &str,
    criteria: Vec<String>,
    calibration: &BTreeMap<String, f64>,
    contributions: &[Contribution],
    store: Option<&EvidenceStore>,
) -> Result<SealedArtifactSet, SealInputError> {
    let mut order: Vec<&Contribution> = contributions.iter().collect();
    order.sort_by(|a, b| a.seq.cmp(&b.seq).then_with(|| a.id.cmp(&b.id)));
    for c in order {
        let expected = content_id(c);
        if c.id != expected {
            return Err(SealInputError::ContentId { id: c.id.clone(), agent_id: c.agent_id.clone(), expected });
        }
    }
    let valid = p3_validate(contributions);
    let empty = EvidenceStore::default();
    let restricted = evidence::validate_store(&valid, store.unwrap_or(&empty)).map_err(SealInputError::Evidence)?;
    let cal = restrict_calibration(calibration, &valid);
    let sealed = SealedArtifactSet::new_with_id_scheme(intent, criteria, cal, valid, Some(CONTRIBUTION_ID_SCHEME))
        .with_evidence_store(Some(restricted));
    debug_assert!(sealed.content_id_violations().is_empty());
    Ok(sealed)
}

// ── Output tuples (replay comparison & --reduce) ───────────

/// One resolved slot: the conflict set, its winner, and the quantized
/// scores that decided it. Ids are contribution ids, not indices.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Selection {
    pub slot: String,
    pub slot_id: Option<String>,
    #[serde(rename = "type")]
    pub typ: String,
    pub members: Vec<String>,
    pub winner: Option<String>,
    pub in_deadband: bool,
    pub schulze_winner: Option<String>,
    /// contribution id → quantized final score (integer, ×10,000).
    pub scores_q: BTreeMap<String, i64>,
    /// Verified-overturn gate trace (`evidence.overturn_gate = verified`);
    /// absent when ungated, so ungated outputs are unchanged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub gate: Option<crate::gate::GateOutput>,
}

/// Everything reduction outputs, keyed by ids so it is comparable across
/// processes. Replay must reproduce this exactly.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ReductionOutput {
    pub root_hash: String,
    pub policy_hash: String,
    pub certificate: String,
    pub admitted: Vec<String>,
    pub rejected: Vec<String>,
    pub selections: Vec<Selection>,
}

impl ReductionOutput {
    pub fn from_result(r: &CompilationResult) -> Self {
        let id = |i: usize| r.all_contributions[i].id.clone();
        let selections = r.conflicts.iter().map(|cs| Selection {
            slot: cs.slot_key.to_string(),
            slot_id: cs.slot_id.as_ref().map(|s| s.0.clone()),
            typ: cs.typ.to_string(),
            members: cs.contribution_ids.iter().map(|&i| id(i)).collect(),
            winner: cs.winner_idx.map(id),
            in_deadband: cs.in_deadband,
            schulze_winner: cs.schulze_winner.map(id),
            scores_q: cs.scores.iter().map(|(&i, sb)| (id(i), quantize(sb.final_score))).collect(),
            gate: cs.gate.as_ref().map(|t| crate::gate::GateOutput::from_trace(t, &r.all_contributions)),
        }).collect();
        Self {
            root_hash: r.artifact_set.root_hash.clone(),
            policy_hash: r.policy_hash.clone(),
            certificate: r.certificate.clone(),
            admitted: r.admitted.iter().map(|&i| id(i)).collect(),
            rejected: r.rejected.iter().map(|&i| id(i)).collect(),
            selections,
        }
    }
}

/// Why one id in `ReductionOutput::rejected` was not admitted
/// (`--reduce --explain-rejected`; derived from the outputs and the sealed
/// set, never hashed or sealed).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RejectionReason {
    pub id: String,
    pub agent_id: String,
    /// `lost_slot` (outscored in a contradiction slot) |
    /// `same_value_as_winner` (same normalized object and polarity as the
    /// slot winner: a redundant copy, or a duplicate inside a
    /// contradiction slot) | `low_lowering_confidence` (LOW lowering
    /// confidence, not in any slot: never admitted) | `not_admitted`.
    pub reason: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub slot_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub winner: Option<String>,
    /// How the slot was decided: `gate` (not a candidate of the deciding
    /// stage of the verified-overturn gate), `score` (higher quantized score),
    /// `schulze` (deadband, Schulze tie-break), `tiebreak_order` (equal
    /// quantized score, broken by `tiebreak_order`).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub decided_by: Option<String>,
    /// Quantized final scores of this contribution and of the winner.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub score_q: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub winner_score_q: Option<i64>,
}

impl ReductionOutput {
    /// One `RejectionReason` per id in `self.rejected`, in that order.
    pub fn rejection_reasons(&self, sealed: &SealedArtifactSet) -> Vec<RejectionReason> {
        let by_id: HashMap<&str, &Contribution> = sealed.contributions.iter().map(|c| (c.id.as_str(), c)).collect();
        let same_value = |a: &str, b: &str| -> bool {
            match (by_id.get(a).and_then(|c| c.canonical_form.as_ref()), by_id.get(b).and_then(|c| c.canonical_form.as_ref())) {
                (Some(x), Some(y)) => x.polarity == y.polarity && normalize_object(&x.object) == normalize_object(&y.object),
                _ => false,
            }
        };
        self.rejected.iter().map(|rid| {
            let agent_id = by_id.get(rid.as_str()).map(|c| c.agent_id.clone()).unwrap_or_default();
            let lost = self.selections.iter().find(|s| s.members.contains(rid) && s.winner.as_deref() != Some(rid.as_str()));
            match lost {
                Some(sel) => {
                    let winner = sel.winner.clone();
                    let score_q = sel.scores_q.get(rid).copied();
                    let winner_score_q = winner.as_ref().and_then(|w| sel.scores_q.get(w).copied());
                    let gated_out = sel.gate.as_ref().is_some_and(|g| !g.candidates.contains(rid));
                    let decided_by = if gated_out { "gate" }
                        else if sel.in_deadband && sel.schulze_winner.is_some() { "schulze" }
                        else if score_q.is_some() && score_q == winner_score_q { "tiebreak_order" }
                        else { "score" };
                    let reason = match &winner {
                        Some(w) if same_value(rid, w) => "same_value_as_winner",
                        _ => "lost_slot",
                    };
                    RejectionReason {
                        id: rid.clone(), agent_id, reason: reason.into(),
                        slot: Some(sel.slot.clone()), slot_id: sel.slot_id.clone(), winner,
                        decided_by: Some(decided_by.into()), score_q, winner_score_q,
                    }
                }
                None => {
                    let low = by_id.get(rid.as_str()).is_some_and(|c| c.lowering_confidence == LoweringConfidence::Low);
                    RejectionReason {
                        id: rid.clone(), agent_id,
                        reason: if low { "low_lowering_confidence" } else { "not_admitted" }.into(),
                        slot: None, slot_id: None, winner: None, decided_by: None, score_q: None, winner_score_q: None,
                    }
                }
            }
        }).collect()
    }
}

// ── EES (Effective Ensemble Size) ───────────────────────────

pub fn compute_ees(roster: &[AgentPersonality]) -> f64 {
    let n = roster.len();
    if n <= 1 {
        return n as f64;
    }

    let mut family_counts: HashMap<&str, usize> = HashMap::new();
    for a in roster {
        *family_counts.entry(a.model_family.as_str()).or_insert(0) += 1;
    }

    let total_pairs = n * (n - 1) / 2;
    let same_pairs: usize = family_counts
        .values()
        .map(|&c| c * (c - 1) / 2)
        .sum();
    let cross_pairs = total_pairs - same_pairs;

    let rho_bar = if total_pairs > 0 {
        (0.7 * same_pairs as f64 + 0.1 * cross_pairs as f64) / total_pairs as f64
    } else {
        0.0
    };

    n as f64 / (1.0 + (n as f64 - 1.0) * rho_bar)
}

/// Compute EES for `n` agents cycling through `base_roster` without
/// materializing the full roster.
pub fn analytical_ees(n: usize, base_roster: &[AgentPersonality]) -> f64 {
    if n <= 1 {
        return n as f64;
    }

    let roster_size = base_roster.len();

    // Count families in base roster
    let mut base_families: HashMap<&str, usize> = HashMap::new();
    for a in base_roster {
        *base_families.entry(a.model_family.as_str()).or_insert(0) += 1;
    }

    // Scale to n agents (cycling through roster)
    let full_cycles = n / roster_size;
    let remainder = n % roster_size;

    let mut family_counts: HashMap<&str, usize> = base_families
        .iter()
        .map(|(&f, &c)| (f, c * full_cycles))
        .collect();

    // Add remainder agents
    for i in 0..remainder {
        let fam = base_roster[i % roster_size].model_family.as_str();
        *family_counts.entry(fam).or_insert(0) += 1;
    }

    let total_pairs = n * (n - 1) / 2;
    if total_pairs == 0 {
        return n as f64;
    }

    let same_pairs: usize = family_counts
        .values()
        .map(|&c| c * (c - 1) / 2)
        .sum();
    let cross_pairs = total_pairs - same_pairs;

    let rho_bar = (0.7 * same_pairs as f64 + 0.1 * cross_pairs as f64) / total_pairs as f64;

    n as f64 / (1.0 + (n as f64 - 1.0) * rho_bar)
}

// ── Tests: arity-aware ClaimSlots ───────────────────────────

#[cfg(test)]
mod slot_tests {
    use super::*;
    use crate::topics;

    fn assertion(agent: &str, triple: CanonicalTriple, cite: bool) -> Contribution {
        let seed = format!("{agent}:{triple}");
        let evidence: Vec<EvidenceItem> = if cite {
            vec![EvidenceItem::new(EvidenceType::Citation, "RFC 793", 0.95, true)]
        } else {
            vec![EvidenceItem::new(EvidenceType::Reasoning, "hunch", 0.3, true)]
        };
        Contribution {
            id: make_id(&seed),
            agent_id: agent.to_string(),
            agent_name: agent.to_string(),
            kind: ContributionKind::Assertion,
            canonical_form: Some(triple),
            confidence: 0.9,
            evidence,
            raw_text: seed,
            lowering_confidence: LoweringConfidence::High,
            seq: 0,
            timestamp: 0.0,
            is_correct: cite,
        }
    }

    fn compile(injected: Vec<Contribution>) -> CompilationResult {
        let topic = topics::get_topic("tcp").unwrap();
        OverturnCompiler::default().compile_with_injected(&topic, &[], 42, injected)
    }

    fn admitted_objects(r: &CompilationResult) -> Vec<(String, Polarity)> {
        let mut v: Vec<(String, Polarity)> = r.admitted.iter()
            .filter_map(|&i| r.all_contributions[i].canonical_form.as_ref())
            .map(|t| (t.object.clone(), t.polarity))
            .collect();
        v.sort_by(|a, b| a.0.cmp(&b.0));
        v
    }

    #[test]
    fn arity_classification() {
        assert_eq!(predicate_arity("has_capital"), PredicateArity::Functional);
        assert_eq!(predicate_arity("uses"), PredicateArity::NonFunctional);
    }

    #[test]
    fn non_functional_compatible_values_get_separate_slots() {
        let seq = CanonicalTriple::new("TCP", "uses", "sequence numbers");
        let ack = CanonicalTriple::new("TCP", "uses", "acknowledgments");
        let k_seq = slot_key(&seq);
        let k_ack = slot_key(&ack);
        assert_ne!(k_seq, k_ack);
        assert_eq!(k_seq.object.as_deref(), Some("sequence numbers"));
        assert_ne!(
            ClaimSlotId::from_slot_key(&k_seq, "g"),
            ClaimSlotId::from_slot_key(&k_ack, "g"),
        );

        let r = compile(vec![assertion("a", seq, true), assertion("b", ack, true)]);
        assert!(r.conflicts.is_empty(), "compatible claims must not conflict: {:?}",
            r.conflicts.iter().map(|c| c.slot_key.to_string()).collect::<Vec<_>>());
        assert_eq!(admitted_objects(&r), vec![
            ("acknowledgments".to_string(), Polarity::Affirm),
            ("sequence numbers".to_string(), Polarity::Affirm),
        ]);
        assert!(crate::properties::prop_slot_arity(&r).is_ok());
        let slots: HashSet<SlotKey> = r.admitted.iter()
            .filter_map(|&i| r.all_contributions[i].canonical_form.as_ref())
            .map(slot_key)
            .collect();
        assert_eq!(slots.len(), 2);
    }

    #[test]
    fn exclusive_values_share_group_slot() {
        let three = CanonicalTriple::new("TCP", "uses", "three-way handshake (SYN, SYN-ACK, ACK)");
        let two = CanonicalTriple::new("TCP", "uses", "two-way handshake");
        let cc = CanonicalTriple::new("TCP", "uses", "congestion control (slow start, AIMD)");
        assert_eq!(slot_key(&three), slot_key(&two));
        assert_eq!(slot_key(&three).group.as_deref(), Some("tcp_handshake"));
        assert!(slot_key(&three).object.is_none());
        // Ungrouped value under the same predicate keeps its own slot.
        assert_ne!(slot_key(&three), slot_key(&cc));
        // Critiques stay object-level: negating one alternative does not hit the other.
        assert_ne!(critique_key(&three), critique_key(&two));

        let r = compile(vec![
            assertion("a", three, true),
            assertion("b", two, false),
            assertion("c", cc, true),
        ]);
        let contradictions: Vec<&ConflictSet> = r.conflicts.iter()
            .filter(|c| c.typ == ConflictType::Contradiction).collect();
        assert_eq!(contradictions.len(), 1);
        let cs = contradictions[0];
        assert_eq!(cs.slot_key.group.as_deref(), Some("tcp_handshake"));
        assert_eq!(cs.contribution_ids.len(), 2);
        let winner = &r.all_contributions[cs.winner_idx.unwrap()];
        assert_eq!(winner.canonical_form.as_ref().unwrap().object, "three-way handshake (SYN, SYN-ACK, ACK)");
        assert_eq!(admitted_objects(&r).len(), 2);
        assert!(crate::properties::prop_slot_arity(&r).is_ok());
    }

    #[test]
    fn empty_value_policy_keeps_per_object_slots() {
        let three = CanonicalTriple::new("TCP", "uses", "three-way handshake (SYN, SYN-ACK, ACK)");
        let two = CanonicalTriple::new("TCP", "uses", "two-way handshake");
        let empty = ValuePolicy::default();
        assert_ne!(slot_key_with(&three, &empty), slot_key_with(&two, &empty));
    }

    #[test]
    fn non_functional_polarity_conflict_shares_slot() {
        let aff = CanonicalTriple::new("TCP", "uses", "Sequence  Numbers");
        let neg = CanonicalTriple::negated("tcp", "uses", "sequence numbers");
        let ack = CanonicalTriple::new("TCP", "uses", "acknowledgments");
        // Polarity-insensitive, normalized object identity
        assert_eq!(slot_key(&aff), slot_key(&neg));

        let r = compile(vec![
            assertion("a", aff, true),
            assertion("b", neg, false),
            assertion("c", ack, true),
        ]);
        let contradictions: Vec<&ConflictSet> = r.conflicts.iter()
            .filter(|c| c.typ == ConflictType::Contradiction).collect();
        assert_eq!(contradictions.len(), 1);
        let cs = contradictions[0];
        assert_eq!(cs.slot_key.object.as_deref(), Some("sequence numbers"));
        assert_eq!(cs.contribution_ids.len(), 2);
        // Evidence-backed AFFIRM wins; NEGATE rejected; acknowledgments untouched.
        let winner = &r.all_contributions[cs.winner_idx.unwrap()];
        assert_eq!(winner.canonical_form.as_ref().unwrap().polarity, Polarity::Affirm);
        assert_eq!(admitted_objects(&r), vec![
            ("Sequence  Numbers".to_string(), Polarity::Affirm),
            ("acknowledgments".to_string(), Polarity::Affirm),
        ]);
        assert!(crate::properties::prop_slot_arity(&r).is_ok());
    }

    #[test]
    fn functional_predicate_keeps_sp_slot() {
        let can = CanonicalTriple::new("Australia", "has_capital", "Canberra");
        let syd = CanonicalTriple::new("Australia", "has_capital", "Sydney");
        assert_eq!(slot_key(&can), slot_key(&syd));
        assert!(slot_key(&can).object.is_none());
        // Functional slot IDs are byte-identical to the legacy (s, p) IDs.
        assert_eq!(
            ClaimSlotId::from_slot_key(&slot_key(&can), "g"),
            ClaimSlotId::new(&("australia".into(), "has_capital".into()), "g"),
        );
        let r = compile(vec![assertion("a", can, true), assertion("b", syd, false)]);
        assert_eq!(r.conflicts.len(), 1);
        assert_eq!(admitted_objects(&r), vec![("Canberra".to_string(), Polarity::Affirm)]);
    }
}

// ── Tests: seal-before-reduce & deadband-restricted Schulze ────

#[cfg(test)]
mod seal_tests {
    use super::*;
    use crate::{agents, topics};
    use rand::seq::SliceRandom;

    fn sealed_tcp(n: usize) -> (OverturnCompiler, SealedArtifactSet, Vec<Contribution>) {
        let topic = topics::get_topic("tcp").unwrap();
        let roster = agents::get_roster(n);
        let compiler = OverturnCompiler::default();
        let mut rng = ChaCha8Rng::seed_from_u64(42);
        let raw = compiler.p2_lower_pub(&roster, &topic, &mut rng);
        let sealed = compiler.seal(topic.goal, &topic.criteria, &roster, &raw);
        (compiler, sealed, raw)
    }

    fn output_ids(r: &CompilationResult) -> (Vec<String>, Vec<Option<String>>) {
        let adm = r.admitted.iter().map(|&i| r.all_contributions[i].id.clone()).collect();
        let win = r.conflicts.iter()
            .map(|cs| cs.winner_idx.map(|i| r.all_contributions[i].id.clone()))
            .collect();
        (adm, win)
    }

    #[test]
    fn compile_equals_reduce_of_seal() {
        let topic = topics::get_topic("tcp").unwrap();
        let roster = agents::get_roster(60);
        let (compiler, sealed, _) = sealed_tcp(60);
        let a = compiler.compile(&topic, &roster, 42);
        let b = compiler.reduce(&sealed);
        assert_eq!(a.certificate, b.certificate);
        assert_eq!(a.artifact_set.root_hash, sealed.root_hash);
    }

    #[test]
    fn permuted_input_order_yields_identical_output() {
        let topic = topics::get_topic("tcp").unwrap();
        let roster = agents::get_roster(80);
        let (compiler, sealed, raw) = sealed_tcp(80);
        let base = compiler.reduce(&sealed);
        let mut rng = ChaCha8Rng::seed_from_u64(7);
        for _ in 0..20 {
            let mut shuffled = raw.clone();
            shuffled.shuffle(&mut rng);
            let s2 = compiler.seal(topic.goal, &topic.criteria, &roster, &shuffled);
            assert_eq!(s2.root_hash, sealed.root_hash);
            let r2 = compiler.reduce(&s2);
            assert_eq!(r2.certificate, base.certificate);
            assert_eq!(output_ids(&r2), output_ids(&base));
        }
    }

    #[test]
    fn changing_any_seq_changes_hash() {
        let (_, sealed, _) = sealed_tcp(40);
        assert!(sealed.verify());
        let max_seq = sealed.contributions.iter().map(|c| c.seq).max().unwrap();
        for i in 0..sealed.contributions.len() {
            let mut t = sealed.clone();
            t.contributions[i].seq = max_seq + 1 + i as u64;
            assert_ne!(t.compute_root_hash(), sealed.root_hash, "seq of #{i} not covered by hash");
            assert!(!t.verify());
        }
    }

    #[test]
    fn reducer_inputs_are_covered_by_hash() {
        let (_, sealed, _) = sealed_tcp(40);
        let h = sealed.root_hash.clone();
        let mutate: Vec<Box<dyn Fn(&mut SealedArtifactSet)>> = vec![
            Box::new(|s| s.contributions[0].confidence += 1e-9),
            Box::new(|s| s.contributions[0].lowering_confidence = LoweringConfidence::Low),
            Box::new(|s| s.contributions[0].kind = ContributionKind::Synthesis),
            Box::new(|s| s.contributions[0].agent_id.push('x')),
            Box::new(|s| s.contributions[0].raw_text.push('x')),
            Box::new(|s| {
                let t = s.contributions[0].canonical_form.as_mut().unwrap();
                t.polarity = if t.polarity == Polarity::Affirm { Polarity::Negate } else { Polarity::Affirm };
            }),
            Box::new(|s| s.contributions[0].canonical_form.as_mut().unwrap().object.push('x')),
            Box::new(|s| {
                let c = s.contributions.iter_mut().find(|c| !c.evidence.is_empty()).unwrap();
                c.evidence[0].verification = EvidenceVerification::ContentHashed;
            }),
            Box::new(|s| {
                let c = s.contributions.iter_mut().find(|c| !c.evidence.is_empty()).unwrap();
                c.evidence[0].reachable = !c.evidence[0].reachable;
            }),
            Box::new(|s| { let v = s.calibration.values_mut().next().unwrap(); *v += 0.01; }),
            Box::new(|s| s.criteria.push("x".into())),
            Box::new(|s| s.intent.push('x')),
        ];
        for (k, m) in mutate.iter().enumerate() {
            let mut t = sealed.clone();
            m(&mut t);
            assert_ne!(t.compute_root_hash(), h, "mutation #{k} not covered by hash");
        }
        // Eval-only fields are not reducer inputs and are not sealed.
        let mut t = sealed.clone();
        t.contributions[0].is_correct = !t.contributions[0].is_correct;
        t.contributions[0].timestamp += 1.0;
        t.contributions[0].agent_name.push('x');
        assert_eq!(t.compute_root_hash(), h);
    }

    #[test]
    fn sealed_set_json_roundtrip_verifies() {
        let (compiler, sealed, _) = sealed_tcp(50);
        let json = serde_json::to_string(&sealed).unwrap();
        let back: SealedArtifactSet = serde_json::from_str(&json).unwrap();
        assert!(back.verify());
        assert_eq!(compiler.reduce(&back).certificate, compiler.reduce(&sealed).certificate);
    }

    fn sb(ev: f64, conf: f64, cs: f64, rec: f64, ca: f64) -> ScoreBreakdown {
        let w = OverturnCompiler::default().weights;
        let raw = w[0] * ev + w[1] * conf + w[2] * cs + w[3] * rec + w[4] * ca;
        ScoreBreakdown { ev, conf, cs, rec, ca, raw, lf: 1.0, final_score: raw }
    }

    fn conflict_with(scores: Vec<ScoreBreakdown>) -> ConflictSet {
        let key = SlotKey { subject: "s".into(), predicate: "p".into(), object: None, group: None };
        ConflictSet {
            typ: ConflictType::Contradiction,
            triple_key: ("s".into(), "p".into()),
            slot_key: key,
            slot_id: None,
            contribution_ids: (0..scores.len()).collect(),
            winner_idx: None,
            scores: scores.into_iter().enumerate().collect(),
            in_deadband: false,
            schulze_winner: None,
            gate: None,
        }
    }

    #[test]
    fn schulze_never_selects_outside_deadband() {
        let c = OverturnCompiler::default();
        // 0: top (0.675), 1: within deadband (0.6625), 2: far (0.585) but
        // beats both others on 4 of 5 dimensions.
        let cs = conflict_with(vec![
            sb(1.00, 0.5, 0.5, 0.5, 0.5),
            sb(0.95, 0.5, 0.5, 0.6, 0.5),
            sb(0.00, 0.9, 0.9, 0.9, 0.9),
        ]);
        // Over the whole set, Schulze would pick the out-of-deadband member.
        assert_eq!(c.schulze_over(&cs, &cs.contribution_ids), Some(2));
        assert_eq!(c.deadband_candidates(&cs), vec![0, 1]);
        let w = c.schulze_select(&cs).unwrap();
        assert_ne!(w, 2);
        assert!(w == 0 || w == 1);
    }

    #[test]
    fn schulze_winner_always_within_deadband_random() {
        use rand::Rng;
        let c = OverturnCompiler::default();
        let mut rng = ChaCha8Rng::seed_from_u64(1);
        for _ in 0..2000 {
            let m = rng.gen_range(2..8);
            let scores: Vec<ScoreBreakdown> = (0..m)
                .map(|_| sb(rng.r#gen(), rng.r#gen(), rng.r#gen(), rng.r#gen(), rng.r#gen()))
                .collect();
            let cs = conflict_with(scores);
            let top = cs.scores.values().map(|s| quantize(s.final_score)).max().unwrap();
            let w = c.schulze_select(&cs).unwrap();
            assert!(top - quantize(cs.scores[&w].final_score) < c.deadband_threshold);
        }
    }
}

#[cfg(test)]
mod policy_hash_tests {
    use super::*;

    fn mutations() -> Vec<(&'static str, Box<dyn Fn(&mut OverturnCompiler)>)> {
        vec![
            ("weights[0]", Box::new(|c| c.weights[0] += 1e-12)),
            ("weights[4]", Box::new(|c| c.weights[4] = 0.150001)),
            ("max_severity_budget", Box::new(|c| c.max_severity_budget = 5.5)),
            ("deadband_threshold", Box::new(|c| c.deadband_threshold += 1)),
            ("schulze_dim_epsilon", Box::new(|c| c.schulze_dim_epsilon -= 1)),
            ("schulze_dims", Box::new(|c| c.schulze_dims = SCHULZE_DIMS_NO_RECENCY)),
            ("tiebreak", Box::new(|c| c.tiebreak = TieBreak::ScoreThenCanonical)),
            ("tiebreak_order", Box::new(|c| c.tiebreak_order = TieOrder::Id)),
            ("hardening.min_corroboration", Box::new(|c| c.hardening.min_corroboration += 1)),
            ("hardening.reject_uncorroborated", Box::new(|c| c.hardening.reject_uncorroborated ^= true)),
            ("hardening.singleton_score_penalty", Box::new(|c| c.hardening.singleton_score_penalty = 0.01)),
            ("hardening.max_critiques_per_agent", Box::new(|c| c.hardening.max_critiques_per_agent += 1)),
            ("incompatible_values: drop one object", Box::new(|c| {
                c.values.incompatible_values.get_mut("uses").unwrap()
                    .get_mut("tcp_handshake").unwrap().pop();
            })),
            ("incompatible_values: edit one object", Box::new(|c| {
                c.values.incompatible_values.get_mut("detects_corruption_via").unwrap()
                    .get_mut("tcp_integrity_check").unwrap()[0].push('x');
            })),
            ("incompatible_values: rename group", Box::new(|c| {
                let t = c.values.incompatible_values.get_mut("uses").unwrap();
                let g = t.remove("tcp_handshake").unwrap();
                t.insert("tcp_handshake2".into(), g);
            })),
            ("incompatible_values: add predicate", Box::new(|c| {
                c.values.incompatible_values.entry("new_pred".into()).or_default()
                    .insert("g".into(), vec!["a".into(), "b".into()]);
            })),
            ("incompatible_values: clear", Box::new(|c| c.values = ValuePolicy::default())),
        ]
    }

    #[test]
    fn same_policy_same_hash() {
        let a = OverturnCompiler::default();
        let b = OverturnCompiler::default();
        assert_eq!(a.canonical_policy_json(), b.canonical_policy_json());
        assert_eq!(a.policy_hash(), b.policy_hash());
        assert_eq!(a.policy_hash().len(), 32);
        // JSON round trip preserves the hash (floats round-trip exactly).
        let back: OverturnCompiler = serde_json::from_str(&serde_json::to_string(&a).unwrap()).unwrap();
        assert_eq!(back.policy_hash(), a.policy_hash());
        // with_weights(default weights) is the default policy.
        assert_eq!(OverturnCompiler::with_weights([0.35, 0.20, 0.25, 0.05, 0.15]).policy_hash(), a.policy_hash());
    }

    #[test]
    fn any_single_field_change_changes_hash() {
        let base = OverturnCompiler::default().policy_hash();
        let mut seen = std::collections::HashSet::new();
        seen.insert(base.clone());
        for (name, m) in mutations() {
            let mut c = OverturnCompiler::default();
            m(&mut c);
            let h = c.policy_hash();
            assert_ne!(h, base, "mutation {name} not covered by policy hash");
            assert!(seen.insert(h), "mutation {name} collides with another mutation");
        }
    }

    #[test]
    fn policy_change_changes_certificate() {
        let topic = crate::topics::get_topic("tcp").unwrap();
        let roster = crate::agents::get_roster(40);
        let base = OverturnCompiler::default();
        let r0 = base.compile(&topic, &roster, 42);
        assert_eq!(r0.policy_hash, base.policy_hash());
        // A policy change that may not alter admitted ids still alters the certificate.
        let mut c = OverturnCompiler::default();
        c.hardening.max_critiques_per_agent += 100;
        let r1 = c.compile(&topic, &roster, 42);
        assert_eq!(r0.artifact_set.root_hash, r1.artifact_set.root_hash);
        assert_ne!(r0.certificate, r1.certificate);
    }

    #[test]
    fn table_key_and_object_order_do_not_matter() {
        let c = OverturnCompiler::default();
        let mut v = serde_json::to_value(&c).unwrap();
        // Rebuild the JSON text with the table's predicates, groups, and
        // group objects in reverse order.
        let table = v.pointer("/values/incompatible_values").unwrap().as_object().unwrap().clone();
        let mut rev = String::from("{");
        for (i, (pred, groups)) in table.iter().rev().enumerate() {
            if i > 0 { rev.push(','); }
            rev.push_str(&format!("{}:{{", serde_json::to_string(pred).unwrap()));
            for (j, (g, objs)) in groups.as_object().unwrap().iter().rev().enumerate() {
                if j > 0 { rev.push(','); }
                let mut objs: Vec<_> = objs.as_array().unwrap().clone();
                objs.reverse();
                rev.push_str(&format!("{}:{}", serde_json::to_string(g).unwrap(),
                    serde_json::to_string(&objs).unwrap()));
            }
            rev.push('}');
        }
        rev.push('}');
        *v.pointer_mut("/values/incompatible_values").unwrap() = serde_json::Value::Null;
        let text = serde_json::to_string(&v).unwrap()
            .replace("\"incompatible_values\":null", &format!("\"incompatible_values\":{rev}"));
        assert!(text.find("\"uses\"").unwrap() < text.find("\"detects_corruption_via\"").unwrap());
        let back: OverturnCompiler = serde_json::from_str(&text).unwrap();
        assert_eq!(back.policy_hash(), c.policy_hash());
        // Same table built from a reordered static table.
        let t = ValuePolicy::from_table(&[
            ("detects_corruption_via", "tcp_integrity_check", &["CRC-32", "16-bit checksum"]),
            ("handles_loss_via", "tcp_loss_recovery", &["forward error correction (FEC)", "retransmission with exponential backoff"]),
            ("uses", "tcp_handshake", &["two-way handshake", "three-way handshake (SYN, SYN-ACK, ACK)"]),
        ]);
        let c2 = OverturnCompiler { values: t, ..OverturnCompiler::default() };
        assert_eq!(c2.policy_hash(), c.policy_hash());
    }

    #[test]
    fn default_policy_hash_unchanged_by_tiebreak_fields() {
        // Hash of the default policy before `schulze_dims` / `tiebreak`
        // existed (v2/evidence/stress/final-replay-file.txt).
        let c = OverturnCompiler::default();
        assert_eq!(c.policy_hash(), "dd8d36e6def3a6d598765e82d461a473");
        let j = c.canonical_policy_json();
        assert!(!j.contains("schulze_dims") && !j.contains("tiebreak"));
        // Explicit defaults in input JSON deserialize to the same policy.
        let mut v = serde_json::to_value(&c).unwrap();
        v["schulze_dims"] = 31.into();
        v["tiebreak"] = "schulze".into();
        v["tiebreak_order"] = "seq".into();
        let back: OverturnCompiler = serde_json::from_value(v).unwrap();
        assert_eq!(back.policy_hash(), c.policy_hash());
        // Non-default values are serialized and round-trip.
        let nd = OverturnCompiler { schulze_dims: SCHULZE_DIMS_NO_RECENCY, tiebreak: TieBreak::ScoreThenCanonical,
            tiebreak_order: TieOrder::Id, ..c };
        let j = nd.canonical_policy_json();
        assert!(j.contains("\"schulze_dims\":23") && j.contains("\"tiebreak\":\"score_then_canonical\"")
            && j.contains("\"tiebreak_order\":\"id\""));
        let back: OverturnCompiler = serde_json::from_str(&serde_json::to_string(&nd).unwrap()).unwrap();
        assert_eq!(back.policy_hash(), nd.policy_hash());
    }

    #[test]
    fn canonical_policy_json_is_sorted_and_compact() {
        let j = OverturnCompiler::default().canonical_policy_json();
        assert!(!j.contains('\n'));
        assert!(j.find("\"config\"").unwrap() < j.find("\"constants\"").unwrap());
        assert!(j.find("\"constants\"").unwrap() < j.find("\"format\"").unwrap());
        assert!(j.contains("\"weights\":[0.35,0.2,0.25,0.05,0.15]"));
        assert!(j.contains("\"lowering_factors\":{\"HIGH\":1.0,\"LOW\":0.5,\"MEDIUM\":0.85}"));
    }

    #[test]
    #[should_panic(expected = "non-finite")]
    fn non_finite_weight_rejected() {
        OverturnCompiler::with_weights([f64::NAN, 0.2, 0.25, 0.05, 0.15]).policy_hash();
    }
}

#[cfg(test)]
mod schulze_equivalence_tests {
    use super::*;
    use rand::Rng;
    use std::collections::BTreeSet;

    fn conflict_from_dims(dims: &[[i64; 5]]) -> ConflictSet {
        let key = SlotKey { subject: "s".into(), predicate: "p".into(), object: None, group: None };
        let scores = dims.iter().map(|v| {
            let f = |q: i64| q as f64 / SCORE_SCALE;
            let (ev, conf, cs, rec, ca) = (f(v[0]), f(v[1]), f(v[2]), f(v[3]), f(v[4]));
            ScoreBreakdown { ev, conf, cs, rec, ca, raw: 0.5, lf: 1.0, final_score: 0.5 }
        });
        let cs = ConflictSet {
            typ: ConflictType::Contradiction,
            triple_key: ("s".into(), "p".into()),
            slot_key: key,
            slot_id: None,
            contribution_ids: (0..dims.len()).collect(),
            winner_idx: None,
            scores: scores.enumerate().collect(),
            in_deadband: false,
            schulze_winner: None,
            gate: None,
        };
        for (i, v) in dims.iter().enumerate() {
            let s = &cs.scores[&i];
            assert_eq!(*v, [quantize(s.ev), quantize(s.conf), quantize(s.cs), quantize(s.rec), quantize(s.ca)]);
        }
        cs
    }

    fn random_size(rng: &mut ChaCha8Rng) -> usize {
        match rng.gen_range(0..100) {
            0..60 => rng.gen_range(2..=12),
            60..85 => rng.gen_range(13..=60),
            85..97 => rng.gen_range(61..=150),
            _ => rng.gen_range(151..=400),
        }
    }

    /// Random candidate dimension vectors with heavy ties: regimes with a
    /// small pool of duplicate vectors, coarse grids (values a multiple of
    /// a step near epsilon), constant dimensions, and fine random values.
    fn random_dims(rng: &mut ChaCha8Rng, n: usize) -> (Vec<[i64; 5]>, &'static str) {
        let regime = rng.gen_range(0..4);
        let constant: [bool; 5] = std::array::from_fn(|_| rng.gen_bool(0.3));
        let mut gen_vec = |rng: &mut ChaCha8Rng| -> [i64; 5] {
            let step = [1i64, 50, 100, 101, 150][rng.gen_range(0..5)];
            std::array::from_fn(|k| {
                if constant[k] { return 5000; }
                match regime {
                    1 | 2 => step * rng.gen_range(0..=4),
                    _ => rng.gen_range(0..=10_000),
                }
            })
        };
        let dims = match regime {
            0 | 1 => {
                let pool_n = rng.gen_range(1..=(n / 3).max(1));
                let pool: Vec<[i64; 5]> = (0..pool_n).map(|_| gen_vec(rng)).collect();
                (0..n).map(|_| pool[rng.gen_range(0..pool_n)]).collect()
            }
            _ => (0..n).map(|_| gen_vec(rng)).collect(),
        };
        (dims, ["pool-fine", "pool-coarse", "coarse", "fine"][regime])
    }

    fn random_eps(rng: &mut ChaCha8Rng) -> i64 {
        [0i64, 0, 1, 50, 100, 100, 100, 150, 250, -1, 20_000][rng.gen_range(0..11)]
    }

    fn cases() -> usize {
        std::env::var("OVERTURN_SCHULZE_CASES").ok().and_then(|s| s.parse().ok())
            .unwrap_or(if cfg!(debug_assertions) { 2_000 } else { 24_000 })
    }

    #[test]
    fn schulze_matches_floyd_warshall_reference() {
        let mut rng = ChaCha8Rng::seed_from_u64(0x5c4u64);
        let n_cases = cases();
        let (mut nonzero, mut dup_sets, mut eps0, mut epspos, mut big) = (0, 0, 0, 0, 0);
        let mut by_regime: BTreeMap<&str, usize> = BTreeMap::new();
        for case in 0..n_cases {
            let n = random_size(&mut rng);
            let (dims, regime) = random_dims(&mut rng, n);
            let eps = random_eps(&mut rng);
            let compiler = OverturnCompiler { schulze_dim_epsilon: eps, ..OverturnCompiler::default() };
            let cs = conflict_from_dims(&dims);
            let want = compiler.schulze_over_reference(&cs, &cs.contribution_ids).unwrap();
            let got = compiler.schulze_over(&cs, &cs.contribution_ids).unwrap();
            assert_eq!(got, want, "case {case}: n={n} eps={eps} regime={regime}");
            // Both internal strategies, forced.
            let lazy = schulze_scan(&dims, eps, SCHULZE_DIMS_ALL, Some(usize::MAX));
            let closure = schulze_scan(&dims, eps, SCHULZE_DIMS_ALL, Some(0));
            assert_eq!(lazy, want, "case {case} (lazy): n={n} eps={eps} regime={regime}");
            assert_eq!(closure, want, "case {case} (closure): n={n} eps={eps} regime={regime}");
            *by_regime.entry(regime).or_default() += 1;
            if want != 0 { nonzero += 1; }
            let mut u = dims.clone(); u.sort(); u.dedup();
            if u.len() < n { dup_sets += 1; }
            if eps == 0 { eps0 += 1; } else if eps > 0 { epspos += 1; }
            if n > 150 { big += 1; }
        }
        eprintln!("schulze equivalence: {n_cases} sets, {nonzero} winner!=first, {dup_sets} with duplicate vectors, \
            eps=0: {eps0}, eps>0: {epspos}, n>150: {big}, regimes {by_regime:?}");
        assert!(n_cases < 20_000 || (eps0 > 1_000 && epspos > 1_000 && dup_sets > 1_000 && big > 100));
    }

    #[test]
    fn schulze_dims_mask_equals_reference_on_zeroed_dims() {
        // Excluding dimension k is the same as making it constant.
        let mut rng = ChaCha8Rng::seed_from_u64(0xd135);
        let n_cases = cases() / 4;
        for case in 0..n_cases {
            let n = random_size(&mut rng).min(120);
            let (dims, regime) = random_dims(&mut rng, n);
            let eps = random_eps(&mut rng).max(0);
            let mask: u8 = rng.gen_range(0..32);
            let zeroed: Vec<[i64; 5]> = dims.iter()
                .map(|v| std::array::from_fn(|k| if mask & (1 << k) != 0 { v[k] } else { 0 }))
                .collect();
            let reference = OverturnCompiler { schulze_dim_epsilon: eps, ..OverturnCompiler::default() };
            let cs0 = conflict_from_dims(&zeroed);
            let want = reference.schulze_over_reference(&cs0, &cs0.contribution_ids).unwrap();
            let masked = OverturnCompiler { schulze_dim_epsilon: eps, schulze_dims: mask, ..OverturnCompiler::default() };
            let cs = conflict_from_dims(&dims);
            assert_eq!(masked.schulze_over(&cs, &cs.contribution_ids).unwrap(), want,
                "case {case}: n={n} eps={eps} mask={mask:05b} regime={regime}");
        }
    }

    /// Adversarial leader-change chains must hit the closure fallback and
    /// still match the reference.
    #[test]
    fn schulze_leader_chain_uses_closure_and_matches() {
        let c = OverturnCompiler::default();
        for n in [50usize, 300] {
            let asc: Vec<[i64; 5]> = (0..n as i64).map(|i| [i * 200; 5]).collect();
            let cs = conflict_from_dims(&asc);
            assert_eq!(c.schulze_over(&cs, &cs.contribution_ids), Some(n - 1));
            assert_eq!(c.schulze_over_reference(&cs, &cs.contribution_ids), Some(n - 1));
        }
    }

    /// `cargo test --release schulze_timing -- --ignored --nocapture`
    #[test]
    #[ignore]
    fn schulze_timing() {
        let c = OverturnCompiler::default();
        let mut rng = ChaCha8Rng::seed_from_u64(7);
        for n in [500usize, 1000, 2000] {
            let fine: Vec<[i64; 5]> = (0..n).map(|_| std::array::from_fn(|_| rng.gen_range(0..=10_000))).collect();
            let asc: Vec<[i64; 5]> = (0..n as i64).map(|i| [i * 200; 5]).collect();
            for (name, dims) in [("random", &fine), ("leader-chain", &asc)] {
                let cs = conflict_from_dims(dims);
                let t = std::time::Instant::now();
                let a = c.schulze_over(&cs, &cs.contribution_ids);
                let fast = t.elapsed();
                let t = std::time::Instant::now();
                let lazy = schulze_scan(dims, c.schulze_dim_epsilon, SCHULZE_DIMS_ALL, Some(usize::MAX));
                let lazy_t = t.elapsed();
                let t = std::time::Instant::now();
                let b = c.schulze_over_reference(&cs, &cs.contribution_ids);
                let slow = t.elapsed();
                assert_eq!(a, b);
                assert_eq!(Some(lazy), b);
                eprintln!("n={n:5} {name:12} auto={fast:?} lazy-only={lazy_t:?} reference={slow:?}");
            }
        }
    }

    #[test]
    fn schulze_small_edge_cases() {
        let c = OverturnCompiler::default();
        let one = conflict_from_dims(&[[1, 2, 3, 4, 5]]);
        assert_eq!(c.schulze_over(&one, &one.contribution_ids), Some(0));
        assert_eq!(c.schulze_over(&one, &[]), None);
        // All identical: first candidate.
        let same = conflict_from_dims(&[[7; 5]; 6]);
        assert_eq!(c.schulze_over(&same, &same.contribution_ids), Some(0));
        // Candidate order is the scan order (subset, permuted).
        let cs = conflict_from_dims(&[[0; 5], [9000; 5], [5000; 5]]);
        assert_eq!(c.schulze_over(&cs, &[2, 0]), Some(2));
        assert_eq!(c.schulze_over(&cs, &[0, 2, 1]), Some(1));
        assert_eq!(c.schulze_over(&cs, &[0, 2, 1]), c.schulze_over_reference(&cs, &[0, 2, 1]));
    }

    /// Recency decides the default tie-break even at recency weight 0
    /// (eval v3 finding); `SCHULZE_DIMS_NO_RECENCY` removes it, and
    /// `score_then_canonical` keeps the raw-score leader.
    #[test]
    fn excluding_recency_changes_a_recency_decided_winner() {
        // a: higher evidence; b: higher confidence and recency.
        //            ev    conf  cs    rec   ca
        let a = [5200, 5000, 5000,    0, 5000];
        let b = [5000, 5200, 5000, 9000, 5000];
        let cs = conflict_from_dims(&[a, b]);
        let mut zero_rec = OverturnCompiler::with_weights([0.35, 0.20, 0.25, 0.0, 0.15]);
        // b beats a on conf and rec (2), a beats b on ev (1): b wins.
        assert_eq!(zero_rec.schulze_over(&cs, &[0, 1]), Some(1));
        assert_eq!(zero_rec.schulze_over_reference(&cs, &[0, 1]), Some(1));
        zero_rec.schulze_dims = SCHULZE_DIMS_NO_RECENCY;
        // Without recency: 1–1, the scan keeps the first candidate.
        assert_eq!(zero_rec.schulze_over(&cs, &[0, 1]), Some(0));
    }

    /// Exactly tied candidates (identical scores; weights give recency 0)
    /// in one functional slot. With `tiebreak_order: id` the winner is the
    /// same for every permutation of `seq` values, under both tie-break
    /// modes (Schulze with recency excluded, and score_then_canonical);
    /// with the default `seq` order the winner follows arrival.
    #[test]
    fn id_order_is_independent_of_seq_permutation() {
        use rand::seq::SliceRandom;
        let objs = ["Sydney", "Melbourne", "Canberra", "Perth", "Hobart", "Darwin"];
        let base: Vec<Contribution> = objs.iter().enumerate().map(|(i, o)| {
            let triple = CanonicalTriple::new("australia", "has_capital", o);
            Contribution {
                id: make_id(&format!("c{i}:{o}")),
                agent_id: format!("agent{i}"),
                agent_name: format!("agent{i}"),
                kind: ContributionKind::Assertion,
                canonical_form: Some(triple),
                confidence: 0.8,
                evidence: vec![EvidenceItem::new(EvidenceType::Citation, &format!("src{i}"), 0.9, true)],
                raw_text: String::new(),
                lowering_confidence: LoweringConfidence::High,
                seq: i as u64,
                timestamp: 0.0,
                is_correct: false,
            }
        }).collect();
        let cal: BTreeMap<String, f64> = (0..objs.len()).map(|i| (format!("agent{i}"), 0.7)).collect();
        let w = [0.35, 0.20, 0.25, 0.0, 0.15];
        let modes = [
            ("schulze/no-rec/id", OverturnCompiler { schulze_dims: SCHULZE_DIMS_NO_RECENCY, tiebreak_order: TieOrder::Id, ..OverturnCompiler::with_weights(w) }),
            ("score/id", OverturnCompiler { tiebreak: TieBreak::ScoreThenCanonical, tiebreak_order: TieOrder::Id, ..OverturnCompiler::with_weights(w) }),
            ("score/seq", OverturnCompiler { tiebreak: TieBreak::ScoreThenCanonical, ..OverturnCompiler::with_weights(w) }),
        ];
        let mut rng = ChaCha8Rng::seed_from_u64(11);
        let mut winners: Vec<BTreeSet<String>> = vec![BTreeSet::new(); modes.len()];
        for _ in 0..50 {
            let mut seqs: Vec<u64> = (0..objs.len() as u64).collect();
            seqs.shuffle(&mut rng);
            let mut cs = base.clone();
            for (c, s) in cs.iter_mut().zip(&seqs) { c.seq = *s; }
            let sealed = seal_contributions("", Vec::new(), &cal, &cs);
            for (m, (name, pol)) in modes.iter().enumerate() {
                let r = pol.reduce(&sealed);
                assert_eq!(r.conflicts.len(), 1, "{name}");
                let c = &r.conflicts[0];
                let q: BTreeSet<i64> = c.scores.values().map(|s| quantize(s.final_score)).collect();
                assert_eq!(q.len(), 1, "{name}: candidates must be exactly tied");
                winners[m].insert(r.all_contributions[c.winner_idx.unwrap()].id.clone());
            }
        }
        let min_id = base.iter().map(|c| c.id.clone()).min().unwrap();
        assert_eq!(winners[0], BTreeSet::from([min_id.clone()]), "schulze/no-rec/id");
        assert_eq!(winners[1], BTreeSet::from([min_id]), "score/id");
        assert!(winners[2].len() > 1, "default seq order should follow arrival");
    }

    #[test]
    fn score_then_canonical_keeps_score_leader_in_deadband() {
        let topic = crate::topics::get_topic("tcp").unwrap();
        let roster = crate::agents::get_roster(200);
        let c = OverturnCompiler { tiebreak: TieBreak::ScoreThenCanonical, ..OverturnCompiler::default() };
        let r = c.compile(&topic, &roster, 42);
        let mut deadband = 0;
        for cs in &r.conflicts {
            let top = cs.scores.values().map(|s| quantize(s.final_score)).max().unwrap();
            let first_top = cs.contribution_ids.iter().copied()
                .find(|i| quantize(cs.scores[i].final_score) == top);
            assert_eq!(cs.winner_idx, first_top);
            assert_eq!(cs.schulze_winner, None);
            if cs.in_deadband { deadband += 1; }
        }
        assert!(deadband > 0);
        // Default (Schulze) differs on at least one deadband conflict here.
        let d = OverturnCompiler::default().compile(&topic, &roster, 42);
        assert!(d.conflicts.iter().zip(&r.conflicts).any(|(x, y)| x.winner_idx != y.winner_idx));
    }
}

// ── Tests: evidence capture/support integration (spec §3) ──

#[cfg(test)]
mod evidence_reduce_tests {
    use super::*;
    use crate::evidence::{fixtures, CaptureOutcome, SupportLabel};
    use crate::{agents, topics};
    use rand::seq::SliceRandom;

    /// Literal default policy hash of the pre-evidence binary (`make replay-file`).
    const LEGACY_DEFAULT_POLICY_HASH: &str = "dd8d36e6def3a6d598765e82d461a473";

    fn ev_policy(accepted: &[String]) -> OverturnCompiler {
        OverturnCompiler {
            evidence: Some(EvidencePolicy { accepted_checkers: accepted.to_vec(), ..EvidencePolicy::default() }),
            ..OverturnCompiler::default()
        }
    }

    fn raw_tcp(n: usize, seed: u64) -> (Topic, Vec<AgentPersonality>, Vec<Contribution>) {
        let topic = topics::get_topic("tcp").unwrap();
        let roster = agents::get_roster(n);
        let mut rng = ChaCha8Rng::seed_from_u64(seed);
        let raw = OverturnCompiler::default().p2_lower_pub(&roster, &topic, &mut rng);
        (topic, roster, raw)
    }

    fn seal_ev(topic: &Topic, roster: &[AgentPersonality], raw: &[Contribution], store: Option<&EvidenceStore>) -> SealedArtifactSet {
        seal_contributions_with_evidence(topic.goal, topic.criteria.iter().map(|c| c.to_string()).collect(),
            &roster_calibration(roster), raw, store).unwrap()
    }

    /// Outcome tuples without the certificate/policy hash.
    fn outcome(r: &CompilationResult) -> (Vec<String>, Vec<String>, Vec<Selection>) {
        let o = ReductionOutput::from_result(r);
        (o.admitted, o.rejected, o.selections)
    }

    #[test]
    fn default_policy_hash_is_legacy_literal() {
        let d = OverturnCompiler::default();
        assert_eq!(d.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        assert!(!d.canonical_policy_json().contains("\"evidence\":"));
        // Explicit `evidence: null` deserializes to the same policy.
        let mut v = serde_json::to_value(&d).unwrap();
        v["evidence"] = serde_json::Value::Null;
        let back: OverturnCompiler = serde_json::from_value(v).unwrap();
        assert_eq!(back.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        // Setting an evidence policy changes the hash; so does each field.
        let e = ev_policy(&[]);
        assert_ne!(e.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        assert!(!e.canonical_policy_json().contains("accepted_checkers"));
        let variants: Vec<Box<dyn Fn(&mut EvidencePolicy)>> = vec![
            Box::new(|p| p.outcome_quality.dead = 0.25),
            Box::new(|p| p.outcome_reach.reachable = 0.7),
            Box::new(|p| p.support_factor.not_enough_info = 0.4),
            Box::new(|p| p.unchecked_factor = 0.5),
            Box::new(|p| p.use_support_score = true),
            Box::new(|p| p.xref_requires_support = false),
            Box::new(|p| p.legacy_source_xref = true),
            Box::new(|p| p.accepted_checkers.push("abc".into())),
        ];
        for (k, m) in variants.iter().enumerate() {
            let mut p = e.clone();
            m(p.evidence.as_mut().unwrap());
            assert_ne!(p.policy_hash(), e.policy_hash(), "evidence field #{k} not hashed");
        }
    }

    #[test]
    fn accepted_checkers_order_and_duplicates_do_not_matter() {
        let a = ev_policy(&["b".into(), "a".into(), "c".into()]);
        let b = ev_policy(&["c".into(), "a".into(), "b".into(), "a".into()]);
        assert_eq!(a.policy_hash(), b.policy_hash());
        assert_ne!(a.policy_hash(), ev_policy(&["a".into(), "b".into()]).policy_hash());
    }

    /// Acceptance 2: "context-associated" from three agents earns x = 1.2
    /// under legacy scoring and 0.9 under the evidence policy.
    #[test]
    fn context_associated_placeholder_loses_xref_bonus() {
        let cs: Vec<Contribution> = ["a", "b", "c"].iter().enumerate().map(|(i, ag)| {
            let mut c = fixtures::contribution(ag, "sequence numbers", vec![fixtures::citation("context-associated")]);
            c.id = make_id(ag);
            c.seq = i as u64;
            c
        }).collect();
        let sealed = seal_contributions_with_evidence("", vec![], &BTreeMap::new(), &cs, None).unwrap();
        assert!(sealed.evidence_store.is_none());
        let ev_of = |p: &OverturnCompiler| {
            let r = p.reduce(&sealed);
            assert_eq!(r.conflicts.len(), 1);
            r.conflicts[0].scores.values().map(|s| quantize(s.ev)).collect::<Vec<_>>()
        };
        // base = w·t·q·r = 1.0 · 0.8 · 0.40 · 0.75 = 0.24
        assert_eq!(ev_of(&OverturnCompiler::default()), vec![quantize(0.24 * 1.2); 3]);
        assert_eq!(ev_of(&ev_policy(&[])), vec![quantize(0.24 * 0.9); 3]);
        // The legacy escape hatch restores the bonus for uncaptured items.
        let mut legacy = ev_policy(&[]);
        legacy.evidence.as_mut().unwrap().legacy_source_xref = true;
        assert_eq!(ev_of(&legacy), vec![quantize(0.24 * 1.2); 3]);
    }

    /// Captured, accepted-`supports` citations of one canonical URL from
    /// distinct agents earn the xref bonus; NEI / unaccepted do not count.
    #[test]
    fn xref_counts_distinct_supporting_agents_by_canonical_url() {
        let ch = fixtures::checker("judge");
        let mut store = EvidenceStore::default();
        let cap = store.add_capture(fixtures::capture("https://e.org/p", CaptureOutcome::Ok));
        let labels = [SupportLabel::Supports, SupportLabel::Supports, SupportLabel::Supports, SupportLabel::NotEnoughInfo];
        let cs: Vec<Contribution> = labels.iter().enumerate().map(|(i, &l)| {
            let mut c = fixtures::contribution(&format!("ag{i}"), &format!("o{i}"), vec![]);
            c.seq = i as u64;
            let mut e = fixtures::citation(&format!("agent-specific text {i}")); // source text irrelevant
            e.capture_ref = Some(cap.clone());
            e.support_ref = Some(store.add_support(fixtures::support(&c, &cap, l, &ch)));
            c.evidence = vec![e];
            c
        }).collect();
        evidence::validate_store(&cs, &store).unwrap();
        let pol = EvidencePolicy { accepted_checkers: vec![ch.checker_id.clone()], ..Default::default() };
        let m = evidence::citer_map(&cs, &store, &pol);
        assert_eq!(m.len(), 1);
        assert_eq!(m["url:https://e.org/p"].len(), 3);
        let x: Vec<f64> = cs.iter().map(|c| evidence::xref_multiplier(&evidence::factors(&c.evidence[0], c, &store, &pol), &m)).collect();
        assert_eq!(x, vec![1.2, 1.2, 1.2, 0.9]);
        // Without the support requirement NEI counts too (n = 4).
        let pol2 = EvidencePolicy { xref_requires_support: false, ..pol.clone() };
        assert_eq!(evidence::citer_map(&cs, &store, &pol2)["url:https://e.org/p"].len(), 4);
        // Unaccepted checker: nobody is an eligible citer.
        assert!(evidence::citer_map(&cs, &store, &EvidencePolicy::default()).is_empty());
    }

    /// Property: evidence records never change outcomes when absent. Over
    /// topics × seeds × N: (a) sealing through the evidence path with no
    /// store, an empty store, or a store no item references is
    /// byte-identical to the legacy seal; (b) the evidence policy with
    /// `legacy_source_xref` and no captures reproduces every legacy
    /// admission, rejection and quantized score.
    #[test]
    fn absent_evidence_never_changes_outcomes() {
        let d = OverturnCompiler::default();
        let mut legacy_x = ev_policy(&[]);
        legacy_x.evidence.as_mut().unwrap().legacy_source_xref = true;
        let mut unused = EvidenceStore::default();
        unused.add_capture(fixtures::capture("https://unused.example/", CaptureOutcome::Ok));
        for key in topics::all_topic_keys() {
            let topic = topics::get_topic(key).unwrap();
            for seed in [1u64, 7, 42, 99] {
                for n in [10usize, 60] {
                    let roster = agents::get_roster(n);
                    let mut rng = ChaCha8Rng::seed_from_u64(seed);
                    let raw = d.p2_lower_pub(&roster, &topic, &mut rng);
                    let legacy = d.seal_legacy(topic.goal, &topic.criteria, &roster, &raw);
                    for store in [None, Some(&EvidenceStore::default()), Some(&unused)] {
                        let s = seal_ev(&topic, &roster, &raw, store);
                        assert!(s.evidence_store.is_none());
                        assert_eq!(s.canonical_json(), legacy.canonical_json(), "{key} seed={seed} n={n}");
                        assert_eq!(s.root_hash, legacy.root_hash);
                    }
                    let base = d.reduce(&legacy);
                    // compile() seals content-addressed (id_scheme is
                    // root-hashed, so the certificate differs); the outcome
                    // over the same ids is identical.
                    let compiled = d.compile(&topic, &roster, seed);
                    assert_eq!(d.reduce(&d.seal(topic.goal, &topic.criteria, &roster, &raw)).certificate, compiled.certificate);
                    assert_eq!(outcome(&base), outcome(&compiled), "{key} seed={seed} n={n}");
                    assert_eq!(outcome(&legacy_x.reduce(&legacy)), outcome(&base), "{key} seed={seed} n={n}");
                }
            }
        }
    }

    #[test]
    fn captured_evidence_changes_scores_and_is_sealed() {
        let (topic, roster, mut raw) = raw_tcp(40, 42);
        let legacy = seal_ev(&topic, &roster, &raw, None);
        let (store, acc) = fixtures::attach(&mut raw);
        let sealed = seal_ev(&topic, &roster, &raw, Some(&store));
        let st = sealed.evidence_store.as_ref().unwrap();
        assert_eq!(st.captures.len(), 3);
        assert!(!st.support.is_empty());
        assert_ne!(sealed.root_hash, legacy.root_hash);
        assert!(sealed.verify());
        // Header lists record ids and captured body hashes.
        let h = sealed.header();
        assert!(st.captures.keys().chain(st.support.keys()).all(|id| h.evidence_hashes.contains(id)));
        assert!(st.captures.values().filter_map(|c| c.content_sha256.as_ref()).all(|x| h.evidence_hashes.contains(x)));
        // Store present but no evidence policy → legacy scores.
        let d = OverturnCompiler::default();
        assert_eq!(outcome(&d.reduce(&sealed)), outcome(&d.reduce(&legacy)));
        // Evidence policy → at least one quantized score moves.
        let p = ev_policy(&[acc]);
        assert_ne!(outcome(&p.reduce(&sealed)).2, outcome(&d.reduce(&legacy)).2);
        // JSON round trip keeps the root and the outputs.
        let back: SealedArtifactSet = serde_json::from_str(&serde_json::to_string(&sealed).unwrap()).unwrap();
        assert!(back.verify());
        assert_eq!(ReductionOutput::from_result(&p.reduce(&back)), ReductionOutput::from_result(&p.reduce(&sealed)));
    }

    /// Acceptance 6: permuting contributions, store insertion order, or
    /// `accepted_checkers` order leaves root, policy hash and outputs unchanged.
    #[test]
    fn permutation_invariance_with_evidence() {
        let (topic, roster, mut raw) = raw_tcp(60, 42);
        let (store, acc) = fixtures::attach(&mut raw);
        let other = fixtures::checker("judge-unvalidated").checker_id;
        let p = ev_policy(&[acc.clone(), other.clone()]);
        let base_s = seal_ev(&topic, &roster, &raw, Some(&store));
        let base = ReductionOutput::from_result(&p.reduce(&base_s));
        // Store re-parsed from JSON text with its map keys in reverse order.
        let mut text = String::from("{");
        for (i, k) in ["support", "captures"].iter().enumerate() {
            let v = serde_json::to_value(&store).unwrap();
            let mut entries: Vec<(String, serde_json::Value)> = v[*k].as_object().unwrap().clone().into_iter().collect();
            entries.reverse();
            let body = entries.iter().map(|(id, x)| format!("{}:{}", serde_json::to_string(id).unwrap(), x)).collect::<Vec<_>>().join(",");
            text.push_str(&format!("{}\"{k}\":{{{body}}}", if i > 0 { "," } else { "" }));
        }
        text.push('}');
        let store_rev: EvidenceStore = serde_json::from_str(&text).unwrap();
        assert_eq!(store_rev, store);
        let p_rev = ev_policy(&[other, acc]);
        assert_eq!(p_rev.policy_hash(), p.policy_hash());
        let mut rng = ChaCha8Rng::seed_from_u64(3);
        for _ in 0..10 {
            let mut shuffled = raw.clone();
            shuffled.shuffle(&mut rng);
            let s = seal_ev(&topic, &roster, &shuffled, Some(&store_rev));
            assert_eq!(s.root_hash, base_s.root_hash);
            assert_eq!(ReductionOutput::from_result(&p_rev.reduce(&s)), base);
        }
    }
}


// ── Tests: content-addressed contribution ids & SYNTHESIS at P3 ──

#[cfg(test)]
mod content_id_tests {
    use super::*;
    use crate::{agents, topics};
    use rand::seq::SliceRandom;

    fn raw(topic: &str, n: usize, seed: u64) -> (Topic, Vec<AgentPersonality>, Vec<Contribution>) {
        let topic = topics::get_topic(topic).unwrap();
        let roster = agents::get_roster(n);
        let mut rng = ChaCha8Rng::seed_from_u64(seed);
        let raw = OverturnCompiler::default().p2_lower_pub(&roster, &topic, &mut rng);
        (topic, roster, raw)
    }

    fn sample() -> Contribution {
        let (_, _, raw) = raw("tcp", 40, 42);
        let mut c = raw.into_iter().find(|c| c.evidence.len() >= 1 && c.kind == ContributionKind::Assertion).unwrap();
        c.evidence[0].capture_ref = Some("ab".repeat(16));
        c.id = content_id(&c);
        c
    }

    #[test]
    fn content_id_equals_reference_payload_hash() {
        let (_, _, mut cs) = raw("tcp", 60, 7);
        cs.push(sample());
        let mut none = sample();
        none.canonical_form = None;
        cs.push(none);
        for c in &cs {
            assert_eq!(content_id(c), sha256_hex16(content_id_payload(c).to_string().as_bytes()));
            assert_eq!(content_id(c).len(), 32);
        }
    }

    #[test]
    fn content_id_changes_when_any_covered_field_changes() {
        let base = sample();
        let h = content_id(&base);
        let muts: Vec<(&str, Box<dyn Fn(&mut Contribution)>)> = vec![
            ("agent_id", Box::new(|c| c.agent_id.push('x'))),
            ("kind", Box::new(|c| c.kind = ContributionKind::Critique)),
            ("subject", Box::new(|c| c.canonical_form.as_mut().unwrap().subject.push('x'))),
            ("predicate", Box::new(|c| c.canonical_form.as_mut().unwrap().predicate.push('x'))),
            ("object", Box::new(|c| c.canonical_form.as_mut().unwrap().object.push('x'))),
            ("polarity", Box::new(|c| c.canonical_form.as_mut().unwrap().polarity = Polarity::Negate)),
            ("canonical_form", Box::new(|c| c.canonical_form = None)),
            ("confidence", Box::new(|c| c.confidence += 1e-12)),
            ("lowering_confidence", Box::new(|c| c.lowering_confidence = LoweringConfidence::Low)),
            ("raw_text", Box::new(|c| c.raw_text.push(' '))),
            ("evidence.type", Box::new(|c| c.evidence[0].typ = EvidenceType::Authority)),
            ("evidence.source", Box::new(|c| c.evidence[0].source.push('x'))),
            ("evidence.weight", Box::new(|c| c.evidence[0].weight += 1e-12)),
            ("evidence.reachable", Box::new(|c| c.evidence[0].reachable = !c.evidence[0].reachable)),
            ("evidence.verification", Box::new(|c| c.evidence[0].verification = EvidenceVerification::Stale)),
            ("evidence.capture_ref", Box::new(|c| c.evidence[0].capture_ref = None)),
            ("evidence added", Box::new(|c| c.evidence.push(EvidenceItem::new(EvidenceType::Reasoning, "r", 0.3, true)))),
            ("evidence removed", Box::new(|c| { c.evidence.pop(); })),
        ];
        for (name, m) in muts {
            let mut c = base.clone();
            m(&mut c);
            assert_ne!(content_id(&c), h, "{name} not covered by the content id");
        }
    }

    #[test]
    fn content_id_ignores_excluded_fields() {
        let base = sample();
        let h = content_id(&base);
        let mut c = base.clone();
        c.id = "anything".into();
        c.seq += 17;
        c.timestamp += 1.0;
        c.is_correct = !c.is_correct;
        c.agent_name.push('x');
        c.evidence[0].support_ref = Some("cd".repeat(16));
        assert_eq!(content_id(&c), h);
    }

    #[test]
    fn compiled_sets_are_content_addressed() {
        for key in topics::all_topic_keys() {
            let (topic, roster, raw) = raw(key, 60, 42);
            assert!(raw.iter().all(|c| c.id == content_id(c)), "{key}: p2 ids");
            let d = OverturnCompiler::default();
            let sealed = d.seal(topic.goal, &topic.criteria, &roster, &raw);
            assert_eq!(sealed.id_scheme.as_deref(), Some(CONTRIBUTION_ID_SCHEME));
            assert!(sealed.content_id_violations().is_empty());
            assert!(sealed.verify());
            assert_eq!(d.compile(&topic, &roster, 42).artifact_set.root_hash, sealed.root_hash);
            // The scheme tag is root-hashed: stripping it breaks the seal.
            let mut t = sealed.clone();
            t.id_scheme = None;
            assert!(!t.verify());
        }
    }

    #[test]
    fn content_seal_is_permutation_invariant() {
        let (topic, _, raw) = raw("tcp", 80, 42);
        let crit: Vec<String> = topic.criteria.iter().map(|c| c.to_string()).collect();
        let base = seal_contributions_content(topic.goal, crit.clone(), &BTreeMap::new(), &raw, None).unwrap();
        let d = OverturnCompiler::default();
        let cert = d.reduce(&base).certificate;
        let mut rng = ChaCha8Rng::seed_from_u64(9);
        for _ in 0..20 {
            let mut s = raw.clone();
            s.shuffle(&mut rng);
            let sealed = seal_contributions_content(topic.goal, crit.clone(), &BTreeMap::new(), &s, None).unwrap();
            assert_eq!(sealed.root_hash, base.root_hash);
            assert_eq!(d.reduce(&sealed).certificate, cert);
        }
    }

    #[test]
    fn tampered_claim_with_kept_id_is_rejected_at_seal() {
        let (topic, _, raw) = raw("tcp", 40, 42);
        let tampers: Vec<Box<dyn Fn(&mut Contribution)>> = vec![
            Box::new(|c| c.canonical_form.as_mut().unwrap().object = "two-way handshake".into()),
            Box::new(|c| c.confidence = 0.99),
            Box::new(|c| c.agent_id = "someone_else".into()),
            Box::new(|c| c.evidence.clear()),
        ];
        for (k, t) in tampers.iter().enumerate() {
            let mut cs = raw.clone();
            t(&mut cs[3]);
            let id = cs[3].id.clone();
            match seal_contributions_content(topic.goal, vec![], &BTreeMap::new(), &cs, None) {
                Err(SealInputError::ContentId { id: got, expected, .. }) => {
                    assert_eq!(got, id, "tamper #{k}");
                    assert_eq!(expected, content_id(&cs[3]));
                }
                other => panic!("tamper #{k}: expected ContentId rejection, got {:?}", other.map(|s| s.root_hash)),
            }
            // A duplicate that P3 would drop is still checked.
            let mut cs = raw.clone();
            let mut dup = cs[3].clone();
            t(&mut dup);
            dup.seq = u64::MAX;
            cs.push(dup);
            assert!(seal_contributions_content(topic.goal, vec![], &BTreeMap::new(), &cs, None).is_err(), "dup tamper #{k}");
        }
    }

    #[test]
    fn legacy_seal_still_accepts_foreign_ids() {
        // `--reduce` without `id_scheme` (e.g. evaluate_v4.py's
        // sha256(item|agent|answer|object)[:16] ids) seals as before.
        let (topic, _, mut raw) = raw("tcp", 20, 42);
        for (i, c) in raw.iter_mut().enumerate() { c.id = format!("{:016x}", i * 7919); }
        let legacy = seal_contributions(topic.goal, vec![], &BTreeMap::new(), &raw);
        assert!(legacy.id_scheme.is_none());
        assert!(legacy.content_id_violations().is_empty());
        assert!(seal_contributions_content(topic.goal, vec![], &BTreeMap::new(), &raw, None).is_err());
    }

    fn synthesis(agent: &str, seq: u64, subject: &str, predicate: &str, object: &str) -> Contribution {
        let mut c = Contribution {
            id: String::new(),
            agent_id: agent.into(),
            agent_name: agent.into(),
            kind: ContributionKind::Synthesis,
            canonical_form: Some(CanonicalTriple::new(subject, predicate, object)),
            confidence: 0.99,
            evidence: vec![EvidenceItem::new(EvidenceType::ToolResult, "synth", 1.0, true)],
            raw_text: format!("synthesis: {subject} {object}"),
            lowering_confidence: LoweringConfidence::High,
            seq, timestamp: 0.0, is_correct: false,
        };
        c.id = content_id(&c);
        c
    }

    #[test]
    fn p3_rejects_synthesis_with_audit_reason() {
        let (topic, _, mut raw) = raw("australia", 30, 42);
        let s1 = synthesis("synth_a", 1, "Australia", "has_capital", "Canberra");
        let s2 = synthesis("synth_b", 2, "Australia", "has_capital", "Sydney");
        raw.push(s1.clone());
        raw.push(s2.clone());
        let mut nocf = raw[0].clone();
        nocf.canonical_form = None;
        nocf.id = content_id(&nocf);
        raw.push(nocf.clone());
        let (valid, rej) = p3_validate_audited(&raw);
        assert!(valid.iter().all(|c| c.kind != ContributionKind::Synthesis));
        let reason = |id: &str| rej.iter().find(|r| r.id == id).map(|r| r.reason.as_str());
        assert_eq!(reason(&s1.id), Some(P3_SYNTHESIS));
        assert_eq!(reason(&s2.id), Some(P3_SYNTHESIS));
        assert_eq!(reason(&nocf.id), Some(P3_NO_CANONICAL_FORM));
        // Audit record is order-independent.
        let mut rev = raw.clone();
        rev.reverse();
        assert_eq!(p3_validate_audited(&rev).1, rej);
        // Sealing drops them; the sealed set and outputs equal those without them.
        let sealed = seal_contributions_content(topic.goal, vec![], &BTreeMap::new(), &raw, None).unwrap();
        let without: Vec<Contribution> = raw.iter().filter(|c| c.kind != ContributionKind::Synthesis).cloned().collect();
        let sealed2 = seal_contributions_content(topic.goal, vec![], &BTreeMap::new(), &without, None).unwrap();
        assert_eq!(sealed.root_hash, sealed2.root_hash);
    }

    /// Property: over topics × seeds with injected SYNTHESIS (one agreeing
    /// with a fact, one contradicting it), every admitted id is an ASSERTION
    /// of the sealed set and no SYNTHESIS id appears in any output.
    #[test]
    fn admitted_ids_are_only_assertions() {
        let d = OverturnCompiler::default();
        for key in topics::all_topic_keys() {
            let topic = topics::get_topic(key).unwrap();
            let f = &topic.facts[0];
            for seed in [1u64, 42, 99] {
                let roster = agents::get_roster(40);
                let inj = vec![
                    synthesis("synth_a", 0, f.subject, f.predicate, f.object),
                    synthesis("synth_b", 0, f.subject, f.predicate, "merged_answer"),
                ];
                let synth_ids: Vec<String> = inj.iter().map(|c| c.id.clone()).collect();
                let r = d.compile_with_injected(&topic, &roster, seed, inj);
                let out = ReductionOutput::from_result(&r);
                for &i in &r.admitted {
                    assert_eq!(r.all_contributions[i].kind, ContributionKind::Assertion, "{key} seed={seed}");
                }
                assert!(r.all_contributions.iter().all(|c| c.kind != ContributionKind::Synthesis));
                for id in &synth_ids {
                    assert!(!out.admitted.contains(id) && !out.rejected.contains(id));
                    assert!(out.selections.iter().all(|s| !s.members.contains(id)));
                }
            }
        }
    }
}

// ── Tests: CLI-facing policy additions (functional_predicates, presets,
//    reducer-constants id, rejection reasons) ──

#[cfg(test)]
mod policy_extension_tests {
    use super::*;

    const LEGACY_DEFAULT_POLICY_HASH: &str = "dd8d36e6def3a6d598765e82d461a473";

    fn triple(s: &str, p: &str, o: &str, pol: Polarity) -> CanonicalTriple {
        CanonicalTriple { subject: s.into(), predicate: p.into(), object: o.into(), polarity: pol }
    }

    fn assertion(agent: &str, seq: u64, t: CanonicalTriple, conf: f64) -> Contribution {
        let mut c = Contribution {
            id: String::new(), agent_id: agent.into(), agent_name: String::new(),
            kind: ContributionKind::Assertion, canonical_form: Some(t), confidence: conf,
            evidence: vec![], raw_text: String::new(), lowering_confidence: LoweringConfidence::High,
            seq, timestamp: 0.0, is_correct: false,
        };
        c.id = content_id(&c);
        c
    }

    fn reduce(p: &OverturnCompiler, cs: &[Contribution]) -> (SealedArtifactSet, ReductionOutput) {
        let sealed = seal_contributions_content("q", vec![], &BTreeMap::new(), cs, None).unwrap();
        let out = ReductionOutput::from_result(&p.reduce(&sealed));
        (sealed, out)
    }

    #[test]
    fn functional_predicates_default_hashes_unchanged() {
        let d = OverturnCompiler::default();
        assert_eq!(d.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        assert!(!serde_json::to_string(&d).unwrap().contains("functional_predicates\":"));
        // Listing only built-ins (any case, duplicated) is the default policy.
        let p = OverturnCompiler { functional_predicates: vec!["is".into(), "HAS_CAPITAL".into(), "is".into()], ..d.clone() };
        assert_eq!(p.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        // A real extension hashes apart, as a set (order/case/dups irrelevant).
        let a = OverturnCompiler { functional_predicates: vec!["capital_city".into(), "born_in".into()], ..d.clone() };
        let b = OverturnCompiler { functional_predicates: vec!["Born_In".into(), "capital_city".into(), "born_in".into()], ..d.clone() };
        assert_ne!(a.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        assert_eq!(a.policy_hash(), b.policy_hash());
        assert!(a.canonical_policy_json().contains("\"functional_predicates\":[\"born_in\",\"capital_city\"]"));
        // Round trip through the serialized policy.
        let back: OverturnCompiler = serde_json::from_value(serde_json::to_value(&a).unwrap()).unwrap();
        assert_eq!(back.policy_hash(), a.policy_hash());
    }

    #[test]
    fn functional_predicates_change_slots_and_critique_targets() {
        let cs = vec![
            assertion("a1", 0, triple("X", "capital_city", "A", Polarity::Affirm), 0.9),
            assertion("a2", 1, triple("X", "capital_city", "B", Polarity::Affirm), 0.6),
        ];
        let d = OverturnCompiler::default();
        let (_, out) = reduce(&d, &cs);
        assert!(out.selections.is_empty(), "non-functional by default: two independent values");
        assert_eq!(out.admitted.len(), 2);
        let f = OverturnCompiler { functional_predicates: vec!["Capital_City".into()], ..d.clone() };
        let (_, out) = reduce(&f, &cs);
        assert_eq!(out.selections.len(), 1);
        assert_eq!(out.selections[0].slot, "(x, capital_city)");
        assert_eq!(out.admitted, vec![cs[0].id.clone()]);
        // Critique targeting follows the policy's arity, like built-ins.
        let t = triple("X", "capital_city", "C", Polarity::Negate);
        assert_eq!(f.critique_key_of(&t), f.slot_key_of(&t));
        assert_ne!(d.critique_key_of(&t), f.critique_key_of(&t));
        let builtin = triple("X", "has_capital", "C", Polarity::Negate);
        assert_eq!(d.critique_key_of(&builtin), critique_key(&builtin));
    }

    #[test]
    fn presets_and_constants_id() {
        assert_eq!(OverturnCompiler::preset("default").unwrap().policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        let g = OverturnCompiler::preset("generic").unwrap();
        assert!(g.values.incompatible_values.is_empty());
        assert_eq!(g.weights, OverturnCompiler::default().weights);
        assert_ne!(g.policy_hash(), LEGACY_DEFAULT_POLICY_HASH);
        assert_eq!(g.policy_hash(), "b905878f08e54d92b5a6f1e73f0682f2");
        assert!(OverturnCompiler::preset("tcp").is_none());
        for n in POLICY_PRESETS { assert!(OverturnCompiler::preset(n).is_some()); }
        // Generic groups nothing: the TCP handshake alternatives are separate slots.
        let three = triple("TCP", "uses", "three-way handshake (SYN, SYN-ACK, ACK)", Polarity::Affirm);
        let two = triple("TCP", "uses", "two-way handshake", Polarity::Affirm);
        assert_eq!(OverturnCompiler::default().slot_key_of(&three), OverturnCompiler::default().slot_key_of(&two));
        assert_ne!(g.slot_key_of(&three), g.slot_key_of(&two));
        // The constants id hashes exactly the block embedded in the policy.
        let doc: serde_json::Value = serde_json::from_str(&OverturnCompiler::default().canonical_policy_json()).unwrap();
        assert_eq!(doc["constants"], reducer_constants());
        assert_eq!(reducer_constants_id(), "456de373bb8a3775c9e7c8755dcbc264");
    }

    #[test]
    fn rejection_reasons_cover_every_rejected_id() {
        let mut low = assertion("a4", 3, triple("Y", "colour", "red", Polarity::Affirm), 0.9);
        low.lowering_confidence = LoweringConfidence::Low;
        low.id = content_id(&low);
        let cs = vec![
            assertion("a1", 0, triple("Australia", "has_capital", "Canberra", Polarity::Affirm), 0.9),
            assertion("a2", 1, triple("Australia", "has_capital", "Sydney", Polarity::Affirm), 0.2),
            assertion("a3", 2, triple("Australia", "has_capital", "canberra ", Polarity::Affirm), 0.3),
            low.clone(),
        ];
        let (sealed, out) = reduce(&OverturnCompiler::default(), &cs);
        let rr = out.rejection_reasons(&sealed);
        assert_eq!(rr.iter().map(|r| r.id.clone()).collect::<Vec<_>>(), out.rejected);
        let by_agent: HashMap<&str, &RejectionReason> = rr.iter().map(|r| (r.agent_id.as_str(), r)).collect();
        let winner = out.selections[0].winner.clone().unwrap();
        assert_eq!(winner, cs[0].id);
        assert_eq!(by_agent["a2"].reason, "lost_slot");
        assert_eq!(by_agent["a2"].winner.as_deref(), Some(winner.as_str()));
        assert_eq!(by_agent["a3"].reason, "same_value_as_winner");
        assert_eq!(by_agent["a4"].reason, "low_lowering_confidence");
        assert!(by_agent["a4"].slot.is_none());
        for r in [by_agent["a2"], by_agent["a3"]] {
            assert!(matches!(r.decided_by.as_deref(), Some("score" | "schulze" | "tiebreak_order")));
            assert!(r.score_q.is_some() && r.winner_score_q.is_some());
        }
    }
}
