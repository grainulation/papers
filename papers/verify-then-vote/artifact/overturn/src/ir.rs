use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};

// ── Evidence Verification Levels ────────────────────────────

/// Tracks how thoroughly a piece of evidence has been verified.
/// Higher levels produce better source_quality scores; the default
/// is Unverified (agents self-reporting).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceVerification {
    /// No verification performed — agent self-reported reachability.
    #[default]
    Unverified,
    /// URL/source was checked for reachability but content not hashed.
    ReachabilityChecked,
    /// Content body was fetched and hashed for integrity.
    ContentHashed,
    /// Multiple independent agents cited the same source.
    CrossReferenced,
    /// Source was previously verified but is now stale / unreachable.
    Stale,
}

impl EvidenceVerification {
    /// Quality multiplier for this verification level.
    pub fn quality_score(self) -> f64 {
        match self {
            Self::Unverified => 0.40,
            Self::ReachabilityChecked => 0.70,
            Self::ContentHashed => 0.85,
            Self::CrossReferenced => 0.95,
            Self::Stale => 0.20,
        }
    }
}

impl std::fmt::Display for EvidenceVerification {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Unverified => write!(f, "UNVERIFIED"),
            Self::ReachabilityChecked => write!(f, "REACHABILITY_CHECKED"),
            Self::ContentHashed => write!(f, "CONTENT_HASHED"),
            Self::CrossReferenced => write!(f, "CROSS_REFERENCED"),
            Self::Stale => write!(f, "STALE"),
        }
    }
}

// ── Hardening Policy ────────────────────────────────────────

/// Configurable hardening policy controlling how aggressively the
/// compiler penalizes uncorroborated or unverified contributions.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HardeningPolicy {
    /// Minimum number of agents that must assert the same (subject, predicate)
    /// for a contribution to avoid a singleton warning.
    pub min_corroboration: usize,
    /// If true, uncorroborated singletons are rejected outright.
    pub reject_uncorroborated: bool,
    /// Score penalty applied to singleton contributions (0.0 = no penalty).
    pub singleton_score_penalty: f64,
    /// Maximum critiques any single agent can emit per conflict key.
    pub max_critiques_per_agent: usize,
}

impl Default for HardeningPolicy {
    fn default() -> Self {
        Self {
            min_corroboration: 2,
            reject_uncorroborated: false,
            singleton_score_penalty: 0.0,
            max_critiques_per_agent: 3,
        }
    }
}

// ── Evidence Oracle ─────────────────────────────────────────

/// Pluggable verification backend. Production deployments can
/// implement this trait to pre-fetch URLs, hash content, etc.
/// The oracle output is an input to compilation — determinism
/// is preserved because verification runs before scoring.
pub trait EvidenceOracle {
    fn verify(&self, e: &EvidenceItem) -> EvidenceVerification;
}

/// Default oracle: returns Unverified for everything.
pub struct DefaultOracle;

impl EvidenceOracle for DefaultOracle {
    fn verify(&self, _e: &EvidenceItem) -> EvidenceVerification {
        EvidenceVerification::Unverified
    }
}

// ── Agent History (Brier score calibration) ─────────────────

/// Per-agent historical accuracy tracking for dynamic calibration.
/// Brier score = 1 − (confidence − is_correct)². Decayed over time.
#[derive(Debug, Clone)]
pub struct AgentHistory {
    pub agent_id: String,
    /// Running decayed Brier score (1.0 = perfect calibration).
    pub brier_score: f64,
    /// Number of evaluated contributions.
    pub n_evaluated: usize,
    /// Decay factor applied each compilation (0.0–1.0).
    pub decay: f64,
}

impl AgentHistory {
    pub fn new(agent_id: &str) -> Self {
        Self {
            agent_id: agent_id.to_string(),
            brier_score: 0.5, // neutral prior
            n_evaluated: 0,
            decay: 0.95,
        }
    }

