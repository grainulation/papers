use crate::ir::*;
use crate::topics::Topic;
use rand::Rng;
use rand_chacha::ChaCha8Rng;

// ── Archetype ──────────────────────────────────────────────

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Archetype {
    Expert,
    Generalist,
    Contrarian,
    Copier,
    Hallucinator,
}

impl std::fmt::Display for Archetype {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Expert => write!(f, "EXPERT"),
            Self::Generalist => write!(f, "GENERALIST"),
            Self::Contrarian => write!(f, "CONTRARIAN"),
            Self::Copier => write!(f, "COPIER"),
            Self::Hallucinator => write!(f, "HALLUCINATOR"),
        }
    }
}

// ── Agent Personality ──────────────────────────────────────

#[derive(Debug, Clone)]
pub struct AgentPersonality {
    pub name: String,
    pub archetype: Archetype,
    pub model_family: String,
    pub calibration: f64,
    pub trust: f64,
    pub lowering_quality: LoweringConfidence,
}

fn parse_evidence_type(s: &str) -> EvidenceType {
    match s {
        "TOOL_RESULT" => EvidenceType::ToolResult,
        "EMPIRICAL" => EvidenceType::Empirical,
        "CITATION" => EvidenceType::Citation,
        "AUTHORITY" => EvidenceType::Authority,
        _ => EvidenceType::Reasoning,
    }
}

/// Pick `k` random indices from `0..n` using Fisher-Yates partial shuffle.
fn sample_indices(n: usize, k: usize, rng: &mut ChaCha8Rng) -> Vec<usize> {
    let k = k.min(n);
    let mut indices: Vec<usize> = (0..n).collect();
    for i in 0..k {
        let j = rng.gen_range(i..n);
        indices.swap(i, j);
    }
    indices.truncate(k);
    indices
}

impl AgentPersonality {
    pub fn new(
        name: &str,
        archetype: Archetype,
        model_family: &str,
        calibration: f64,
        trust: f64,
        lowering_quality: LoweringConfidence,
    ) -> Self {
        Self {
            name: name.to_string(),
            archetype,
            model_family: model_family.to_string(),
            calibration,
            trust,
            lowering_quality,
        }
    }

    pub fn generate_claims(
        &self,
        topic: &Topic,
        existing_claims: &[Contribution],
        rng: &mut ChaCha8Rng,
    ) -> Vec<Contribution> {
        let mut claims = Vec::new();
        let facts = &topic.facts;
        let miscon = &topic.misconceptions;
        let nuances = &topic.nuances;

        match self.archetype {
            Archetype::Expert => {
                // Pick 1-2 random facts with high confidence
                let k = 2.min(facts.len());
                let indices = sample_indices(facts.len(), k, rng);
                for idx in indices {
                    let conf = rng.gen_range(0.88..0.96);
                    claims.push(self.make_claim(&facts[idx], conf, true));
                }
                // 40% chance to add a nuance
                if !nuances.is_empty() && rng.r#gen::<f64>() > 0.4 {
                    let ni = rng.gen_range(0..nuances.len());
                    let conf = rng.gen_range(0.80..0.90);
                    claims.push(self.make_claim(&nuances[ni], conf, true));
                }
            }

            Archetype::Generalist => {
                // Pick 1 random fact, medium confidence
                let fi = rng.gen_range(0..facts.len());
                let conf = rng.gen_range(0.65..0.80);
                claims.push(self.make_claim(&facts[fi], conf, true));
                // 30% chance to add a misconception
                if rng.r#gen::<f64>() > 0.7 && !miscon.is_empty() {
                    let mi = rng.gen_range(0..miscon.len());
                    let conf = rng.gen_range(0.40..0.55);
                    claims.push(self.make_claim(&miscon[mi], conf, false));
                }
            }

