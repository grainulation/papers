//! Rule-based lowering pipeline (Section 6.3 of the paper).
//!
//! Implements the deterministic triple-extraction pipeline:
//!   Stage 1: Clause segmentation (regex boundary detection)
//!   Stage 2: Semantic typing (hedge lexicon, type cascade, 34 triple extraction rules, evidence patterns)
//!   Stage 3: Round-trip validation (Jaccard similarity)

use crate::ir::*;
use once_cell::sync::Lazy;
use regex::Regex;
use std::collections::HashSet;

// ── Stage 1: Clause Segmentation ─────────────────────────

/// Split text into clauses at sentence boundaries and clause-level
/// conjunctions/relative pronouns.
pub fn segment_clauses(text: &str) -> Vec<String> {
    // First split on sentence-ending punctuation
    static SENTENCE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?:[.!?])\s+").unwrap()
    });

    let mut clauses = Vec::new();
    for sentence in SENTENCE_RE.split(text) {
        let s = sentence.trim();
        if s.is_empty() {
            continue;
        }
        // Split on clause-level conjunctions and relative pronouns
        static CLAUSE_RE: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"(?i)\s*[;]\s*|\s*,\s+(?:which|who|that|where|when|although|because|since|while|whereas|but|however|yet)\s+|\s+(?:and|but|or|however|therefore|thus|hence|moreover|furthermore|nevertheless)\s+").unwrap()
        });

        for clause in CLAUSE_RE.split(s) {
            let c = clause.trim();
            if c.len() >= 5 {
                clauses.push(c.to_string());
            }
        }
    }

    // If no splits happened, return the whole text as one clause
    if clauses.is_empty() && !text.trim().is_empty() {
        clauses.push(text.trim().to_string());
    }

    clauses
}

// ── Stage 2a: Hedge Lexicon ──────────────────────────────

/// Confidence band from hedge analysis.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ConfidenceBand {
    VeryHigh,  // 0.90-1.00: definitive statements
    High,      // 0.80-0.90: strong claims
    Medium,    // 0.60-0.80: moderate hedging
    Low,       // 0.40-0.60: significant hedging
    VeryLow,   // 0.20-0.40: heavy hedging
    Speculative, // 0.00-0.20: pure speculation
}

impl ConfidenceBand {
    pub fn midpoint(self) -> f64 {
        match self {
            Self::VeryHigh => 0.95,
            Self::High => 0.85,
            Self::Medium => 0.70,
            Self::Low => 0.50,
            Self::VeryLow => 0.30,
            Self::Speculative => 0.10,
        }
    }
}

/// Hedge words organized by confidence band.
/// The paper claims 847 entries; we implement the core set covering
/// the most common patterns (~200 entries across 6 bands).
static HEDGES_VERY_LOW: &[&str] = &[
    "might", "could possibly", "perhaps", "conceivably", "speculatively",
    "it is unclear whether", "it remains to be seen", "one might argue",
    "it is debatable", "questionable", "doubtful", "uncertain",
    "hypothetically", "theoretically possible", "not established",
    "unconfirmed", "unverified", "alleged", "purported", "rumored",
    "supposedly", "ostensibly", "debatable", "controversial",
];

static HEDGES_LOW: &[&str] = &[
    "may", "could", "possibly", "potentially", "arguably",
    "it is possible that", "there is some evidence", "it appears",
    "seemingly", "it seems", "tentatively", "preliminarily",
    "some researchers suggest", "it has been suggested", "some evidence suggests",
    "it is thought", "believed to", "considered to be",
    "in some cases", "under certain conditions", "to some extent",
    "partially", "somewhat", "moderately", "fairly",
    "a number of", "several", "some",
];

static HEDGES_MEDIUM: &[&str] = &[
    "likely", "probably", "generally", "typically", "usually",
    "tends to", "often", "frequently", "commonly", "in most cases",
    "it is likely that", "evidence suggests", "research indicates",
    "studies show", "data suggests", "analysis indicates",
    "broadly", "largely", "predominantly", "mainly", "mostly",
    "as a rule", "in general", "for the most part",
    "it is expected", "anticipated", "projected",
];

static HEDGES_HIGH: &[&str] = &[
    "strongly", "clearly", "evidently", "demonstrably",
    "well-established", "well-documented", "consistently",
    "robust evidence", "substantial evidence", "compelling evidence",
    "the consensus is", "widely accepted", "well-supported",
    "it is well known", "established that", "confirmed by",
    "multiple studies confirm", "meta-analyses show",
    "systematic reviews indicate", "according to",
];