    /// Update Brier score with a new observation.
    pub fn update(&mut self, confidence: f64, is_correct: bool) {
        let correct_f = if is_correct { 1.0 } else { 0.0 };
        let score = 1.0 - (confidence - correct_f).powi(2);
        self.brier_score = self.brier_score * self.decay + score * (1.0 - self.decay);
        self.n_evaluated += 1;
    }

    /// Use Brier score as calibration factor.
    pub fn calibration_factor(&self) -> f64 {
        self.brier_score.clamp(0.1, 1.0)
    }
}

// ── ClaimSlot Identity ─────────────────────────────────────

/// Stable slot identity: SHA-256(conflict_key ‖ intent).
/// Survives recompilation; enables slot-level streaming & patching.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ClaimSlotId(pub String);

impl ClaimSlotId {
    /// Compute slot identity from a conflict key and the compilation intent.
    pub fn new(conflict_key: &(String, String), intent: &str) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(conflict_key.0.as_bytes());
        hasher.update(b"|");
        hasher.update(conflict_key.1.as_bytes());
        hasher.update(b"|");
        hasher.update(intent.as_bytes());
        let result = hasher.finalize();
        Self(hex::encode(&result[..16]))
    }
}

impl ClaimSlotId {
    /// Compute slot identity from an arity-aware `SlotKey`.
    /// Functional slots (object == None, group == None) hash to exactly the
    /// same bytes as `ClaimSlotId::new(&(s, p), intent)`, so their IDs are
    /// unchanged. Non-functional slots additionally hash the normalized
    /// object, or the exclusivity group id for grouped values.
    pub fn from_slot_key(key: &SlotKey, intent: &str) -> Self {
        if let Some(g) = &key.group {
            let mut hasher = Sha256::new();
            hasher.update(key.subject.as_bytes());
            hasher.update(b"|");
            hasher.update(key.predicate.as_bytes());
            hasher.update(b"|g:");
            hasher.update(g.as_bytes());
            hasher.update(b"|");
            hasher.update(intent.as_bytes());
            let result = hasher.finalize();
            return Self(hex::encode(&result[..16]));
        }
        match &key.object {
            None => Self::new(&(key.subject.clone(), key.predicate.clone()), intent),
            Some(obj) => {
                let mut hasher = Sha256::new();
                hasher.update(key.subject.as_bytes());
                hasher.update(b"|");
                hasher.update(key.predicate.as_bytes());
                hasher.update(b"|o:");
                hasher.update(obj.as_bytes());
                hasher.update(b"|");
                hasher.update(intent.as_bytes());
                let result = hasher.finalize();
                Self(hex::encode(&result[..16]))
            }
        }
    }
}

// ── Predicate Arity & Slot Key ─────────────────────────────

/// FUNCTIONAL predicates admit exactly one value per subject (e.g.
/// `has_capital`): distinct objects compete for one slot.
/// NON_FUNCTIONAL predicates admit many compatible values (e.g. `uses`):
/// each normalized object gets its own slot, and only AFFIRM vs NEGATE
/// on the same (s, p, o) conflicts.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PredicateArity {
    Functional,
    NonFunctional,
}

/// Arity-aware slot key. `object` is `None` for functional predicates
/// and `Some(normalized_object)` for non-functional ones. Polarity is
/// never part of the key, so AFFIRM and NEGATE on the same (s, p, o)
/// land in the same slot.
/// `group` is set (and `object` is `None`) when a non-functional object
/// belongs to an exclusivity group in `ValuePolicy`: all members of the
/// group compete for the single slot (s, p, group).
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct SlotKey {
    pub subject: String,
    pub predicate: String,
    pub object: Option<String>,
    pub group: Option<String>,
}

// ── Value Incompatibility Policy (B1b) ─────────────────────

/// Mutually exclusive values for NON_FUNCTIONAL predicates.
/// A non-functional predicate admits many compatible values, but some
/// values are exclusive alternatives (e.g. a connection uses *either* a
/// two-way *or* a three-way handshake). Objects listed in the same group
/// share one slot keyed (s, p, group id) and form a contradiction set;
/// objects not in any group keep per-object slots.
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct ValuePolicy {
    /// predicate (lowercase) → group id → normalized objects in the group.
    pub incompatible_values: BTreeMap<String, BTreeMap<String, Vec<String>>>,
}

