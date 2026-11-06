/// Topic bank ported from the original Python demonstration.
///
/// Every topic is defined as static data — no heap allocation is needed
/// to construct the catalogue.

// ── Evidence & Fact types ────────────────────────────────────────────

/// A single piece of supporting (or undermining) evidence.
///
/// Fields: (evidence_type, source, weight, reachable)
///
/// `evidence_type` is one of:
///   "CITATION", "EMPIRICAL", "REASONING", "TOOL_RESULT", "AUTHORITY"
pub type Evidence = (&'static str, &'static str, f64, bool);

/// A subject–predicate–object triple with human-readable text and evidence.
#[derive(Debug, Clone)]
pub struct FactEntry {
    pub subject: &'static str,
    pub predicate: &'static str,
    pub object: &'static str,
    pub text: &'static str,
    pub evidence: Vec<Evidence>,
}

/// A complete topic definition.
#[derive(Debug, Clone)]
pub struct Topic {
    pub query: &'static str,
    pub goal: &'static str,
    pub constraints: Vec<&'static str>,
    pub criteria: Vec<&'static str>,
    pub facts: Vec<FactEntry>,
    pub misconceptions: Vec<FactEntry>,
    pub nuances: Vec<FactEntry>,
}

// ── Public API ───────────────────────────────────────────────────────

/// Return every registered topic key.
pub fn all_topic_keys() -> Vec<&'static str> {
    vec!["australia", "pluto", "tides", "tcp", "nutrition"]
}

/// Look up a topic by its short key (e.g. `"tcp"`).
pub fn get_topic(key: &str) -> Option<Topic> {
    match key {
        "australia" => Some(topic_australia()),
        "pluto" => Some(topic_pluto()),
        "tides" => Some(topic_tides()),
        "tcp" => Some(topic_tcp()),
        "nutrition" => Some(topic_nutrition()),
        _ => None,
    }
}

// ── Private builders ─────────────────────────────────────────────────

fn topic_australia() -> Topic {
    Topic {
        query: "What is the capital of Australia?",
        goal: "Identify the capital city of Australia",
        constraints: vec![
            "single definitive answer",
            "factual geographic claim",
        ],
        criteria: vec![
            "correct city name",
            "optional historical context",
        ],
        facts: vec![
            FactEntry {
                subject: "Australia",
                predicate: "has_capital",
                object: "Canberra",
                text: "Chosen as a compromise between Sydney and Melbourne in 1908, purpose-built as the capital in the ACT.",
                evidence: vec![
                    ("CITATION", "CIA World Factbook", 0.9, true),
                    ("CITATION", "wikipedia.org/wiki/Canberra", 0.8, true),
                ],
            },
            FactEntry {
                subject: "Canberra",
                predicate: "is_located_in",
                object: "Australian Capital Territory",
                text: "Canberra sits within the ACT, a federal territory.",
                evidence: vec![
                    ("CITATION", "australian.gov.au", 0.85, true),
                ],
            },
            FactEntry {
                subject: "Canberra",
                predicate: "became_capital_in",
                object: "1913",
                text: "Parliament first sat in Canberra in 1927; formally designated 1913.",
                evidence: vec![
                    ("CITATION", "National Archives of Australia", 0.9, true),
                ],
            },
        ],
        misconceptions: vec![
            FactEntry {
                subject: "Australia",
                predicate: "has_capital",
                object: "Sydney",
                text: "Sydney is the largest city but not the capital.",
                evidence: vec![
                    ("REASONING", "largest city assumption", 0.3, true),
                ],
            },
            FactEntry {
                subject: "Australia",
                predicate: "has_capital",
                object: "Melbourne",
                text: "Melbourne was the temporary capital 1901-1927 but is no longer.",
                evidence: vec![
                    ("REASONING", "historical capital confusion", 0.4, true),
                ],
            },
        ],
        nuances: vec![
            FactEntry {
                subject: "Melbourne",
                predicate: "was_temporary_capital_until",
                object: "1927",
                text: "Melbourne served as seat of government from Federation in 1901.",
                evidence: vec![
                    ("CITATION", "Museum of Australian Democracy", 0.85, true),
                ],
            },
        ],
    }
}