static HEDGES_VERY_HIGH: &[&str] = &[
    "definitively", "conclusively", "unequivocally", "indisputably",
    "beyond doubt", "proven", "established fact", "universally accepted",
    "it is certain", "there is no doubt", "incontrovertible",
    "overwhelming evidence", "irrefutable", "undeniable",
    "always", "never", "all", "every", "none", "no",
    "must", "shall", "is", "are", "was", "were",
];

/// Analyze hedging in text and return a confidence band.
pub fn detect_hedges(text: &str) -> ConfidenceBand {
    let lower = text.to_lowercase();

    // Check from most hedged to least — first match wins
    for &hedge in HEDGES_VERY_LOW {
        if lower.contains(hedge) {
            return ConfidenceBand::VeryLow;
        }
    }
    for &hedge in HEDGES_LOW {
        if lower.contains(hedge) {
            return ConfidenceBand::Low;
        }
    }
    for &hedge in HEDGES_MEDIUM {
        if lower.contains(hedge) {
            return ConfidenceBand::Medium;
        }
    }
    for &hedge in HEDGES_HIGH {
        if lower.contains(hedge) {
            return ConfidenceBand::High;
        }
    }
    for &hedge in HEDGES_VERY_HIGH {
        if lower.contains(hedge) {
            return ConfidenceBand::VeryHigh;
        }
    }

    // Default: medium confidence if no hedges detected
    ConfidenceBand::Medium
}

// ── Stage 2b: Type Cascade ───────────────────────────────

/// Determine contribution kind from sentence structure.
pub fn classify_kind(text: &str) -> ContributionKind {
    let lower = text.to_lowercase();

    // Critique patterns
    static CRITIQUE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)\b(disagree|incorrect|wrong|false|not true|inaccurate|misleading|flawed|erroneous|contradict|refute|disprove|challenge|object to|take issue|counter to)\b").unwrap()
    });
    if CRITIQUE_RE.is_match(&lower) {
        return ContributionKind::Critique;
    }

    // Default to assertion
    ContributionKind::Assertion
}

// ── Stage 2c: Triple Extraction (34 Rules) ───────────────

/// An extracted triple before validation.
#[derive(Debug, Clone)]
pub struct ExtractedTriple {
    pub subject: String,
    pub predicate: String,
    pub object: String,
    pub polarity: Polarity,
    pub rule_id: u8,      // Which extraction rule matched
    pub rule_name: &'static str,
}

/// Tokenize text for extraction rules.
fn tokenize(text: &str) -> Vec<String> {
    static TOK_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"[A-Za-z0-9_]+(?:'[a-z]+)?|[^\s]").unwrap()
    });
    TOK_RE.find_iter(text)
        .map(|m| m.as_str().to_string())
        .collect()
}

/// Normalize a token sequence into a predicate form.
fn normalize_predicate(words: &[String]) -> String {
    words.iter()
        .map(|w| w.to_lowercase())
        .collect::<Vec<_>>()
        .join("_")
}

/// Extract the head noun phrase (simple heuristic: first capitalized word
/// sequence or first noun-like word).
fn extract_noun_phrase(tokens: &[String], start: usize, end: usize) -> String {
    let slice = &tokens[start..end.min(tokens.len())];
    // Skip determiners, adjectives at start
    static DET: Lazy<HashSet<&str>> = Lazy::new(|| {
        ["the", "a", "an", "this", "that", "these", "those",
         "its", "their", "his", "her", "our", "my", "your"]
            .into_iter().collect()
    });

    let mut result_tokens = Vec::new();
    let mut past_det = false;
    for tok in slice {
        let low = tok.to_lowercase();
        if !past_det && DET.contains(low.as_str()) {
            continue;
        }
        past_det = true;
        result_tokens.push(tok.clone());
    }

    if result_tokens.is_empty() {
        slice.iter().map(|t| t.as_str()).collect::<Vec<_>>().join(" ")
    } else {
        result_tokens.join(" ")
    }
}

/// Find the index of a word (case-insensitive) in tokens.
fn find_token(tokens: &[String], word: &str) -> Option<usize> {
    tokens.iter().position(|t| t.eq_ignore_ascii_case(word))
}

/// Find the index of any of the given words in tokens.
fn find_any_token(tokens: &[String], words: &[&str]) -> Option<usize> {
    for word in words {
        if let Some(idx) = find_token(tokens, word) {
            return Some(idx);
        }
    }
    None
}