impl ValuePolicy {
    /// Build from a static (predicate, group id, objects) table.
    /// Predicates are lowercased and objects normalized on insert.
    pub fn from_table(table: &[(&str, &str, &[&str])]) -> Self {
        let mut incompatible_values: BTreeMap<String, BTreeMap<String, Vec<String>>> = BTreeMap::new();
        for &(pred, group, objects) in table {
            let objs = incompatible_values
                .entry(pred.to_lowercase())
                .or_default()
                .entry(group.to_string())
                .or_default();
            objs.extend(objects.iter().map(|o| normalize_object(o)));
            objs.sort();
            objs.dedup();
        }
        Self { incompatible_values }
    }

    /// Exclusivity group of a normalized object under `predicate`, if any.
    pub fn group_of(&self, predicate: &str, normalized_object: &str) -> Option<&str> {
        self.incompatible_values.get(predicate)?
            .iter()
            .find(|(_, objs)| objs.iter().any(|o| o == normalized_object))
            .map(|(g, _)| g.as_str())
    }
}

/// Normalize an object for polarity-insensitive slot identity:
/// lowercase, trim, collapse internal whitespace.
pub fn normalize_object(object: &str) -> String {
    object.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

impl std::fmt::Display for SlotKey {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        if let Some(g) = &self.group {
            return write!(f, "({}, {}, <{}>)", self.subject, self.predicate, g);
        }
        match &self.object {
            None => write!(f, "({}, {})", self.subject, self.predicate),
            Some(o) => write!(f, "({}, {}, {})", self.subject, self.predicate, o),
        }
    }
}

impl std::fmt::Display for ClaimSlotId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "slot:{}", self.0)
    }
}

// ── Artifact Set ───────────────────────────────────────────

/// Immutable compilation artifact set (§5). The determinism invariant
/// is defined over this boundary: all operations below it are pure
/// functions of these committed artifacts.
#[derive(Debug, Clone)]
pub struct ArtifactSet {
    /// Pinned intent (goal + constraints + criteria), canonicalized.
    pub intent_hash: String,
    /// Per-contribution hashes over each canonical serialization, in canonical order.
    pub contribution_hashes: Vec<String>,
    /// Evidence artifact hashes (URL body hashes, tool output hashes).
    pub evidence_hashes: Vec<String>,
    /// SHA-256 over the canonical serialization of the sealed set.
    pub root_hash: String,
}

/// The sealed input to reduction (P4–P6). Built once, before any
/// conflict detection or scoring, and hashed over a canonical JSON
/// serialization that covers every field the reducer reads:
/// intent, criteria (constraint alignment), per-agent calibration,
/// and for each contribution its id, seq, agent id, kind, canonical
/// triple incl. polarity, confidence, lowering confidence, evidence
/// incl. verification, and raw text. Contributions are held in
/// canonical order: ascending (seq, id), deduplicated by id.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SealedArtifactSet {
    pub intent: String,
    pub criteria: Vec<String>,
    /// agent_id → calibration factor, for every agent with a contribution.
    pub calibration: BTreeMap<String, f64>,
    pub contributions: Vec<Contribution>,
    /// Sealed `bran-capture/1` / `bran-support/1` records referenced by
    /// evidence items (`crate::evidence`). Absent (and not serialized)
    /// when no item references a record, so legacy root hashes are
    /// unchanged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub evidence_store: Option<crate::evidence::EvidenceStore>,
    /// `Some(CONTRIBUTION_ID_SCHEME)` when every contribution id is its
    /// content id (`bran-artifact/4`). Absent (and not serialized or
    /// hashed) for legacy generator ids, so legacy root hashes are
    /// unchanged; when present it is root-hashed, so it cannot be
    /// stripped without breaking the seal.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id_scheme: Option<String>,
    /// SHA-256 (128-bit, hex) of `canonical_json()`.
    pub root_hash: String,
}