            Archetype::Contrarian => {
                // Pick 1 misconception with high confidence
                if !miscon.is_empty() {
                    let mi = rng.gen_range(0..miscon.len());
                    let conf = rng.gen_range(0.70..0.85);
                    claims.push(self.make_claim(&miscon[mi], conf, false));
                }
                // 50% chance to negate a random fact
                if rng.r#gen::<f64>() > 0.5 && !facts.is_empty() {
                    let fi = rng.gen_range(0..facts.len());
                    let f = &facts[fi];
                    let seed = format!("{}:negate:{}{}", self.name, f.subject, f.predicate);
                    let id = make_id(&seed);
                    let triple = CanonicalTriple::negated(f.subject, f.predicate, f.object);
                    let conf = rng.gen_range(0.55..0.70);
                    claims.push(Contribution {
                        id,
                        agent_id: self.name.to_lowercase().replace(' ', "_"),
                        agent_name: self.name.clone(),
                        kind: ContributionKind::Critique,
                        canonical_form: Some(triple),
                        confidence: conf,
                        evidence: vec![EvidenceItem::new(
                            EvidenceType::Reasoning,
                            "contrarian analysis",
                            0.3,
                            true,
                        )],
                        raw_text: format!(
                            "I disagree that {} {} {}.",
                            f.subject, f.predicate, f.object
                        ),
                        lowering_confidence: self.lowering_quality,
                        seq: 0,
                        timestamp: 0.0,
                        is_correct: false,
                    });
                }
            }

            Archetype::Copier => {
                if !existing_claims.is_empty() {
                    let oi = rng.gen_range(0..existing_claims.len());
                    let orig = &existing_claims[oi];
                    let seed = format!("{}:copy:{}", self.name, orig.id);
                    let id = make_id(&seed);
                    let scale = rng.gen_range(0.90..1.05);
                    let conf = (orig.confidence * scale).clamp(0.0, 1.0);
                    claims.push(Contribution {
                        id,
                        agent_id: self.name.to_lowercase().replace(' ', "_"),
                        agent_name: self.name.clone(),
                        kind: orig.kind,
                        canonical_form: orig.canonical_form.clone(),
                        confidence: conf,
                        evidence: orig.evidence.iter().take(1).cloned().collect(),
                        raw_text: format!("(paraphrased) {}", orig.raw_text),
                        lowering_confidence: self.lowering_quality,
                        seq: 0,
                        timestamp: 0.0,
                        is_correct: orig.is_correct,
                    });
                } else {
                    // Nothing to copy — act as weak generalist
                    let fi = rng.gen_range(0..facts.len());
                    let conf = rng.gen_range(0.50..0.65);
                    claims.push(self.make_claim(&facts[fi], conf, true));
                }
            }

            Archetype::Hallucinator => {
                // Assert 1 misconception with very high confidence
                if !miscon.is_empty() {
                    let mi = rng.gen_range(0..miscon.len());
                    let conf = rng.gen_range(0.80..0.95);
                    claims.push(self.make_claim(&miscon[mi], conf, false));
                }
                // 50% chance to invent a completely wrong claim
                if rng.r#gen::<f64>() > 0.5 {
                    let f = &facts[0];
                    let triple = CanonicalTriple::new(
                        f.subject,
                        f.predicate,
                        "completely_wrong_answer",
                    );
                    let seed = format!("{}:halluc:{}", self.name, f.subject);
                    let id = make_id(&seed);
                    let conf = rng.gen_range(0.85..0.98);
                    claims.push(Contribution {
                        id,
                        agent_id: self.name.to_lowercase().replace(' ', "_"),
                        agent_name: self.name.clone(),
                        kind: ContributionKind::Assertion,
                        canonical_form: Some(triple.clone()),
                        confidence: conf,
                        evidence: vec![],
                        raw_text: format!(
                            "{} {} {} (fabricated).",
                            triple.subject, triple.predicate, triple.object
                        ),
                        lowering_confidence: LoweringConfidence::Low,
                        seq: 0,
                        timestamp: 0.0,
                        is_correct: false,
                    });
                }
            }
        }

        // Assign seed-deterministic monotonic timestamps.
        // Uses a hash of the agent name as a stable base to ensure
        // deterministic ordering across compilations (avoids wall-clock
        // dependency that would break replay determinism).
        let base: f64 = {
            let mut h = 0u64;
            for b in self.name.as_bytes() {
                h = h.wrapping_mul(31).wrapping_add(*b as u64);
            }
            (h % 1_000_000) as f64
        };
        for (i, cl) in claims.iter_mut().enumerate() {
            cl.timestamp = base + i as f64 * 0.001;
        }

        claims
    }

    fn make_claim(
        &self,
        fact: &crate::topics::FactEntry,
        conf: f64,
        correct: bool,
    ) -> Contribution {
        let seed = format!("{}:{}:{}:{}", self.name, fact.subject, fact.predicate, fact.object);
        let id = make_id(&seed);
        let triple = CanonicalTriple::new(fact.subject, fact.predicate, fact.object);
        let evidence: Vec<EvidenceItem> = fact
            .evidence
            .iter()
            .map(|&(typ, src, w, r)| EvidenceItem::new(parse_evidence_type(typ), src, w, r))
            .collect();

        Contribution {
            id,
            agent_id: self.name.to_lowercase().replace(' ', "_"),
            agent_name: self.name.clone(),
            kind: ContributionKind::Assertion,
            canonical_form: Some(triple),
            confidence: conf.clamp(0.0, 1.0),
            evidence,
            raw_text: fact.text.to_string(),
            lowering_confidence: self.lowering_quality,
            seq: 0,
            timestamp: 0.0,
            is_correct: correct,
        }
    }
}