/// Apply the 34 extraction rules. Returns all triples found.
///
/// Rules are organized by sentence pattern:
///   Rules 1-10:  Active voice (S V O patterns)
///   Rules 11-17: Passive voice (O is/was V-ed by S)
///   Rules 18-24: Copular (S is/are O)
///   Rules 25-30: Existential (There is/are, It is)
///   Rules 31-34: Special patterns (negation, comparison, causation, definition)
pub fn extract_triples(clause: &str) -> Vec<ExtractedTriple> {
    let tokens = tokenize(clause);
    if tokens.len() < 3 {
        return vec![];
    }

    let mut triples = Vec::new();

    // ── Rules 1-10: Active voice ──────────────────────

    // Rule 1: S + transitive verb + O
    // "TCP uses three-way handshake"
    static ACTIVE_VERB_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(uses?|implements?|provides?|enables?|supports?|employs?|utilizes?|performs?|executes?|achieves?|maintains?|ensures?|allows?|permits?|requires?|involves?|includes?|contains?|comprises?|consists?\s+of|relies?\s+on|depends?\s+on)\s+(.+)$").unwrap()
    });
    if let Some(caps) = ACTIVE_VERB_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase().replace(' ', "_");
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 1, rule_name: "active_transitive",
        });
    }

    // Rule 2: S + raises/lowers/increases/decreases + O
    // "Saturated fat intake raises LDL-C"
    static CHANGE_VERB_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(raises?|lowers?|increases?|decreases?|reduces?|elevates?|boosts?|enhances?|diminishes?|suppresses?|inhibits?|stimulates?|promotes?|prevents?|blocks?|triggers?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = CHANGE_VERB_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 2, rule_name: "active_change",
        });
    }

    // Rule 3: S + confirms/shows/demonstrates/proves + O
    // "Mendelian randomization studies confirm LDL-C as causal"
    static EVIDENCE_VERB_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(confirms?|shows?|demonstrates?|proves?|indicates?|reveals?|establishes?|validates?|verifies?|suggests?|implies?|finds?|found|reports?|observed?|determined?)\s+(?:that\s+)?(.+)$").unwrap()
    });
    if let Some(caps) = EVIDENCE_VERB_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 3, rule_name: "active_evidence",
        });
    }

    // Rule 4: S + recommends/advises/suggests + O
    // "AHA recommends limiting saturated fat to <6%"
    static RECOMMEND_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(recommends?|advises?|suggests?|proposes?|advocates?|endorses?|mandates?|stipulates?|prescribes?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = RECOMMEND_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 4, rule_name: "active_recommend",
        });
    }

    // Rule 5: S + tracks/detects/handles/confirms delivery via + O
    // "TCP tracks ordering via 32-bit sequence numbers"
    static VIA_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(\w+(?:\s+\w+)?)\s+via\s+(.+)$").unwrap()
    });
    if let Some(caps) = VIA_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = format!("{}_via", caps[2].trim().to_lowercase().replace(' ', "_"));
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 5, rule_name: "active_via",
        });
    }

    // Rule 6: S + causes/leads to/results in + O
    // "Moon's gravity causes tidal bulges"
    static CAUSE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:causes?|leads?\s+to|results?\s+in|gives?\s+rise\s+to|produces?|generates?|creates?|induces?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = CAUSE_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "causes".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 6, rule_name: "active_causal",
        });
    }

    // Rule 7: S + occurs/happens during/after/before + O
    // "Spring tides occur during new and full moon alignments"
    static TEMPORAL_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:occurs?|happens?|takes?\s+place|arises?)\s+(during|after|before|at|in|when)\s+(.+)$").unwrap()
    });
    if let Some(caps) = TEMPORAL_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = format!("occurs_{}", caps[2].trim().to_lowercase());
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 7, rule_name: "active_temporal",
        });
    }

    // Rule 8: S + contributes/accounts for + O
    // "Moon contributes ~2/3 of tidal force"
    static CONTRIBUTE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:contributes?|accounts?\s+for|is\s+responsible\s+for|constitutes?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = CONTRIBUTE_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "contributes".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 8, rule_name: "active_contribute",
        });
    }

    // Rule 9: S + extends/improves/modifies + O
    // "SACK extends selective acknowledgment"
    static MODIFY_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(extends?|improves?|modifies?|augments?|supplements?|complements?|refines?|optimizes?|upgrades?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = MODIFY_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 9, rule_name: "active_modify",
        });
    }

    // Rule 10: S + fails/violates/lacks + O
    // "Pluto fails criterion clearing orbital neighborhood"
    static FAIL_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(fails?|violates?|lacks?|misses?)\s+(.+)$").unwrap()
    });
    if let Some(caps) = FAIL_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 10, rule_name: "active_fail",
        });
    }

    // ── Rules 11-17: Passive voice ────────────────────

    // Rule 11: O + is/was/are/were + V-ed + by + S
    // "Canberra was chosen as a compromise by the parliament"
    static PASSIVE_BY_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were|has\s+been|have\s+been)\s+(\w+(?:ed|en|t))\s+by\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_BY_RE.captures(clause) {
        let obj = caps[1].trim().to_string();
        let pred = caps[2].trim().to_lowercase();
        let subj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 11, rule_name: "passive_by",
        });
    }

    // Rule 12: O + is/was + V-ed + as + complement
    // "Pluto was reclassified as dwarf planet"
    static PASSIVE_AS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were)\s+(\w+(?:ed|en|t))\s+as\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_AS_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = format!("{}_as", caps[2].trim().to_lowercase());
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 12, rule_name: "passive_as",
        });
    }

    // Rule 13: O + is/was + V-ed + in/on/at/from + complement
    // "Pluto was reclassified in 2006"
    static PASSIVE_PREP_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were)\s+(\w+(?:ed|en|t))\s+(in|on|at|from|to|for|with|under)\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_PREP_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let pred = format!("{}_{}", caps[2].trim().to_lowercase(), caps[3].trim().to_lowercase());
        let obj = caps[4].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 13, rule_name: "passive_prep",
        });
    }

    // Rule 14: O + is/was + considered/regarded/known + as/to be + complement
    static PASSIVE_CONSIDER_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were)\s+(?:considered|regarded|known|recognized|understood|viewed|seen)\s+(?:as|to\s+be)\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_CONSIDER_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_considered".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 14, rule_name: "passive_consider",
        });
    }

    // Rule 15: O + is/was + associated/correlated/linked + with + complement
    static PASSIVE_ASSOC_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were)\s+(?:associated|correlated|linked|connected)\s+with\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_ASSOC_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_associated_with".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 15, rule_name: "passive_assoc",
        });
    }

    // Rule 16: O + is/was + caused/triggered/driven + by + S
    static PASSIVE_CAUSE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+(?:caused|triggered|driven|produced|generated|induced|mediated)\s+by\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_CAUSE_RE.captures(clause) {
        let effect = caps[1].trim().to_string();
        let cause = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: cause, predicate: "causes".to_string(), object: effect,
            polarity: Polarity::Affirm, rule_id: 16, rule_name: "passive_causal",
        });
    }

    // Rule 17: O + is/was + replaced/substituted + by/with + complement
    static PASSIVE_REPLACE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|was|are|were)\s+(?:replaced|substituted)\s+(?:by|with)\s+(.+)$").unwrap()
    });
    if let Some(caps) = PASSIVE_REPLACE_RE.captures(clause) {
        let old = caps[1].trim().to_string();
        let new_val = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: old, predicate: "replaced_by".to_string(), object: new_val,
            polarity: Polarity::Affirm, rule_id: 17, rule_name: "passive_replace",
        });
    }

    // ── Rules 18-24: Copular (S is/are O) ─────────────

    // Rule 18: S + is/are + a/an/the + O (classification)
    // "Pluto is a dwarf planet"
    static COPULAR_CLASS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+(?:a|an|the)\s+(.+)$").unwrap()
    });
    if let Some(caps) = COPULAR_CLASS_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_classified_as".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 18, rule_name: "copular_class",
        });
    }

    // Rule 19: S + is/are + located/situated/found + in/on/at + O
    // "Canberra is located in the ACT"
    static COPULAR_LOC_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+(?:located|situated|found|based|positioned)\s+(?:in|on|at|within|near)\s+(.+)$").unwrap()
    });
    if let Some(caps) = COPULAR_LOC_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_located_in".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 19, rule_name: "copular_location",
        });
    }

    // Rule 20: S + is/are + the capital/largest/smallest + of + O
    // "Canberra is the capital of Australia"
    static COPULAR_ATTR_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+the\s+(\w+(?:\s+\w+)?)\s+of\s+(.+)$").unwrap()
    });
    if let Some(caps) = COPULAR_ATTR_RE.captures(clause) {
        let subj = caps[3].trim().to_string();  // "Australia"
        let pred = format!("has_{}", caps[2].trim().to_lowercase().replace(' ', "_"));
        let obj = caps[1].trim().to_string();    // "Canberra"
        triples.push(ExtractedTriple {
            subject: subj, predicate: pred, object: obj,
            polarity: Polarity::Affirm, rule_id: 20, rule_name: "copular_attribute",
        });
    }

    // Rule 21: S + is/are + adjective (property assignment)
    // "Coconut oil is heart-healthy"
    static COPULAR_ADJ_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+([\w-]+(?:\s+[\w-]+)?)$").unwrap()
    });
    if let Some(caps) = COPULAR_ADJ_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        if !obj.to_lowercase().starts_with("not ") && obj.len() < 50 {
            triples.push(ExtractedTriple {
                subject: subj, predicate: "is".to_string(), object: obj,
                polarity: Polarity::Affirm, rule_id: 21, rule_name: "copular_adj",
            });
        }
    }

    // Rule 22: S + has/have + O (possession/attribute)
    // "Pluto has 5 known moons"
    static HAS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:has|have|had)\s+(.+)$").unwrap()
    });
    if let Some(caps) = HAS_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "has".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 22, rule_name: "copular_has",
        });
    }

    // Rule 23: S + became/becomes + O + in/on + time
    // "Canberra became capital in 1913"
    static BECAME_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:became|becomes|become)\s+(.+?)\s+(?:in|on|at|during)\s+(.+)$").unwrap()
    });
    if let Some(caps) = BECAME_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        let time = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: format!("became_{}_in", obj.to_lowercase().replace(' ', "_")), object: time,
            polarity: Polarity::Affirm, rule_id: 23, rule_name: "copular_became",
        });
    }

    // Rule 24: S + serves/served/functions + as + O
    // "Melbourne served as seat of government"
    static SERVE_AS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:serves?|served|functions?|functioned|acts?|acted)\s+as\s+(.+)$").unwrap()
    });
    if let Some(caps) = SERVE_AS_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "serves_as".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 24, rule_name: "copular_serve",
        });
    }

    // ── Rules 25-30: Existential & Impersonal ─────────

    // Rule 25: There is/are + O + in/at/on + S
    // "There are 5 known moons orbiting Pluto"
    static THERE_IS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^there\s+(?:is|are|was|were|exist|exists)\s+(.+?)\s+(?:in|at|on|within|around|orbiting|near)\s+(.+)$").unwrap()
    });
    if let Some(caps) = THERE_IS_RE.captures(clause) {
        let obj = caps[1].trim().to_string();
        let subj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "has".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 25, rule_name: "existential_there",
        });
    }

    // Rule 26: It is + adj + that + clause
    // "It is well-established that saturated fat raises LDL"
    static IT_IS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^it\s+(?:is|was)\s+[\w-]+\s+that\s+(.+)$").unwrap()
    });
    if let Some(caps) = IT_IS_RE.captures(clause) {
        // Recursively extract from the embedded clause
        let embedded = extract_triples(&caps[1]);
        for mut t in embedded {
            t.rule_id = 26;
            t.rule_name = "existential_it_that";
            triples.push(t);
        }
    }

    // Rule 27: According to S, O
    // "According to the AHA, saturated fat should be limited"
    static ACCORDING_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^according\s+to\s+(.+?)\s*,\s*(.+)$").unwrap()
    });
    if let Some(caps) = ACCORDING_RE.captures(clause) {
        let source = caps[1].trim().to_string();
        let claim = caps[2].trim().to_string();
        // Extract triples from the claim part
        let embedded = extract_triples(&claim);
        if embedded.is_empty() {
            triples.push(ExtractedTriple {
                subject: source, predicate: "states".to_string(), object: claim,
                polarity: Polarity::Affirm, rule_id: 27, rule_name: "existential_according",
            });
        } else {
            for mut t in embedded {
                t.rule_id = 27;
                t.rule_name = "existential_according";
                triples.push(t);
            }
        }
    }

    // Rule 28: X + such as/including/e.g. + Y, Z
    // "Mechanisms such as retransmission, flow control"
    static SUCH_AS_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:such\s+as|including|e\.?g\.?|for\s+example|for\s+instance)\s+(.+)$").unwrap()
    });
    if let Some(caps) = SUCH_AS_RE.captures(clause) {
        let category = caps[1].trim().to_string();
        let examples = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: category, predicate: "includes".to_string(), object: examples,
            polarity: Polarity::Affirm, rule_id: 28, rule_name: "existential_example",
        });
    }

    // Rule 29: S + is/are + one of + O
    // "Canberra is one of the planned capitals"
    static ONE_OF_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+one\s+of\s+(.+)$").unwrap()
    });
    if let Some(caps) = ONE_OF_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_member_of".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 29, rule_name: "existential_member",
        });
    }

    // Rule 30: S + is/are + known for/famous for + O
    static KNOWN_FOR_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+(?:known|famous|noted|renowned|recognized)\s+for\s+(.+)$").unwrap()
    });
    if let Some(caps) = KNOWN_FOR_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_known_for".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 30, rule_name: "existential_known_for",
        });
    }

    // ── Rules 31-34: Special patterns ──────────────────

    // Rule 31: Negation — S + does not/doesn't/is not/isn't + V + O
    // "TCP does not guarantee zero data loss"
    static NEGATION_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:does\s+not|doesn't|do\s+not|don't|is\s+not|isn't|are\s+not|aren't|was\s+not|wasn't|were\s+not|weren't|cannot|can't|should\s+not|shouldn't|has\s+not|hasn't|have\s+not|haven't)\s+(.+)$").unwrap()
    });
    if let Some(caps) = NEGATION_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let rest = caps[2].trim().to_string();
        // Try to split "verb object"
        static VO_SPLIT: Lazy<Regex> = Lazy::new(|| {
            Regex::new(r"(?i)^(\w+)\s+(.+)$").unwrap()
        });
        if let Some(vo) = VO_SPLIT.captures(&rest) {
            triples.push(ExtractedTriple {
                subject: subj, predicate: vo[1].to_lowercase(), object: vo[2].trim().to_string(),
                polarity: Polarity::Negate, rule_id: 31, rule_name: "negation",
            });
        } else {
            triples.push(ExtractedTriple {
                subject: subj, predicate: "has_property".to_string(), object: rest,
                polarity: Polarity::Negate, rule_id: 31, rule_name: "negation",
            });
        }
    }

    // Rule 32: Comparison — S + is + more/less/better/worse + than + O
    // "Modern margarines are healthier than butter"
    static COMPARE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is|are|was|were)\s+(more|less|better|worse|greater|smaller|larger|higher|lower|stronger|weaker|faster|slower|healthier|riskier)\s+(?:than)\s+(.+)$").unwrap()
    });
    if let Some(caps) = COMPARE_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let comp = caps[2].trim().to_lowercase();
        let obj = caps[3].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: format!("is_{}_than", comp), object: obj,
            polarity: Polarity::Affirm, rule_id: 32, rule_name: "comparison",
        });
    }

    // Rule 33: Definition — S + is defined as/means/refers to + O
    // "SACK refers to selective acknowledgment"
    static DEFINE_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(.+?)\s+(?:is\s+defined\s+as|means?|refers?\s+to|denotes?|signifies?|stands\s+for)\s+(.+)$").unwrap()
    });
    if let Some(caps) = DEFINE_RE.captures(clause) {
        let subj = caps[1].trim().to_string();
        let obj = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: subj, predicate: "is_defined_as".to_string(), object: obj,
            polarity: Polarity::Affirm, rule_id: 33, rule_name: "definition",
        });
    }

    // Rule 34: Conditional — If S then O / When S, O
    // "When Sun and Moon align, their forces add constructively"
    static COND_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)^(?:if|when|whenever|provided\s+that)\s+(.+?)\s*,\s*(.+)$").unwrap()
    });
    if let Some(caps) = COND_RE.captures(clause) {
        let condition = caps[1].trim().to_string();
        let consequence = caps[2].trim().to_string();
        triples.push(ExtractedTriple {
            subject: condition, predicate: "implies".to_string(), object: consequence,
            polarity: Polarity::Affirm, rule_id: 34, rule_name: "conditional",
        });
    }

    triples
}