/// Canonical (hashed) view of one contribution: exactly the fields the
/// reducer reads. Excludes `agent_name`, `timestamp`, and `is_correct`.
fn canonical_contribution(c: &Contribution) -> serde_json::Value {
    serde_json::json!({
        "id": c.id,
        "seq": c.seq,
        "agent_id": c.agent_id,
        "kind": c.kind,
        "canonical_form": c.canonical_form,
        "confidence": c.confidence,
        "lowering_confidence": c.lowering_confidence,
        "evidence": c.evidence,
        "raw_text": c.raw_text,
    })
}

pub(crate) fn sha256_hex16(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    hex::encode(&h.finalize()[..16])
}

impl SealedArtifactSet {
    /// Seal validated, canonically ordered contributions. The caller is
    /// responsible for validation and ordering (see `OverturnCompiler::seal`).
    pub fn new(
        intent: &str,
        criteria: Vec<String>,
        calibration: BTreeMap<String, f64>,
        contributions: Vec<Contribution>,
    ) -> Self {
        Self::new_with_id_scheme(intent, criteria, calibration, contributions, None)
    }

    /// `new` with `id_scheme` set before hashing (`Some` only when every
    /// id has been checked or assigned as a content id).
    pub fn new_with_id_scheme(
        intent: &str,
        criteria: Vec<String>,
        calibration: BTreeMap<String, f64>,
        contributions: Vec<Contribution>,
        id_scheme: Option<&str>,
    ) -> Self {
        let mut s = Self {
            intent: intent.to_string(),
            criteria,
            calibration,
            contributions,
            evidence_store: None,
            id_scheme: id_scheme.map(str::to_string),
            root_hash: String::new(),
        };
        s.root_hash = s.compute_root_hash();
        s
    }

    /// Attach a (validated, restricted) evidence store and reseal.
    /// `None` or an empty store leaves the set, and its root hash, as
    /// `new` produced it.
    pub fn with_evidence_store(mut self, store: Option<crate::evidence::EvidenceStore>) -> Self {
        self.evidence_store = store.filter(|s| !s.is_empty());
        self.root_hash = self.compute_root_hash();
        self
    }

    /// `bran-artifact/4` invariants for a content-addressed set: every id
    /// equals its content id and no SYNTHESIS is present. Empty for a
    /// valid set; legacy sets (no `id_scheme`) are not checked.
    pub fn content_id_violations(&self) -> Vec<String> {
        let mut v = Vec::new();
        match self.id_scheme.as_deref() {
            None => return v,
            Some(CONTRIBUTION_ID_SCHEME) => {}
            Some(other) => { v.push(format!("unknown id scheme {other}")); return v; }
        }
        for c in &self.contributions {
            let want = content_id(c);
            if c.id != want {
                v.push(format!("contribution {} (agent {}): id is not its content id {want}", c.id, c.agent_id));
            }
            if c.kind == ContributionKind::Synthesis {
                v.push(format!("contribution {}: SYNTHESIS is out of scope for the reducer", c.id));
            }
        }
        v
    }

    /// Canonical JSON: serde_json maps are key-sorted (BTreeMap), arrays
    /// keep the canonical contribution order, floats print shortest
    /// round-trip form.
    pub fn canonical_json(&self) -> String {
        let mut v = serde_json::json!({
            "intent": self.intent,
            "criteria": self.criteria,
            "calibration": self.calibration,
            "contributions": self.contributions.iter().map(canonical_contribution).collect::<Vec<_>>(),
        });
        if let Some(store) = &self.evidence_store {
            v["evidence_store"] = serde_json::to_value(store).expect("evidence store serialization");
        }
        if let Some(scheme) = &self.id_scheme {
            v["id_scheme"] = serde_json::Value::String(scheme.clone());
        }
        serde_json::to_string(&v).expect("canonical JSON serialization")
    }

    pub fn compute_root_hash(&self) -> String {
        sha256_hex16(self.canonical_json().as_bytes())
    }

