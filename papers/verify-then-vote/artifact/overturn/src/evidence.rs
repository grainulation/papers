//! Evidence capture and support verification (spec
//! `v2/evidence-verification-spec.md` §1–§3).
//!
//! Records produced outside the reducer (evidence capture, support check)
//! are sealed into `SealedArtifactSet::evidence_store` and read here as
//! plain data. Nothing in this module touches the network, a clock, a
//! cache, or a model: `factors` is a pure function of the sealed item,
//! its records and the policy.

use crate::ir::{sha256_hex16, CanonicalTriple, Contribution, EvidenceItem, EvidenceType, Polarity};
use serde::{Deserialize, Deserializer, Serialize};
use std::collections::{BTreeMap, HashMap, HashSet};

pub const CAPTURE_FORMAT: &str = "bran-capture/1";
pub const SUPPORT_FORMAT: &str = "bran-support/1";
pub const EVIDENCE_POLICY_FORMAT: &str = "bran-evidence-policy/1";

/// Canonical JSON of a record: keys sorted (serde_json `Value` maps are
/// BTreeMaps), compact, UTF-8 unescaped. Records hold no floats, so this
/// equals Python `json.dumps(obj, sort_keys=True, separators=(",", ":"),
/// ensure_ascii=False)` byte for byte (spec §3.5).
pub fn canonical_json<T: Serialize>(v: &T) -> String {
    let value = serde_json::to_value(v).expect("record serialization");
    serde_json::to_string(&value).expect("record serialization")
}

/// 128-bit SHA-256 id over the canonical JSON of `v`.
pub fn record_id<T: Serialize>(v: &T) -> String {
    sha256_hex16(canonical_json(v).as_bytes())
}

// ── bran-capture/1 (§1.1) ───────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IdentifierKind {
    Url, Doi, Arxiv, Rfc, Pmid, Isbn,
    /// A passage of a sealed local corpus, `corpus://<corpus_id>/<key>`
    /// (`v3/DESIGN.md` §2.4, `v3/evidence-corpus-addendum.md`).
    Corpus,
}

// ── Local corpus identifiers (v3 addendum §1) ───────────────

pub const CORPUS_SCHEME: &str = "corpus://";
pub const CORPUS_EXTRACTION_METHOD: &str = "corpus/1";
const CORPUS_MAX_KEY_CHARS: usize = 1024;

/// Characters a passage key keeps verbatim in its URL (RFC 3986
/// unreserved plus `:`); every other byte is `%XX`, uppercase hex. This is
/// Python `urllib.parse.quote(key, safe=":")`.
fn corpus_verbatim(b: u8) -> bool {
    b.is_ascii_alphanumeric() || matches!(b, b'-' | b'.' | b'_' | b'~' | b':')
}

fn corpus_id_ok(s: &str) -> bool {
    let b = s.as_bytes();
    !b.is_empty() && b.len() <= 64
        && (b[0].is_ascii_lowercase() || b[0].is_ascii_digit())
        && b.iter().all(|&c| c.is_ascii_lowercase() || c.is_ascii_digit() || matches!(c, b'.' | b'_' | b'-'))
}

/// `(corpus_id, passage_key)` of a canonical corpus URL, else `None`.
/// Exactly one URL is accepted per passage: non-verbatim bytes must be
/// `%XX` with uppercase hex, and verbatim bytes must not be encoded.
pub fn parse_corpus_url(url: &str) -> Option<(String, String)> {
    let rest = url.strip_prefix(CORPUS_SCHEME)?;
    let (cid, enc) = rest.split_once('/')?;
    if !corpus_id_ok(cid) || enc.is_empty() {
        return None;
    }
    let b = enc.as_bytes();
    let mut key = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' {
            let hex = |c: u8| match c { b'0'..=b'9' => Some(c - b'0'), b'A'..=b'F' => Some(c - b'A' + 10), _ => None };
            let v = hex(*b.get(i + 1)?)? * 16 + hex(*b.get(i + 2)?)?;
            if corpus_verbatim(v) {
                return None;
            }
            key.push(v);
            i += 3;
        } else if corpus_verbatim(b[i]) {
            key.push(b[i]);
            i += 1;
        } else {
            return None;
        }
    }
    let key = String::from_utf8(key).ok()?;
    (key.chars().count() <= CORPUS_MAX_KEY_CHARS).then(|| (cid.to_string(), key))
}