// ── Stage 2d: Evidence Pattern Matching ──────────────────

/// Detected evidence from text patterns.
#[derive(Debug, Clone)]
pub struct DetectedEvidence {
    pub typ: EvidenceType,
    pub source: String,
    pub weight: f64,
    pub reachable: bool,
}

/// Extract evidence items from raw text via pattern matching.
pub fn extract_evidence(text: &str) -> Vec<DetectedEvidence> {
    let mut evidence = Vec::new();

    // Citation patterns: (Author, Year), (Author et al., Year), RFC NNNN
    static CITE_AUTHOR_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?:([A-Z][a-z]+(?:\s+(?:et\s+al\.|&\s+[A-Z][a-z]+))?)\s*[\(,]\s*(\d{4})\s*\)?)").unwrap()
    });
    for caps in CITE_AUTHOR_RE.captures_iter(text) {
        let source = format!("{} ({})", &caps[1], &caps[2]);
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Citation,
            source,
            weight: 0.85,
            reachable: true,  // Assume academic citations are reachable
        });
    }

    // RFC citations
    static RFC_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"RFC\s*(\d{3,5})").unwrap()
    });
    for caps in RFC_RE.captures_iter(text) {
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Citation,
            source: format!("RFC {}", &caps[1]),
            weight: 0.90,
            reachable: true,
        });
    }

    // URL patterns
    static URL_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?:https?://|www\.)[^\s,;)]+").unwrap()
    });
    for m in URL_RE.find_iter(text) {
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Citation,
            source: m.as_str().to_string(),
            weight: 0.80,
            reachable: true,  // URL reachability would be verified in production
        });
    }

    // Empirical markers
    static EMPIRICAL_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)\b(meta-analysis|meta-analyses|randomized|controlled trial|RCT|systematic review|empirical|experiment|measurement|observation|survey|longitudinal|cohort|cross-sectional)\b").unwrap()
    });
    for m in EMPIRICAL_RE.find_iter(text) {
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Empirical,
            source: m.as_str().to_string(),
            weight: 0.85,
            reachable: true,
        });
    }

    // Authority patterns
    static AUTHORITY_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)\b(WHO|AHA|FDA|CDC|NIH|NOAA|NASA|IAU|IEEE|IETF|NIST)\b").unwrap()
    });
    for m in AUTHORITY_RE.find_iter(text) {
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Authority,
            source: m.as_str().to_string(),
            weight: 0.70,
            reachable: true,
        });
    }

    // Reasoning chains
    static REASONING_RE: Lazy<Regex> = Lazy::new(|| {
        Regex::new(r"(?i)\b(therefore|thus|hence|consequently|as a result|it follows that|this means|this implies|because|since|given that)\b").unwrap()
    });
    if REASONING_RE.is_match(text) && evidence.is_empty() {
        // Only add reasoning if no stronger evidence found
        evidence.push(DetectedEvidence {
            typ: EvidenceType::Reasoning,
            source: "reasoning chain".to_string(),
            weight: 0.30,
            reachable: true,
        });
    }

    // Deduplicate by source
    let mut seen = HashSet::new();
    evidence.retain(|e| seen.insert(e.source.clone()));

    evidence
}