    /// True iff the stored root hash matches the content.
    pub fn verify(&self) -> bool {
        self.root_hash == self.compute_root_hash()
    }

    /// Summary header for the certificate / property checks.
    pub fn header(&self) -> ArtifactSet {
        let intent_hash = sha256_hex16(self.intent.as_bytes());
        let contribution_hashes: Vec<String> = self
            .contributions
            .iter()
            .map(|c| sha256_hex16(canonical_contribution(c).to_string().as_bytes()))
            .collect();
        let mut evidence_hashes: Vec<String> = self
            .contributions
            .iter()
            .flat_map(|c| c.evidence.iter().map(|e| e.content_hash()))
            .collect();
        if let Some(store) = &self.evidence_store {
            evidence_hashes.extend(store.captures.keys().cloned());
            evidence_hashes.extend(store.support.keys().cloned());
            evidence_hashes.extend(self.contributions.iter()
                .flat_map(|c| c.evidence.iter())
                .filter_map(|e| e.capture_ref.as_ref().and_then(|id| store.captures.get(id)))
                .filter_map(|cap| cap.content_sha256.clone()));
        }
        evidence_hashes.sort();
        evidence_hashes.dedup();
        ArtifactSet { intent_hash, contribution_hashes, evidence_hashes, root_hash: self.root_hash.clone() }
    }
}

// ── Evidence Types ──────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum EvidenceType {
    ToolResult,
    Empirical,
    Citation,
    Authority,
    Reasoning,
}

impl EvidenceType {
    pub fn weight(self) -> f64 {
        match self {
            Self::ToolResult => 1.0,
            Self::Empirical => 0.9,
            Self::Citation => 0.8,
            Self::Authority => 0.5,
            Self::Reasoning => 0.3,
        }
    }
}

impl std::fmt::Display for EvidenceType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ToolResult => write!(f, "TOOL_RESULT"),
            Self::Empirical => write!(f, "EMPIRICAL"),
            Self::Citation => write!(f, "CITATION"),
            Self::Authority => write!(f, "AUTHORITY"),
            Self::Reasoning => write!(f, "REASONING"),
        }
    }
}

// ── Evidence Item ───────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EvidenceItem {
    #[serde(rename = "type")]
    pub typ: EvidenceType,
    pub source: String,
    pub weight: f64,
    #[serde(default = "default_true")]
    pub reachable: bool,
    /// Verification level — defaults to Unverified.  Higher levels
    /// produce better source_quality scores, penalizing self-reported
    /// evidence that hasn't been independently checked.
    #[serde(default)]
    pub verification: EvidenceVerification,
    /// `capture_id` of the sealed `bran-capture/1` record for this item.
    /// Skipped when absent, so legacy serializations are unchanged.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub capture_ref: Option<String>,
    /// `support_id` of the sealed `bran-support/1` record for this item.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub support_ref: Option<String>,
}

fn default_true() -> bool { true }

impl EvidenceItem {
    pub fn new(typ: EvidenceType, source: &str, weight: f64, reachable: bool) -> Self {
        Self {
            typ,
            source: source.to_string(),
            weight,
            reachable,
            verification: EvidenceVerification::Unverified,
            capture_ref: None,
            support_ref: None,
        }
    }

    /// Construct with an explicit verification level.
    pub fn with_verification(
        typ: EvidenceType,
        source: &str,
        weight: f64,
        reachable: bool,
        verification: EvidenceVerification,
    ) -> Self {
        Self { typ, source: source.to_string(), weight, reachable, verification, capture_ref: None, support_ref: None }
    }

    pub fn type_weight(&self) -> f64 {
        self.typ.weight()
    }

    /// Source quality now incorporates the verification level.
    /// ToolResult and Reasoning are intrinsic (not source-verified),
    /// so they stay at 1.0.  Everything else uses the verification
    /// quality score, which defaults to 0.40 for Unverified (down
    /// from the old 0.8 for "reachable").
    pub fn source_quality(&self) -> f64 {
        match self.typ {
            EvidenceType::ToolResult => 1.0,
            EvidenceType::Reasoning => 1.0,
            _ => self.verification.quality_score(),
        }
    }