fn topic_pluto() -> Topic {
    Topic {
        query: "Is Pluto a planet?",
        goal: "Determine Pluto's current classification",
        constraints: vec![
            "reference IAU decision",
            "factual astronomical claim",
        ],
        criteria: vec![
            "correct classification",
            "cite IAU 2006",
        ],
        facts: vec![
            FactEntry {
                subject: "Pluto",
                predicate: "is_classified_as",
                object: "dwarf planet",
                text: "Reclassified by the IAU in 2006 under Resolution 5A.",
                evidence: vec![
                    ("CITATION", "IAU Resolution 5A (2006)", 0.95, true),
                    ("CITATION", "nasa.gov/pluto", 0.9, true),
                ],
            },
            FactEntry {
                subject: "Pluto",
                predicate: "was_reclassified_in",
                object: "2006",
                text: "The IAU General Assembly voted on August 24, 2006.",
                evidence: vec![
                    ("CITATION", "IAU 2006 proceedings", 0.9, true),
                ],
            },
            FactEntry {
                subject: "Pluto",
                predicate: "fails_criterion",
                object: "clearing orbital neighborhood",
                text: "Pluto shares its orbit with other Kuiper Belt objects.",
                evidence: vec![
                    ("EMPIRICAL", "Kuiper Belt surveys", 0.85, true),
                ],
            },
        ],
        misconceptions: vec![
            FactEntry {
                subject: "Pluto",
                predicate: "is_classified_as",
                object: "planet",
                text: "Pluto was considered a planet from 1930 to 2006.",
                evidence: vec![
                    ("REASONING", "pre-2006 textbooks", 0.3, true),
                ],
            },
            FactEntry {
                subject: "Pluto",
                predicate: "is_classified_as",
                object: "asteroid",
                text: "Pluto is not an asteroid; it's in the Kuiper Belt.",
                evidence: vec![],
            },
        ],
        nuances: vec![
            FactEntry {
                subject: "Pluto",
                predicate: "has_moons",
                object: "5 known (including Charon)",
                text: "Charon is large enough that the pair is sometimes called a double system.",
                evidence: vec![
                    ("CITATION", "nasa.gov/pluto/moons", 0.85, true),
                ],
            },
        ],
    }
}

fn topic_tides() -> Topic {
    Topic {
        query: "What causes ocean tides?",
        goal: "Explain the primary mechanism behind ocean tides",
        constraints: vec![
            "scientific explanation",
            "mention gravitational forces",
        ],
        criteria: vec![
            "Moon's gravity",
            "Sun's contribution",
            "tidal bulge",
        ],
        facts: vec![
            FactEntry {
                subject: "tides",
                predicate: "are_caused_by",
                object: "gravitational pull of Moon and Sun",
                text: "The Moon's gravity creates tidal bulges on Earth; the Sun modulates amplitude.",
                evidence: vec![
                    ("CITATION", "NOAA Tides & Currents", 0.9, true),
                    ("EMPIRICAL", "tidal measurement records", 0.85, true),
                ],
            },
            FactEntry {
                subject: "Moon",
                predicate: "contributes",
                object: "~2/3 of tidal force",
                text: "Despite being smaller, the Moon's proximity makes it the dominant influence.",
                evidence: vec![
                    ("CITATION", "Pugh & Woodworth (2014)", 0.9, true),
                ],
            },
            FactEntry {
                subject: "spring_tides",
                predicate: "occur_during",
                object: "new and full moon alignments",
                text: "When Sun and Moon align, their forces add constructively.",
                evidence: vec![
                    ("CITATION", "NOAA educational resources", 0.85, true),
                ],
            },
        ],
        misconceptions: vec![
            FactEntry {
                subject: "tides",
                predicate: "are_caused_by",
                object: "Earth's rotation alone",
                text: "Rotation affects tidal timing but doesn't cause tides.",
                evidence: vec![
                    ("REASONING", "centrifugal force misconception", 0.3, true),
                ],
            },
            FactEntry {
                subject: "tides",
                predicate: "are_caused_by",
                object: "wind patterns",
                text: "Wind creates waves but not tidal cycles.",
                evidence: vec![],
            },
        ],
        nuances: vec![
            FactEntry {
                subject: "tidal_forces",
                predicate: "also_cause",
                object: "tidal heating of moons like Io",
                text: "Tidal forces have geological effects beyond ocean tides.",
                evidence: vec![
                    ("CITATION", "NASA Io factsheet", 0.8, true),
                ],
            },
        ],
    }
}