/// Shape of a `corpus` capture (addendum §1): no fetch happened, so no
/// redirects, status or robots check; a found passage is `text/plain`
/// with a `corpus/1` extraction and all four URL fields equal; a missing
/// one is `invalid_identifier` with no content.
fn check_corpus_capture(id: &str, r: &CaptureRecord) -> Result<(), SealError> {
    if parse_corpus_url(&r.request_url).is_none() {
        return Err(invalid(id, format!("corpus request_url {} is not a canonical corpus URL", r.request_url)));
    }
    if r.requested != r.request_url {
        return Err(invalid(id, "corpus capture: requested != request_url"));
    }
    if !r.redirects.is_empty() || r.http_status.is_some() || r.truncated
        || r.robots != (Robots { checked: false, allowed: None, robots_sha256: None })
    {
        return Err(invalid(id, "corpus capture with fetch fields (redirects, http_status, truncated or robots)"));
    }
    match r.outcome {
        CaptureOutcome::Ok | CaptureOutcome::OkNoText => {
            let url = Some(&r.request_url);
            let hex64 = |h: &Option<String>| h.as_ref().is_some_and(|h| h.len() == 64 && h.bytes().all(|c| matches!(c, b'0'..=b'9' | b'a'..=b'f')));
            if r.resolved_url.as_ref() != url || r.canonical_url.as_ref() != url
                || r.content_type.as_deref() != Some("text/plain") || !hex64(&r.content_sha256)
                || !r.extraction.as_ref().is_some_and(|x| x.method == CORPUS_EXTRACTION_METHOD)
            {
                return Err(invalid(id, "corpus passage capture: URL fields, content_type, content_sha256 or extraction malformed"));
            }
        }
        CaptureOutcome::InvalidIdentifier => {
            if r.resolved_url.is_some() || r.canonical_url.is_some() || r.content_type.is_some()
                || r.content_sha256.is_some() || r.extraction.is_some() || r.content_length != 0
            {
                return Err(invalid(id, "corpus invalid_identifier capture carries content"));
            }
        }
        o => return Err(invalid(id, format!("outcome {o:?} impossible for a corpus capture"))),
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CaptureOutcome {
    Ok,
    OkNoText,
    NotFound,
    DnsNxdomain,
    InvalidIdentifier,
    HttpError,
    ConnectError,
    Timeout,
    TlsError,
    TooManyRedirects,
    RobotsDisallowed,
    BlockedSsrf,
    BlockedProxy,
    UnsupportedIdentifier,
}

/// Outcome class k(e) (§1.3, §3.2).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum OutcomeClass { ReachableText, Reachable, Dead, Transient }

impl CaptureOutcome {
    pub fn class(self) -> OutcomeClass {
        use CaptureOutcome::*;
        match self {
            Ok => OutcomeClass::ReachableText,
            OkNoText => OutcomeClass::Reachable,
            NotFound | DnsNxdomain | InvalidIdentifier | BlockedSsrf => OutcomeClass::Dead,
            HttpError | ConnectError | Timeout | TlsError | TooManyRedirects
            | RobotsDisallowed | BlockedProxy | UnsupportedIdentifier => OutcomeClass::Transient,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Redirect { pub url: String, pub status: i64 }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Extraction {
    pub method: String,
    pub method_version: String,
    pub text_sha256: String,
    pub text_chars: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Robots {
    pub checked: bool,
    pub allowed: Option<bool>,
    pub robots_sha256: Option<String>,
}

/// Sealed capture record. Telemetry (§1.2) lives in a sidecar and is
/// rejected here (`deny_unknown_fields`), so it can never enter A.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureRecord {
    pub format: String,
    pub requested: String,
    pub identifier_kind: IdentifierKind,
    pub request_url: String,
    pub redirects: Vec<Redirect>,
    pub resolved_url: Option<String>,
    pub canonical_url: Option<String>,
    pub http_status: Option<i64>,
    pub content_type: Option<String>,
    pub content_length: u64,
    pub truncated: bool,
    pub content_sha256: Option<String>,
    pub extraction: Option<Extraction>,
    pub outcome: CaptureOutcome,
    pub robots: Robots,
    pub license_note: Option<String>,
    pub capture_tool_version: String,
}

impl CaptureRecord {
    pub fn capture_id(&self) -> String { record_id(self) }
}

// ── bran-support/1 (§2.1) ───────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupportStatus { Ok, ParseError, Timeout, InputTooLong, ModelMismatch }

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SupportLabel { Supports, Refutes, NotEnoughInfo }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SupportClaim {
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub polarity: Polarity,
    pub raw_text: String,
}

impl SupportClaim {
    pub fn of(t: &CanonicalTriple, raw_text: &str) -> Self {
        Self {
            subject: t.subject.clone(),
            predicate: t.predicate.clone(),
            object: t.object.clone(),
            polarity: t.polarity,
            raw_text: raw_text.to_string(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Span { pub start: u64, pub end: u64, pub text: String }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SpanParams { pub k1_x1000: i64, pub b_x1000: i64, pub chunk_chars: u64, pub overlap_chars: u64 }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SpanSelector { pub method: String, pub version: String, pub params: SpanParams }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Decoding {
    pub temperature_x1000: i64,
    pub top_k: i64,
    pub top_p_x1000: i64,
    pub num_ctx: i64,
    pub num_predict: i64,
    pub seed: i64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Checker {
    pub checker_id: String,
    pub model: String,
    pub model_digest: String,
    pub prompt_template_sha256: String,
    pub decoding: Decoding,
    pub ollama_version: String,
    pub checker_tool_version: String,
}

impl Checker {
    /// `sha256_hex16(canonical_json({model, model_digest,
    /// prompt_template_sha256, decoding, checker_tool_version}))`;
    /// `ollama_version` is recorded but not part of the id (§2.1).
    pub fn compute_id(&self) -> String {
        record_id(&serde_json::json!({
            "model": self.model,
            "model_digest": self.model_digest,
            "prompt_template_sha256": self.prompt_template_sha256,
            "decoding": self.decoding,
            "checker_tool_version": self.checker_tool_version,
        }))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SupportRecord {
    pub format: String,
    pub contribution_id: String,
    pub claim: SupportClaim,
    pub capture_id: String,
    pub spans: Vec<Span>,
    pub span_selector: SpanSelector,
    pub checker: Checker,
    pub status: SupportStatus,
    pub label: Option<SupportLabel>,
    /// Confidence in `label` on the 10,000 scale (integer, no floats).
    pub score_q: Option<i64>,
    pub raw_output_sha256: Option<String>,
}

impl SupportRecord {
    pub fn support_id(&self) -> String { record_id(self) }
}

// ── Store ───────────────────────────────────────────────────

/// Sealed evidence records keyed by their ids. BTreeMaps, so insertion
/// order never reaches the canonical serialization.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceStore {
    #[serde(default)]
    pub captures: BTreeMap<String, CaptureRecord>,
    #[serde(default)]
    pub support: BTreeMap<String, SupportRecord>,
}

#[allow(dead_code)] // add_*: record builders for tests and fixtures
impl EvidenceStore {
    pub fn is_empty(&self) -> bool { self.captures.is_empty() && self.support.is_empty() }

    /// Insert a capture under its computed id; returns the id.
    pub fn add_capture(&mut self, r: CaptureRecord) -> String {
        let id = r.capture_id();
        self.captures.insert(id.clone(), r);
        id
    }

    /// Insert a support record under its computed id; returns the id.
    pub fn add_support(&mut self, r: SupportRecord) -> String {
        let id = r.support_id();
        self.support.insert(id.clone(), r);
        id
    }
}

/// Why a store cannot be sealed (or replayed).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SealError {
    /// A record's map key (or `checker_id`) is not the hash of its content.
    RecordHash { kind: &'static str, stored: String, recomputed: String },
    /// An evidence item references a record that is not in the store.
    Dangling { contribution_id: String, kind: &'static str, id: String },
    /// A record is malformed or inconsistent with the item referencing it.
    Invalid { id: String, reason: String },
}

impl std::fmt::Display for SealError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SealError::RecordHash { kind, stored, recomputed } =>
                write!(f, "{kind} id mismatch: stored {stored}, recomputed {recomputed}"),
            SealError::Dangling { contribution_id, kind, id } =>
                write!(f, "contribution {contribution_id}: dangling {kind} ref {id}"),
            SealError::Invalid { id, reason } => write!(f, "record {id}: {reason}"),
        }
    }
}

fn invalid(id: &str, reason: impl Into<String>) -> SealError {
    SealError::Invalid { id: id.to_string(), reason: reason.into() }
}

/// Check every record's own invariants: id = hash of content, format
/// tag, `checker_id`, label/score present iff status = ok, ranges.
pub fn verify_record_ids(store: &EvidenceStore) -> Result<(), SealError> {
    for (id, r) in &store.captures {
        let h = r.capture_id();
        if &h != id {
            return Err(SealError::RecordHash { kind: "capture", stored: id.clone(), recomputed: h });
        }
        if r.format != CAPTURE_FORMAT {
            return Err(invalid(id, format!("format {} (expected {CAPTURE_FORMAT})", r.format)));
        }
        if r.redirects.len() > 5 {
            return Err(invalid(id, "more than 5 redirects"));
        }
        if r.identifier_kind == IdentifierKind::Corpus {
            check_corpus_capture(id, r)?;
        }
    }
    for (id, r) in &store.support {
        let h = r.support_id();
        if &h != id {
            return Err(SealError::RecordHash { kind: "support", stored: id.clone(), recomputed: h });
        }
        let ch = r.checker.compute_id();
        if ch != r.checker.checker_id {
            return Err(SealError::RecordHash { kind: "checker", stored: r.checker.checker_id.clone(), recomputed: ch });
        }
        if r.format != SUPPORT_FORMAT {
            return Err(invalid(id, format!("format {} (expected {SUPPORT_FORMAT})", r.format)));
        }
        let ok = r.status == SupportStatus::Ok;
        if r.label.is_some() != ok || r.score_q.is_some() != ok {
            return Err(invalid(id, "label and score_q must be present iff status = ok"));
        }
        if let Some(q) = r.score_q && !(0..=10_000).contains(&q) {
            return Err(invalid(id, format!("score_q {q} outside 0..=10000")));
        }
        if r.spans.len() > 3 {
            return Err(invalid(id, "more than 3 spans"));
        }
        for s in &r.spans {
            if s.start > s.end || s.text.chars().count() > 1_000 {
                return Err(invalid(id, "span out of range or longer than 1000 chars"));
            }
        }
    }
    Ok(())
}

/// Validate `store` against the (canonical, P3-validated) contributions
/// and return it restricted to the referenced records (spec §3.1):
/// every id is the hash of its record; every ref resolves; a support
/// ref needs a capture ref; each support record names the referencing
/// contribution, its claim, and the item's capture, whose outcome is ok.
pub fn validate_store(contribs: &[Contribution], store: &EvidenceStore) -> Result<EvidenceStore, SealError> {
    verify_record_ids(store)?;
    let mut out = EvidenceStore::default();
    for c in contribs {
        for e in &c.evidence {
            let Some(cid) = &e.capture_ref else {
                if let Some(sid) = &e.support_ref {
                    return Err(invalid(sid, format!("contribution {}: support_ref without capture_ref", c.id)));
                }
                continue;
            };
            let cap = store.captures.get(cid).ok_or_else(|| SealError::Dangling {
                contribution_id: c.id.clone(), kind: "capture", id: cid.clone(),
            })?;
            out.captures.insert(cid.clone(), cap.clone());
            let Some(sid) = &e.support_ref else { continue };
            let sup = store.support.get(sid).ok_or_else(|| SealError::Dangling {
                contribution_id: c.id.clone(), kind: "support", id: sid.clone(),
            })?;
            if sup.contribution_id != c.id {
                return Err(invalid(sid, format!("contribution_id {} but referenced by {}", sup.contribution_id, c.id)));
            }
            if &sup.capture_id != cid {
                return Err(invalid(sid, format!("capture_id {} but item capture_ref is {cid}", sup.capture_id)));
            }
            let expected = c.canonical_form.as_ref().map(|t| SupportClaim::of(t, &c.raw_text));
            if expected.as_ref() != Some(&sup.claim) {
                return Err(invalid(sid, format!("claim differs from contribution {}", c.id)));
            }
            if cap.outcome != CaptureOutcome::Ok {
                return Err(invalid(sid, "support record for a capture whose outcome is not ok"));
            }
            out.support.insert(sid.clone(), sup.clone());
        }
    }
    Ok(out)
}

// ── Policy (§3.4) ───────────────────────────────────────────

fn unit<'de, D: Deserializer<'de>>(d: D) -> Result<f64, D::Error> {
    let v = f64::deserialize(d)?;
    if v.is_finite() && (0.0..=1.0).contains(&v) {
        Ok(v)
    } else {
        Err(serde::de::Error::custom(format!("evidence factor {v} outside [0, 1]")))
    }
}

fn policy_format<'de, D: Deserializer<'de>>(d: D) -> Result<String, D::Error> {
    let s = String::deserialize(d)?;
    if s == EVIDENCE_POLICY_FORMAT {
        Ok(s)
    } else {
        Err(serde::de::Error::custom(format!("evidence policy format {s} (expected {EVIDENCE_POLICY_FORMAT})")))
    }
}

/// Per-outcome-class factors (the transient class has no entry: it falls
/// back to the item's sealed fields).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OutcomeFactors {
    #[serde(deserialize_with = "unit")]
    pub reachable_text: f64,
    #[serde(deserialize_with = "unit")]
    pub reachable: f64,
    #[serde(deserialize_with = "unit")]
    pub dead: f64,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SupportFactors {
    #[serde(deserialize_with = "unit")]
    pub supports: f64,
    #[serde(deserialize_with = "unit")]
    pub not_enough_info: f64,
    #[serde(deserialize_with = "unit")]
    pub refutes: f64,
}

impl SupportFactors {
    pub fn get(&self, l: SupportLabel) -> f64 {
        match l {
            SupportLabel::Supports => self.supports,
            SupportLabel::NotEnoughInfo => self.not_enough_info,
            SupportLabel::Refutes => self.refutes,
        }
    }
}

/// Evidence scoring policy. Lives in `OverturnCompiler::evidence` and is
/// hashed with the rest of the config. Missing fields take the defaults
/// below; `accepted_checkers` is serialized only when non-empty.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct EvidencePolicy {
    #[serde(deserialize_with = "policy_format")]
    pub format: String,
    pub outcome_quality: OutcomeFactors,
    pub outcome_reach: OutcomeFactors,
    pub support_factor: SupportFactors,
    #[serde(deserialize_with = "unit")]
    pub unchecked_factor: f64,
    pub use_support_score: bool,
    pub xref_requires_support: bool,
    pub legacy_source_xref: bool,
    /// `checker_id`s whose validation report passed (§2.2). Labels from
    /// any other checker are scored as unchecked. Order-free: sorted and
    /// deduplicated in `canonical_policy_json`.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub accepted_checkers: Vec<String>,
    /// Verified-overturn gate ("verify, then vote"; `crate::gate`,
    /// `v3/GATE_SPEC.md`). `none` (default) = ungated selection. Serialized
    /// (and hashed) only when non-default, so every existing
    /// `bran-evidence-policy/1` hash is unchanged.
    #[serde(skip_serializing_if = "OverturnGate::is_none")]
    pub overturn_gate: OverturnGate,
}

/// Overturn gate of a contradiction slot (policy field
/// `evidence.overturn_gate`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum OverturnGate {
    /// Ungated: the policy score selects among all candidates.
    #[default]
    None,
    /// The plurality value (by distinct agents) is the default winner; the
    /// policy score selects among *verified* values (≥ 1 member carrying an
    /// accepted `supports` label) when there is one, else among the
    /// plurality values. See `crate::gate`.
    Verified,
}

impl OverturnGate {
    pub fn is_none(&self) -> bool { *self == OverturnGate::None }
}

/// `unchecked_factor` for grounded (local-corpus) runs, design §2.4 item
/// 6: an `ok` passage whose check was refused or failed scores
/// 0.85·0.75·0.5 = 0.319, the not-enough-info level, instead of 0.638
/// (the supported level). The default stays 1.0 (spec §7 Q1; v4 prereg).
pub const UNCHECKED_FACTOR_GROUNDED: f64 = 0.5;

#[allow(dead_code)] // used by v5 drivers through `--reduce` JSON and by tests
impl EvidencePolicy {
    /// The spec defaults with `unchecked_factor` = 0.5. The field is
    /// always serialized, so this differs from the default in exactly one
    /// hashed key; every existing `bran-evidence-policy/1` hash is unchanged.
    pub fn grounded(accepted_checkers: Vec<String>) -> Self {
        Self { unchecked_factor: UNCHECKED_FACTOR_GROUNDED, accepted_checkers, ..Self::default() }
    }
}

impl Default for EvidencePolicy {
    fn default() -> Self {
        Self {
            format: EVIDENCE_POLICY_FORMAT.to_string(),
            // Defaults reuse the verification table (ir.rs):
            // CONTENT_HASHED, REACHABILITY_CHECKED, STALE.
            outcome_quality: OutcomeFactors { reachable_text: 0.85, reachable: 0.70, dead: 0.20 },
            outcome_reach: OutcomeFactors { reachable_text: 0.75, reachable: 0.75, dead: 0.45 },
            support_factor: SupportFactors { supports: 1.0, not_enough_info: 0.5, refutes: 0.0 },
            unchecked_factor: 1.0,
            use_support_score: false,
            xref_requires_support: true,
            legacy_source_xref: false,
            accepted_checkers: Vec::new(),
            overturn_gate: OverturnGate::None,
        }
    }
}

// ── Factors (§3.2) ──────────────────────────────────────────

/// Per-item factors under the evidence policy.
#[derive(Debug, Clone, PartialEq)]
pub struct EvFactors {
    /// q'_e, source quality.
    pub q: f64,
    /// r'_e, reachability.
    pub r: f64,
    /// s_e, support.
    pub s: f64,
    /// Cross-reference key (`url:<canonical_url>` or, with
    /// `legacy_source_xref`, `src:<source lowercased>`).
    pub xref_key: Option<String>,
    /// Whether this item counts toward n(key).
    pub eligible_citer: bool,
}

/// Today's reachability rule on the sealed `reachable` flag.
fn legacy_reach(e: &EvidenceItem) -> f64 {
    match e.typ {
        EvidenceType::Citation | EvidenceType::ToolResult | EvidenceType::Empirical => {
            if e.reachable { 0.75 } else { 0.45 }
        }
        EvidenceType::Authority => 0.5,
        EvidenceType::Reasoning => 0.3,
    }
}

/// Effective support label: set iff the item has a support record for
/// this contribution with status ok from an accepted checker.
pub fn effective_label(
    e: &EvidenceItem,
    c: &Contribution,
    store: &EvidenceStore,
    pol: &EvidencePolicy,
) -> Option<(SupportLabel, i64)> {
    let sup = store.support.get(e.support_ref.as_ref()?)?;
    if sup.status != SupportStatus::Ok
        || sup.contribution_id != c.id
        || e.capture_ref.as_deref() != Some(sup.capture_id.as_str())
        || !pol.accepted_checkers.iter().any(|a| a == &sup.checker.checker_id)
    {
        return None;
    }
    Some((sup.label?, sup.score_q?))
}

/// Pure per-item factors (spec §3.2). Items without a capture record keep
/// today's q and r, get s = `unchecked_factor`, and an xref key only
/// under `legacy_source_xref`.
pub fn factors(e: &EvidenceItem, c: &Contribution, store: &EvidenceStore, pol: &EvidencePolicy) -> EvFactors {
    let r_legacy = legacy_reach(e);
    let Some(cap) = e.capture_ref.as_ref().and_then(|id| store.captures.get(id)) else {
        let xref_key = pol.legacy_source_xref.then(|| format!("src:{}", e.source.to_lowercase()));
        return EvFactors {
            q: e.source_quality(),
            r: r_legacy,
            s: pol.unchecked_factor,
            eligible_citer: xref_key.is_some(),
            xref_key,
        };
    };
    let class = cap.outcome.class();
    let q = match e.typ {
        EvidenceType::ToolResult | EvidenceType::Reasoning => 1.0,
        _ => match class {
            OutcomeClass::ReachableText => pol.outcome_quality.reachable_text,
            OutcomeClass::Reachable => pol.outcome_quality.reachable,
            OutcomeClass::Dead => pol.outcome_quality.dead,
            OutcomeClass::Transient => e.verification.quality_score(),
        },
    };
    let r = match e.typ {
        EvidenceType::Citation | EvidenceType::ToolResult | EvidenceType::Empirical => match class {
            OutcomeClass::ReachableText => pol.outcome_reach.reachable_text,
            OutcomeClass::Reachable => pol.outcome_reach.reachable,
            OutcomeClass::Dead => pol.outcome_reach.dead,
            OutcomeClass::Transient => r_legacy,
        },
        _ => r_legacy,
    };
    let label = effective_label(e, c, store, pol);
    let s = match label {
        Some((l, score_q)) => {
            let f = pol.support_factor.get(l);
            if pol.use_support_score { f * score_q as f64 / 10_000.0 } else { f }
        }
        None => pol.unchecked_factor,
    };
    let xref_key = match (class, &cap.canonical_url) {
        // Corpus passages: `corpus:<corpus_id>/<encoded key>` (addendum §1.3).
        (OutcomeClass::ReachableText | OutcomeClass::Reachable, Some(u)) if cap.identifier_kind == IdentifierKind::Corpus =>
            Some(format!("corpus:{}", u.strip_prefix(CORPUS_SCHEME).unwrap_or(u))),
        (OutcomeClass::ReachableText | OutcomeClass::Reachable, Some(u)) => Some(format!("url:{u}")),
        _ => None,
    };
    let eligible_citer = xref_key.is_some()
        && (!pol.xref_requires_support || matches!(label, Some((SupportLabel::Supports, _))));
    EvFactors { q, r, s, xref_key, eligible_citer }
}

/// key → distinct agent ids with an eligible citer under that key, over
/// all valid contributions.
pub fn citer_map(valid: &[Contribution], store: &EvidenceStore, pol: &EvidencePolicy) -> HashMap<String, HashSet<String>> {
    let mut m: HashMap<String, HashSet<String>> = HashMap::new();
    for c in valid {
        for e in &c.evidence {
            let f = factors(e, c, store, pol);
            if f.eligible_citer && let Some(k) = f.xref_key {
                m.entry(k).or_default().insert(c.agent_id.clone());
            }
        }
    }
    m
}

/// x'_e: 1.2 for ≥ 3 distinct eligible citing agents, 1.1 for 2, else
/// 0.9; an item that is not itself an eligible citer gets 0.9.
pub fn xref_multiplier(f: &EvFactors, citers: &HashMap<String, HashSet<String>>) -> f64 {
    if !f.eligible_citer {
        return 0.9;
    }
    let n = f.xref_key.as_ref().and_then(|k| citers.get(k)).map(|s| s.len()).unwrap_or(1);
    if n >= 3 { 1.2 } else if n >= 2 { 1.1 } else { 0.9 }
}

// ── Tests ───────────────────────────────────────────────────

#[cfg(test)]
pub(crate) mod fixtures {
    use super::*;
    use crate::ir::{ContributionKind, LoweringConfidence, make_id};

    pub fn capture(url: &str, outcome: CaptureOutcome) -> CaptureRecord {
        let ok = matches!(outcome, CaptureOutcome::Ok | CaptureOutcome::OkNoText);
        CaptureRecord {
            format: CAPTURE_FORMAT.into(),
            requested: url.into(),
            identifier_kind: IdentifierKind::Url,
            request_url: url.into(),
            redirects: vec![],
            resolved_url: ok.then(|| url.to_string()),
            canonical_url: ok.then(|| url.to_lowercase()),
            http_status: Some(if ok { 200 } else { 404 }),
            content_type: ok.then(|| "text/html".to_string()),
            content_length: if ok { 4096 } else { 0 },
            truncated: false,
            content_sha256: ok.then(|| format!("{:0>64}", make_id(url))),
            extraction: (outcome == CaptureOutcome::Ok).then(|| Extraction {
                method: "html-stdlib/1".into(),
                method_version: "1".into(),
                text_sha256: format!("{:f>64}", make_id(url)),
                text_chars: 1234,
            }),
            outcome,
            robots: Robots { checked: true, allowed: Some(true), robots_sha256: None },
            license_note: None,
            capture_tool_version: "0.1.0+fixture".into(),
        }
    }

    pub fn checker(model: &str) -> Checker {
        let mut ch = Checker {
            checker_id: String::new(),
            model: model.into(),
            model_digest: format!("sha256:{:0>64}", make_id(model)),
            prompt_template_sha256: format!("{:a>64}", make_id("prompt")),
            decoding: Decoding { temperature_x1000: 0, top_k: 1, top_p_x1000: 1000, num_ctx: 4096, num_predict: 64, seed: 42 },
            ollama_version: "0.5.0".into(),
            checker_tool_version: "0.1.0+fixture".into(),
        };
        ch.checker_id = ch.compute_id();
        ch
    }

    pub fn support(c: &Contribution, capture_id: &str, label: SupportLabel, ch: &Checker) -> SupportRecord {
        SupportRecord {
            format: SUPPORT_FORMAT.into(),
            contribution_id: c.id.clone(),
            claim: SupportClaim::of(c.canonical_form.as_ref().unwrap(), &c.raw_text),
            capture_id: capture_id.into(),
            spans: vec![Span { start: 10, end: 60, text: "Passage text — naïve “quotes”.".into() }],
            span_selector: SpanSelector {
                method: "bm25/1".into(),
                version: "1".into(),
                params: SpanParams { k1_x1000: 1200, b_x1000: 750, chunk_chars: 800, overlap_chars: 200 },
            },
            checker: ch.clone(),
            status: SupportStatus::Ok,
            label: Some(label),
            score_q: Some(9000),
            raw_output_sha256: Some(format!("{:b>64}", make_id("raw"))),
        }
    }

    pub fn contribution(agent: &str, object: &str, evidence: Vec<EvidenceItem>) -> Contribution {
        let triple = CanonicalTriple::new("TCP", "uses", object);
        let raw = format!("{agent}: TCP uses {object}");
        Contribution {
            id: make_id(&raw),
            agent_id: agent.into(),
            agent_name: agent.into(),
            kind: ContributionKind::Assertion,
            canonical_form: Some(triple),
            confidence: 0.8,
            evidence,
            raw_text: raw,
            lowering_confidence: LoweringConfidence::High,
            seq: 0,
            timestamp: 0.0,
            is_correct: true,
        }
    }

    pub fn citation(source: &str) -> EvidenceItem {
        EvidenceItem::new(EvidenceType::Citation, source, 1.0, true)
    }

    /// Attach fixture captures/support to simulated contributions (no
    /// network, no model): "RFC 793 Section 3.3" citations → one shared
    /// live page with support labels cycling supports, supports, NEI,
    /// refutes, and every fifth labelled by an unaccepted checker;
    /// "RFC 5681" → dead link; "Jacobson (1988) Congestion paper" → live,
    /// no text. Returns the store and the accepted checker id.
    pub fn attach(contribs: &mut [Contribution]) -> (EvidenceStore, String) {
        attach_with(contribs, [
            capture("https://www.rfc-editor.org/rfc/rfc793", CaptureOutcome::Ok),
            capture("https://www.rfc-editor.org/rfc/rfc5681-missing", CaptureOutcome::NotFound),
            capture("https://ee.lbl.gov/papers/congavoid.pdf", CaptureOutcome::OkNoText),
        ], false)
    }

    /// A `corpus` capture as `tools/evidence/corpus_capture.py` writes it
    /// (addendum §1.2): `Ok`/`OkNoText` for a found passage, otherwise
    /// `InvalidIdentifier`.
    pub fn corpus_capture(corpus_id: &str, encoded_key: &str, outcome: CaptureOutcome) -> CaptureRecord {
        let url = format!("{CORPUS_SCHEME}{corpus_id}/{encoded_key}");
        let found = matches!(outcome, CaptureOutcome::Ok | CaptureOutcome::OkNoText);
        let chars = if outcome == CaptureOutcome::Ok { 812 } else { 0 }; // ok_no_text = empty after normalization
        CaptureRecord {
            format: CAPTURE_FORMAT.into(),
            requested: url.clone(),
            identifier_kind: IdentifierKind::Corpus,
            request_url: url.clone(),
            redirects: vec![],
            resolved_url: found.then(|| url.clone()),
            canonical_url: found.then(|| url.clone()),
            http_status: None,
            content_type: found.then(|| "text/plain".to_string()),
            content_length: if found { chars } else { 0 },
            truncated: false,
            content_sha256: found.then(|| format!("{:0>64}", make_id(&url))),
            extraction: found.then(|| Extraction {
                method: CORPUS_EXTRACTION_METHOD.into(),
                method_version: "1".into(),
                text_sha256: format!("{:0>64}", make_id(&url)),
                text_chars: chars,
            }),
            outcome,
            robots: Robots { checked: false, allowed: None, robots_sha256: None },
            license_note: found.then(|| "cc-by-sa-3.0".to_string()),
            capture_tool_version: format!("0.1.0+fixture.c{:0>64}", make_id(corpus_id)),
        }
    }

    /// `attach` with corpus passages instead of web pages: the shared
    /// citation is one FEVER passage, the dead link is a key that is not
    /// in the corpus, the no-text page is an empty passage; and every fifth
    /// check (k % 5 == 3) is refused (status `parse_error`), so
    /// `unchecked_factor` matters.
    pub fn attach_corpus(contribs: &mut [Contribution]) -> (EvidenceStore, String) {
        attach_with(contribs, [
            corpus_capture("fever17", "fever17:Transmission_Control_Protocol:0", CaptureOutcome::Ok),
            corpus_capture("fever17", "fever17:RFC_5681_missing:0", CaptureOutcome::InvalidIdentifier),
            corpus_capture("fever17", "fever17:Blank:0", CaptureOutcome::OkNoText),
        ], true)
    }

    fn attach_with(contribs: &mut [Contribution], [live, dead, notext]: [CaptureRecord; 3], refuse: bool) -> (EvidenceStore, String) {
        let accepted = checker("judge-accepted");
        let rogue = checker("judge-unvalidated");
        let mut store = EvidenceStore::default();
        let live = store.add_capture(live);
        let dead = store.add_capture(dead);
        let notext = store.add_capture(notext);
        let mut k = 0usize;
        for c in contribs.iter_mut() {
            for i in 0..c.evidence.len() {
                let src = c.evidence[i].source.clone();
                if src == "RFC 793 Section 3.3" && c.canonical_form.is_some() {
                    let label = [SupportLabel::Supports, SupportLabel::Supports,
                                 SupportLabel::NotEnoughInfo, SupportLabel::Refutes][k % 4];
                    let ch = if k % 5 == 4 { &rogue } else { &accepted };
                    let mut sup = support(c, &live, label, ch);
                    if refuse && k % 5 == 3 {
                        (sup.status, sup.label, sup.score_q) = (SupportStatus::ParseError, None, None);
                    }
                    k += 1;
                    let sid = store.add_support(sup);
                    c.evidence[i].capture_ref = Some(live.clone());
                    c.evidence[i].support_ref = Some(sid);
                } else if src == "RFC 5681" {
                    c.evidence[i].capture_ref = Some(dead.clone());
                } else if src == "Jacobson (1988) Congestion paper" {
                    c.evidence[i].capture_ref = Some(notext.clone());
                }
            }
        }
        (store, accepted.checker_id)
    }
}

#[cfg(test)]
mod tests {
    use super::fixtures::*;
    use super::*;
    use crate::compiler::quantize;

    fn product(f: &EvFactors) -> i64 { quantize(f.q * f.r * f.s) }

    /// One CITATION item for `class × label × accepted`; returns its factors.
    fn cite_factors(outcome: Option<CaptureOutcome>, label: Option<SupportLabel>, accepted: bool) -> EvFactors {
        let ch = checker("judge");
        let mut store = EvidenceStore::default();
        let mut e = citation("https://example.org/a");
        let mut c = contribution("a", "x", vec![]);
        if let Some(o) = outcome {
            let cid = store.add_capture(capture("https://example.org/a", o));
            e.capture_ref = Some(cid.clone());
            if let Some(l) = label {
                e.support_ref = Some(store.add_support(support(&c, &cid, l, &ch)));
            }
        }
        c.evidence = vec![e];
        let pol = EvidencePolicy {
            accepted_checkers: if accepted { vec![ch.checker_id.clone()] } else { vec![] },
            ..EvidencePolicy::default()
        };
        validate_store(std::slice::from_ref(&c), &store).unwrap();
        factors(&c.evidence[0], &c, &store, &pol)
    }

    #[test]
    fn formula_table_matches_spec_quantized() {
        use CaptureOutcome as O;
        use SupportLabel as L;
        // §3.2 ordering table for a CITATION (q·r·s before w, t, x).
        assert_eq!(product(&cite_factors(Some(O::Ok), Some(L::Supports), true)), 6375); // 0.638
        assert_eq!(product(&cite_factors(Some(O::OkNoText), None, true)), 5250); // 0.525
        assert_eq!(product(&cite_factors(None, None, true)), 3000); // unchecked marker 0.300
        assert_eq!(product(&cite_factors(Some(O::Ok), Some(L::NotEnoughInfo), true)), 3188); // 0.319
        assert_eq!(product(&cite_factors(Some(O::NotFound), None, true)), 900); // dead 0.090
        assert_eq!(product(&cite_factors(Some(O::Ok), Some(L::Refutes), true)), 0); // refuted
        // Every class × label × accepted/unaccepted.
        let classes = [(O::Ok, 0.85, 0.75), (O::OkNoText, 0.70, 0.75), (O::DnsNxdomain, 0.20, 0.45),
                       (O::Timeout, 0.40, 0.75)];
        for (o, q, r) in classes {
            for label in [None, Some(L::Supports), Some(L::NotEnoughInfo), Some(L::Refutes)] {
                // Support records exist only for ok captures.
                if label.is_some() && o != O::Ok { continue; }
                for accepted in [true, false] {
                    let f = cite_factors(Some(o), label, accepted);
                    let s = match (label, accepted) {
                        (Some(l), true) => EvidencePolicy::default().support_factor.get(l),
                        _ => 1.0,
                    };
                    assert_eq!(product(&f), quantize(q * r * s), "{o:?} {label:?} accepted={accepted}");
                    assert_eq!(f.xref_key.is_some(), matches!(o, O::Ok | O::OkNoText));
                    assert_eq!(f.eligible_citer, accepted && label == Some(L::Supports));
                }
            }
        }
    }

    #[test]
    fn unaccepted_checker_scores_as_unchecked() {
        let f = cite_factors(Some(CaptureOutcome::Ok), Some(SupportLabel::Refutes), false);
        assert_eq!(f.s, EvidencePolicy::default().unchecked_factor);
        let unchecked = cite_factors(Some(CaptureOutcome::Ok), None, true);
        assert_eq!(f, unchecked);
    }

    #[test]
    fn refutes_zeroes_the_item() {
        let f = cite_factors(Some(CaptureOutcome::Ok), Some(SupportLabel::Refutes), true);
        assert_eq!(f.s, 0.0);
        assert!(!f.eligible_citer);
    }

    #[test]
    fn non_ok_support_status_is_unchecked() {
        let ch = checker("judge");
        let mut store = EvidenceStore::default();
        let mut c = contribution("a", "x", vec![]);
        let cid = store.add_capture(capture("https://e.org/", CaptureOutcome::Ok));
        let mut s = support(&c, &cid, SupportLabel::Refutes, &ch);
        s.status = SupportStatus::ParseError;
        s.label = None;
        s.score_q = None;
        let sid = store.add_support(s);
        let mut e = citation("https://e.org/");
        e.capture_ref = Some(cid);
        e.support_ref = Some(sid);
        c.evidence = vec![e];
        validate_store(std::slice::from_ref(&c), &store).unwrap();
        let pol = EvidencePolicy { accepted_checkers: vec![ch.checker_id.clone()], ..Default::default() };
        assert_eq!(factors(&c.evidence[0], &c, &store, &pol).s, 1.0);
    }

    #[test]
    fn use_support_score_scales_by_score_q() {
        let ch = checker("judge");
        let mut store = EvidenceStore::default();
        let mut c = contribution("a", "x", vec![]);
        let cid = store.add_capture(capture("https://e.org/", CaptureOutcome::Ok));
        let sid = store.add_support(support(&c, &cid, SupportLabel::NotEnoughInfo, &ch));
        let mut e = citation("https://e.org/");
        e.capture_ref = Some(cid);
        e.support_ref = Some(sid);
        c.evidence = vec![e];
        let pol = EvidencePolicy { accepted_checkers: vec![ch.checker_id.clone()], use_support_score: true, ..Default::default() };
        assert_eq!(factors(&c.evidence[0], &c, &store, &pol).s, 0.5 * 0.9);
    }

    #[test]
    fn intrinsic_types_keep_quality_one() {
        let mut store = EvidenceStore::default();
        let cid = store.add_capture(capture("https://e.org/", CaptureOutcome::NotFound));
        let mut e = EvidenceItem::new(EvidenceType::ToolResult, "https://e.org/", 1.0, true);
        e.capture_ref = Some(cid.clone());
        let c = contribution("a", "x", vec![e.clone()]);
        let f = factors(&e, &c, &store, &EvidencePolicy::default());
        assert_eq!((f.q, f.r), (1.0, 0.45));
        let mut a = EvidenceItem::new(EvidenceType::Authority, "https://e.org/", 1.0, true);
        a.capture_ref = Some(cid);
        let f = factors(&a, &c, &store, &EvidencePolicy::default());
        assert_eq!((f.q, f.r), (0.20, 0.5));
    }

    #[test]
    fn seal_errors() {
        let ch = checker("judge");
        let mut store = EvidenceStore::default();
        let c0 = contribution("a", "x", vec![]);
        let cid = store.add_capture(capture("https://e.org/", CaptureOutcome::Ok));
        let sid = store.add_support(support(&c0, &cid, SupportLabel::Supports, &ch));
        let with = |cap: Option<&str>, sup: Option<&str>| {
            let mut e = citation("https://e.org/");
            e.capture_ref = cap.map(str::to_string);
            e.support_ref = sup.map(str::to_string);
            let mut c = c0.clone();
            c.evidence = vec![e];
            c
        };
        // Valid, and restricted to referenced records.
        let mut extra = store.clone();
        extra.add_capture(capture("https://unused.org/", CaptureOutcome::Ok));
        let r = validate_store(&[with(Some(&cid), Some(&sid))], &extra).unwrap();
        assert_eq!(r, store);
        assert!(validate_store(&[with(Some(&cid), None)], &store).unwrap().support.is_empty());
        // Dangling refs.
        assert!(matches!(validate_store(&[with(Some("00"), None)], &store), Err(SealError::Dangling { kind: "capture", .. })));
        assert!(matches!(validate_store(&[with(Some(&cid), Some("00"))], &store), Err(SealError::Dangling { kind: "support", .. })));
        assert!(matches!(validate_store(&[with(None, Some(&sid))], &store), Err(SealError::Invalid { .. })));
        // Id mismatch.
        let mut bad = store.clone();
        bad.support.get_mut(&sid).unwrap().label = Some(SupportLabel::Refutes);
        assert!(matches!(validate_store(&[with(Some(&cid), Some(&sid))], &bad), Err(SealError::RecordHash { kind: "support", .. })));
        let mut bad = store.clone();
        bad.captures.get_mut(&cid).unwrap().outcome = CaptureOutcome::NotFound;
        assert!(matches!(validate_store(&[with(Some(&cid), None)], &bad), Err(SealError::RecordHash { kind: "capture", .. })));
        // Forged checker_id (support id recomputed, checker id not).
        let mut s = store.support[&sid].clone();
        s.checker.model_digest.push('0');
        let mut bad = store.clone();
        let sid2 = bad.add_support(s);
        assert!(matches!(validate_store(&[with(Some(&cid), Some(&sid2))], &bad), Err(SealError::RecordHash { kind: "checker", .. })));
        // Support record whose claim differs from its contribution.
        let mut s = store.support[&sid].clone();
        s.claim.object.push('!');
        let mut bad = store.clone();
        let sid3 = bad.add_support(s);
        assert!(matches!(validate_store(&[with(Some(&cid), Some(&sid3))], &bad), Err(SealError::Invalid { .. })));
        // ... or names another contribution.
        let other = contribution("b", "y", vec![]);
        let mut bad = store.clone();
        let sid4 = bad.add_support(support(&other, &cid, SupportLabel::Supports, &ch));
        assert!(matches!(validate_store(&[with(Some(&cid), Some(&sid4))], &bad), Err(SealError::Invalid { .. })));
        // Label present with a non-ok status.
        let mut s = store.support[&sid].clone();
        s.status = SupportStatus::Timeout;
        let mut bad = store.clone();
        let sid5 = bad.add_support(s);
        assert!(matches!(validate_store(&[with(Some(&cid), Some(&sid5))], &bad), Err(SealError::Invalid { .. })));
    }

    #[test]
    fn policy_rejects_out_of_range_and_unknown_fields() {
        let ok: EvidencePolicy = serde_json::from_str("{}").unwrap();
        assert_eq!(ok, EvidencePolicy::default());
        assert!(serde_json::from_str::<EvidencePolicy>(r#"{"unchecked_factor": 1.5}"#).is_err());
        assert!(serde_json::from_str::<EvidencePolicy>(r#"{"support_factor": {"supports": 1.0, "not_enough_info": 0.5, "refutes": -0.1}}"#).is_err());
        assert!(serde_json::from_str::<EvidencePolicy>(r#"{"format": "bran-evidence-policy/2"}"#).is_err());
        assert!(serde_json::from_str::<EvidencePolicy>(r#"{"accepted_checker": []}"#).is_err());
        let j = serde_json::to_string(&EvidencePolicy::default()).unwrap();
        assert!(!j.contains("accepted_checkers"));
    }

    #[test]
    fn telemetry_cannot_enter_a_record() {
        let mut v = serde_json::to_value(capture("https://e.org/", CaptureOutcome::Ok)).unwrap();
        v["fetched_at"] = "2026-10-21T00:00:00Z".into();
        assert!(serde_json::from_value::<CaptureRecord>(v).is_err());
    }

    /// Mutate one JSON leaf to a different value that still parses as `T`.
    fn mutate_leaf<T: serde::de::DeserializeOwned>(root: &serde_json::Value, path: &[String]) -> Option<T> {
        let alts: [serde_json::Value; 8] = [
            "x".into(), "not_found".into(), "refutes".into(), "NEGATE".into(), "doi".into(),
            "parse_error".into(), true.into(), 7.into(),
        ];
        let orig = path.iter().fold(root, |v, k| match v {
            serde_json::Value::Array(a) => &a[k.parse::<usize>().unwrap()],
            _ => &v[k.as_str()],
        });
        let mut cands: Vec<serde_json::Value> = match orig {
            serde_json::Value::String(s) => vec![format!("{s}x").into()],
            serde_json::Value::Number(n) => vec![(n.as_i64().unwrap() + 1).into()],
            serde_json::Value::Bool(b) => vec![(!b).into()],
            _ => vec![],
        };
        cands.extend(alts.iter().cloned());
        for cand in cands {
            if &cand == orig { continue; }
            let mut v = root.clone();
            let slot = path.iter().fold(&mut v, |v, k| match v {
                serde_json::Value::Array(a) => &mut a[k.parse::<usize>().unwrap()],
                _ => &mut v[k.as_str()],
            });
            *slot = cand;
            if let Ok(t) = serde_json::from_value(v) { return Some(t); }
        }
        None
    }

    fn leaf_paths(v: &serde_json::Value, prefix: Vec<String>, out: &mut Vec<Vec<String>>) {
        match v {
            serde_json::Value::Object(o) => for (k, x) in o { let mut p = prefix.clone(); p.push(k.clone()); leaf_paths(x, p, out) },
            serde_json::Value::Array(a) if !a.is_empty() => for (i, x) in a.iter().enumerate() { let mut p = prefix.clone(); p.push(i.to_string()); leaf_paths(x, p, out) },
            _ => out.push(prefix),
        }
    }

    /// Tamper test 5 (§4): every sealed field of both record types is
    /// covered by the record id and by the root hash.
    #[test]
    fn every_record_field_changes_ids_and_root() {
        every_field_sealed(capture("https://e.org/", CaptureOutcome::Ok));
    }

    /// Tamper test 5 on a corpus capture.
    #[test]
    fn every_corpus_record_field_changes_ids_and_root() {
        every_field_sealed(corpus_capture("fever17", "fever17:Pluto:0", CaptureOutcome::Ok));
    }

    fn every_field_sealed(mut cap: CaptureRecord) {
        use crate::ir::SealedArtifactSet;
        let ch = checker("judge");
        // Non-empty / non-null leaves so every field has a mutation (ids
        // and root only; the corpus shape check is not run here).
        cap.redirects = vec![Redirect { url: "http://e.org/".into(), status: 301 }];
        cap.license_note = Some("cc-by-4.0".into());
        cap.http_status = Some(200);
        cap.robots.allowed = Some(true);
        cap.robots.robots_sha256 = Some("r".repeat(64));
        let c0 = contribution("a", "x", vec![]);
        let sup = support(&c0, &cap.capture_id(), SupportLabel::Supports, &ch);
        let seal = |cap: &CaptureRecord, sup: &SupportRecord| {
            let mut store = EvidenceStore::default();
            store.add_capture(cap.clone());
            store.add_support(sup.clone());
            SealedArtifactSet::new("i", vec![], Default::default(), vec![c0.clone()]).with_evidence_store(Some(store)).root_hash
        };
        let root = seal(&cap, &sup);
        let (cv, sv) = (serde_json::to_value(&cap).unwrap(), serde_json::to_value(&sup).unwrap());
        let (mut cp, mut sp) = (Vec::new(), Vec::new());
        leaf_paths(&cv, vec![], &mut cp);
        leaf_paths(&sv, vec![], &mut sp);
        assert!(cp.len() >= 22 && sp.len() >= 25, "{} {}", cp.len(), sp.len());
        for p in &cp {
            let m: CaptureRecord = mutate_leaf(&cv, p).unwrap_or_else(|| panic!("no mutation for capture {p:?}"));
            assert_ne!(m.capture_id(), cap.capture_id(), "capture {p:?}");
            assert_ne!(seal(&m, &sup), root, "capture {p:?}");
        }
        for p in &sp {
            let m: SupportRecord = mutate_leaf(&sv, p).unwrap_or_else(|| panic!("no mutation for support {p:?}"));
            assert_ne!(m.support_id(), sup.support_id(), "support {p:?}");
            assert_ne!(seal(&cap, &m), root, "support {p:?}");
        }
    }

    /// Golden cross-language fixture (spec §3.5, capture acceptance 6): the
    /// ids below were computed independently with Python
    /// `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
    /// + SHA-256[:16] over `v2/evidence/fixtures/golden-records.json`.
    #[test]
    fn golden_cross_language_ids() {
        let text = include_str!("../../v2/evidence/fixtures/golden-records.json");
        let g: serde_json::Value = serde_json::from_str(text).unwrap();
        let cap: CaptureRecord = serde_json::from_value(g["capture"].clone()).unwrap();
        let sup: SupportRecord = serde_json::from_value(g["support"].clone()).unwrap();
        assert_eq!(canonical_json(&cap), g["capture_canonical"].as_str().unwrap());
        assert_eq!(cap.capture_id(), g["capture_id"].as_str().unwrap());
        assert_eq!(sup.checker.compute_id(), g["checker_id"].as_str().unwrap());
        assert_eq!(sup.checker.checker_id, g["checker_id"].as_str().unwrap());
        assert_eq!(sup.support_id(), g["support_id"].as_str().unwrap());
    }

    // ── Local corpus captures (v3 addendum) ─────────────────

    fn corpus_cite(store: &mut EvidenceStore, cap: CaptureRecord) -> EvidenceItem {
        let mut e = citation(&cap.requested.clone());
        e.capture_ref = Some(store.add_capture(cap));
        e
    }

    #[test]
    fn corpus_kind_and_url_parsing() {
        assert_eq!(serde_json::to_value(IdentifierKind::Corpus).unwrap(), "corpus");
        let ok = |u: &str| parse_corpus_url(u);
        assert_eq!(ok("corpus://fever17/fever17:Pluto:0"), Some(("fever17".into(), "fever17:Pluto:0".into())));
        assert_eq!(ok("corpus://fever17/fever17:AC%2FDC_%28band%29%23%C3%A9:2"),
                   Some(("fever17".into(), "fever17:AC/DC_(band)#é:2".into())));
        assert_eq!(ok("corpus://scifact-2020.v1/scifact:4983:0").map(|p| p.0), Some("scifact-2020.v1".into()));
        for bad in [
            "https://fever17/fever17:Pluto:0", // wrong scheme
            "corpus://Fever17/k",               // uppercase corpus id
            "corpus://fever17/",                // empty key
            "corpus://fever17",                 // no key
            "corpus:///k",                      // empty corpus id
            "corpus://fever17/a/b",             // raw '/'
            "corpus://fever17/a b",             // raw space
            "corpus://fever17/%c3%a9",          // lowercase hex
            "corpus://fever17/%41",             // verbatim char encoded
            "corpus://fever17/%3",              // truncated escape
            "corpus://fever17/%FF",             // not UTF-8
            "corpus://fever17/é",               // raw non-ASCII
        ] {
            assert_eq!(ok(bad), None, "{bad}");
        }
        assert!(ok(&format!("corpus://c/{}", "k".repeat(1024))).is_some());
        assert!(ok(&format!("corpus://c/{}", "k".repeat(1025))).is_none());
    }

    #[test]
    fn corpus_record_shape_enforced() {
        let good = corpus_capture("fever17", "fever17:Pluto:0", CaptureOutcome::Ok);
        for o in [CaptureOutcome::Ok, CaptureOutcome::OkNoText, CaptureOutcome::InvalidIdentifier] {
            let mut st = EvidenceStore::default();
            st.add_capture(corpus_capture("fever17", "fever17:Pluto:0", o));
            assert!(verify_record_ids(&st).is_ok(), "{o:?}");
        }
        let cases: Vec<(&str, Box<dyn Fn(&mut CaptureRecord)>)> = vec![
            ("redirect", Box::new(|r| r.redirects.push(Redirect { url: "corpus://x/y".into(), status: 301 }))),
            ("http_status", Box::new(|r| r.http_status = Some(200))),
            ("truncated", Box::new(|r| r.truncated = true)),
            ("robots checked", Box::new(|r| r.robots.checked = true)),
            ("https url", Box::new(|r| { let u = "https://fever17/k".to_string(); r.requested = u.clone(); r.request_url = u.clone(); r.resolved_url = Some(u.clone()); r.canonical_url = Some(u); })),
            ("non-canonical encoding", Box::new(|r| { let u = "corpus://fever17/%50luto".to_string(); r.requested = u.clone(); r.request_url = u.clone(); r.resolved_url = Some(u.clone()); r.canonical_url = Some(u); })),
            ("requested differs", Box::new(|r| r.requested = "P1".into())),
            ("canonical differs", Box::new(|r| r.canonical_url = Some("corpus://fever17/other".into()))),
            ("content type", Box::new(|r| r.content_type = Some("text/html".into()))),
            ("no content hash", Box::new(|r| r.content_sha256 = None)),
            ("short content hash", Box::new(|r| r.content_sha256 = Some("ab".into()))),
            ("html extraction", Box::new(|r| r.extraction.as_mut().unwrap().method = "html-stdlib/1".into())),
            ("fetch outcome", Box::new(|r| r.outcome = CaptureOutcome::NotFound)),
            ("invalid with content", Box::new(|r| r.outcome = CaptureOutcome::InvalidIdentifier)),
        ];
        for (name, m) in cases {
            let mut r = good.clone();
            m(&mut r);
            let mut st = EvidenceStore::default();
            st.add_capture(r);
            assert!(matches!(verify_record_ids(&st), Err(SealError::Invalid { .. })), "{name}");
        }
        // Web records are untouched by the corpus rule.
        let mut st = EvidenceStore::default();
        st.add_capture(capture("https://e.org/", CaptureOutcome::Ok));
        assert!(verify_record_ids(&st).is_ok());
    }

    /// Design §2.4 item 6: under the default unchecked_factor 1.0 a
    /// passage whose check was refused scores like a supported one; at
    /// 0.5 it scores at the not-enough-info level.
    #[test]
    fn corpus_factors_and_grounded_unchecked_factor() {
        use SupportLabel as L;
        let ch = checker("judge");
        let score = |outcome: CaptureOutcome, label: Option<L>, refused: bool, pol: &EvidencePolicy| {
            let mut store = EvidenceStore::default();
            let mut c = contribution("a", "x", vec![]);
            let mut e = corpus_cite(&mut store, corpus_capture("fever17", "fever17:TCP:0", outcome));
            if let Some(l) = label {
                let mut s = support(&c, e.capture_ref.as_ref().unwrap(), l, &ch);
                if refused { (s.status, s.label, s.score_q) = (SupportStatus::ParseError, None, None); }
                e.support_ref = Some(store.add_support(s));
            }
            c.evidence = vec![e];
            validate_store(std::slice::from_ref(&c), &store).unwrap();
            product(&factors(&c.evidence[0], &c, &store, pol))
        };
        let acc = vec![ch.checker_id.clone()];
        let (d, g) = (EvidencePolicy { accepted_checkers: acc.clone(), ..Default::default() }, EvidencePolicy::grounded(acc));
        assert_eq!(score(CaptureOutcome::Ok, Some(L::Supports), false, &d), 6375);
        assert_eq!(score(CaptureOutcome::Ok, Some(L::Supports), false, &g), 6375);
        assert_eq!(score(CaptureOutcome::Ok, Some(L::NotEnoughInfo), false, &g), 3188);
        assert_eq!(score(CaptureOutcome::Ok, Some(L::Refutes), false, &g), 0);
        // Refused check: 0.638 under the default, NEI level under grounded.
        assert_eq!(score(CaptureOutcome::Ok, Some(L::Supports), true, &d), 6375);
        assert_eq!(score(CaptureOutcome::Ok, Some(L::Supports), true, &g), 3188);
        assert_eq!(score(CaptureOutcome::Ok, None, false, &g), 3188);
        assert_eq!(score(CaptureOutcome::OkNoText, None, false, &d), 5250);
        assert_eq!(score(CaptureOutcome::OkNoText, None, false, &g), 2625);
        // Impossible passage id = dead.
        assert_eq!(score(CaptureOutcome::InvalidIdentifier, None, false, &d), 900);
        assert_eq!(score(CaptureOutcome::InvalidIdentifier, None, false, &g), 450);
    }

    #[test]
    fn corpus_xref_key_and_bonus() {
        let ch = checker("judge");
        let pol = EvidencePolicy::grounded(vec![ch.checker_id.clone()]);
        let mut store = EvidenceStore::default();
        let mut contribs: Vec<Contribution> = ["a", "b", "c"].iter().map(|a| contribution(a, "x", vec![])).collect();
        for c in contribs.iter_mut() {
            let mut e = corpus_cite(&mut store, corpus_capture("fever17", "fever17:AC%2FDC:0", CaptureOutcome::Ok));
            e.support_ref = Some(store.add_support(support(c, e.capture_ref.as_ref().unwrap(), SupportLabel::Supports, &ch)));
            // A web page whose canonical URL spells the same string never shares the key.
            let mut w = capture("corpus://fever17/fever17:AC%2FDC:0", CaptureOutcome::Ok);
            w.canonical_url = Some("corpus://fever17/fever17:AC%2FDC:0".into());
            let mut we = citation("w");
            we.capture_ref = Some(store.add_capture(w));
            c.evidence = vec![e, we];
        }
        validate_store(&contribs, &store).unwrap();
        let f = factors(&contribs[0].evidence[0], &contribs[0], &store, &pol);
        assert_eq!(f.xref_key.as_deref(), Some("corpus:fever17/fever17:AC%2FDC:0"));
        let w = factors(&contribs[0].evidence[1], &contribs[0], &store, &pol);
        assert_eq!(w.xref_key.as_deref(), Some("url:corpus://fever17/fever17:AC%2FDC:0"));
        let m = citer_map(&contribs, &store, &pol);
        assert_eq!(xref_multiplier(&f, &m), 1.2);
        assert_eq!(xref_multiplier(&w, &m), 0.9); // unchecked: not an eligible citer
        // Invalid passage ids have no key.
        let mut st = EvidenceStore::default();
        let e = corpus_cite(&mut st, corpus_capture("fever17", "P7", CaptureOutcome::InvalidIdentifier));
        assert_eq!(factors(&e, &contribs[0], &st, &pol).xref_key, None);
    }

    /// `unchecked_factor` is always serialized: the legacy default policy
    /// hash (no evidence key), the default evidence policy JSON and every
    /// committed hash are unchanged; the grounded value hashes apart.
    #[test]
    fn grounded_policy_serialization_and_hash() {
        use crate::compiler::OverturnCompiler;
        assert_eq!(OverturnCompiler::default().policy_hash(), "dd8d36e6def3a6d598765e82d461a473");
        let j = serde_json::to_string(&EvidencePolicy::default()).unwrap();
        assert!(j.contains("\"unchecked_factor\":1.0"), "{j}");
        let g = EvidencePolicy::grounded(vec![]);
        assert!(serde_json::to_string(&g).unwrap().contains("\"unchecked_factor\":0.5"));
        assert_eq!(serde_json::from_str::<EvidencePolicy>(r#"{"unchecked_factor": 0.5}"#).unwrap(), g);
        let with = |p: EvidencePolicy| OverturnCompiler { evidence: Some(p), ..OverturnCompiler::default() }.policy_hash();
        assert_ne!(with(EvidencePolicy::default()), with(g));
        // The committed /3 fixture's evidence policy (unchecked 1.0) still hashes to its stored value.
        let fx: serde_json::Value = serde_json::from_str(include_str!("../../v2/evidence/fixtures/tcp-evidence.bran-artifact-3.json")).unwrap();
        let pol: OverturnCompiler = serde_json::from_value(fx["policy"].clone()).unwrap();
        assert_eq!(pol.policy_hash(), fx["policy_hash"].as_str().unwrap());
        assert_eq!(pol.evidence.as_ref().unwrap().unchecked_factor, 1.0);
    }

    /// Golden cross-language corpus records: ids computed by
    /// `tools/evidence/corpus_capture.py` equal Rust's, and each record
    /// passes the corpus shape check.
    #[test]
    fn golden_corpus_capture_ids() {
        let g: serde_json::Value = serde_json::from_str(include_str!("../../tools/evidence/tests/golden/corpus_captures.json")).unwrap();
        let cases = g["cases"].as_array().unwrap();
        assert_eq!(cases.len(), 4);
        for case in cases {
            let name = case["name"].as_str().unwrap();
            let cap: CaptureRecord = serde_json::from_value(case["record"].clone()).unwrap();
            assert_eq!(cap.identifier_kind, IdentifierKind::Corpus, "{name}");
            assert_eq!(canonical_json(&cap), case["canonical_json"].as_str().unwrap(), "{name}");
            assert_eq!(cap.capture_id(), case["capture_id"].as_str().unwrap(), "{name}");
            let (cid, key) = parse_corpus_url(&cap.request_url).unwrap();
            assert_eq!((cid.as_str(), key.as_str()), (case["corpus_id"].as_str().unwrap(), case["passage_key"].as_str().unwrap()), "{name}");
            let mut st = EvidenceStore::default();
            st.add_capture(cap.clone());
            verify_record_ids(&st).unwrap_or_else(|e| panic!("{name}: {e}"));
            let mut e = citation("x");
            e.capture_ref = Some(cap.capture_id());
            let c = contribution("a", "x", vec![e.clone()]);
            assert_eq!(factors(&e, &c, &st, &EvidencePolicy::default()).xref_key.as_deref(), case["xref_key"].as_str(), "{name}");
        }
    }
}