    /// Content fingerprint: SHA-256(type ‖ source ‖ weight).
    /// Enables verification that evidence artifacts haven't changed
    /// between compilation runs (§6.6 evidence authenticity).
    /// Uses 16 bytes (128 bits) to resist collision attacks.
    pub fn content_hash(&self) -> String {
        let mut hasher = Sha256::new();
        hasher.update(format!("{}", self.typ).as_bytes());
        hasher.update(b"|");
        hasher.update(self.source.as_bytes());
        hasher.update(b"|");
        hasher.update(self.weight.to_bits().to_le_bytes());
        let result = hasher.finalize();
        hex::encode(&result[..16])
    }
}

// ── Lowering Confidence ─────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum LoweringConfidence {
    High,
    Medium,
    Low,
}

impl LoweringConfidence {
    pub fn factor(self) -> f64 {
        match self {
            Self::High => 1.0,
            Self::Medium => 0.85,
            Self::Low => 0.5,
        }
    }
}

impl std::fmt::Display for LoweringConfidence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::High => write!(f, "HIGH"),
            Self::Medium => write!(f, "MEDIUM"),
            Self::Low => write!(f, "LOW"),
        }
    }
}

// ── Canonical Triple ────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CanonicalTriple {
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub polarity: Polarity,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Polarity {
    Affirm,
    Negate,
}

impl CanonicalTriple {
    pub fn new(subject: &str, predicate: &str, object: &str) -> Self {
        Self {
            subject: subject.to_string(),
            predicate: predicate.to_string(),
            object: object.to_string(),
            polarity: Polarity::Affirm,
        }
    }

    pub fn negated(subject: &str, predicate: &str, object: &str) -> Self {
        Self {
            subject: subject.to_string(),
            predicate: predicate.to_string(),
            object: object.to_string(),
            polarity: Polarity::Negate,
        }
    }

    /// Grouping key: (subject_lower, predicate_lower)
    pub fn key(&self) -> (String, String) {
        (self.subject.to_lowercase(), self.predicate.to_lowercase())
    }

    /// Full value key for redundancy detection
    pub fn value_key(&self) -> (String, String, String, Polarity) {
        (
            self.subject.to_lowercase(),
            self.predicate.to_lowercase(),
            self.object.to_lowercase(),
            self.polarity,
        )
    }
}

impl std::fmt::Display for CanonicalTriple {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let pol = if self.polarity == Polarity::Negate { "¬" } else { "" };
        write!(f, "({}, {}, {}{})", self.subject, self.predicate, pol, self.object)
    }
}

// ── Contribution Kind ───────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ContributionKind {
    Assertion,
    Critique,
    Synthesis,
}

impl std::fmt::Display for ContributionKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Assertion => write!(f, "ASSERTION"),
            Self::Critique => write!(f, "CRITIQUE"),
            Self::Synthesis => write!(f, "SYNTHESIS"),
        }
    }
}

// ── Contribution ────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contribution {
    pub id: String,
    pub agent_id: String,
    /// Display name only; never read by the reducer.
    #[serde(default)]
    pub agent_name: String,
    pub kind: ContributionKind,
    pub canonical_form: Option<CanonicalTriple>,
    pub confidence: f64,
    #[serde(default)]
    pub evidence: Vec<EvidenceItem>,
    /// Read by constraint-alignment scoring, so it is part of the seal.
    #[serde(default)]
    pub raw_text: String,
    pub lowering_confidence: LoweringConfidence,
    /// Recorded arrival sequence number, assigned at ingestion. The sole
    /// recency input to scoring and the primary canonical sort key.
    pub seq: u64,
    /// Synthetic generation time. Only used to derive `seq` for simulated
    /// agents; never read by the reducer and not sealed.
    #[serde(default)]
    pub timestamp: f64,
    /// Ground-truth label for evaluation only; never read by the reducer
    /// and not sealed.
    #[serde(default)]
    pub is_correct: bool,
}