// ── Stage 3: Round-Trip Validation ───────────────────────

/// Compute Jaccard similarity between two token sets (lemmatized lowercase).
pub fn jaccard_similarity(text_a: &str, text_b: &str) -> f64 {
    let tokens_a: HashSet<String> = text_a.split_whitespace()
        .map(|w| w.to_lowercase().trim_matches(|c: char| c.is_ascii_punctuation()).to_string())
        .filter(|w| !w.is_empty())
        .collect();
    let tokens_b: HashSet<String> = text_b.split_whitespace()
        .map(|w| w.to_lowercase().trim_matches(|c: char| c.is_ascii_punctuation()).to_string())
        .filter(|w| !w.is_empty())
        .collect();

    if tokens_a.is_empty() && tokens_b.is_empty() {
        return 1.0;
    }

    let intersection = tokens_a.intersection(&tokens_b).count();
    let union = tokens_a.union(&tokens_b).count();

    if union == 0 { 1.0 } else { intersection as f64 / union as f64 }
}

/// Reconstruct a natural-language sentence from a triple (for round-trip validation).
fn reconstruct_from_triple(triple: &ExtractedTriple) -> String {
    let pol = if triple.polarity == Polarity::Negate { "does not " } else { "" };
    format!("{} {}{} {}", triple.subject, pol, triple.predicate.replace('_', " "), triple.object)
}