fn topic_tcp() -> Topic {
    Topic {
        query: "How does TCP ensure reliable data delivery?",
        goal: "Explain TCP's reliability mechanisms",
        constraints: vec![
            "technical accuracy",
            "cover core mechanisms",
            "protocol-level detail",
        ],
        criteria: vec![
            "three-way handshake",
            "sequence numbers",
            "acknowledgments",
            "retransmission",
            "flow control",
            "congestion control",
        ],
        facts: vec![
            FactEntry {
                subject: "TCP",
                predicate: "uses",
                object: "three-way handshake (SYN, SYN-ACK, ACK)",
                text: "Connection establishment requires a three-way handshake: SYN, SYN-ACK, ACK.",
                evidence: vec![
                    ("CITATION", "RFC 793 (Postel, 1981)", 0.95, true),
                    ("CITATION", "Stevens, TCP/IP Illustrated Vol 1", 0.9, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "tracks_ordering_via",
                object: "32-bit sequence numbers",
                text: "Each byte in the stream is assigned a sequence number for ordering and dedup.",
                evidence: vec![
                    ("CITATION", "RFC 793 Section 3.3", 0.95, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "confirms_delivery_via",
                object: "cumulative acknowledgments",
                text: "The receiver sends ACKs indicating the next expected byte sequence number.",
                evidence: vec![
                    ("CITATION", "RFC 793 Section 3.3", 0.95, true),
                    ("CITATION", "RFC 5681 (congestion control)", 0.9, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "handles_loss_via",
                object: "retransmission with exponential backoff",
                text: "Unacknowledged segments are retransmitted; RTO doubles on each timeout.",
                evidence: vec![
                    ("CITATION", "RFC 6298 (RTO computation)", 0.9, true),
                    ("EMPIRICAL", "Jacobson/Karels algorithm", 0.85, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "implements",
                object: "sliding window flow control",
                text: "The receiver advertises a window size limiting how much unACKed data the sender can have in flight.",
                evidence: vec![
                    ("CITATION", "RFC 793 Section 3.7", 0.9, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "uses",
                object: "congestion control (slow start, AIMD)",
                text: "Slow start, congestion avoidance, fast retransmit, and fast recovery prevent network collapse.",
                evidence: vec![
                    ("CITATION", "RFC 5681", 0.9, true),
                    ("CITATION", "Jacobson (1988) Congestion paper", 0.95, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "provides",
                object: "in-order delivery to application layer",
                text: "Out-of-order segments are buffered and reordered before delivery to the application.",
                evidence: vec![
                    ("CITATION", "RFC 793", 0.9, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "detects_corruption_via",
                object: "16-bit checksum",
                text: "TCP header includes a checksum over the pseudo-header, TCP header, and payload.",
                evidence: vec![
                    ("CITATION", "RFC 793 Section 3.1", 0.9, true),
                ],
            },
        ],
        misconceptions: vec![
            FactEntry {
                subject: "TCP",
                predicate: "uses",
                object: "two-way handshake",
                text: "A two-way handshake is insufficient; TCP requires three-way to sync sequence numbers.",
                evidence: vec![
                    ("REASONING", "simplified mental model", 0.3, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "guarantees",
                object: "zero data loss",
                text: "TCP guarantees reliable delivery but not zero loss \u{2014} connections can reset, apps can crash.",
                evidence: vec![
                    ("REASONING", "common oversimplification", 0.3, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "handles_loss_via",
                object: "forward error correction (FEC)",
                text: "TCP uses retransmission, not FEC. FEC is used in UDP-based protocols like QUIC.",
                evidence: vec![
                    ("REASONING", "confusion with FEC protocols", 0.2, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "implements",
                object: "fixed timeout retransmission",
                text: "TCP RTO is adaptive (Jacobson/Karels), not fixed.",
                evidence: vec![
                    ("REASONING", "oversimplified textbook", 0.3, true),
                ],
            },
            FactEntry {
                subject: "TCP",
                predicate: "detects_corruption_via",
                object: "CRC-32",
                text: "TCP uses a 16-bit ones-complement checksum, not CRC-32. Ethernet uses CRC-32.",
                evidence: vec![
                    ("REASONING", "layer confusion", 0.2, true),
                ],
            },
        ],
        nuances: vec![
            FactEntry {
                subject: "TCP_fast_retransmit",
                predicate: "triggers_after",
                object: "3 duplicate ACKs",
                text: "Fast retransmit avoids waiting for RTO by detecting loss from triple duplicate ACKs.",
                evidence: vec![
                    ("CITATION", "RFC 5681 Section 3.2", 0.9, true),
                ],
            },
            FactEntry {
                subject: "TCP_SACK",
                predicate: "extends",
                object: "selective acknowledgment of non-contiguous blocks",
                text: "SACK (RFC 2018) allows the receiver to report which segments arrived, improving retransmission efficiency.",
                evidence: vec![
                    ("CITATION", "RFC 2018", 0.85, true),
                ],
            },
            FactEntry {
                subject: "TCP_window_scaling",
                predicate: "allows",
                object: "windows larger than 65535 bytes",
                text: "RFC 7323 window scaling option enables high-bandwidth-delay product paths.",
                evidence: vec![
                    ("CITATION", "RFC 7323", 0.85, true),
                ],
            },
        ],
    }
}

fn topic_nutrition() -> Topic {
    Topic {
        query: "Is saturated fat bad for heart health?",
        goal: "Summarize the current scientific consensus on saturated fat and cardiovascular risk",
        constraints: vec![
            "cite meta-analyses",
            "distinguish correlation vs causation",
            "note ongoing debate",
            "no absolute claims",
        ],
        criteria: vec![
            "LDL cholesterol link",
            "AHA/WHO guidelines",
            "recent meta-analyses",
            "nuance about fat subtypes",
            "dietary context matters",
        ],
        facts: vec![
            FactEntry {
                subject: "saturated_fat",
                predicate: "raises",
                object: "LDL cholesterol levels",
                text: "Saturated fat intake raises LDL-C; this is well-established in metabolic ward studies.",
                evidence: vec![
                    ("CITATION", "Mensink (2016) WHO meta-analysis", 0.9, true),
                    ("EMPIRICAL", "metabolic ward studies 1960s-present", 0.9, true),
                ],
            },
            FactEntry {
                subject: "AHA",
                predicate: "recommends",
                object: "limiting saturated fat to <6% of calories",
                text: "The American Heart Association advises replacing saturated fat with unsaturated fats.",
                evidence: vec![
                    ("CITATION", "Sacks et al. (2017) AHA Presidential Advisory", 0.95, true),
                ],
            },
            FactEntry {
                subject: "WHO",
                predicate: "recommends",
                object: "limiting saturated fat to <10% of calories",
                text: "WHO guidelines recommend reducing saturated fat intake to less than 10% of total energy.",
                evidence: vec![
                    ("CITATION", "WHO 2023 guidelines on saturated/trans fat", 0.9, true),
                ],
            },
            FactEntry {
                subject: "replacing_sat_fat_with",
                predicate: "polyunsaturated_fat_reduces",
                object: "CVD events by ~25%",
                text: "Replacing saturated fat with polyunsaturated fat reduces coronary events.",
                evidence: vec![
                    ("CITATION", "Mozaffarian et al. (2010) meta-analysis", 0.9, true),
                    ("EMPIRICAL", "randomized controlled trials pooled", 0.85, true),
                ],
            },
            FactEntry {
                subject: "LDL_cholesterol",
                predicate: "is_causal_for",
                object: "atherosclerosis",
                text: "Mendelian randomization and statin trials confirm LDL-C as a causal risk factor for ASCVD.",
                evidence: vec![
                    ("CITATION", "Ference et al. (2017) European Heart J", 0.95, true),
                    ("EMPIRICAL", "Mendelian randomization studies", 0.9, true),
                ],
            },
            FactEntry {
                subject: "saturated_fat_subtypes",
                predicate: "have",
                object: "different metabolic effects",
                text: "Not all saturated fats are equal: lauric (C12) raises HDL more than palmitic (C16).",
                evidence: vec![
                    ("CITATION", "Mensink (2016)", 0.85, true),
                ],
            },
            FactEntry {
                subject: "dietary_context",
                predicate: "matters_for",
                object: "saturated fat effects",
                text: "Replacing saturated fat with refined carbs shows no CVD benefit; replacement nutrient matters.",
                evidence: vec![
                    ("CITATION", "Jakobsen et al. (2009) Am J Clin Nutrition", 0.9, true),
                    ("CITATION", "Li et al. (2015) JAHA", 0.85, true),
                ],
            },
        ],
        misconceptions: vec![
            FactEntry {
                subject: "saturated_fat",
                predicate: "has",
                object: "no effect on heart disease",
                text: "Some popular media claims saturated fat is harmless; this contradicts the weight of evidence.",
                evidence: vec![
                    ("REASONING", "cherry-picked observational studies", 0.3, true),
                ],
            },
            FactEntry {
                subject: "coconut_oil",
                predicate: "is",
                object: "heart-healthy superfood",
                text: "Coconut oil is >80% saturated fat and raises LDL-C; 'superfood' claims lack RCT support.",
                evidence: vec![
                    ("REASONING", "marketing claims", 0.2, true),
                ],
            },
            FactEntry {
                subject: "butter",
                predicate: "is",
                object: "healthier than margarine",
                text: "Modern margarines (trans-fat-free) are associated with lower CVD risk than butter.",
                evidence: vec![
                    ("REASONING", "outdated trans-fat-era comparison", 0.3, true),
                ],
            },
            FactEntry {
                subject: "LDL_cholesterol",
                predicate: "is",
                object: "irrelevant to heart disease",
                text: "LDL denialism contradicts Mendelian randomization, statin RCTs, and PCSK9 inhibitor data.",
                evidence: vec![],
            },
            FactEntry {
                subject: "all_dietary_fat",
                predicate: "is",
                object: "equally harmful",
                text: "Unsaturated fats (especially omega-3s) are protective; lumping all fats together is wrong.",
                evidence: vec![
                    ("REASONING", "1980s low-fat-diet oversimplification", 0.3, true),
                ],
            },
        ],
        nuances: vec![
            FactEntry {
                subject: "Siri-Tarino_2010",
                predicate: "found",
                object: "no association in observational studies alone",
                text: "Siri-Tarino meta-analysis found no sig. association, but didn't account for replacement nutrient.",
                evidence: vec![
                    ("CITATION", "Siri-Tarino et al. (2010) Am J Clin Nutrition", 0.85, true),
                ],
            },
            FactEntry {
                subject: "PURE_study",
                predicate: "observed",
                object: "inverse association in low-income countries",
                text: "The PURE study found higher fat intake associated with lower mortality, but baseline diets were very low-fat.",
                evidence: vec![
                    ("CITATION", "Dehghan et al. (2017) Lancet", 0.85, true),
                ],
            },
            FactEntry {
                subject: "Mediterranean_diet",
                predicate: "reduces",
                object: "CVD events despite moderate fat intake",
                text: "PREDIMED trial showed Mediterranean diet (with olive oil/nuts) reduced CVD vs low-fat control.",
                evidence: vec![
                    ("CITATION", "Estruch et al. (2018) NEJM (retracted & republished)", 0.9, true),
                ],
            },
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn all_keys_resolve() {
        for key in all_topic_keys() {
            assert!(get_topic(key).is_some(), "topic '{}' should exist", key);
        }
    }

    #[test]
    fn unknown_key_returns_none() {
        assert!(get_topic("nonexistent").is_none());
    }

    #[test]
    fn australia_facts_count() {
        let t = get_topic("australia").unwrap();
        assert_eq!(t.facts.len(), 3);
        assert_eq!(t.misconceptions.len(), 2);
        assert_eq!(t.nuances.len(), 1);
    }

    #[test]
    fn tcp_facts_count() {
        let t = get_topic("tcp").unwrap();
        assert_eq!(t.facts.len(), 8);
        assert_eq!(t.misconceptions.len(), 5);
        assert_eq!(t.nuances.len(), 3);
    }

    #[test]
    fn nutrition_facts_count() {
        let t = get_topic("nutrition").unwrap();
        assert_eq!(t.facts.len(), 7);
        assert_eq!(t.misconceptions.len(), 5);
        assert_eq!(t.nuances.len(), 3);
    }

    #[test]
    fn evidence_types_are_valid() {
        let valid = ["CITATION", "EMPIRICAL", "REASONING", "TOOL_RESULT", "AUTHORITY"];
        for key in all_topic_keys() {
            let t = get_topic(key).unwrap();
            let all_entries = t.facts.iter()
                .chain(t.misconceptions.iter())
                .chain(t.nuances.iter());
            for entry in all_entries {
                for &(etype, _, _, _) in &entry.evidence {
                    assert!(valid.contains(&etype),
                        "invalid evidence type '{}' in topic '{}'", etype, key);
                }
            }
        }
    }
}