impl Contribution {
    pub fn lowering_factor(&self) -> f64 {
        self.lowering_confidence.factor()
    }
}

// ── Content-addressed contribution ids (`bran-contribution-id/1`) ──

/// Id scheme tag. A sealed set that carries it (`bran-artifact/4`)
/// requires every contribution id to equal `content_id(c)`.
pub const CONTRIBUTION_ID_SCHEME: &str = "bran-contribution-id/1";

/// The canonical payload a contribution id hashes. Covered: `agent_id`,
/// `kind`, `canonical_form` (incl. polarity), `confidence`,
/// `lowering_confidence`, `raw_text`, and each evidence item's `type`,
/// `source`, `weight`, `reachable`, `verification` and `capture_ref`
/// (omitted when absent), plus the scheme tag.
///
/// Excluded, and why:
/// - `id`: it is the output.
/// - `seq`: assigned by the ingesting compiler at arrival, not by the
///   author, so the id must be computable before arrival; and P3's
///   "same content, earliest arrival wins" dedup needs seq-free ids
///   (a re-delivered duplicate must not count twice). `seq` is still
///   sealed by the root hash and is the primary canonical sort key.
/// - evidence `support_ref`: a `bran-support/1` record names the
///   contribution id it judges, so hashing the ref into that id would
///   be circular. The record itself is sealed in `evidence_store` and
///   validated against the contribution at seal time.
/// - calibration: a per-agent input held in the sealed set's
///   `calibration` map (root-hashed), not a property of one payload.
/// - `agent_name`, `timestamp`, `is_correct`: never read by the reducer
///   and not sealed.
///
/// `agent_id` is a label, not an authenticated identity: hashing it binds
/// the claim to the label (the same claim from two agents has two ids;
/// changing the label changes the id), but nothing proves who produced
/// it. There is no signing.
#[cfg_attr(not(test), allow(dead_code))] // the reference definition; `content_id` is its fast path
pub fn content_id_payload(c: &Contribution) -> serde_json::Value {
    let evidence: Vec<serde_json::Value> = c.evidence.iter().map(|e| {
        let mut v = serde_json::json!({
            "type": e.typ,
            "source": e.source,
            "weight": e.weight,
            "reachable": e.reachable,
            "verification": e.verification,
        });
        if let Some(r) = &e.capture_ref {
            v["capture_ref"] = serde_json::Value::String(r.clone());
        }
        v
    }).collect();
    serde_json::json!({
        "scheme": CONTRIBUTION_ID_SCHEME,
        "agent_id": c.agent_id,
        "kind": c.kind,
        "canonical_form": c.canonical_form,
        "confidence": c.confidence,
        "lowering_confidence": c.lowering_confidence,
        "evidence": evidence,
        "raw_text": c.raw_text,
    })
}

/// Content id: SHA-256 of the compact JSON of `content_id_payload(c)`
/// (serde_json: object keys sorted at every level, no whitespace, floats
/// in shortest round-trip form), truncated to 128 bits, lowercase hex
/// (32 chars).
///
/// Computed through borrowed structs whose fields are declared in sorted
/// key order, so the bytes equal `content_id_payload(c).to_string()`
/// without building a `Value` tree (tested in `content_id_tests`).
pub fn content_id(c: &Contribution) -> String {
    #[derive(Serialize)]
    struct Triple<'a> { object: &'a str, polarity: Polarity, predicate: &'a str, subject: &'a str }
    #[derive(Serialize)]
    struct Ev<'a> {
        #[serde(skip_serializing_if = "Option::is_none")]
        capture_ref: Option<&'a str>,
        reachable: bool,
        source: &'a str,
        #[serde(rename = "type")]
        typ: EvidenceType,
        verification: EvidenceVerification,
        weight: f64,
    }
    #[derive(Serialize)]
    struct Payload<'a> {
        agent_id: &'a str,
        canonical_form: Option<Triple<'a>>,
        confidence: f64,
        evidence: Vec<Ev<'a>>,
        kind: ContributionKind,
        lowering_confidence: LoweringConfidence,
        raw_text: &'a str,
        scheme: &'static str,
    }
    let p = Payload {
        agent_id: &c.agent_id,
        canonical_form: c.canonical_form.as_ref().map(|t| Triple {
            object: &t.object, polarity: t.polarity, predicate: &t.predicate, subject: &t.subject,
        }),
        confidence: c.confidence,
        evidence: c.evidence.iter().map(|e| Ev {
            capture_ref: e.capture_ref.as_deref(), reachable: e.reachable, source: &e.source,
            typ: e.typ, verification: e.verification, weight: e.weight,
        }).collect(),
        kind: c.kind,
        lowering_confidence: c.lowering_confidence,
        raw_text: &c.raw_text,
        scheme: CONTRIBUTION_ID_SCHEME,
    };
    let bytes = serde_json::to_vec(&p).expect("content id serialization");
    sha256_hex16(&bytes)
}