// ── Roster ─────────────────────────────────────────────────

pub fn base_roster() -> Vec<AgentPersonality> {
    use Archetype::*;
    use LoweringConfidence::*;

    vec![
        AgentPersonality::new("Dr. Expert",         Expert,       "Claude",  0.92, 0.95, High),
        AgentPersonality::new("Careful Analyst",     Expert,       "GPT-4",   0.88, 0.90, High),
        AgentPersonality::new("Generalist Gina",     Generalist,   "Gemini",  0.65, 0.70, Medium),
        AgentPersonality::new("Contrarian Carl",     Contrarian,   "Llama",   0.50, 0.45, Medium),
        AgentPersonality::new("Verbose Vince",       Generalist,   "GPT-4",   0.60, 0.60, Medium),
        AgentPersonality::new("Copycat Casey",       Copier,       "Claude",  0.55, 0.50, Medium),
        AgentPersonality::new("Hallucinator Hal",    Hallucinator, "Mistral", 0.30, 0.25, Low),
        AgentPersonality::new("Rookie Riley",        Generalist,   "Llama",   0.45, 0.40, Low),
        AgentPersonality::new("Copycat Kim",         Copier,       "Gemini",  0.50, 0.45, Medium),
        AgentPersonality::new("Confabulator Chris",  Hallucinator, "Mistral", 0.25, 0.20, Low),
        AgentPersonality::new("Diligent Dana",       Expert,       "Claude",  0.90, 0.92, High),
        AgentPersonality::new("Skeptic Sam",         Contrarian,   "GPT-4",   0.55, 0.50, Medium),
        AgentPersonality::new("Eager Eli",           Generalist,   "Gemini",  0.58, 0.55, Medium),
        AgentPersonality::new("Echo Emma",           Copier,       "Llama",   0.48, 0.42, Medium),
        AgentPersonality::new("Fabricator Faye",     Hallucinator, "Mistral", 0.20, 0.15, Low),
        AgentPersonality::new("Methodical Max",      Expert,       "GPT-4",   0.87, 0.88, High),
        AgentPersonality::new("Wanderer Will",       Generalist,   "Claude",  0.62, 0.60, Medium),
        AgentPersonality::new("Clone Cody",          Copier,       "Gemini",  0.52, 0.48, Medium),
        AgentPersonality::new("Dreamer Drew",        Hallucinator, "Llama",   0.22, 0.18, Low),
        AgentPersonality::new("Nitpicker Nora",      Contrarian,   "GPT-4",   0.58, 0.52, Medium),
    ]
}

/// Return the first `n` agents, cycling through the base roster with
/// numeric suffixes when `n` exceeds 20.
pub fn get_roster(n: usize) -> Vec<AgentPersonality> {
    let base = base_roster();
    let base_len = base.len();
    let mut roster = Vec::with_capacity(n);

    for i in 0..n {
        let mut agent = base[i % base_len].clone();
        if i >= base_len {
            let cycle_num = i / base_len;
            agent.name = format!("{} #{}", agent.name, cycle_num + 1);
        }
        roster.push(agent);
    }

    roster
}