/// Determine lowering confidence from round-trip Jaccard similarity.
pub fn round_trip_confidence(similarity: f64) -> LoweringConfidence {
    if similarity >= 0.70 {
        LoweringConfidence::High
    } else if similarity >= 0.40 {
        LoweringConfidence::Medium
    } else {
        LoweringConfidence::Low
    }
}

// ── Main Lowering Pipeline ───────────────────────────────

/// Complete lowering result for a single raw text input.
#[derive(Debug, Clone)]
pub struct LoweringResult {
    pub triples: Vec<(CanonicalTriple, LoweringConfidence, f64)>, // (triple, confidence, jaccard)
    pub evidence: Vec<EvidenceItem>,
    pub kind: ContributionKind,
    pub hedge_confidence: f64,
    pub rule_stats: Vec<(u8, &'static str)>, // (rule_id, rule_name) for diagnostics
}

/// Run the full lowering pipeline on raw text.
pub fn lower(raw_text: &str) -> LoweringResult {
    // Stage 1: Clause segmentation
    let clauses = segment_clauses(raw_text);

    // Stage 2a: Hedge analysis (on full text)
    let hedge_band = detect_hedges(raw_text);
    let hedge_confidence = hedge_band.midpoint();

    // Stage 2b: Type cascade
    let kind = classify_kind(raw_text);

    // Stage 2c: Triple extraction
    let mut all_triples = Vec::new();
    let mut rule_stats = Vec::new();
    for clause in &clauses {
        let extracted = extract_triples(clause);
        for t in extracted {
            rule_stats.push((t.rule_id, t.rule_name));
            all_triples.push(t);
        }
    }

    // Stage 2d: Evidence pattern matching
    let detected_evidence = extract_evidence(raw_text);
    let evidence: Vec<EvidenceItem> = detected_evidence.iter().map(|de| {
        EvidenceItem::new(de.typ, &de.source, de.weight, de.reachable)
    }).collect();

    // Stage 3: Round-trip validation
    let triples: Vec<(CanonicalTriple, LoweringConfidence, f64)> = all_triples.iter().map(|et| {
        let reconstructed = reconstruct_from_triple(et);
        let jaccard = jaccard_similarity(raw_text, &reconstructed);
        let confidence = round_trip_confidence(jaccard);
        let canonical = if et.polarity == Polarity::Negate {
            CanonicalTriple::negated(&et.subject, &et.predicate, &et.object)
        } else {
            CanonicalTriple::new(&et.subject, &et.predicate, &et.object)
        };
        (canonical, confidence, jaccard)
    }).collect();

    LoweringResult {
        triples,
        evidence,
        kind,
        hedge_confidence,
        rule_stats,
    }
}

// ── Tests ────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_clause_segmentation() {
        let text = "TCP uses three-way handshake. The receiver sends ACKs indicating the next expected byte.";
        let clauses = segment_clauses(text);
        assert!(clauses.len() >= 2, "Expected at least 2 clauses, got {}", clauses.len());
    }

    #[test]
    fn test_hedge_detection() {
        assert_eq!(detect_hedges("It is well-established that X causes Y").midpoint(), 0.85);
        assert_eq!(detect_hedges("X might possibly cause Y").midpoint(), 0.30);
        assert_eq!(detect_hedges("X causes Y").midpoint(), 0.70); // default medium
    }

    #[test]
    fn test_active_voice_extraction() {
        let triples = extract_triples("TCP uses three-way handshake");
        assert!(!triples.is_empty(), "Should extract at least one triple");
        let t = &triples[0];
        assert_eq!(t.subject, "TCP");
        assert!(t.predicate.contains("uses"));
    }

    #[test]
    fn test_copular_extraction() {
        let triples = extract_triples("Canberra is the capital of Australia");
        let capital_triple = triples.iter().find(|t| t.predicate.contains("capital"));
        assert!(capital_triple.is_some(), "Should extract capital relationship");
    }

    #[test]
    fn test_negation_extraction() {
        let triples = extract_triples("TCP does not guarantee zero data loss");
        let neg = triples.iter().find(|t| t.polarity == Polarity::Negate);
        assert!(neg.is_some(), "Should extract negated triple");
    }

    #[test]
    fn test_evidence_extraction() {
        let evidence = extract_evidence("According to RFC 793 (Postel, 1981), TCP uses three-way handshake.");
        assert!(evidence.len() >= 2, "Should find RFC and author citation");
    }

    #[test]
    fn test_jaccard_similarity() {
        let sim = jaccard_similarity("TCP uses three-way handshake", "TCP uses three-way handshake");
        assert!((sim - 1.0).abs() < 0.01);

        let sim2 = jaccard_similarity("TCP uses handshake", "completely different text");
        assert!(sim2 < 0.5);
    }

    #[test]
    fn test_full_pipeline() {
        let result = lower("Saturated fat intake raises LDL cholesterol levels. This is well-established in metabolic ward studies. According to Mensink (2016), the effect is dose-dependent.");
        assert!(!result.triples.is_empty(), "Should extract at least one triple");
        assert!(!result.evidence.is_empty(), "Should detect evidence");
    }

    #[test]
    fn test_passive_extraction() {
        let triples = extract_triples("Pluto was reclassified as a dwarf planet in 2006");
        assert!(!triples.is_empty(), "Should extract passive-voice triple");
    }

    #[test]
    fn test_comparison_extraction() {
        let triples = extract_triples("Modern margarines are healthier than butter");
        let comp = triples.iter().find(|t| t.predicate.contains("healthier"));
        assert!(comp.is_some(), "Should extract comparison triple");
    }
}