/// Overwrite every id with its content id (ingestion of the compiler's
/// own lowered output; external ids are checked, not rewritten).
pub fn assign_content_ids(contributions: &mut [Contribution]) {
    for c in contributions.iter_mut() {
        c.id = content_id(c);
    }
}

/// Generate a content-hash ID from a seed string (legacy generator ids,
/// `bran-artifact/2` and `/3`).
pub fn make_id(seed: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(seed.as_bytes());
    let result = hasher.finalize();
    hex::encode(&result[..8])
}

// Inline hex encoding (avoid extra dependency)
mod hex {
    pub fn encode(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{b:02x}")).collect()
    }
}

// ── Score Breakdown ─────────────────────────────────────────

#[derive(Debug, Clone, Copy)]
pub struct ScoreBreakdown {
    pub ev: f64,
    pub conf: f64,
    pub cs: f64,
    pub rec: f64,
    pub ca: f64,
    pub raw: f64,
    pub lf: f64,
    pub final_score: f64,
}

// ── Conflict Set ────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConflictType {
    Contradiction,
    Redundancy,
}

impl std::fmt::Display for ConflictType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Contradiction => write!(f, "CONTRADICTION"),
            Self::Redundancy => write!(f, "REDUNDANCY"),
        }
    }
}

#[derive(Debug, Clone)]
pub struct ConflictSet {
    pub typ: ConflictType,
    pub triple_key: (String, String),
    /// Arity-aware slot key this conflict set occupies.
    pub slot_key: SlotKey,
    pub slot_id: Option<ClaimSlotId>,
    pub contribution_ids: Vec<usize>, // indices into the valid contributions list
    pub winner_idx: Option<usize>,
    pub scores: HashMap<usize, ScoreBreakdown>,
    /// True when top-2 score gap < deadband threshold, signalling
    /// that the Election Leader (Schulze path) should be consulted.
    pub in_deadband: bool,
    /// Schulze method winner for deadband conflicts.
    /// Set when `in_deadband` is true and Schulze voting resolves the tie.
    pub schulze_winner: Option<usize>,
    /// Verified-overturn gate trace (`evidence.overturn_gate = verified`,
    /// contradiction slots only); `None` when the slot is ungated.
    pub gate: Option<crate::gate::GateTrace>,
}

// ── Compilation Result ──────────────────────────────────────

#[derive(Debug)]
pub struct CompilationResult {
    pub admitted: Vec<usize>,       // indices into all_contributions
    pub rejected: Vec<usize>,
    pub conflicts: Vec<ConflictSet>,
    pub ees: f64,
    pub time_us: u64,               // microseconds for precision
    pub certificate: String,
    /// Policy hash the certificate was computed under (see
    /// `OverturnCompiler::policy_hash`).
    pub policy_hash: String,
    pub artifact_set: ArtifactSet,
    pub all_contributions: Vec<Contribution>,
    /// Indices of admitted contributions with zero corroboration
    /// (no other agent asserted the same (subject, predicate)).
    pub singleton_warnings: Vec<usize>,
}