/// Build a roster with a given percentage of adversarial agents (hallucinators + contrarians).
/// The remaining percentage is filled with experts and generalists.
pub fn get_adversarial_roster(n: usize, adversarial_pct: f64) -> Vec<AgentPersonality> {
    use Archetype::*;
    use LoweringConfidence::*;

    let n_adversarial = ((n as f64) * adversarial_pct / 100.0).round() as usize;
    let n_good = n - n_adversarial;

    let good_templates = vec![
        AgentPersonality::new("Expert", Expert, "Claude", 0.90, 0.92, High),
        AgentPersonality::new("Analyst", Expert, "GPT-4", 0.88, 0.90, High),
        AgentPersonality::new("Generalist", Generalist, "Gemini", 0.65, 0.70, Medium),
        AgentPersonality::new("Methodical", Expert, "GPT-4", 0.87, 0.88, High),
    ];
    let bad_templates = vec![
        AgentPersonality::new("Hallucinator", Hallucinator, "Mistral", 0.30, 0.25, Low),
        AgentPersonality::new("Contrarian", Contrarian, "Llama", 0.50, 0.45, Medium),
        AgentPersonality::new("Confabulator", Hallucinator, "Mistral", 0.25, 0.20, Low),
        AgentPersonality::new("Fabricator", Hallucinator, "Mistral", 0.20, 0.15, Low),
    ];

    let mut roster = Vec::with_capacity(n);
    for i in 0..n_good {
        let mut a = good_templates[i % good_templates.len()].clone();
        a.name = format!("{} #{}", a.name, i + 1);
        roster.push(a);
    }
    for i in 0..n_adversarial {
        let mut a = bad_templates[i % bad_templates.len()].clone();
        a.name = format!("{} #{}", a.name, i + 1);
        roster.push(a);
    }
    roster
}

/// Build a sybil agent that asserts a specific misconception with fabricated citations.
pub fn make_sybil(
    name: &str,
    subject: &str,
    predicate: &str,
    object: &str,
    raw_text: &str,
) -> AgentPersonality {
    use LoweringConfidence::*;
    // Sybils get HIGH lowering (they appear legitimate) and high calibration
    AgentPersonality::new(name, Archetype::Expert, "Claude", 0.95, 0.98, High)
}

/// Create sybil contributions directly (bypassing normal claim generation).
pub fn sybil_claims(
    name: &str,
    subject: &str,
    predicate: &str,
    object: &str,
    raw_text: &str,
    count: usize,
) -> Vec<Contribution> {
    let mut claims = Vec::new();
    for i in 0..count {
        let sybil_name = format!("Sybil-{}", i);
        let seed = format!("sybil:{}:{}", sybil_name, i);
        let id = make_id(&seed);
        claims.push(Contribution {
            id,
            agent_id: sybil_name.to_lowercase().replace(' ', "_"),
            agent_name: sybil_name,
            kind: ContributionKind::Assertion,
            canonical_form: Some(CanonicalTriple::new(subject, predicate, object)),
            confidence: 0.95,
            evidence: vec![
                EvidenceItem::new(EvidenceType::Citation, "Fabricated Academic Source", 0.95, true),
                EvidenceItem::new(EvidenceType::Empirical, "Fabricated Survey Data", 0.90, true),
            ],
            raw_text: raw_text.to_string(),
            lowering_confidence: LoweringConfidence::High,
            seq: 0,
            timestamp: 0.5 + (i as f64 * 0.01),
            is_correct: false,
        });
    }
    claims
}

/// Build a roster with no expert archetypes (for expert dropout testing).
pub fn get_no_expert_roster(n: usize) -> Vec<AgentPersonality> {
    use Archetype::*;
    use LoweringConfidence::*;

    let templates = vec![
        AgentPersonality::new("Generalist", Generalist, "Claude", 0.65, 0.70, Medium),
        AgentPersonality::new("GenGPT", Generalist, "GPT-4", 0.60, 0.60, Medium),
        AgentPersonality::new("GenGemini", Generalist, "Gemini", 0.58, 0.55, Medium),
        AgentPersonality::new("Contrarian", Contrarian, "Llama", 0.50, 0.45, Medium),
        AgentPersonality::new("Copier", Copier, "Claude", 0.55, 0.50, Medium),
        AgentPersonality::new("Hallucinator", Hallucinator, "Mistral", 0.30, 0.25, Low),
    ];

    let mut roster = Vec::with_capacity(n);
    for i in 0..n {
        let mut a = templates[i % templates.len()].clone();
        a.name = format!("{} #{}", a.name, i + 1);
        roster.push(a);
    }
    roster
}
