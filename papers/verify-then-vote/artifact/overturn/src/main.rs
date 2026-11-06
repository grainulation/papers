mod ir;
mod topics;
mod agents;
mod compiler;
mod lowering;
mod properties;
mod value_mode;
mod evidence;
mod gate;

use clap::Parser;
use ir::*;
use compiler::OverturnCompiler;
use std::collections::{HashMap, HashSet};
use rand::SeedableRng;

// ── ANSI helpers ──────────────────────────────────────────

static mut USE_COLOR: bool = true;

fn c(code: &str, text: &str) -> String {
    if unsafe { !USE_COLOR } {
        return text.to_string();
    }
    format!("\x1b[{code}m{text}\x1b[0m")
}

fn bold(t: &str) -> String { c("1", t) }
fn dim(t: &str) -> String { c("2", t) }
fn green(t: &str) -> String { c("32", t) }
fn red(t: &str) -> String { c("31", t) }
fn yellow(t: &str) -> String { c("33", t) }
fn cyan(t: &str) -> String { c("36", t) }

fn header(title: &str) {
    let w = 64;
    println!();
    println!("{}", bold(&cyan(&"─".repeat(w))));
    println!("{}", bold(&cyan(&format!("  {title}"))));
    println!("{}", bold(&cyan(&"─".repeat(w))));
}

fn stage(name: &str) {
    println!();
    println!("{}", bold(&yellow(&format!("  ▸ {name}"))));
    println!("{}", dim(&format!("  {}", "·".repeat(56))));
}

// ── CLI ───────────────────────────────────────────────────

#[derive(Parser)]
#[command(name = "overturn", about = "overturn: deterministic, replayable arbitration of multi-agent outputs (reducer and demo)")]
struct Cli {
    /// Number of agents
    #[arg(short = 'n', long = "agents", default_value_t = 5)]
    agents: usize,

    /// Topic to compile
    #[arg(short, long, default_value = "tcp")]
    topic: String,

    /// Run N-scaling analysis
    #[arg(short, long)]
    scaling: bool,

    /// Mega-scale stress test
    #[arg(long)]
    stress: bool,

    /// Disable ANSI colors
    #[arg(long = "no-color")]
    no_color: bool,

    /// Random seed
    #[arg(long, default_value_t = 42)]
    seed: u64,

    /// Custom scoring weights: ev,conf,cs,rec,ca
    #[arg(long)]
    weights: Option<String>,

    /// Run adversarial resilience sweep
    #[arg(long)]
    adversarial: bool,

    /// Run expert dropout test
    #[arg(long)]
    expert_dropout: bool,

    /// Run sybil attack test
    #[arg(long)]
    sybil: bool,

    /// Run scoring noise sensitivity test
    #[arg(long)]
    noise: bool,

    /// Run family dominance (EES-is-decorative) test
    #[arg(long)]
    family_dominance: bool,

    /// Run per-pass timing breakdown
    #[arg(long)]
    pass_timing: bool,

    /// Run scoring component ablation study
    #[arg(long)]
    ablation: bool,

    /// Measure score gaps in conflict sets (Schulze investigation)
    #[arg(long)]
    score_gaps: bool,

    /// CP-WBFT threshold comparison (85.7% and 93.3% adversarial ratios)
    #[arg(long)]
    cpwbft: bool,

    /// Condorcet jury condition check (agent accuracy distribution)
    #[arg(long)]
    condorcet: bool,

    /// Run baseline comparison (majority-vote, best-confidence, last-writer-wins, random)
    #[arg(long)]
    baselines: bool,

    /// Test minimum-score threshold for FP reduction
    #[arg(long)]
    min_score: bool,

    /// Multi-scale baseline comparison (N=100, 1000, 10000)
    #[arg(long)]
    baselines_scale: bool,

    /// Topology simulation (fully-connected, star, chain, tree)
    #[arg(long)]
    topology: bool,

    /// Run real rule-based lowering benchmark
    #[arg(long)]
    real_lowering: bool,

    /// Run formal property checks across all topics
    #[arg(long)]
    properties: bool,

    /// Replay determinism test: compile K times, assert identical certificate
    #[arg(long)]
    replay: bool,

    /// Number of replay iterations (default 1000)
    #[arg(long, default_value_t = 1000)]
    replay_count: usize,

    /// Replay variance comparison: overturn vs baselines across K runs
    #[arg(long)]
    replay_variance: bool,

    /// Compile --topic with --agents/--seed and write the sealed artifact
    /// set, policy, and output tuples as canonical JSON to this path
    #[arg(long, value_name = "PATH")]
    dump_artifact: Option<String>,

    /// Read a `--reduce` input (object or bare array), set every
    /// contribution's id to its `bran-contribution-id/1` content id, and
    /// print it (canonical JSON) for a content-addressed `--reduce`
    #[arg(long, value_name = "CLAIMS_JSON")]
    assign_ids: Option<String>,

    /// With --dump-artifact: use the legacy generator-seed contribution
    /// ids (`bran-artifact/2`) instead of content ids (`bran-artifact/4`)
    #[arg(long)]
    legacy_ids: bool,

    /// Load a dumped artifact (`-` = stdin), verify its format tag, root
    /// hash, ids and records, policy hash, re-reduce and compare the
    /// output tuples, then verify `envelope_hash` when present. Exit 0 ok,
    /// 1 output mismatch, 2 unreadable/unparsable, 3 sealed-set hash
    /// mismatch, 4 policy mismatch, 5 format tag mismatch, 6 envelope
    /// mismatch (see `ReplayError`)
    #[arg(long, value_name = "PATH")]
    replay_from: Option<String>,

    /// With --replay-from: print one JSON result object on stdout instead
    /// of the PASS/FAIL line (same exit codes)
    #[arg(long, requires = "replay_from")]
    json: bool,

    /// With --replay-from: a file without `envelope_hash` fails (exit 6)
    #[arg(long, requires = "replay_from")]
    require_envelope: bool,

    /// Reduce externally supplied contributions (JSON schema documented at
    /// `run_reduce`; `-` = stdin) and print the selections as JSON on stdout
    #[arg(long, value_name = "CLAIMS_JSON")]
    reduce: Option<String>,

    /// With --reduce: also seal the input and outputs into a replayable
    /// artifact file (`bran-artifact/4` when the input sets `id_scheme`)
    #[arg(long, value_name = "PATH", requires = "reduce")]
    emit_artifact: Option<String>,

    /// With --reduce: add `rejected_reasons` (one entry per rejected id)
    /// to the output
    #[arg(long, requires = "reduce")]
    explain_rejected: bool,

    /// Base policy for --reduce and --print-policy: default | generic
    /// (default without the TCP demo's incompatible_values groups; the
    /// recommended base for external use)
    #[arg(long, value_name = "NAME")]
    preset: Option<String>,

    /// Print the effective policy (base preset, plus the overlay in
    /// POLICY_JSON if given; `-` = stdin) as JSON: the policy, its
    /// canonical `bran-policy/1` serialization and its hash
    #[arg(long, value_name = "POLICY_JSON", num_args = 0..=1, default_missing_value = "")]
    print_policy: Option<String>,

    /// Print version, supported artifact formats and the reducer-constants
    /// id as JSON
    #[arg(long)]
    version: bool,

    /// Experimental P5 candidate granularity for every policy built by this
    /// run: member (default) | value | value:max | value:pooled
    #[arg(long, value_name = "MODE")]
    candidate_mode: Option<String>,
}

// ── Metrics ─────────────────────────────────────────────

struct Metrics {
    tp: usize,
    fp: usize,
    tn: usize,
    fn_: usize,
}

impl Metrics {
    fn from_result(result: &CompilationResult) -> Self {
        let mut tp = 0;
        let mut fp = 0;
        let mut tn = 0;
        let mut fn_ = 0;
        for &idx in &result.admitted {
            if result.all_contributions[idx].is_correct { tp += 1; } else { fp += 1; }
        }
        for &idx in &result.rejected {
            if result.all_contributions[idx].is_correct { fn_ += 1; } else { tn += 1; }
        }
        Self { tp, fp, tn, fn_ }
    }

    fn precision(&self) -> f64 {
        if self.tp + self.fp == 0 { 1.0 } else { self.tp as f64 / (self.tp + self.fp) as f64 }
    }

    fn recall(&self) -> f64 {
        if self.tp + self.fn_ == 0 { 1.0 } else { self.tp as f64 / (self.tp + self.fn_) as f64 }
    }

    fn f1(&self) -> f64 {
        let p = self.precision();
        let r = self.recall();
        if p + r == 0.0 { 0.0 } else { 2.0 * p * r / (p + r) }
    }
}

fn unique_keys(result: &CompilationResult) -> usize {
    let mut keys = HashSet::new();
    for &idx in &result.admitted {
        if let Some(ref cf) = result.all_contributions[idx].canonical_form {
            keys.insert(compiler::slot_key(cf));
        }
    }
    keys.len()
}

// ── Rendering ─────────────────────────────────────────────

fn render(result: &CompilationResult, topic: &topics::Topic, roster: &[agents::AgentPersonality]) {
    header("OVERTURN COMPILATION DEMO");

    // P1
    stage("P1 — Intent Normalization");
    println!("    Goal:        {}", topic.goal);
    println!("    Constraints: {}", topic.constraints.join(", "));
    println!("    Criteria:    {}", topic.criteria.join(", "));

    // P2
    stage(&format!("P2 — Lowering to IR ({} contributions from {} agents)",
        result.all_contributions.len(), roster.len()));
    for co in &result.all_contributions {
        let mark = if co.is_correct { green("✓") } else { red("✗") };
        println!("    {} [{}] {}", mark, bold(&co.agent_name), co.kind);
        if let Some(ref cf) = co.canonical_form {
            println!("      Triple: {cf}");
        }
        println!("      Confidence: {:.2}  |  Lowering: {}", co.confidence, co.lowering_confidence);
        if co.evidence.is_empty() {
            println!("      Evidence: {}", dim("(none)"));
        } else {
            let ev_str: Vec<String> = co.evidence.iter()
                .map(|e| format!("{}({}, w={:.1})", e.typ, &e.source[..e.source.len().min(25)], e.weight))
                .collect();
            println!("      Evidence: {}", dim(&ev_str.join(", ")));
        }
    }

    // P3
    stage(&format!("P3 — Validation ({} passed)", result.all_contributions.len()));
    println!("    All {} contributions passed schema validation.", result.all_contributions.len());

    // P4
    stage(&format!("P4 — Conflict Detection ({} conflict sets)", result.conflicts.len()));
    for (i, cs) in result.conflicts.iter().enumerate() {
        let label = if cs.typ == ConflictType::Contradiction {
            red("CONTRADICTION")
        } else {
            yellow("REDUNDANCY")
        };
        let slot_str = cs.slot_id.as_ref().map_or(String::new(), |s| format!(" [{}]", s));
        let db_str = if cs.in_deadband { dim(" ⚠ DEADBAND") } else { String::new() };
        println!("    {} #{}: ({}, {}){}{}", label, i + 1, cs.triple_key.0, cs.triple_key.1, slot_str, db_str);

        if cs.typ == ConflictType::Contradiction {
            let mut groups: HashMap<String, Vec<String>> = HashMap::new();
            for &idx in &cs.contribution_ids {
                let co = &result.all_contributions[idx];
                if let Some(ref cf) = co.canonical_form {
                    groups.entry(cf.object.clone()).or_default().push(co.agent_name.clone());
                }
            }
            for (val, ag) in &groups {
                println!("      → {}: {}", bold(val), ag.join(", "));
            }
        } else {
            let ag: Vec<&str> = cs.contribution_ids.iter()
                .map(|&idx| result.all_contributions[idx].agent_name.as_str())
                .collect();
            println!("      → {} agents: {}", ag.len(), ag.join(", "));
        }
    }

    // P5
    stage("P5 — Selection & Scoring");
    for (i, cs) in result.conflicts.iter().enumerate() {
        println!("\n    Conflict #{} ({}):", i + 1, cs.typ);
        let cols = ["Agent", "Ev", "Conf", "CS", "Rec", "CA", "Raw", "LF", "Final"];
        let widths = [20usize, 6, 6, 6, 6, 6, 6, 5, 7];

        print_table_header(&cols, &widths, "    ");

        let mut sorted_ids = cs.contribution_ids.clone();
        sorted_ids.sort_by(|a, b| {
            let sa = cs.scores[a].final_score;
            let sb = cs.scores[b].final_score;
            sb.partial_cmp(&sa).unwrap()
        });

        for &idx in &sorted_ids {
            let co = &result.all_contributions[idx];
            let s = &cs.scores[&idx];
            let is_winner = cs.winner_idx == Some(idx);
            let winner_mark = if is_winner { "★ " } else { "  " };
            let mut name = format!("{}{}", winner_mark, co.agent_name);
            name.truncate(20);

            let row = format!("    │{}│{}│{}│{}│{}│{}│{}│{}│{}│",
                pad_left(&name, widths[0]),
                center_str(&format!("{:.2}", s.ev), widths[1]),
                center_str(&format!("{:.2}", s.conf), widths[2]),
                center_str(&format!("{:.2}", s.cs), widths[3]),
                center_str(&format!("{:.2}", s.rec), widths[4]),
                center_str(&format!("{:.2}", s.ca), widths[5]),
                center_str(&format!("{:.2}", s.raw), widths[6]),
                center_str(&format!("{:.1}", s.lf), widths[7]),
                center_str(&format!("{:.3}", s.final_score), widths[8]),
            );

            if is_winner {
                println!("{}", bold(&green(&row)));
            } else if !co.is_correct {
                println!("{}", red(&row));
            } else {
                println!("{row}");
            }
        }
        print_table_bottom(&widths, "    ");

        if let Some(winner_idx) = cs.winner_idx {
            let w = &result.all_contributions[winner_idx];
            if let Some(ref cf) = w.canonical_form {
                println!("    Winner: {} → {}", bold(&w.agent_name), cf.object);
            }
        }
    }

    // P6
    stage("P6 — Compiled Output");
    let mut seen_keys = HashSet::new();
    let mut output_lines = Vec::new();
    for &idx in &result.admitted {
        let co = &result.all_contributions[idx];
        if let Some(ref cf) = co.canonical_form {
            let k = compiler::slot_key(cf);
            if seen_keys.insert(k) {
                output_lines.push(co.raw_text.clone());
            }
        }
    }

    let box_w = 60;
    println!("    ┌{}┐", "─".repeat(box_w));
    for line in &output_lines {
        let words: Vec<&str> = line.split_whitespace().collect();
        let mut current = String::new();
        for w in words {
            if current.len() + w.len() + 1 > box_w - 2 {
                println!("    │ {:<width$} │", current, width = box_w - 2);
                current = w.to_string();
            } else {
                if !current.is_empty() { current.push(' '); }
                current.push_str(w);
            }
        }
        if !current.is_empty() {
            println!("    │ {:<width$} │", current, width = box_w - 2);
        }
        println!("    │{:width$}│", "", width = box_w);
    }
    println!("    └{}┘", "─".repeat(box_w));

    // Metrics
    let m = Metrics::from_result(result);
    let n_contra = result.conflicts.iter().filter(|c| c.typ == ConflictType::Contradiction).count();
    let n_redund = result.conflicts.iter().filter(|c| c.typ == ConflictType::Redundancy).count();

    stage("Compilation Metrics");
    println!("    Agents:             {}", bold(&roster.len().to_string()));
    println!("    Total claims:       {}", result.all_contributions.len());
    println!("    Admitted:           {}", green(&result.admitted.len().to_string()));
    println!("    Rejected:           {}", red(&result.rejected.len().to_string()));
    println!("    Contradictions:     {n_contra}");
    println!("    Redundancies:       {n_redund}");

    stage("Correctness Analysis");
    println!("    True positives:     {}  (correct claims admitted)", green(&m.tp.to_string()));
    println!("    False positives:    {}  (incorrect claims admitted)", red(&m.fp.to_string()));
    println!("    True negatives:     {}  (incorrect claims rejected)", green(&m.tn.to_string()));
    println!("    False negatives:    {}  (correct claims rejected)", yellow(&m.fn_.to_string()));
    println!();
    println!("    Precision:          {:.1}%", m.precision() * 100.0);
    println!("    Recall:             {:.1}%", m.recall() * 100.0);
    println!("    F1 Score:           {:.3}", m.f1());

    stage("Diversity & Compilation");
    println!("    EES:                {:.1} / {} ({:.0}% effective diversity)",
        result.ees, roster.len(), result.ees / roster.len() as f64 * 100.0);
    println!("    Compilation time:   {:.3}ms", result.time_us as f64 / 1000.0);
    println!("    Certificate:        {}", dim(&format!("sha256:{}", result.certificate)));
    println!("    Artifact root:      {}", dim(&format!("sha256:{}", result.artifact_set.root_hash)));
    let deadband_count = result.conflicts.iter().filter(|cs| cs.in_deadband).count();
    if deadband_count > 0 {
        println!("    Deadband conflicts: {}", yellow(&format!("{}", deadband_count)));
    }

    let naive_output = result.all_contributions.len();
    let compiled_output = unique_keys(result);
    let naive_incorrect = result.all_contributions.iter().filter(|c| !c.is_correct).count();
    println!();
    stage("Naive Concatenation vs Overturn Compilation");
    println!("                        {:>10}    {:>10}", "Naive", "Overturn");
    println!("    Output statements:  {:>10}    {:>10}", naive_output, green(&compiled_output.to_string()));
    println!("    Incorrect claims:   {:>10}    {:>10}",
        red(&naive_incorrect.to_string()),
        if m.fp > 0 { red(&m.fp.to_string()) } else { green(&m.fp.to_string()) });
    println!("    Compression ratio:  {:>10}    {:>10}", "1.0x",
        green(&format!("{:.1}x", naive_output as f64 / compiled_output.max(1) as f64)));
    println!();
}

// ── Scaling ─────────────────────────────────────────────

fn run_scaling(topic_key: &str, seed: u64, weights: [f64; 5]) {
    let topic = topics::get_topic(topic_key).expect("Unknown topic");
    header("SCALING ANALYSIS");
    println!();
    println!("  Topic: {}", bold(topic.query));
    println!();

    let cols = ["N", "Claims", "Conflicts", "Output", "Prec", "FP", "EES", "Compress", "Time"];
    let widths = [5usize, 7, 9, 7, 7, 4, 6, 9, 10];
    print_table_header(&cols, &widths, "  ");

    let compiler = OverturnCompiler::with_weights(weights);

    for n in [3, 5, 10, 20, 50] {
        let roster = agents::get_roster(n);
        let r = compiler.compile(&topic, &roster, seed);
        let m = Metrics::from_result(&r);
        let uk = unique_keys(&r);
        let compress = r.all_contributions.len() as f64 / uk.max(1) as f64;

        let time_str = if r.time_us < 1000 {
            format!("{}μs", r.time_us)
        } else if r.time_us < 1_000_000 {
            format!("{:.1}ms", r.time_us as f64 / 1000.0)
        } else {
            format!("{:.2}s", r.time_us as f64 / 1_000_000.0)
        };

        let vals = [
            n.to_string(),
            r.all_contributions.len().to_string(),
            r.conflicts.len().to_string(),
            uk.to_string(),
            format!("{:.0}%", m.precision() * 100.0),
            m.fp.to_string(),
            format!("{:.1}", r.ees),
            format!("{:.1}x", compress),
            time_str,
        ];
        print_table_row(&vals, &widths, "  ");
    }
    print_table_bottom(&widths, "  ");
    println!();
}

// ── Stress test ─────────────────────────────────────────

fn run_stress(seed: u64, weights: [f64; 5]) {
    let scales: &[usize] = &[10, 100, 1_000, 5_000, 10_000];

    header("STRESS TEST");
    println!();
    println!("  3 task types × {} scales ({} → {} agents), every row a full compile()",
        scales.len(), format_num(scales[0]), format_num(*scales.last().unwrap()));
    println!("  Time = wall time of one compile() call (P1–P6 incl. seal), single run");
    println!("  Build: {}, seed: {seed}",
        if cfg!(debug_assertions) { "debug" } else { "release" });
    println!();

    let task_types = [
        ("Simple Factual", "australia", "Single correct answer, few predicates"),
        ("Complex Technical", "tcp", "Multiple mechanisms, 8 facts, 5 misconceptions"),
        ("Contested Scientific", "nutrition", "Nuanced evidence, 7 facts, 5 misconceptions"),
    ];

    let compiler = OverturnCompiler::with_weights(weights);

    for &(label, topic_key, desc) in &task_types {
        let topic = topics::get_topic(topic_key).unwrap();
        stage(&format!("{label}: {desc}"));
        println!("    Topic: {}", bold(topic.query));
        println!();

        let cols = ["N", "Claims", "Conflicts", "Output", "Prec", "FP", "EES", "Compress", "Time"];
        let widths = [9usize, 9, 9, 7, 7, 4, 6, 10, 12];
        print_table_header(&cols, &widths, "    ");

        for &n in scales {
            let roster = agents::get_roster(n);
            let t0 = std::time::Instant::now();
            let r = compiler.compile(&topic, &roster, seed);
            let elapsed = t0.elapsed();

            let m = Metrics::from_result(&r);
            let uk = unique_keys(&r);
            let n_claims = r.all_contributions.len();

            let time_str = if elapsed.as_micros() < 1000 {
                format!("{}μs", elapsed.as_micros())
            } else if elapsed.as_millis() < 1000 {
                format!("{:.1}ms", elapsed.as_micros() as f64 / 1000.0)
            } else {
                format!("{:.2}s", elapsed.as_secs_f64())
            };
            let compress = n_claims as f64 / uk.max(1) as f64;

            let vals = [
                format_num(n),
                format_num(n_claims),
                r.conflicts.len().to_string(),
                uk.to_string(),
                format!("{:.0}%", m.precision() * 100.0),
                m.fp.to_string(),
                format!("{:.1}", r.ees),
                format!("{:.0}x", compress),
                time_str,
            ];

            let row_str = format!("    │{}│",
                vals.iter().zip(widths.iter()).map(|(v, w)| center_str(v, *w)).collect::<Vec<_>>().join("│"));

            if m.fp == 0 {
                println!("{}", green(&row_str));
            } else if m.fp <= 2 {
                println!("{}", yellow(&row_str));
            } else {
                println!("{}", red(&row_str));
            }
        }
        print_table_bottom(&widths, "    ");
        println!();
    }
}

// ── Table helpers ─────────────────────────────────────────

fn center_str(s: &str, w: usize) -> String {
    let slen = s.chars().count();
    if slen >= w { return s.chars().take(w).collect(); }
    let pad = w - slen;
    let left = pad / 2;
    let right = pad - left;
    format!("{}{}{}", " ".repeat(left), s, " ".repeat(right))
}

fn pad_left(s: &str, w: usize) -> String {
    let slen = s.chars().count();
    if slen >= w { return s.chars().take(w).collect(); }
    format!("{}{}", s, " ".repeat(w - slen))
}

fn format_num(n: usize) -> String {
    let s = n.to_string();
    let mut result = String::new();
    for (i, ch) in s.chars().rev().enumerate() {
        if i > 0 && i % 3 == 0 { result.push(','); }
        result.push(ch);
    }
    result.chars().rev().collect()
}

fn print_table_header(cols: &[&str], widths: &[usize], prefix: &str) {
    println!("{prefix}┌{}┐", widths.iter().map(|w| "─".repeat(*w)).collect::<Vec<_>>().join("┬"));
    println!("{prefix}│{}│",
        cols.iter().zip(widths.iter()).map(|(c, w)| center_str(c, *w)).collect::<Vec<_>>().join("│"));
    println!("{prefix}├{}┤", widths.iter().map(|w| "─".repeat(*w)).collect::<Vec<_>>().join("┼"));
}

fn print_table_row(vals: &[String], widths: &[usize], prefix: &str) {
    println!("{prefix}│{}│",
        vals.iter().zip(widths.iter()).map(|(v, w)| center_str(v, *w)).collect::<Vec<_>>().join("│"));
}

fn print_table_bottom(widths: &[usize], prefix: &str) {
    println!("{prefix}└{}┘", widths.iter().map(|w| "─".repeat(*w)).collect::<Vec<_>>().join("┴"));
}

// ── Adversarial resilience sweep ─────────────────────────

fn run_adversarial(seed: u64, weights: [f64; 5]) {
    header("ADVERSARIAL RESILIENCE SWEEP");
    println!();
    println!("  N=100 agents, adversarial ratio 0%–90%, seed={seed}");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let pcts = vec![0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);

        let widths = vec![10, 8, 8, 8, 6, 10];
        let cols = vec!["Adv %", "Claims", "Output", "Prec", "FP", "Time"];
        print_table_header(&cols, &widths, "    ");

        for &pct in &pcts {
            let roster = agents::get_adversarial_roster(100, pct);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);
            let m = Metrics::from_result(&result);

            let row = vec![
                format!("{}%", pct as u32),
                format!("{}", result.all_contributions.len()),
                format!("{}", result.admitted.len()),
                format!("{:.0}%", m.precision() * 100.0),
                format!("{}", m.fp),
                format!("{:.3}ms", result.time_us as f64 / 1000.0),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }
}

// ── Expert dropout test ─────────────────────────────────

fn run_expert_dropout(seed: u64, weights: [f64; 5]) {
    header("EXPERT DROPOUT TEST");
    println!();
    println!("  Comparing normal roster vs no-expert roster, N=100, seed={seed}");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        // Normal roster
        let normal_roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);
        let normal_result = compiler.compile(&topic, &normal_roster, seed);
        let nm = Metrics::from_result(&normal_result);

        // No-expert roster
        let no_expert_roster = agents::get_no_expert_roster(100);
        let no_expert_result = compiler.compile(&topic, &no_expert_roster, seed);
        let nem = Metrics::from_result(&no_expert_result);

        println!("    {:20} {:>10} {:>10}", "", "Normal", "No Expert");
        println!("    {:20} {:>10} {:>10}", "Admitted:", normal_result.admitted.len(), no_expert_result.admitted.len());
        println!("    {:20} {:>9.0}% {:>9.0}%", "Precision:", nm.precision() * 100.0, nem.precision() * 100.0);
        println!("    {:20} {:>10} {:>10}", "False positives:", nm.fp, nem.fp);
        println!("    {:20} {:>10} {:>10}", "True positives:", nm.tp, nem.tp);
        println!();
    }
}

// ── Sybil attack test ───────────────────────────────────

fn run_sybil(seed: u64, weights: [f64; 5]) {
    header("SYBIL ATTACK TEST");
    println!();
    println!("  Injecting sybil agents with fabricated citations, seed={seed}");
    println!();

    // Australia sybil: assert Sydney as capital
    let topic = topics::get_topic("australia").unwrap();
    let roster = agents::get_roster(20);
    let compiler = OverturnCompiler::with_weights(weights);

    println!("  {} — target: (Australia, has_capital, Sydney)", bold("australia"));
    println!();

    let sybil_counts = vec![0, 1, 2, 5, 10, 20];
    let widths = vec![8, 8, 8, 8, 6, 24];
    let cols = vec!["Sybils", "Legit", "Prec", "FP", "Win", "Winner"];
    print_table_header(&cols, &widths, "    ");

    for &n_sybils in &sybil_counts {
        let injected = agents::sybil_claims(
            "Sybil",
            "Australia", "has_capital", "Sydney",
            "Sydney is Australia's largest city and de facto capital",
            n_sybils,
        );
        let result = compiler.compile_with_injected(&topic, &roster, seed, injected);
        let m = Metrics::from_result(&result);

        // Check who won the has_capital conflict
        let winner_name = result.conflicts.iter()
            .find(|cs| cs.triple_key.1 == "has_capital")
            .and_then(|cs| cs.winner_idx)
            .map(|idx| {
                let c = &result.all_contributions[idx];
                let obj = c.canonical_form.as_ref().map(|t| t.object.as_str()).unwrap_or("?");
                format!("{} → {}", c.agent_name, obj)
            })
            .unwrap_or_else(|| "—".to_string());

        let sybil_won = winner_name.contains("Sydney");
        let row = vec![
            format!("{}", n_sybils),
            format!("{}", 20),
            format!("{:.0}%", m.precision() * 100.0),
            format!("{}", m.fp),
            if sybil_won { "YES".to_string() } else { "no".to_string() },
            winner_name,
        ];
        print_table_row(&row, &widths, "    ");
    }
    print_table_bottom(&widths, "    ");

    // Nutrition sybil: assert "no effect on heart disease"
    println!();
    let topic = topics::get_topic("nutrition").unwrap();
    let roster = agents::get_roster(20);

    println!("  {} — target: (saturated_fat, has, no effect on heart disease)", bold("nutrition"));
    println!();

    print_table_header(&cols, &widths, "    ");

    for &n_sybils in &sybil_counts {
        let injected = agents::sybil_claims(
            "Sybil",
            "saturated_fat", "has", "no effect on heart disease",
            "Saturated fat has no effect on heart disease, debunking decades of dietary guidelines",
            n_sybils,
        );
        let result = compiler.compile_with_injected(&topic, &roster, seed, injected);
        let m = Metrics::from_result(&result);

        let winner_name = result.conflicts.iter()
            .find(|cs| cs.triple_key == ("saturated_fat".to_string(), "has".to_string()))
            .and_then(|cs| cs.winner_idx)
            .map(|idx| {
                let c = &result.all_contributions[idx];
                let obj = c.canonical_form.as_ref().map(|t| t.object.as_str()).unwrap_or("?");
                format!("{} → {}", c.agent_name, obj)
            })
            .unwrap_or_else(|| "—".to_string());

        let sybil_won = winner_name.contains("Sybil");
        let row = vec![
            format!("{}", n_sybils),
            format!("{}", 20),
            format!("{:.0}%", m.precision() * 100.0),
            format!("{}", m.fp),
            if sybil_won { "YES".to_string() } else { "no".to_string() },
            winner_name,
        ];
        print_table_row(&row, &widths, "    ");
    }
    print_table_bottom(&widths, "    ");
    println!();
}

// ── Scoring noise sensitivity ─────────────────────────────

fn run_noise(base_weights: [f64; 5]) {
    header("SCORING NOISE SENSITIVITY");
    println!();
    println!("  Testing: seed variance vs parameter noise across 50 seeds × 3 topics");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let seeds: Vec<u64> = (1..=50).collect();

    // Weight noise profiles: add σ noise to each weight, renormalize
    let noise_levels = [0.0, 0.05, 0.10, 0.20, 0.50];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["Noise σ", "Mean FP", "FP Std", "Min FP", "Max FP", "Mean Prec", "Prec Std"];
        let widths = vec![8, 8, 8, 7, 7, 10, 10];
        print_table_header(&cols, &widths, "    ");

        for &sigma in &noise_levels {
            let mut fps = Vec::new();
            let mut precs = Vec::new();

            for &seed in &seeds {
                // Apply noise to weights using deterministic RNG
                let weights = if sigma > 0.0 {
                    let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed * 1000 + (sigma * 100.0) as u64);
                    let mut w = base_weights;
                    for wi in &mut w {
                        use rand::Rng;
                        let noise: f64 = rng.gen_range(-sigma..sigma);
                        *wi = (*wi + noise).max(0.01);
                    }
                    // Renormalize
                    let sum: f64 = w.iter().sum();
                    for wi in &mut w { *wi /= sum; }
                    w
                } else {
                    base_weights
                };

                let roster = agents::get_roster(100);
                let compiler = OverturnCompiler::with_weights(weights);
                let result = compiler.compile(&topic, &roster, seed);
                let m = Metrics::from_result(&result);
                fps.push(m.fp as f64);
                precs.push(m.precision());
            }

            let mean_fp = fps.iter().sum::<f64>() / fps.len() as f64;
            let fp_std = (fps.iter().map(|x| (x - mean_fp).powi(2)).sum::<f64>() / fps.len() as f64).sqrt();
            let min_fp = fps.iter().cloned().fold(f64::INFINITY, f64::min);
            let max_fp = fps.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
            let mean_prec = precs.iter().sum::<f64>() / precs.len() as f64;
            let prec_std = (precs.iter().map(|x| (x - mean_prec).powi(2)).sum::<f64>() / precs.len() as f64).sqrt();

            let row = vec![
                format!("{:.2}", sigma),
                format!("{:.1}", mean_fp),
                format!("{:.2}", fp_std),
                format!("{:.0}", min_fp),
                format!("{:.0}", max_fp),
                format!("{:.1}%", mean_prec * 100.0),
                format!("{:.2}%", prec_std * 100.0),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Also show seed-only variance (σ=0, different seeds)
    println!("  {}", bold("Conclusion: compare FP Std at σ=0 (seed variance) vs σ=0.50 (max noise)"));
    println!("  If seed variance ≥ noise variance, claim selection dominates parameter tuning.");
    println!();
}

// ── Family dominance (EES-is-decorative) ─────────────────

fn run_family_dominance(seed: u64, weights: [f64; 5]) {
    header("FAMILY DOMINANCE — EES-IS-DECORATIVE TEST");
    println!();
    println!("  N=100, seed={seed}. Varying Claude proportion from 20% to 100%.", seed=seed);
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let claude_pcts = vec![20, 40, 60, 80, 100];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["Claude %", "EES", "Prec", "FP", "Admitted", "Conflicts"];
        let widths = vec![9, 7, 7, 5, 9, 9];
        print_table_header(&cols, &widths, "    ");

        for &pct in &claude_pcts {
            let roster = build_family_dominated_roster(100, pct);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);
            let m = Metrics::from_result(&result);

            let row = vec![
                format!("{}%", pct),
                format!("{:.2}", result.ees),
                format!("{:.0}%", m.precision() * 100.0),
                format!("{}", m.fp),
                format!("{}", result.admitted.len()),
                format!("{}", result.conflicts.len()),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }
}

fn build_family_dominated_roster(n: usize, claude_pct: usize) -> Vec<agents::AgentPersonality> {
    use agents::AgentPersonality;
    use crate::ir::LoweringConfidence::*;

    let n_claude = (n * claude_pct) / 100;
    let n_other = n - n_claude;

    let claude_templates = vec![
        AgentPersonality::new("Claude Expert", agents::Archetype::Expert, "Claude", 0.90, 0.92, High),
        AgentPersonality::new("Claude Generalist", agents::Archetype::Generalist, "Claude", 0.65, 0.70, Medium),
        AgentPersonality::new("Claude Copier", agents::Archetype::Copier, "Claude", 0.55, 0.50, Medium),
        AgentPersonality::new("Claude Halluc", agents::Archetype::Hallucinator, "Claude", 0.30, 0.25, Low),
    ];
    let other_templates = vec![
        AgentPersonality::new("GPT Expert", agents::Archetype::Expert, "GPT-4", 0.88, 0.90, High),
        AgentPersonality::new("Gemini Gen", agents::Archetype::Generalist, "Gemini", 0.65, 0.70, Medium),
        AgentPersonality::new("Llama Contrarian", agents::Archetype::Contrarian, "Llama", 0.50, 0.45, Medium),
        AgentPersonality::new("Mistral Halluc", agents::Archetype::Hallucinator, "Mistral", 0.30, 0.25, Low),
    ];

    let mut roster = Vec::with_capacity(n);
    for i in 0..n_claude {
        let mut a = claude_templates[i % claude_templates.len()].clone();
        a.name = format!("{} #{}", a.name, i + 1);
        roster.push(a);
    }
    for i in 0..n_other {
        let mut a = other_templates[i % other_templates.len()].clone();
        a.name = format!("{} #{}", a.name, i + 1);
        roster.push(a);
    }
    roster
}

// ── Per-pass timing breakdown ────────────────────────────

fn run_pass_timing(seed: u64, weights: [f64; 5]) {
    header("PER-PASS TIMING BREAKDOWN");
    println!();
    println!("  Measuring each pass individually across scales, seed={seed}");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let scales: &[usize] = &[10, 100, 1_000, 10_000];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["N", "P1+P2", "P3", "P4", "P5", "P6", "Total", "P5 %"];
        let widths = vec![7, 10, 10, 10, 10, 10, 10, 7];
        print_table_header(&cols, &widths, "    ");

        for &n in scales {
            let roster = agents::get_roster(n);
            let compiler = OverturnCompiler::with_weights(weights);

            // P1+P2
            let t0 = std::time::Instant::now();
            let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
            let _intent = (topic.goal, &topic.constraints, &topic.criteria);
            let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);
            let t_p12 = t0.elapsed();

            // P3
            let t0 = std::time::Instant::now();
            let valid = compiler.p3_validate_pub(&contributions);
            let t_p3 = t0.elapsed();

            // P4
            let t0 = std::time::Instant::now();
            let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
            let t_p4 = t0.elapsed();

            // P5
            let t0 = std::time::Instant::now();
            compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
            let t_p5 = t0.elapsed();

            // P6
            let t0 = std::time::Instant::now();
            let _result = compiler.p6_commit_pub(valid, conflicts, &roster, 0, &topic);
            let t_p6 = t0.elapsed();

            let total = t_p12 + t_p3 + t_p4 + t_p5 + t_p6;
            let p5_pct = if total.as_nanos() > 0 {
                t_p5.as_nanos() as f64 / total.as_nanos() as f64 * 100.0
            } else { 0.0 };

            let fmt_dur = |d: std::time::Duration| -> String {
                let us = d.as_micros();
                if us < 1000 { format!("{}μs", us) }
                else if us < 1_000_000 { format!("{:.1}ms", us as f64 / 1000.0) }
                else { format!("{:.2}s", us as f64 / 1_000_000.0) }
            };

            let row = vec![
                format_num(n),
                fmt_dur(t_p12),
                fmt_dur(t_p3),
                fmt_dur(t_p4),
                fmt_dur(t_p5),
                fmt_dur(t_p6),
                fmt_dur(total),
                format!("{:.0}%", p5_pct),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }
}

// ── Scoring component ablation ────────────────────────────

fn run_ablation(seed: u64) {
    header("SCORING COMPONENT ABLATION STUDY");
    println!();
    println!("  Testing: which scoring components actually flip conflict winners?");
    println!("  N=100, seed={seed}");
    println!();

    // Ablation profiles: zero out one component at a time, plus special configs
    let profiles: Vec<(&str, [f64; 5])> = vec![
        ("Default",        [0.35, 0.20, 0.25, 0.05, 0.15]),
        ("No evidence",    [0.00, 0.35, 0.25, 0.15, 0.25]),
        ("No confidence",  [0.45, 0.00, 0.30, 0.05, 0.20]),
        ("No critique-surv",[0.45, 0.25, 0.00, 0.05, 0.25]),
        ("No recency",     [0.40, 0.20, 0.25, 0.00, 0.15]),
        ("No constraint",  [0.40, 0.25, 0.30, 0.05, 0.00]),
        ("Evidence only",  [1.00, 0.00, 0.00, 0.00, 0.00]),
        ("Confidence only",[0.00, 1.00, 0.00, 0.00, 0.00]),
        ("CS only",        [0.00, 0.00, 1.00, 0.00, 0.00]),
        ("Uniform",        [0.20, 0.20, 0.20, 0.20, 0.20]),
    ];

    let topic_keys = vec!["australia", "tcp", "nutrition"];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["Profile", "Prec", "FP", "FN", "Adm", "Winners Changed"];
        let widths = vec![16, 7, 5, 5, 5, 16];
        print_table_header(&cols, &widths, "    ");

        // Get default winners for comparison
        let roster = agents::get_roster(100);
        let default_compiler = OverturnCompiler::with_weights(profiles[0].1);
        let default_result = default_compiler.compile(&topic, &roster, seed);
        let default_winners: Vec<Option<usize>> = default_result.conflicts.iter()
            .map(|cs| cs.winner_idx).collect();

        for &(name, weights) in &profiles {
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);
            let m = Metrics::from_result(&result);

            // Count how many conflict winners changed vs default
            let changed = result.conflicts.iter().zip(default_winners.iter())
                .filter(|(cs, dw)| cs.winner_idx != **dw)
                .count();

            let row = vec![
                name.to_string(),
                format!("{:.0}%", m.precision() * 100.0),
                format!("{}", m.fp),
                format!("{}", m.fn_),
                format!("{}", result.admitted.len()),
                if name == "Default" { "—".to_string() } else { format!("{}/{}", changed, result.conflicts.len()) },
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Test lowering factor impact: what if all agents have HIGH lowering?
    println!();
    stage("Lowering Factor Ablation: All agents HIGH vs Default mix");
    println!();

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {}", bold(key));

        // Default roster
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights([0.35, 0.20, 0.25, 0.05, 0.15]);
        let result = compiler.compile(&topic, &roster, seed);
        let m = Metrics::from_result(&result);
        println!("    Default mix (H/M/L):  Prec={:.0}%, FP={}, Admitted={}", m.precision() * 100.0, m.fp, result.admitted.len());

        // All-HIGH roster
        let mut all_high_roster = agents::get_roster(100);
        for a in &mut all_high_roster {
            a.lowering_quality = ir::LoweringConfidence::High;
        }
        let result2 = compiler.compile(&topic, &all_high_roster, seed);
        let m2 = Metrics::from_result(&result2);
        println!("    All HIGH lowering:    Prec={:.0}%, FP={}, Admitted={}", m2.precision() * 100.0, m2.fp, result2.admitted.len());

        // All-LOW roster
        let mut all_low_roster = agents::get_roster(100);
        for a in &mut all_low_roster {
            a.lowering_quality = ir::LoweringConfidence::Low;
        }
        let result3 = compiler.compile(&topic, &all_low_roster, seed);
        let m3 = Metrics::from_result(&result3);
        println!("    All LOW lowering:     Prec={:.0}%, FP={}, Admitted={}", m3.precision() * 100.0, m3.fp, result3.admitted.len());
        println!();
    }

    // Critique impact analysis
    stage("Critique Impact Analysis");
    println!();

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights([0.35, 0.20, 0.25, 0.05, 0.15]);
        let result = compiler.compile(&topic, &roster, seed);

        let n_critiques = result.all_contributions.iter()
            .filter(|c| c.kind == ContributionKind::Critique).count();

        // Check which conflicts have non-1.0 CS scores
        let mut affected_conflicts = 0;
        for cs in &result.conflicts {
            let has_reduced_cs = cs.scores.values().any(|s| s.cs < 0.99);
            if has_reduced_cs { affected_conflicts += 1; }
        }

        println!("  {}: {} critiques, {}/{} conflicts have reduced CS scores",
            bold(key), n_critiques, affected_conflicts, result.conflicts.len());
    }
    println!();
}

// ── Main ──────────────────────────────────────────────────

// ── Score-Gap Analysis (Schulze Investigation) ─────────

fn run_score_gaps(seed: u64, weights: [f64; 5]) {
    header("Score-Gap Analysis: Do Deadband Ties Occur?");
    println!("  Paper claims Schulze voting triggers when top-2 scores are within 5% of range.");
    println!("  Testing whether this condition EVER occurs in practice.\n");

    let topic_keys = ["australia", "tcp", "nutrition"];
    let scales: &[usize] = &[10, 50, 100, 500, 1000, 10000];
    let deadband_threshold = 0.05; // 5% of score range

    // Track overall stats
    let mut total_conflicts = 0usize;
    let mut total_within_deadband = 0usize;
    let mut narrowest_gap = f64::INFINITY;
    let mut narrowest_info = String::new();

    for &topic_key in &topic_keys {
        let topic = topics::get_topic(topic_key).unwrap();
        stage(&format!("Topic: {topic_key}"));

        for &n in scales {
            let roster = agents::get_roster(n);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);

            let mut conflicts_this = 0;
            let mut deadband_this = 0;
            let abs_deadband_this = result.conflicts.iter().filter(|cs| cs.in_deadband).count();
            let schulze_this = result.conflicts.iter().filter(|cs| cs.schulze_winner.is_some()).count();

            for cs in &result.conflicts {
                if cs.contribution_ids.len() < 2 {
                    continue;
                }

                // Collect all final scores
                let mut scores: Vec<(usize, f64)> = cs.contribution_ids.iter()
                    .filter_map(|&idx| cs.scores.get(&idx).map(|s| (idx, s.final_score)))
                    .collect();
                scores.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

                if scores.len() < 2 {
                    continue;
                }

                conflicts_this += 1;
                total_conflicts += 1;

                let top1 = scores[0].1;
                let top2 = scores[1].1;
                let gap = top1 - top2;
                let range = scores[0].1 - scores.last().unwrap().1;
                let relative_gap = if range > 0.0 { gap / range } else { 1.0 };

                if relative_gap < deadband_threshold {
                    deadband_this += 1;
                    total_within_deadband += 1;
                }

                if gap < narrowest_gap {
                    narrowest_gap = gap;
                    let winner = &result.all_contributions[scores[0].0];
                    let runner = &result.all_contributions[scores[1].0];
                    narrowest_info = format!(
                        "topic={}, N={}, gap={:.6}, rel={:.4}, winner='{}' vs runner='{}'",
                        topic_key, n, gap, relative_gap,
                        winner.canonical_form.as_ref().map(|t| t.to_string()).unwrap_or_default(),
                        runner.canonical_form.as_ref().map(|t| t.to_string()).unwrap_or_default(),
                    );
                }
            }

            println!(
                "    N={:>6}: {} conflicts, {} within 5%-of-range gap, {} in compiler deadband (abs 500), {} Schulze-resolved",
                n, conflicts_this, deadband_this, abs_deadband_this, schulze_this
            );
        }
    }

    // Multi-seed analysis at N=100
    stage("Multi-seed analysis (50 seeds, N=100)");
    let mut seed_deadbands = 0usize;
    let mut seed_conflicts = 0usize;
    let mut all_gaps: Vec<f64> = Vec::new();

    for &topic_key in &topic_keys {
        let topic = topics::get_topic(topic_key).unwrap();
        for s in 0..50u64 {
            let roster = agents::get_roster(100);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, s);

            for cs in &result.conflicts {
                if cs.contribution_ids.len() < 2 { continue; }
                let mut scores: Vec<f64> = cs.contribution_ids.iter()
                    .filter_map(|&idx| cs.scores.get(&idx).map(|s| s.final_score))
                    .collect();
                scores.sort_by(|a, b| b.partial_cmp(a).unwrap_or(std::cmp::Ordering::Equal));
                if scores.len() < 2 { continue; }

                seed_conflicts += 1;
                let gap = scores[0] - scores[1];
                let range = scores[0] - scores.last().unwrap();
                let relative = if range > 0.0 { gap / range } else { 1.0 };
                all_gaps.push(relative);

                if relative < deadband_threshold {
                    seed_deadbands += 1;
                }
            }
        }
    }

    all_gaps.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    // ── Detailed Conflict Analysis (N=100, seed=42) ─────────
    stage("Detailed Conflict Analysis (N=100, seed=42)");
    println!("  Key question: in deadband cases, are top-2 candidates always same correctness?");
    println!("  If so, Schulze cannot change a correctness outcome.\n");

    let mut same_correctness_total = 0usize;
    let mut diff_correctness_total = 0usize;
    let mut same_correctness_deadband = 0usize;
    let mut diff_correctness_deadband = 0usize;

    for &topic_key in &topic_keys {
        let topic = topics::get_topic(topic_key).unwrap();
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);
        let result = compiler.compile(&topic, &roster, 42);

        println!("    {} ({} conflicts)", bold(topic_key), result.conflicts.len());

        for cs in &result.conflicts {
            if cs.contribution_ids.len() < 2 { continue; }

            let mut scored: Vec<(usize, f64)> = cs.contribution_ids.iter()
                .filter_map(|&idx| cs.scores.get(&idx).map(|s| (idx, s.final_score)))
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

            if scored.len() < 2 { continue; }

            let top1_idx = scored[0].0;
            let top2_idx = scored[1].0;
            let top1_score = scored[0].1;
            let top2_score = scored[1].1;
            let abs_gap = top1_score - top2_score;
            let range = top1_score - scored.last().unwrap().1;
            let rel_gap = if range > 0.0 { abs_gap / range } else { 1.0 };
            let in_deadband = rel_gap < deadband_threshold;

            let top1_correct = result.all_contributions[top1_idx].is_correct;
            let top2_correct = result.all_contributions[top2_idx].is_correct;
            let same_correct = top1_correct == top2_correct;

            if same_correct { same_correctness_total += 1; } else { diff_correctness_total += 1; }
            if in_deadband {
                if same_correct { same_correctness_deadband += 1; } else { diff_correctness_deadband += 1; }
            }

            let top1_label = result.all_contributions[top1_idx].canonical_form
                .as_ref().map(|t| t.to_string()).unwrap_or_else(|| "???".to_string());
            let top2_label = result.all_contributions[top2_idx].canonical_form
                .as_ref().map(|t| t.to_string()).unwrap_or_else(|| "???".to_string());

            let deadband_marker = if in_deadband { red(" [DEADBAND]") } else { String::new() };
            let correctness_marker = if same_correct {
                dim(" (same correctness)")
            } else {
                red(" (DIFFERENT correctness!)")
            };

            println!("      {} | members={} | top1={:.4} top2={:.4} | abs_gap={:.4} rel_gap={:.4}{}{}",
                cs.typ, cs.contribution_ids.len(),
                top1_score, top2_score, abs_gap, rel_gap,
                deadband_marker, correctness_marker);
            println!("        winner: {} [{}]",
                if top1_correct { green("correct") } else { red("WRONG") },
                dim(&top1_label));
            println!("        runner: {} [{}]",
                if top2_correct { green("correct") } else { red("WRONG") },
                dim(&top2_label));
        }

        // Mixed-correctness analysis for CONTRADICTION conflicts
        let mut contra_total = 0usize;
        let mut contra_mixed = 0usize;
        let mut top2_all_same = true;
        for cs in &result.conflicts {
            if cs.typ != ConflictType::Contradiction { continue; }
            if cs.contribution_ids.len() < 2 { continue; }
            contra_total += 1;

            let correctness_vals: Vec<bool> = cs.contribution_ids.iter()
                .map(|&idx| result.all_contributions[idx].is_correct)
                .collect();
            let has_true = correctness_vals.iter().any(|&c| c);
            let has_false = correctness_vals.iter().any(|&c| !c);
            if has_true && has_false {
                contra_mixed += 1;
            }

            // Check top-2 correctness
            let mut scored: Vec<(usize, f64)> = cs.contribution_ids.iter()
                .filter_map(|&idx| cs.scores.get(&idx).map(|s| (idx, s.final_score)))
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            if scored.len() >= 2 {
                let t1_correct = result.all_contributions[scored[0].0].is_correct;
                let t2_correct = result.all_contributions[scored[1].0].is_correct;
                if t1_correct != t2_correct {
                    top2_all_same = false;
                }
            }
        }
        println!("      Contradictions with mixed correctness: {}/{}", contra_mixed, contra_total);
        println!("      (top-2 same correctness in all: {})",
            if top2_all_same { "yes" } else { "no" });

        println!();
    }

    // ── Correctness Boundary Gap ───────────────────────────
    stage("Correctness Boundary Gap (contradiction sets only)");
    println!("  Measures the score gap between last-correct and first-incorrect in each contradiction.\n");

    for &topic_key in &topic_keys {
        let topic = topics::get_topic(topic_key).unwrap();
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);
        let result = compiler.compile(&topic, &roster, 42);

        println!("    {}", bold(topic_key));
        for cs in &result.conflicts {
            if cs.typ != ConflictType::Contradiction { continue; }

            // Sort all members by score descending
            let mut scored: Vec<(usize, f64, bool)> = cs.contribution_ids.iter()
                .filter_map(|&idx| {
                    cs.scores.get(&idx).map(|s| (idx, s.final_score, result.all_contributions[idx].is_correct))
                })
                .collect();
            scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

            // Find lowest correct and highest incorrect
            let lowest_correct = scored.iter().filter(|s| s.2).last();
            let highest_incorrect = scored.iter().filter(|s| !s.2).next();

            if let (Some(lc), Some(hi)) = (lowest_correct, highest_incorrect) {
                let boundary_gap = lc.1 - hi.1;
                let n_correct = scored.iter().filter(|s| s.2).count();
                let n_incorrect = scored.iter().filter(|s| !s.2).count();
                println!(
                    "      {} | {}C/{}W | lowest_correct={:.4} highest_wrong={:.4} | boundary_gap={:.4} ({:.1}%)",
                    cs.slot_key,
                    n_correct, n_incorrect,
                    lc.1, hi.1, boundary_gap, boundary_gap / lc.1 * 100.0
                );
            }
        }
        println!();
    }

    // ── Separation margin per contradiction set ─────────────
    stage("Separation Margin: min(correct score) − max(incorrect score) per contradiction set");
    println!("  Separated = margin > 0.05 on final score. Mixed = set has both correct and incorrect members.");
    println!("  Unmixed sets have no margin (all-correct or all-incorrect).\n");
    println!("    {:<10} {:>6} {:>6} {:>6} {:>10} {:>12} {:>12} {:>10}",
        "topic", "N", "contra", "mixed", "sep>0.05", "0<m≤0.05", "m≤0 (inv.)", "min m");
    for &topic_key in &topic_keys {
        let topic = topics::get_topic(topic_key).unwrap();
        for &n in &[100usize, 1_000, 10_000] {
            let roster = agents::get_roster(n);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);
            let (mut contra, mut mixed, mut sep, mut thin, mut inverted) = (0, 0, 0, 0, 0);
            let mut min_margin = f64::INFINITY;
            for cs in &result.conflicts {
                if cs.typ != ConflictType::Contradiction { continue; }
                contra += 1;
                let (mut min_c, mut max_w) = (f64::INFINITY, f64::NEG_INFINITY);
                for &idx in &cs.contribution_ids {
                    let sc = cs.scores[&idx].final_score;
                    if result.all_contributions[idx].is_correct { min_c = min_c.min(sc); } else { max_w = max_w.max(sc); }
                }
                if min_c.is_finite() && max_w.is_finite() {
                    mixed += 1;
                    let margin = min_c - max_w;
                    min_margin = min_margin.min(margin);
                    if margin > 0.05 { sep += 1; } else if margin > 0.0 { thin += 1; } else { inverted += 1; }
                }
            }
            let mm = if min_margin.is_finite() { format!("{:.4}", min_margin) } else { "—".to_string() };
            println!("    {:<10} {:>6} {:>6} {:>6} {:>10} {:>12} {:>12} {:>10}",
                topic_key, n, contra, mixed, sep, thin, inverted, mm);
        }
    }
    println!();

    println!("    {}", bold("Correctness concordance:"));
    println!("      All conflicts:     same={}, different={}", same_correctness_total, diff_correctness_total);
    println!("      Deadband only:     same={}, different={}", same_correctness_deadband, diff_correctness_deadband);
    if diff_correctness_total == 0 && diff_correctness_deadband == 0 {
        println!("      {} Top-2 always share correctness. Schulze CANNOT change quality.", green("VERDICT:"));
    } else if diff_correctness_deadband == 0 {
        println!("      {} Deadband cases share correctness. Schulze irrelevant in close races.", green("VERDICT:"));
    } else {
        println!("      {} {} deadband conflicts have different correctness -- Schulze could matter!",
            yellow("VERDICT:"), diff_correctness_deadband);
    }
    println!();

    stage("Summary");
    println!("  Total conflicts analyzed (scale sweep): {}", total_conflicts);
    println!("  Within 5% deadband (scale sweep):       {}", total_within_deadband);
    println!();
    println!("  Total conflicts (50-seed, N=100):       {}", seed_conflicts);
    println!("  Within 5% deadband (50-seed):           {}", seed_deadbands);
    println!();
    if !all_gaps.is_empty() {
        let p5 = all_gaps[all_gaps.len() * 5 / 100];
        let p25 = all_gaps[all_gaps.len() * 25 / 100];
        let p50 = all_gaps[all_gaps.len() / 2];
        let min = all_gaps[0];
        println!("  Relative gap distribution (50-seed):");
        println!("    min={:.4}, p5={:.4}, p25={:.4}, median={:.4}", min, p5, p25, p50);
    }
    println!();
    println!("  Narrowest absolute gap: {}", narrowest_info);
    println!();

    if total_within_deadband == 0 && seed_deadbands == 0 {
        println!("  {} No deadband ties found. Schulze escalation would NEVER trigger.", green("RESULT:"));
        println!("  Simple argmax is sufficient for all tested conditions.");
    } else {
        let pct = (total_within_deadband + seed_deadbands) as f64 / (total_conflicts + seed_conflicts) as f64 * 100.0;
        println!("  {} {:.1}% of conflicts fall within deadband.", yellow("RESULT:"), pct);
        println!("  Schulze escalation would be relevant.");
    }
}

// ── CP-WBFT threshold comparison ─────────────────────────

fn run_cpwbft(seed: u64, weights: [f64; 5]) {
    header("CP-WBFT THRESHOLD COMPARISON");
    println!();
    println!("  Comparing overturn's adversarial resilience at CP-WBFT's exact thresholds");
    println!("  Yan et al. (2025): 85.7% and 93.3% Byzantine tolerance on 15-node networks");
    println!("  N=100 agents, seed={seed}");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    // Include 0% baseline, standard checkpoints, and CP-WBFT exact thresholds
    let pcts: Vec<f64> = vec![0.0, 33.3, 50.0, 66.7, 80.0, 85.7, 90.0, 93.3];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);

        let widths = vec![10, 8, 8, 8, 6, 10];
        let cols = vec!["Adv %", "Claims", "Output", "Prec", "FP", "Time"];
        print_table_header(&cols, &widths, "    ");

        for &pct in &pcts {
            let roster = agents::get_adversarial_roster(100, pct);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed);
            let m = Metrics::from_result(&result);

            let row = vec![
                format!("{:.1}%", pct),
                format!("{}", result.all_contributions.len()),
                format!("{}", result.admitted.len()),
                format!("{:.0}%", m.precision() * 100.0),
                format!("{}", m.fp),
                format!("{:.3}ms", result.time_us as f64 / 1000.0),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Multi-seed analysis at the two CP-WBFT thresholds
    println!("  {} Multi-seed analysis (50 seeds) at CP-WBFT thresholds:", bold("SEED SWEEP"));
    println!();

    let cpwbft_pcts = vec![85.7, 93.3];
    let num_seeds = 50;

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);

        let widths = vec![10, 10, 10, 10, 10, 10];
        let cols = vec!["Adv %", "Mean FP", "Min FP", "Max FP", "Mean Prec", "Std Prec"];
        print_table_header(&cols, &widths, "    ");

        for &pct in &cpwbft_pcts {
            let mut fps: Vec<usize> = Vec::new();
            let mut precs: Vec<f64> = Vec::new();

            for s in 0..num_seeds {
                let roster = agents::get_adversarial_roster(100, pct);
                let compiler = OverturnCompiler::with_weights(weights);
                let result = compiler.compile(&topic, &roster, seed + s);
                let m = Metrics::from_result(&result);
                fps.push(m.fp);
                precs.push(m.precision());
            }

            let mean_fp = fps.iter().sum::<usize>() as f64 / num_seeds as f64;
            let min_fp = *fps.iter().min().unwrap();
            let max_fp = *fps.iter().max().unwrap();
            let mean_prec = precs.iter().sum::<f64>() / num_seeds as f64;
            let std_prec = {
                let var = precs.iter().map(|p| (p - mean_prec).powi(2)).sum::<f64>() / num_seeds as f64;
                var.sqrt()
            };

            let row = vec![
                format!("{:.1}%", pct),
                format!("{:.1}", mean_fp),
                format!("{}", min_fp),
                format!("{}", max_fp),
                format!("{:.1}%", mean_prec * 100.0),
                format!("{:.1}%", std_prec * 100.0),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    println!("  {} CP-WBFT comparison notes:", bold("CONTEXT:"));
    println!("    Yan et al. tolerate 85.7% Byzantine on 15 nodes (HCP method).");
    println!("    Yan et al. tolerate 93.3% Byzantine on 15 nodes (best case).");
    println!("    Classical BFT bound: f < n/3 = 33.3% Byzantine tolerance.");
    println!("    Overturn's mechanism: evidence-quality scoring, not voting/consensus.");
}

// ── Condorcet jury condition check ───────────────────────

fn run_condorcet(seed: u64, weights: [f64; 5]) {
    header("CONDORCET JURY CONDITION CHECK");
    println!();
    println!("  Testing: what fraction of agents are 'more likely than not to be correct'?");
    println!("  Condorcet jury theorem requires p > 0.5 for each voter for majority→truth.");
    println!("  N=100 agents, 50 seeds");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let num_seeds = 50;

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        // Track per-agent accuracy across seeds
        let mut agent_correct_total: HashMap<String, usize> = HashMap::new();
        let mut agent_claim_total: HashMap<String, usize> = HashMap::new();

        for s in 0..num_seeds {
            let roster = agents::get_roster(100);
            let compiler = OverturnCompiler::with_weights(weights);
            let result = compiler.compile(&topic, &roster, seed + s);

            // Count per-agent correctness
            for c in &result.all_contributions {
                *agent_claim_total.entry(c.agent_name.clone()).or_insert(0) += 1;
                if c.is_correct {
                    *agent_correct_total.entry(c.agent_name.clone()).or_insert(0) += 1;
                }
            }
        }

        // Compute per-agent accuracy
        let mut accuracies: Vec<(String, f64)> = Vec::new();
        for (name, total) in &agent_claim_total {
            let correct = *agent_correct_total.get(name).unwrap_or(&0);
            let acc = correct as f64 / *total as f64;
            accuracies.push((name.clone(), acc));
        }
        accuracies.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());

        let total_agents = accuracies.len();
        let above_half = accuracies.iter().filter(|(_, a)| *a > 0.5).count();
        let at_half = accuracies.iter().filter(|(_, a)| (*a - 0.5).abs() < 0.001).count();
        let below_half = accuracies.iter().filter(|(_, a)| *a < 0.5).count();

        println!("    Agents with accuracy > 50%: {} / {} ({:.0}%)",
            above_half, total_agents, above_half as f64 / total_agents as f64 * 100.0);
        println!("    Agents with accuracy ≈ 50%: {} / {}", at_half, total_agents);
        println!("    Agents with accuracy < 50%: {} / {} ({:.0}%)",
            below_half, total_agents, below_half as f64 / total_agents as f64 * 100.0);
        println!();

        // Show accuracy distribution by archetype pattern
        let widths = vec![25, 10, 10, 10];
        let cols = vec!["Agent Pattern", "Claims", "Accuracy", "p>0.5?"];
        print_table_header(&cols, &widths, "    ");

        // Group by base name (strip # suffix)
        let mut grouped: HashMap<String, (usize, usize)> = HashMap::new();
        for (name, total) in &agent_claim_total {
            let base = name.split(" #").next().unwrap_or(name).to_string();
            let correct = *agent_correct_total.get(name).unwrap_or(&0);
            let entry = grouped.entry(base).or_insert((0, 0));
            entry.0 += correct;
            entry.1 += total;
        }
        let mut grouped_vec: Vec<(String, f64, usize)> = grouped.iter()
            .map(|(name, (correct, total))| (name.clone(), *correct as f64 / *total as f64, *total))
            .collect();
        grouped_vec.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap());

        for (name, acc, total) in &grouped_vec {
            let check = if *acc > 0.5 { green("YES") } else { red("NO") };
            let row = vec![
                name.clone(),
                format!("{}", total),
                format!("{:.1}%", acc * 100.0),
                check,
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");

        let mean_acc: f64 = grouped_vec.iter().map(|(_, a, _)| a).sum::<f64>() / grouped_vec.len() as f64;
        println!("    Mean agent-type accuracy: {:.1}%", mean_acc * 100.0);
        println!("    Condorcet condition (majority p > 0.5): {}",
            if above_half as f64 / total_agents as f64 > 0.5 { green("SATISFIED") } else { red("VIOLATED") });
        println!();
    }
}

// ── Baseline comparison ───────────────────────────────────

/// Select conflict winners by majority vote: the (object, polarity) tuple
/// asserted by the most agents wins.  Ties broken by first-seen order.
fn majority_vote_select(
    conflicts: &mut [ConflictSet],
    valid: &[Contribution],
) {
    for cs in conflicts.iter_mut() {
        // Group members by (object_lower, polarity)
        let mut groups: HashMap<(String, Polarity), Vec<usize>> = HashMap::new();
        for &idx in &cs.contribution_ids {
            if let Some(ref t) = valid[idx].canonical_form {
                let key = (t.object.to_lowercase(), t.polarity);
                groups.entry(key).or_default().push(idx);
            }
        }
        // Winner = group with most members; ties broken by first member index (deterministic)
        let winner_group = groups.values()
            .max_by_key(|members| (members.len(), std::cmp::Reverse(members[0])))
            .cloned()
            .unwrap_or_default();
        // Within winning group, pick the first member (lowest index)
        cs.winner_idx = winner_group.into_iter().min();
    }
}

/// Select conflict winners by highest self-reported confidence.
fn best_confidence_select(
    conflicts: &mut [ConflictSet],
    valid: &[Contribution],
) {
    for cs in conflicts.iter_mut() {
        cs.winner_idx = cs.contribution_ids.iter()
            .max_by(|&&a, &&b| valid[a].confidence.partial_cmp(&valid[b].confidence)
                .unwrap_or(std::cmp::Ordering::Equal))
            .copied();
    }
}

/// Select conflict winners by latest recorded arrival `seq` (last writer wins).
fn last_writer_wins_select(
    conflicts: &mut [ConflictSet],
    valid: &[Contribution],
) {
    for cs in conflicts.iter_mut() {
        cs.winner_idx = cs.contribution_ids.iter()
            .max_by_key(|&&a| valid[a].seq)
            .copied();
    }
}

/// Select conflict winners uniformly at random (deterministic via seed).
fn random_select(
    conflicts: &mut [ConflictSet],
    seed: u64,
) {
    use rand::Rng;
    let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
    for cs in conflicts.iter_mut() {
        if cs.contribution_ids.is_empty() {
            cs.winner_idx = None;
        } else {
            let pick = rng.gen_range(0..cs.contribution_ids.len());
            cs.winner_idx = Some(cs.contribution_ids[pick]);
        }
    }
}

/// Compute FP count from a CompilationResult where conflict winners have been
/// overridden by a baseline selector.
fn count_fp_from_conflicts(
    conflicts: &[ConflictSet],
    valid: &[Contribution],
) -> (usize, usize, usize) {
    let mut tp = 0usize;
    let mut fp = 0usize;
    let mut admitted = HashSet::new();

    // Collect all conflicting indices
    let mut conflicting = HashSet::new();
    for cs in conflicts {
        for &idx in &cs.contribution_ids {
            conflicting.insert(idx);
        }
        if let Some(winner) = cs.winner_idx {
            admitted.insert(winner);
            if valid[winner].is_correct { tp += 1; } else { fp += 1; }
        }
    }

    // Non-conflicting, non-critique assertions are admitted if lowering_confidence >= MEDIUM
    for (idx, c) in valid.iter().enumerate() {
        if !conflicting.contains(&idx) && c.kind != ContributionKind::Critique && !admitted.contains(&idx) {
            if c.lowering_confidence == LoweringConfidence::Low {
                continue; // P6 gate: reject LOW-confidence
            }
            admitted.insert(idx);
            if c.is_correct { tp += 1; } else { fp += 1; }
        }
    }

    let total_admitted = admitted.len();
    (fp, tp, total_admitted)
}

fn run_baselines(seed: u64, weights: [f64; 5]) {
    header("BASELINE COMPARISON: Overturn vs Majority-Vote vs Best-Confidence vs Last-Writer vs Random");
    println!();
    println!("  N=100, 50 seeds × 3 topics. Comparing selection strategies on identical conflict sets.");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let num_seeds = 50u64;

    // Summary table across topics
    let cols = vec!["Topic", "Method", "Mean FP", "Min FP", "Max FP", "Mean Prec", "Std Prec"];
    let widths = vec![12, 19, 8, 7, 7, 10, 10];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();
        print_table_header(&cols, &widths, "    ");

        let methods: Vec<&str> = vec!["Overturn (scored)", "Majority vote", "Best confidence", "Last writer", "Random"];

        for method in &methods {
            let mut fps = Vec::new();
            let mut precs = Vec::new();

            for s in 0..num_seeds {
                let roster = agents::get_roster(100);
                let compiler = OverturnCompiler::with_weights(weights);

                // Run the overturn pipeline through P4 to get conflicts
                let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed + s);
                let _intent = (topic.goal, &topic.constraints, &topic.criteria);
                let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);
                let valid = compiler.p3_validate_pub(&contributions);
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);

                match *method {
                    "Overturn (scored)" => {
                        compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
                    }
                    "Majority vote" => {
                        majority_vote_select(&mut conflicts, &valid);
                    }
                    "Best confidence" => {
                        best_confidence_select(&mut conflicts, &valid);
                    }
                    "Last writer" => {
                        last_writer_wins_select(&mut conflicts, &valid);
                    }
                    "Random" => {
                        random_select(&mut conflicts, seed + s);
                    }
                    _ => unreachable!(),
                }

                let (fp, tp, total) = count_fp_from_conflicts(&conflicts, &valid);
                fps.push(fp);
                let precision = if total == 0 { 1.0 } else { tp as f64 / total as f64 };
                precs.push(precision);
            }

            let mean_fp = fps.iter().sum::<usize>() as f64 / num_seeds as f64;
            let min_fp = *fps.iter().min().unwrap();
            let max_fp = *fps.iter().max().unwrap();
            let mean_prec = precs.iter().sum::<f64>() / num_seeds as f64;
            let std_prec = {
                let var = precs.iter().map(|p| (p - mean_prec).powi(2)).sum::<f64>() / num_seeds as f64;
                var.sqrt()
            };

            let row = vec![
                if *method == "Overturn (scored)" { key.to_string() } else { "".to_string() },
                method.to_string(),
                format!("{:.1}", mean_fp),
                format!("{}", min_fp),
                format!("{}", max_fp),
                format!("{:.1}%", mean_prec * 100.0),
                format!("{:.2}%", std_prec * 100.0),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Adversarial resilience comparison at key thresholds
    stage("Adversarial Resilience: Overturn vs Majority Vote");
    println!("  N=100, single seed={seed}, adversarial ratio sweep");
    println!();

    let adv_pcts = vec![0.0, 20.0, 40.0, 60.0, 80.0, 90.0];
    let cols2 = vec!["Topic", "Adv %", "Overturn FP", "MajVote FP", "BestConf FP", "Random FP"];
    let widths2 = vec![10, 7, 13, 11, 12, 10];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {}", bold(key));
        print_table_header(&cols2, &widths2, "    ");

        for &pct in &adv_pcts {
            let roster = agents::get_adversarial_roster(100, pct);
            let compiler = OverturnCompiler::with_weights(weights);

            let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
            let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);
            let valid = compiler.p3_validate_pub(&contributions);

            // overturn
            let mut conflicts_ov = compiler.p4_detect_pub(&valid, topic.goal);
            compiler.p5_select_pub(&mut conflicts_ov, &valid, &roster, &topic);
            let (fp_ov, _, _) = count_fp_from_conflicts(&conflicts_ov, &valid);

            // Majority vote
            let mut conflicts_mv = compiler.p4_detect_pub(&valid, topic.goal);
            majority_vote_select(&mut conflicts_mv, &valid);
            let (fp_mv, _, _) = count_fp_from_conflicts(&conflicts_mv, &valid);

            // Best confidence
            let mut conflicts_bc = compiler.p4_detect_pub(&valid, topic.goal);
            best_confidence_select(&mut conflicts_bc, &valid);
            let (fp_bc, _, _) = count_fp_from_conflicts(&conflicts_bc, &valid);

            // Random
            let mut conflicts_rand = compiler.p4_detect_pub(&valid, topic.goal);
            random_select(&mut conflicts_rand, seed);
            let (fp_rand, _, _) = count_fp_from_conflicts(&conflicts_rand, &valid);

            let row = vec![
                if pct == 0.0 { key.to_string() } else { "".to_string() },
                format!("{:.0}%", pct),
                format!("{}", fp_ov),
                format!("{}", fp_mv),
                format!("{}", fp_bc),
                format!("{}", fp_rand),
            ];
            print_table_row(&row, &widths2, "    ");
        }
        print_table_bottom(&widths2, "    ");
        println!();
    }

    // Summary verdict
    stage("Verdict");
    println!("  Overturn's evidence scoring selects winners based on evidence QUALITY,");
    println!("  not evidence QUANTITY. Majority vote fails when misconceptions are");
    println!("  popular (many agents repeat them). Best-confidence fails because");
    println!("  hallucinators report high confidence. Last-writer-wins is arbitrary.");
    println!("  Random provides the expected-value lower bound.");
    println!();
}

// ── Minimum-score threshold test ──────────────────────────

fn run_min_score(seed: u64, weights: [f64; 5]) {
    header("MINIMUM-SCORE THRESHOLD TEST");
    println!();
    println!("  Testing: does rejecting low-scoring winners reduce FP?");
    println!("  N=100, 50 seeds × 3 topics, threshold sweep 0.00–0.50");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let num_seeds = 50u64;
    let thresholds: Vec<f64> = vec![0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["Threshold", "Mean FP", "Mean FN", "Mean Prec", "Mean Recall", "Mean Adm"];
        let widths = vec![10, 8, 8, 10, 11, 9];
        print_table_header(&cols, &widths, "    ");

        for &threshold in &thresholds {
            let mut fps = Vec::new();
            let mut fns = Vec::new();
            let mut precs = Vec::new();
            let mut recalls = Vec::new();
            let mut admitteds = Vec::new();

            for s in 0..num_seeds {
                let roster = agents::get_roster(100);
                let compiler = OverturnCompiler::with_weights(weights);
                let result = compiler.compile(&topic, &roster, seed + s);

                // Apply threshold: reject winners whose final_score < threshold
                let mut tp = 0usize;
                let mut fp = 0usize;
                let mut fn_ = 0usize;
                let mut admitted_set: HashSet<usize> = HashSet::new();
                let mut conflicting: HashSet<usize> = HashSet::new();

                for cs in &result.conflicts {
                    for &idx in &cs.contribution_ids {
                        conflicting.insert(idx);
                    }
                    if let Some(winner) = cs.winner_idx {
                        let score = cs.scores.get(&winner)
                            .map(|s| s.final_score).unwrap_or(0.0);
                        if score >= threshold {
                            admitted_set.insert(winner);
                            if result.all_contributions[winner].is_correct { tp += 1; } else { fp += 1; }
                        } else {
                            // Winner rejected by threshold — all members in this conflict are rejected
                            for &idx in &cs.contribution_ids {
                                if result.all_contributions[idx].is_correct {
                                    fn_ += 1;
                                }
                            }
                        }
                    }
                }

                // Non-conflicting, non-critique assertions always admitted (no threshold)
                for (idx, c) in result.all_contributions.iter().enumerate() {
                    if !conflicting.contains(&idx) && c.kind != ContributionKind::Critique
                        && !admitted_set.contains(&idx) {
                        admitted_set.insert(idx);
                        if c.is_correct { tp += 1; } else { fp += 1; }
                    }
                }

                let total = admitted_set.len();
                let precision = if total == 0 { 1.0 } else { tp as f64 / total as f64 };
                let recall = if tp + fn_ == 0 { 1.0 } else { tp as f64 / (tp + fn_) as f64 };
                fps.push(fp);
                fns.push(fn_);
                precs.push(precision);
                recalls.push(recall);
                admitteds.push(total);
            }

            let mean = |v: &[usize]| v.iter().sum::<usize>() as f64 / v.len() as f64;
            let meanf = |v: &[f64]| v.iter().sum::<f64>() / v.len() as f64;

            let row = vec![
                format!("{:.2}", threshold),
                format!("{:.1}", mean(&fps)),
                format!("{:.1}", mean(&fns)),
                format!("{:.1}%", meanf(&precs) * 100.0),
                format!("{:.1}%", meanf(&recalls) * 100.0),
                format!("{:.1}", mean(&admitteds)),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Show which FPs get caught
    stage("FP Score Distribution (N=100, seed=42)");
    println!("  Showing final_score of each admitted FP contribution:");
    println!();

    for key in &["australia", "tcp", "nutrition"] {
        let topic = topics::get_topic(key).unwrap();
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);
        let result = compiler.compile(&topic, &roster, seed);

        println!("  {}", bold(key));
        let mut fp_scores: Vec<(String, f64, String)> = Vec::new();
        for cs in &result.conflicts {
            if let Some(winner) = cs.winner_idx {
                let c = &result.all_contributions[winner];
                if !c.is_correct {
                    let score = cs.scores.get(&winner).map(|s| s.final_score).unwrap_or(0.0);
                    let triple = c.canonical_form.as_ref()
                        .map(|t| format!("({}, {}, {})", t.subject, t.predicate, t.object))
                        .unwrap_or_default();
                    fp_scores.push((triple, score, cs.typ.to_string()));
                }
            }
        }
        // Also check non-conflict FPs
        let conflicting: HashSet<usize> = result.conflicts.iter()
            .flat_map(|cs| cs.contribution_ids.iter().copied())
            .collect();
        for &idx in &result.admitted {
            if !conflicting.contains(&idx) && !result.all_contributions[idx].is_correct {
                let c = &result.all_contributions[idx];
                let triple = c.canonical_form.as_ref()
                    .map(|t| format!("({}, {}, {})", t.subject, t.predicate, t.object))
                    .unwrap_or_default();
                fp_scores.push((triple, -1.0, "SINGLETON".to_string()));
            }
        }

        if fp_scores.is_empty() {
            println!("    No FPs");
        } else {
            fp_scores.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
            for (triple, score, typ) in &fp_scores {
                let score_str = if *score < 0.0 { "N/A (singleton)".to_string() } else { format!("{:.4}", score) };
                println!("    {} | score={} | {}", typ, score_str, dim(triple));
            }
        }
        println!();
    }
}

// ── Multi-scale baseline comparison ──────────────────────

fn run_baselines_scale(seed: u64, weights: [f64; 5]) {
    header("MULTI-SCALE BASELINE COMPARISON");
    println!();
    println!("  Does overturn's advantage over baselines grow with N?");
    println!("  N ∈ {{100, 1000, 10000}}, 50 seeds × 3 topics × 5 methods");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let scales: Vec<usize> = vec![100, 1_000, 10_000];
    let num_seeds = 50u64;

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["N", "Overturn FP", "MajVote FP", "BestConf FP", "LastWr FP", "Random FP", "Overturn Δ"];
        let widths = vec![7, 13, 11, 12, 10, 10, 12];
        print_table_header(&cols, &widths, "    ");

        for &n in &scales {
            let mut ov_fps = Vec::new();
            let mut mv_fps = Vec::new();
            let mut bc_fps = Vec::new();
            let mut lw_fps = Vec::new();
            let mut rand_fps = Vec::new();

            for s in 0..num_seeds {
                let roster = agents::get_roster(n);
                let compiler = OverturnCompiler::with_weights(weights);

                let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed + s);
                let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);
                let valid = compiler.p3_validate_pub(&contributions);

                // overturn
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
                compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
                let (fp, _, _) = count_fp_from_conflicts(&conflicts, &valid);
                ov_fps.push(fp);

                // Majority vote
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
                majority_vote_select(&mut conflicts, &valid);
                let (fp, _, _) = count_fp_from_conflicts(&conflicts, &valid);
                mv_fps.push(fp);

                // Best confidence
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
                best_confidence_select(&mut conflicts, &valid);
                let (fp, _, _) = count_fp_from_conflicts(&conflicts, &valid);
                bc_fps.push(fp);

                // Last writer
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
                last_writer_wins_select(&mut conflicts, &valid);
                let (fp, _, _) = count_fp_from_conflicts(&conflicts, &valid);
                lw_fps.push(fp);

                // Random
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
                random_select(&mut conflicts, seed + s);
                let (fp, _, _) = count_fp_from_conflicts(&conflicts, &valid);
                rand_fps.push(fp);
            }

            let mean = |v: &[usize]| v.iter().sum::<usize>() as f64 / v.len() as f64;
            let ov_mean = mean(&ov_fps);
            let mv_mean = mean(&mv_fps);
            // Delta = average FP reduction vs best baseline other than overturn
            let best_other = mv_mean.min(mean(&bc_fps)).min(mean(&lw_fps)).min(mean(&rand_fps));
            let delta = best_other - ov_mean;

            let row = vec![
                format_num(n),
                format!("{:.1}", ov_mean),
                format!("{:.1}", mv_mean),
                format!("{:.1}", mean(&bc_fps)),
                format!("{:.1}", mean(&lw_fps)),
                format!("{:.1}", mean(&rand_fps)),
                format!("{:+.1}", delta),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }
}

// ── Topology simulation ──────────────────────────────────

/// Simulate constrained communication topologies by filtering which
/// existing claims each agent can see during P2 lowering.
fn compile_with_topology(
    compiler: &OverturnCompiler,
    topic: &topics::Topic,
    roster: &[agents::AgentPersonality],
    seed: u64,
    topology: &str,
) -> CompilationResult {
    let t0 = std::time::Instant::now();
    let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
    let _intent = (topic.goal, &topic.constraints, &topic.criteria);

    let n = roster.len();
    let mut all_claims: Vec<Contribution> = Vec::new();

    for (i, agent) in roster.iter().enumerate() {
        // Determine which existing claims this agent can see based on topology
        let visible: Vec<Contribution> = match topology {
            "full" => {
                // Fully connected: sees all previous claims
                all_claims.clone()
            }
            "star" => {
                // Star: agent 0 is hub. Others only see hub's claims.
                if i == 0 {
                    all_claims.clone()
                } else {
                    all_claims.iter()
                        .filter(|c| c.agent_id == roster[0].name.to_lowercase().replace(' ', "_"))
                        .cloned()
                        .collect()
                }
            }
            "chain" => {
                // Chain: agent i only sees claims from agent i-1
                if i == 0 {
                    vec![]
                } else {
                    let prev_id = roster[i - 1].name.to_lowercase().replace(' ', "_");
                    all_claims.iter()
                        .filter(|c| c.agent_id == prev_id)
                        .cloned()
                        .collect()
                }
            }
            "tree" => {
                // Binary tree: agent i sees claims from parent = (i-1)/2
                if i == 0 {
                    all_claims.clone()
                } else {
                    let parent_idx = (i - 1) / 2;
                    let parent_id = roster[parent_idx].name.to_lowercase().replace(' ', "_");
                    all_claims.iter()
                        .filter(|c| c.agent_id == parent_id)
                        .cloned()
                        .collect()
                }
            }
            "ring" => {
                // Ring: agent i sees claims from agent (i-1) mod n
                if i == 0 && all_claims.is_empty() {
                    vec![]
                } else {
                    let prev_idx = if i == 0 { n - 1 } else { i - 1 };
                    let prev_id = roster[prev_idx].name.to_lowercase().replace(' ', "_");
                    all_claims.iter()
                        .filter(|c| c.agent_id == prev_id)
                        .cloned()
                        .collect()
                }
            }
            "isolated" => {
                // Fully isolated: no agent sees any other's claims
                vec![]
            }
            _ => all_claims.clone(),
        };

        let claims = agent.generate_claims(topic, &visible, &mut rng);
        all_claims.extend(claims);
    }

    // Ingest (record arrival seq), then standard P3-P6 on the collected claims
    compiler::assign_arrival_seq(&mut all_claims);
    let valid = compiler.p3_validate_pub(&all_claims);
    let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
    compiler.p5_select_pub(&mut conflicts, &valid, roster, topic);

    let time_us = t0.elapsed().as_micros() as u64;
    compiler.p6_commit_pub(valid, conflicts, roster, time_us, topic)
}

fn run_topology(seed: u64, weights: [f64; 5]) {
    header("TOPOLOGY SIMULATION");
    println!();
    println!("  Testing: how does agent communication topology affect compilation quality?");
    println!("  N=100, 50 seeds × 3 topics × 6 topologies");
    println!();
    println!("  Topologies:");
    println!("    full     — all agents see all previous claims (current default)");
    println!("    star     — agent 0 is hub; others only see hub's claims");
    println!("    chain    — agent i only sees agent i-1's claims");
    println!("    tree     — binary tree; agent i sees parent (i-1)/2's claims");
    println!("    ring     — agent i sees agent (i-1 mod N)'s claims");
    println!("    isolated — no agent sees any other's claims (pure parallel)");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let topologies = vec!["full", "star", "chain", "tree", "ring", "isolated"];
    let num_seeds = 50u64;

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();

        let cols = vec!["Topology", "Mean FP", "Min FP", "Max FP", "Mean Prec", "Claims", "Conflicts"];
        let widths = vec![10, 8, 7, 7, 10, 8, 10];
        print_table_header(&cols, &widths, "    ");

        for topo in &topologies {
            let mut fps = Vec::new();
            let mut precs = Vec::new();
            let mut claims_counts = Vec::new();
            let mut conflict_counts = Vec::new();

            for s in 0..num_seeds {
                let roster = agents::get_roster(100);
                let compiler = OverturnCompiler::with_weights(weights);
                let result = compile_with_topology(&compiler, &topic, &roster, seed + s, topo);
                let m = Metrics::from_result(&result);
                fps.push(m.fp);
                precs.push(m.precision());
                claims_counts.push(result.all_contributions.len());
                conflict_counts.push(result.conflicts.len());
            }

            let mean_fp = fps.iter().sum::<usize>() as f64 / num_seeds as f64;
            let min_fp = *fps.iter().min().unwrap();
            let max_fp = *fps.iter().max().unwrap();
            let mean_prec = precs.iter().sum::<f64>() / num_seeds as f64;
            let mean_claims = claims_counts.iter().sum::<usize>() as f64 / num_seeds as f64;
            let mean_conflicts = conflict_counts.iter().sum::<usize>() as f64 / num_seeds as f64;

            let row = vec![
                topo.to_string(),
                format!("{:.1}", mean_fp),
                format!("{}", min_fp),
                format!("{}", max_fp),
                format!("{:.1}%", mean_prec * 100.0),
                format!("{:.0}", mean_claims),
                format!("{:.1}", mean_conflicts),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    // Adversarial topology test: star topology + adversarial hub
    stage("Adversarial Hub: Star Topology with Hallucinator Hub");
    println!("  What if the star hub is a hallucinator?");
    println!();

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();

        // Normal star: expert hub
        let roster_normal = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);
        let result_normal = compile_with_topology(&compiler, &topic, &roster_normal, seed, "star");
        let m_normal = Metrics::from_result(&result_normal);

        // Adversarial star: hallucinator as agent 0
        let mut roster_adv = agents::get_roster(100);
        // Swap agent 0 (Dr. Expert) with a hallucinator
        roster_adv[0] = agents::AgentPersonality::new(
            "Hallucinator Hub", agents::Archetype::Hallucinator,
            "Mistral", 0.30, 0.25, ir::LoweringConfidence::Low,
        );
        let result_adv = compile_with_topology(&compiler, &topic, &roster_adv, seed, "star");
        let m_adv = Metrics::from_result(&result_adv);

        println!("  {}: expert hub FP={}, prec={:.0}% | halluc hub FP={}, prec={:.0}%",
            bold(key), m_normal.fp, m_normal.precision() * 100.0,
            m_adv.fp, m_adv.precision() * 100.0);
    }
    println!();
}

// ── Real lowering benchmark ──────────────────────────────

fn run_real_lowering(seed: u64, weights: [f64; 5]) {
    header("REAL RULE-BASED LOWERING BENCHMARK");
    println!();
    println!("  Testing the 34 extraction rules on topic bank raw texts.");
    println!("  Measures: triple extraction recall, evidence detection, lowering quality, end-to-end timing.");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];

    // Part 1: Per-claim lowering analysis
    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        stage(&format!("Topic: {} — {}", key, topic.query));
        println!();

        let all_entries: Vec<(&str, &topics::FactEntry, bool)> = topic.facts.iter().map(|f| ("fact", f, true))
            .chain(topic.misconceptions.iter().map(|f| ("miscon", f, false)))
            .chain(topic.nuances.iter().map(|f| ("nuance", f, true)))
            .collect();

        let cols = vec!["Type", "Text (trunc)", "Triples", "Rules", "Evidence", "Hedges", "Jaccard", "LowConf"];
        let widths = vec![6, 35, 8, 12, 8, 7, 8, 8];
        print_table_header(&cols, &widths, "    ");

        let mut total_entries = 0usize;
        let mut extracted_at_least_one = 0usize;
        let mut total_triples = 0usize;
        let mut total_evidence = 0usize;
        let mut total_high = 0usize;
        let mut total_medium = 0usize;
        let mut total_low = 0usize;
        let mut jaccards = Vec::new();

        for (typ, entry, _correct) in &all_entries {
            total_entries += 1;
            let result = lowering::lower(entry.text);

            if !result.triples.is_empty() {
                extracted_at_least_one += 1;
            }
            total_triples += result.triples.len();
            total_evidence += result.evidence.len();

            let rule_names: Vec<String> = result.rule_stats.iter()
                .map(|(id, name)| format!("R{}:{}", id, name.split('_').last().unwrap_or(name)))
                .collect();

            let best_jaccard = result.triples.iter()
                .map(|(_, _, j)| *j)
                .fold(0.0_f64, f64::max);
            jaccards.push(best_jaccard);

            let best_conf = result.triples.iter()
                .map(|(_, c, _)| *c)
                .next()
                .unwrap_or(LoweringConfidence::Low);
            match best_conf {
                LoweringConfidence::High => total_high += 1,
                LoweringConfidence::Medium => total_medium += 1,
                LoweringConfidence::Low => total_low += 1,
            }

            let text_trunc: String = entry.text.chars().take(33).collect::<String>() +
                if entry.text.len() > 33 { ".." } else { "" };

            let row = vec![
                typ.to_string(),
                text_trunc,
                format!("{}", result.triples.len()),
                if rule_names.is_empty() { "—".to_string() } else {
                    rule_names.iter().take(2).cloned().collect::<Vec<_>>().join(",")
                },
                format!("{}", result.evidence.len()),
                format!("{:.2}", result.hedge_confidence),
                format!("{:.2}", best_jaccard),
                format!("{}", best_conf),
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");

        let mean_jaccard = if jaccards.is_empty() { 0.0 } else {
            jaccards.iter().sum::<f64>() / jaccards.len() as f64
        };
        let recall = extracted_at_least_one as f64 / total_entries as f64;

        println!();
        println!("    Extraction recall:   {}/{} entries ({:.0}%)", extracted_at_least_one, total_entries, recall * 100.0);
        println!("    Total triples:       {} ({:.1} per entry)", total_triples, total_triples as f64 / total_entries as f64);
        println!("    Total evidence:      {} ({:.1} per entry)", total_evidence, total_evidence as f64 / total_entries as f64);
        println!("    Mean best Jaccard:   {:.3}", mean_jaccard);
        println!("    Lowering conf:       HIGH={}, MEDIUM={}, LOW={}", total_high, total_medium, total_low);
        println!();
    }

    // Part 2: End-to-end compilation with real lowering vs simulated
    stage("End-to-End Comparison: Real Lowering vs Simulated");
    println!("  Compiling with rule-based lowered contributions vs archetype-assigned.");
    println!();

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);

        // Simulated lowering (current approach)
        let t0 = std::time::Instant::now();
        let result_sim = compiler.compile(&topic, &roster, seed);
        let time_sim = t0.elapsed();
        let m_sim = Metrics::from_result(&result_sim);

        // Real lowering: re-lower each contribution's raw_text
        let t0 = std::time::Instant::now();
        let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
        let contributions_raw = compiler.p2_lower_pub(&roster, &topic, &mut rng);

        // Apply real lowering to each contribution
        let mut contributions_lowered: Vec<Contribution> = Vec::new();
        for mut c in contributions_raw {
            if c.kind == ContributionKind::Critique {
                contributions_lowered.push(c);
                continue;
            }

            let lr = lowering::lower(&c.raw_text);

            // Replace canonical_form with extracted triple (best Jaccard)
            if let Some((best_triple, best_conf, _jaccard)) = lr.triples.first() {
                c.canonical_form = Some(best_triple.clone());
                c.lowering_confidence = *best_conf;
            } else {
                // No triple extracted — opaque bucket
                c.lowering_confidence = LoweringConfidence::Low;
            }

            // Replace evidence with extracted evidence (merge with existing)
            if !lr.evidence.is_empty() {
                // Keep existing evidence, add extracted
                c.evidence.extend(lr.evidence.clone());
            }

            // Adjust confidence from hedge analysis
            c.confidence = c.confidence.min(lr.hedge_confidence + 0.1).max(0.1);

            contributions_lowered.push(c);
        }

        let valid = compiler.p3_validate_pub(&contributions_lowered);
        let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
        compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
        let time_us = t0.elapsed().as_micros() as u64;
        let result_real = compiler.p6_commit_pub(valid, conflicts, &roster, time_us, &topic);
        let time_real = t0.elapsed();
        let m_real = Metrics::from_result(&result_real);

        let fmt_dur = |d: std::time::Duration| -> String {
            let us = d.as_micros();
            if us < 1000 { format!("{}μs", us) }
            else if us < 1_000_000 { format!("{:.1}ms", us as f64 / 1000.0) }
            else { format!("{:.2}s", us as f64 / 1_000_000.0) }
        };

        println!("  {}", bold(key));
        println!("    {:24} {:>12} {:>12}", "", "Simulated", "Real Lowered");
        println!("    {:24} {:>12} {:>12}", "Precision:", format!("{:.0}%", m_sim.precision() * 100.0), format!("{:.0}%", m_real.precision() * 100.0));
        println!("    {:24} {:>12} {:>12}", "False positives:", m_sim.fp, m_real.fp);
        println!("    {:24} {:>12} {:>12}", "True positives:", m_sim.tp, m_real.tp);
        println!("    {:24} {:>12} {:>12}", "Admitted:", result_sim.admitted.len(), result_real.admitted.len());
        println!("    {:24} {:>12} {:>12}", "Conflicts:", result_sim.conflicts.len(), result_real.conflicts.len());
        println!("    {:24} {:>12} {:>12}", "Time:", fmt_dur(time_sim), fmt_dur(time_real));
        println!();
    }

    // Part 3: Lowering timing at scale
    stage("Lowering Latency at Scale");
    println!("  Time for rule-based lowering per contribution (batch of 1000 texts).");
    println!();

    let mut all_texts: Vec<String> = Vec::new();
    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        for entry in topic.facts.iter().chain(topic.misconceptions.iter()).chain(topic.nuances.iter()) {
            all_texts.push(entry.text.to_string());
        }
    }

    // Run lowering on 1000 texts (cycling through topic bank)
    let n_bench = 1000;
    let t0 = std::time::Instant::now();
    for i in 0..n_bench {
        let text = &all_texts[i % all_texts.len()];
        let _result = lowering::lower(text);
    }
    let elapsed = t0.elapsed();
    let per_text_us = elapsed.as_micros() as f64 / n_bench as f64;

    println!("    {} texts lowered in {:.1}ms ({:.1}μs/text, {:.0} texts/sec)",
        n_bench,
        elapsed.as_micros() as f64 / 1000.0,
        per_text_us,
        1_000_000.0 / per_text_us);
    println!();

    // Run at N=10000 agents to measure end-to-end with lowering
    stage("End-to-End Timing with Real Lowering (N=10,000)");

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        let roster = agents::get_roster(10_000);
        let compiler = OverturnCompiler::with_weights(weights);

        let t0 = std::time::Instant::now();
        let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
        let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);

        let t_p2 = t0.elapsed();

        // Real lowering pass
        let t_lower_start = std::time::Instant::now();
        let mut lowered: Vec<Contribution> = Vec::new();
        for mut c in contributions {
            if c.kind != ContributionKind::Critique {
                let lr = lowering::lower(&c.raw_text);
                if let Some((best_triple, best_conf, _)) = lr.triples.first() {
                    c.canonical_form = Some(best_triple.clone());
                    c.lowering_confidence = *best_conf;
                } else {
                    c.lowering_confidence = LoweringConfidence::Low;
                }
            }
            lowered.push(c);
        }
        let t_lower = t_lower_start.elapsed();

        let valid = compiler.p3_validate_pub(&lowered);
        let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);
        compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
        let _result = compiler.p6_commit_pub(valid, conflicts, &roster, 0, &topic);

        let total = t0.elapsed();

        let fmt = |d: std::time::Duration| -> String {
            let ms = d.as_micros() as f64 / 1000.0;
            if ms < 1000.0 { format!("{:.1}ms", ms) } else { format!("{:.2}s", ms / 1000.0) }
        };

        println!("    {}: P2={}, Lowering={} ({:.0}% of total), Total={}",
            bold(key), fmt(t_p2), fmt(t_lower),
            t_lower.as_nanos() as f64 / total.as_nanos() as f64 * 100.0,
            fmt(total));
    }
    println!();
}

fn run_properties(seed: u64, weights: [f64; 5]) {
    header("FORMAL PROPERTY CHECKS");
    println!();
    println!("  Checking 14 invariants across all topics × 10 seeds...");
    println!();

    let all_topics = topics::all_topic_keys();
    let seeds: Vec<u64> = (0..10).map(|i| seed + i).collect();
    let mut total_pass = 0usize;
    let mut total_fail = 0usize;

    for topic_key in &all_topics {
        let topic = topics::get_topic(topic_key).unwrap();
        let roster = agents::get_roster(20);

        for &s in &seeds {
            let report = properties::check_all(&topic, &roster, s, weights);
            total_pass += report.passed();
            total_fail += report.failed();

            for (name, result) in &report.results {
                if let Err(msg) = result {
                    println!("    {} topic={} seed={}: {}",
                        red("FAIL"), topic_key, s, name);
                    println!("      {}", dim(msg));
                }
            }
        }
    }

    let total = total_pass + total_fail;
    println!();
    if total_fail == 0 {
        println!("  {} {}/{} property checks passed across {} topics × {} seeds",
            green("✓"), total, total, all_topics.len(), seeds.len());
    } else {
        println!("  {} {}/{} passed, {} failed",
            red("✗"), total_pass, total, total_fail);
    }
    println!();
}

// ── Replay variance comparison ──────────────────────────

fn run_replay_variance(seed: u64, weights: [f64; 5]) {
    header("REPLAY VARIANCE: OVERTURN vs BASELINES");
    println!();
    println!("  Running each method 100 times on identical inputs, measuring output hash variance.");
    println!("  Overturn should have 0 variance (deterministic). Baselines with randomness: nonzero.");
    println!();

    let topic_keys = vec!["australia", "tcp", "nutrition"];
    let k = 100usize;

    let cols = vec!["Topic", "Method", "Unique Hashes", "Unique Certs", "Variance"];
    let widths = vec![12, 19, 14, 13, 10];

    for key in &topic_keys {
        let topic = topics::get_topic(key).unwrap();
        println!("  {} — {}", bold(key), topic.query);
        println!();
        print_table_header(&cols, &widths, "    ");

        let roster = agents::get_roster(100);
        let compiler = OverturnCompiler::with_weights(weights);

        // Methods to test
        let methods = vec!["Overturn (scored)", "Majority vote", "Best confidence", "Last writer", "Random"];

        for method in &methods {
            let mut certs = std::collections::HashSet::new();
            let mut admitted_hashes = std::collections::HashSet::new();

            for run in 0..k {
                let run_seed = seed + run as u64;
                let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
                let contributions = compiler.p2_lower_pub(&roster, &topic, &mut rng);
                let valid = compiler.p3_validate_pub(&contributions);
                let mut conflicts = compiler.p4_detect_pub(&valid, topic.goal);

                match *method {
                    "Overturn (scored)" => {
                        compiler.p5_select_pub(&mut conflicts, &valid, &roster, &topic);
                    }
                    "Majority vote" => {
                        majority_vote_select(&mut conflicts, &valid);
                    }
                    "Best confidence" => {
                        best_confidence_select(&mut conflicts, &valid);
                    }
                    "Last writer" => {
                        last_writer_wins_select(&mut conflicts, &valid);
                    }
                    "Random" => {
                        random_select(&mut conflicts, run_seed);
                    }
                    _ => unreachable!(),
                }

                let result = compiler.p6_commit_pub(valid, conflicts, &roster, 0, &topic);
                certs.insert(result.certificate.clone());

                // Hash the admitted set for comparison
                let mut hasher = sha2::Sha256::new();
                use sha2::Digest;
                for &idx in &result.admitted {
                    hasher.update(result.all_contributions[idx].id.as_bytes());
                }
                let hash = hasher.finalize();
                admitted_hashes.insert(format!("{:x}", hash));
            }

            let variance_str = if certs.len() == 1 {
                green("0 (deterministic)")
            } else {
                red(&format!("{} unique", certs.len()))
            };

            let row = vec![
                if *method == "Overturn (scored)" { key.to_string() } else { "".to_string() },
                method.to_string(),
                format!("{}/{}", admitted_hashes.len(), k),
                format!("{}/{}", certs.len(), k),
                if certs.len() == 1 { "0".to_string() } else { format!("{}", certs.len()) },
            ];
            print_table_row(&row, &widths, "    ");
        }
        print_table_bottom(&widths, "    ");
        println!();
    }

    println!("  {}", bold("Key insight: overturn produces identical output across all runs (deterministic)."));
    println!("  Random baseline produces different outputs per seed (non-deterministic).");
    println!("  Other baselines are deterministic when given identical inputs.");
    println!();
}

// ── Replay determinism test ─────────────────────────────

fn run_replay(seed: u64, weights: [f64; 5], count: usize) {
    header("REPLAY DETERMINISM TEST");
    println!();
    println!("  Compiling {} times with seed={}, asserting identical output each time.", count, seed);
    println!();

    let all_topics = topics::all_topic_keys();
    let compiler = OverturnCompiler::with_weights(weights);
    let mut total_ok = 0usize;
    let mut total_fail = 0usize;

    for topic_key in &all_topics {
        let topic = topics::get_topic(topic_key).unwrap();
        let roster = agents::get_roster(20);

        // Reference run
        let ref_result = compiler.compile(&topic, &roster, seed);
        let ref_cert = ref_result.certificate.clone();
        let ref_admitted: Vec<usize> = ref_result.admitted.clone();
        let ref_rejected: Vec<usize> = ref_result.rejected.clone();

        let mut pass = 0usize;
        let mut fail = 0usize;

        for _ in 1..count {
            let result = compiler.compile(&topic, &roster, seed);
            if result.certificate != ref_cert
                || result.admitted != ref_admitted
                || result.rejected != ref_rejected
            {
                fail += 1;
                eprintln!("    {} DIVERGENCE on topic={} at iteration {}",
                    red("FAIL"), topic_key, pass + fail + 1);
                eprintln!("      Expected cert: {}", ref_cert);
                eprintln!("      Got cert:      {}", result.certificate);
                break;
            }
            pass += 1;
        }

        if fail == 0 {
            println!("    {} {}: {}/{} replays identical  cert={}",
                green("PASS"), bold(topic_key), count, count, dim(&ref_cert));
            total_ok += 1;
        } else {
            total_fail += 1;
        }
    }

    println!();
    if total_fail == 0 {
        println!("  {} All {} topics × {} replays = {} total compilations identical.",
            green("OK"), all_topics.len(), count, all_topics.len() * count);
    } else {
        eprintln!("  {} {}/{} topics had replay divergence!",
            red("FAIL"), total_fail, all_topics.len());
        std::process::exit(1);
    }
    println!();
}

// ── Artifact dump / file replay / external reduce ──────

/// On-disk artifact: the sealed set (hashed), the policy it was reduced
/// under and that policy's hash, eval-only labels (not hashed), and the
/// expected output tuples.
///
/// `topic`, `agents`, `seed`, `labels` and the unsealed display fields of
/// each contribution (`agent_name`, `timestamp`, `is_correct`) are not
/// covered by the root hash, the policy hash or the certificate. The
/// optional `envelope_hash` (`bran-envelope/1`, see
/// `ArtifactFile::envelope_json`) covers them; it is verified by
/// `--replay-from` when present and emitted for every new non-legacy file.
///
/// What `--replay-from` checks, field by field:
///   * `artifact` (sealed set): root hash; for `/4` every id is its
///     content id; evidence records are id-hashed and consistent.
///   * `policy`, `policy_hash`, `outputs.policy_hash`: policy hash.
///   * `outputs`: re-reduced and compared for equality (the certificate
///     inside binds root hash, policy hash and admitted ids).
///   * `format`: must equal the tag the content requires.
///   * `envelope_hash`, when present: `format`, `topic`, `agents`, `seed`,
///     the whole `labels` map, each contribution's `agent_name`,
///     `timestamp`, `is_correct`, bound to the stored root hash, policy
///     hash and certificate (so an envelope cannot be moved to another
///     artifact).
/// Not covered: (1) the presence of `envelope_hash` itself — deleting it
/// gives a file that verifies as a pre-envelope one (use
/// `--require-envelope`, or check `"envelope": "verified"` in `--json`);
/// (2) unknown extra keys anywhere (ignored by the parser); (3) JSON
/// formatting (whitespace, key order, number spelling of the same
/// value). Like the root hash, the envelope hash is an unkeyed digest,
/// not a signature: it detects edits, not a forger who recomputes it.
/// Existing `/2`, `/3`, `/4` root hashes, policy hashes and certificates
/// are unchanged (the envelope is outside all of them).
#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct ArtifactFile {
    format: String,
    topic: String,
    agents: usize,
    seed: u64,
    policy: OverturnCompiler,
    /// `OverturnCompiler::policy_hash()` of `policy` under the dumping binary.
    policy_hash: String,
    artifact: SealedArtifactSet,
    /// contribution id → ground-truth correctness (evaluation only).
    labels: std::collections::BTreeMap<String, bool>,
    outputs: compiler::ReductionOutput,
    /// `bran-envelope/1` hash of the unhashed metadata, bound to the root
    /// hash, policy hash and certificate. Absent in legacy files (and in
    /// `--legacy-ids` dumps, which must reproduce the committed `/2`
    /// files byte for byte); not part of any root hash or certificate.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    envelope_hash: Option<String>,
}

/// v2: adds `policy_hash` (top level and in `outputs`); the certificate
/// covers it. v1 files (no policy hash) are rejected.
const ARTIFACT_FORMAT: &str = "bran-artifact/2";
/// v3 = v2 + `artifact.evidence_store` and/or `policy.evidence` (spec
/// §3.5). Used only when evidence records or an evidence policy are
/// present; everything else stays v2, byte for byte.
const ARTIFACT_FORMAT_V3: &str = "bran-artifact/3";
/// v4 = content-addressed contribution ids (`artifact.id_scheme` =
/// `bran-contribution-id/1`): every id must equal the hash of its
/// contribution's canonical payload (`ir::content_id`) and no SYNTHESIS
/// may be sealed. May also carry evidence records / an evidence policy.
/// v2 and v3 files carry no `id_scheme` and verify exactly as before.
const ARTIFACT_FORMAT_V4: &str = "bran-artifact/4";
/// Every format tag `--replay-from` reads.
const ARTIFACT_FORMATS: &[&str] = &[ARTIFACT_FORMAT, ARTIFACT_FORMAT_V3, ARTIFACT_FORMAT_V4];
/// Format tag of the envelope serialization (hashed).
const ENVELOPE_FORMAT: &str = "bran-envelope/1";

/// Exit codes shared by `--replay-from` (and, for 2, every mode).
const EXIT_CODES: &[(i32, &str)] = &[
    (0, "ok"),
    (1, "output mismatch: hashes verify but re-reduction differs from the stored outputs"),
    (2, "usage, unreadable or unparsable input, or input rejected by --reduce"),
    (3, "sealed-set mismatch: root hash, evidence record hash, or contribution content id"),
    (4, "policy mismatch: stored policy does not hash to the stored policy hash under this binary"),
    (5, "format tag unknown, or does not match the file's content"),
    (6, "envelope mismatch: envelope_hash does not cover the stored metadata (or is missing under --require-envelope)"),
];

/// The format tag a file with this sealed set and policy must carry.
fn artifact_format(artifact: &SealedArtifactSet, policy: &OverturnCompiler) -> &'static str {
    if artifact.id_scheme.is_some() { ARTIFACT_FORMAT_V4 }
    else if artifact.evidence_store.is_some() || policy.evidence.is_some() { ARTIFACT_FORMAT_V3 }
    else { ARTIFACT_FORMAT }
}

/// Serialize with sorted keys: round-trip through `serde_json::Value`,
/// whose maps are BTreeMaps.
fn to_canonical_json<T: serde::Serialize>(v: &T) -> String {
    let value = serde_json::to_value(v).expect("serialize");
    serde_json::to_string_pretty(&value).expect("serialize")
}

fn hash128(bytes: &[u8]) -> String {
    use sha2::{Digest, Sha256};
    Sha256::digest(bytes).iter().take(16).map(|b| format!("{b:02x}")).collect()
}

impl ArtifactFile {
    /// Canonical `bran-envelope/1` serialization (compact, sorted keys):
    /// `format`, `topic`, `agents`, `seed`, `labels`, the stored
    /// `artifact.root_hash`, `policy_hash` and `outputs.certificate`
    /// (binding the envelope to this sealed set, policy and decision),
    /// and per contribution (canonical order) the fields the root hash
    /// excludes: `id`, `agent_name`, `timestamp`, `is_correct`.
    fn envelope_json(&self) -> String {
        let unsealed: Vec<serde_json::Value> = self.artifact.contributions.iter().map(|c| serde_json::json!({
            "id": c.id, "agent_name": c.agent_name, "timestamp": c.timestamp, "is_correct": c.is_correct,
        })).collect();
        serde_json::to_string(&serde_json::json!({
            "envelope_format": ENVELOPE_FORMAT,
            "format": self.format,
            "topic": self.topic,
            "agents": self.agents,
            "seed": self.seed,
            "labels": self.labels,
            "root_hash": self.artifact.root_hash,
            "policy_hash": self.policy_hash,
            "certificate": self.outputs.certificate,
            "unsealed_contribution_fields": unsealed,
        })).expect("envelope serialization")
    }

    /// SHA-256 of `envelope_json()`, truncated to 128 bits (hex).
    fn compute_envelope_hash(&self) -> String {
        hash128(self.envelope_json().as_bytes())
    }

    fn with_envelope(mut self) -> Self {
        self.envelope_hash = Some(self.compute_envelope_hash());
        self
    }
}

#[cfg(test)]
fn build_artifact(topic_key: &str, n: usize, seed: u64, weights: [f64; 5]) -> ArtifactFile {
    build_artifact_ids(topic_key, n, seed, weights, false)
}

fn build_artifact_ids(topic_key: &str, n: usize, seed: u64, weights: [f64; 5], legacy_ids: bool) -> ArtifactFile {
    let topic = topics::get_topic(topic_key).unwrap_or_else(|| {
        eprintln!("Unknown topic: {}. Available: {:?}", topic_key, topics::all_topic_keys());
        std::process::exit(2);
    });
    let roster = agents::get_roster(n);
    let compiler = OverturnCompiler::with_weights(weights);

    // Same pipeline as compile(): ingest → seal → reduce.
    let mut rng = rand_chacha::ChaCha8Rng::seed_from_u64(seed);
    let (sealed, result) = if legacy_ids {
        let raw = compiler.p2_lower_legacy_ids_pub(&roster, &topic, &mut rng);
        let sealed = compiler.seal_legacy(topic.goal, &topic.criteria, &roster, &raw);
        let result = compiler.reduce(&sealed);
        (sealed, result)
    } else {
        let raw = compiler.p2_lower_pub(&roster, &topic, &mut rng);
        let sealed = compiler.seal(topic.goal, &topic.criteria, &roster, &raw);
        let result = compiler.reduce(&sealed);
        let check = compiler.compile(&topic, &roster, seed);
        assert_eq!(check.certificate, result.certificate, "dump pipeline diverged from compile()");
        (sealed, result)
    };

    let labels = sealed.contributions.iter().map(|c| (c.id.clone(), c.is_correct)).collect();
    let file = ArtifactFile {
        format: artifact_format(&sealed, &compiler).to_string(),
        topic: topic_key.to_string(),
        agents: n,
        seed,
        policy_hash: compiler.policy_hash(),
        policy: compiler,
        outputs: compiler::ReductionOutput::from_result(&result),
        artifact: sealed,
        labels,
        envelope_hash: None,
    };
    // Legacy dumps stay byte-identical to the committed `/2` files.
    if legacy_ids { file } else { file.with_envelope() }
}

fn run_dump_artifact(path: &str, topic_key: &str, n: usize, seed: u64, weights: [f64; 5], legacy_ids: bool) {
    let file = build_artifact_ids(topic_key, n, seed, weights, legacy_ids);
    std::fs::write(path, to_canonical_json(&file)).unwrap_or_else(|e| {
        eprintln!("Cannot write {path}: {e}");
        std::process::exit(2);
    });
    println!("  dumped {} N={} seed={}: {} contributions, {} slots resolved, root={} policy={} cert={} -> {}",
        topic_key, n, seed, file.artifact.contributions.len(), file.outputs.selections.len(),
        file.artifact.root_hash, file.policy_hash, file.outputs.certificate, path);
}

/// Read a file, or stdin for `-`.
fn read_input(path: &str) -> Result<String, String> {
    if path == "-" {
        let mut s = String::new();
        std::io::Read::read_to_string(&mut std::io::stdin(), &mut s).map_err(|e| format!("Cannot read stdin: {e}"))?;
        Ok(s)
    } else {
        std::fs::read_to_string(path).map_err(|e| format!("Cannot read {path}: {e}"))
    }
}

fn read_or_exit(path: &str) -> String {
    read_input(path).unwrap_or_else(|e| {
        eprintln!("{e}");
        std::process::exit(2);
    })
}

/// Why a replay was rejected. Each class has its own exit code so a
/// policy change is distinguishable from an input or output change.
#[derive(Debug, PartialEq)]
enum ReplayError {
    /// exit 5: `found` is not a supported format tag, or is one but does
    /// not match the content, which requires `expected`.
    Format { found: String, expected: &'static str },
    /// exit 3: sealed set content does not match its stored root hash.
    ArtifactHash { stored: String, recomputed: String },
    /// exit 3 (`bran-artifact/3`): an evidence record id is not the hash
    /// of its record, or the store is inconsistent with its items.
    RecordHash(String),
    /// exit 3 (`bran-artifact/4`): a contribution id is not its content id
    /// (claim edited, id kept), or a SYNTHESIS is sealed.
    ContributionId(String),
    /// exit 4: the stored policy does not hash to the stored policy hash
    /// under this binary (policy fields edited, or the binary's reducer
    /// constants differ from the dumping binary's).
    PolicyHash { stored: String, recomputed: String },
    /// exit 1: hashes verify but re-reduction produced different outputs.
    Output { replayed: Box<compiler::ReductionOutput> },
    /// exit 6: everything else verifies, but `envelope_hash` does not
    /// match the metadata (`stored` = None: missing under
    /// `--require-envelope`).
    Envelope { stored: Option<String>, recomputed: String },
}

impl ReplayError {
    fn exit_code(&self) -> i32 {
        match self {
            ReplayError::Output { .. } => 1,
            ReplayError::ArtifactHash { .. } | ReplayError::RecordHash(_) | ReplayError::ContributionId(_) => 3,
            ReplayError::PolicyHash { .. } => 4,
            ReplayError::Format { .. } => 5,
            ReplayError::Envelope { .. } => 6,
        }
    }

    /// Machine-readable class (`--replay-from --json` `reason`).
    fn kind(&self) -> &'static str {
        match self {
            ReplayError::Format { .. } => "format",
            ReplayError::ArtifactHash { .. } => "artifact_hash",
            ReplayError::RecordHash(_) => "record_hash",
            ReplayError::ContributionId(_) => "contribution_id",
            ReplayError::PolicyHash { .. } => "policy_hash",
            ReplayError::Output { .. } => "output",
            ReplayError::Envelope { .. } => "envelope",
        }
    }

    fn message(&self, file: &ArtifactFile) -> String {
        match self {
            ReplayError::Format { found, expected } if ARTIFACT_FORMATS.contains(&found.as_str()) =>
                format!("format tag {found} does not match content (expected {expected})"),
            ReplayError::Format { found, .. } =>
                format!("unsupported format {found} (supported: {})", ARTIFACT_FORMATS.join(", ")),
            ReplayError::ContributionId(msg) => format!("contribution id mismatch: {msg}"),
            ReplayError::RecordHash(msg) => format!("evidence record mismatch: {msg}"),
            ReplayError::ArtifactHash { stored, recomputed } =>
                format!("artifact hash mismatch (stored {stored}, recomputed {recomputed})"),
            ReplayError::PolicyHash { stored, recomputed } =>
                format!("POLICY MISMATCH: policy hash stored {stored}, recomputed {recomputed}; \
                    the policy was modified or this binary's reducer constants differ (not reduced)"),
            ReplayError::Output { replayed } => {
                let n_sel_diff = replayed.selections.iter().zip(file.outputs.selections.iter())
                    .filter(|(a, b)| a != b).count();
                format!("output tuples differ (cert {} vs stored {}; admitted {} vs {}; {} selections differ; {} vs {} selections)",
                    replayed.certificate, file.outputs.certificate,
                    replayed.admitted.len(), file.outputs.admitted.len(), n_sel_diff,
                    replayed.selections.len(), file.outputs.selections.len())
            }
            ReplayError::Envelope { stored: Some(stored), recomputed } =>
                format!("envelope mismatch: envelope_hash stored {stored}, recomputed {recomputed}; \
                    format, topic, agents, seed, labels or a contribution's agent_name/timestamp/is_correct was edited"),
            ReplayError::Envelope { stored: None, recomputed } =>
                format!("envelope missing: no envelope_hash (--require-envelope; would be {recomputed})"),
        }
    }
}

/// Verify a loaded artifact: format, root hash, policy hash (checked
/// before reducing, against both the top-level and the `outputs` copy),
/// then re-reduce and compare output tuples byte-for-byte, then the
/// envelope hash when present.
fn verify_artifact(file: &ArtifactFile) -> Result<compiler::ReductionOutput, ReplayError> {
    verify_artifact_opts(file, false)
}

fn verify_artifact_opts(file: &ArtifactFile, require_envelope: bool) -> Result<compiler::ReductionOutput, ReplayError> {
    // A v2 file carrying a store or an evidence policy is rejected (and a
    // v3 tag on a legacy file), so the format tag names the semantics.
    let expected = artifact_format(&file.artifact, &file.policy);
    if file.format != expected {
        return Err(ReplayError::Format { found: file.format.clone(), expected });
    }
    let recomputed = file.artifact.compute_root_hash();
    if recomputed != file.artifact.root_hash {
        return Err(ReplayError::ArtifactHash { stored: file.artifact.root_hash.clone(), recomputed });
    }
    // v4: ids must be content ids. Checked after the root hash, so an
    // edited claim with a recomputed root hash but a kept id fails here.
    if let Some(v) = file.artifact.content_id_violations().into_iter().next() {
        return Err(ReplayError::ContributionId(v));
    }
    if let Some(store) = &file.artifact.evidence_store {
        evidence::validate_store(&file.artifact.contributions, store)
            .map_err(|e| ReplayError::RecordHash(e.to_string()))?;
    }
    let policy_hash = file.policy.policy_hash();
    for stored in [&file.policy_hash, &file.outputs.policy_hash] {
        if &policy_hash != stored {
            return Err(ReplayError::PolicyHash { stored: stored.clone(), recomputed: policy_hash });
        }
    }
    let replayed = compiler::ReductionOutput::from_result(&file.policy.reduce(&file.artifact));
    if replayed != file.outputs {
        return Err(ReplayError::Output { replayed: Box::new(replayed) });
    }
    // Last: the envelope covers only unhashed metadata, so any sealed-set,
    // policy or output problem is reported under its own code first.
    match &file.envelope_hash {
        Some(stored) => {
            let recomputed = file.compute_envelope_hash();
            if &recomputed != stored {
                return Err(ReplayError::Envelope { stored: Some(stored.clone()), recomputed });
            }
        }
        None if require_envelope =>
            return Err(ReplayError::Envelope { stored: None, recomputed: file.compute_envelope_hash() }),
        None => {}
    }
    Ok(replayed)
}

/// `--replay-from PATH [--json] [--require-envelope]`.
///
/// `--json` prints one object on stdout (also on failure; exit codes as
/// without it):
/// ```text
/// { "ok": bool, "exit_code": int,
///   "reason": null | "io" | "parse" | "format" | "artifact_hash" | "record_hash"
///           | "contribution_id" | "policy_hash" | "output" | "envelope",
///   "message": string,
///   // present once the file parsed:
///   "format", "topic", "agents", "seed",
///   "root_hash", "policy_hash", "certificate",   // stored values
///   "selections": int, "admitted": int,          // stored counts
///   "envelope": "verified" | "absent" | "mismatch" | "missing" | "unchecked" }
/// ```
/// `envelope` is `absent` when the file has no `envelope_hash` (accepted
/// unless `--require-envelope`, then `missing`, exit 6) and `unchecked`
/// when an earlier check failed.
fn run_replay_from(path: &str, json: bool, require_envelope: bool) {
    fn fail_early(json: bool, reason: &str, msg: String) -> ! {
        if json {
            println!("{}", to_canonical_json(&serde_json::json!({
                "ok": false, "exit_code": 2, "reason": reason, "message": msg,
            })));
        } else {
            eprintln!("{msg}");
        }
        std::process::exit(2);
    }
    let text = read_input(path).unwrap_or_else(|e| fail_early(json, "io", e));
    let file: ArtifactFile = serde_json::from_str(&text)
        .unwrap_or_else(|e| fail_early(json, "parse", format!("Cannot parse {path}: {e}")));
    let res = verify_artifact_opts(&file, require_envelope);
    if json {
        let (ok, code, reason, message, envelope) = match &res {
            Ok(_) => (true, 0, None, "replay verified".to_string(),
                if file.envelope_hash.is_some() { "verified" } else { "absent" }),
            Err(e) => (false, e.exit_code(), Some(e.kind()), e.message(&file), match e {
                ReplayError::Envelope { stored: Some(_), .. } => "mismatch",
                ReplayError::Envelope { stored: None, .. } => "missing",
                _ => "unchecked",
            }),
        };
        println!("{}", to_canonical_json(&serde_json::json!({
            "ok": ok, "exit_code": code, "reason": reason, "message": message,
            "format": file.format, "topic": file.topic, "agents": file.agents, "seed": file.seed,
            "root_hash": file.artifact.root_hash, "policy_hash": file.policy_hash,
            "certificate": file.outputs.certificate,
            "selections": file.outputs.selections.len(), "admitted": file.outputs.admitted.len(),
            "envelope": envelope,
        })));
        if code != 0 { std::process::exit(code); }
        return;
    }
    match res {
        Ok(replayed) => println!(
            "  {} {} N={} seed={}: hash verified ({}), policy verified ({}), {} selections + {} admitted identical, cert={}{}",
            green("PASS"), file.topic, file.agents, file.seed, replayed.root_hash, replayed.policy_hash,
            replayed.selections.len(), replayed.admitted.len(), replayed.certificate,
            if file.envelope_hash.is_some() { ", envelope verified" } else { "" }),
        Err(err) => {
            eprintln!("  {} {path}: {}", red("FAIL"), err.message(&file));
            std::process::exit(err.exit_code());
        }
    }
}

/// A parsed `--reduce` input (see `run_reduce` for the schema).
struct ReduceInput {
    intent: String,
    criteria: Vec<String>,
    calibration: std::collections::BTreeMap<String, f64>,
    policy: Option<serde_json::Value>,
    evidence_store: Option<evidence::EvidenceStore>,
    id_scheme: Option<String>,
    /// `--emit-artifact` only: the artifact's `topic` (default `external`).
    topic: Option<String>,
    contributions: Vec<Contribution>,
    /// id → `is_correct`, for items that state it explicitly
    /// (`--emit-artifact` labels).
    labels: std::collections::BTreeMap<String, bool>,
}

/// Parse a `--reduce` input. Errors name the field or the contribution
/// index (`contributions[3]: missing field `kind``) instead of serde's
/// untagged-enum summary. With `"id_scheme": "bran-contribution-id/1"`, a
/// contribution without `id` (or with `"id": null`) gets its content id;
/// a supplied id is kept (and checked at seal time).
fn parse_reduce_input(text: &str) -> Result<ReduceInput, String> {
    fn field<T: serde::de::DeserializeOwned + Default>(obj: &mut serde_json::Map<String, serde_json::Value>, k: &str) -> Result<T, String> {
        match obj.remove(k) {
            None | Some(serde_json::Value::Null) => Ok(T::default()),
            Some(v) => serde_json::from_value(v).map_err(|e| format!("field `{k}`: {e}")),
        }
    }
    let v: serde_json::Value = serde_json::from_str(text).map_err(|e| e.to_string())?;
    let mut input = ReduceInput {
        intent: String::new(), criteria: Vec::new(), calibration: Default::default(), policy: None,
        evidence_store: None, id_scheme: None, topic: None, contributions: Vec::new(), labels: Default::default(),
    };
    let items = match v {
        serde_json::Value::Array(items) => items,
        serde_json::Value::Object(mut obj) => {
            input.intent = field(&mut obj, "intent")?;
            input.criteria = field(&mut obj, "criteria")?;
            input.calibration = field(&mut obj, "calibration")?;
            input.policy = field(&mut obj, "policy")?;
            input.evidence_store = field(&mut obj, "evidence_store")?;
            input.id_scheme = field(&mut obj, "id_scheme")?;
            input.topic = field(&mut obj, "topic")?;
            match obj.remove("contributions") {
                Some(serde_json::Value::Array(items)) => items,
                Some(_) => return Err("field `contributions`: expected an array of contributions".into()),
                None => return Err("missing field `contributions`".into()),
            }
        }
        _ => return Err("expected an object or an array of contributions".into()),
    };
    let fill_ids = input.id_scheme.as_deref() == Some(CONTRIBUTION_ID_SCHEME);
    for (i, mut item) in items.into_iter().enumerate() {
        let Some(obj) = item.as_object_mut() else {
            return Err(format!("contributions[{i}]: expected an object"));
        };
        let missing_id = matches!(obj.get("id"), None | Some(serde_json::Value::Null));
        if missing_id && fill_ids {
            obj.insert("id".into(), serde_json::Value::String(String::new()));
        }
        let explicit_label = obj.get("is_correct").and_then(|b| b.as_bool());
        let mut c: Contribution = serde_json::from_value(item).map_err(|e| {
            if missing_id && !fill_ids && e.to_string().contains("missing field `id`") {
                format!("contributions[{i}]: {e} (an id may be omitted only with \"id_scheme\": \"{CONTRIBUTION_ID_SCHEME}\")")
            } else {
                format!("contributions[{i}]: {e}")
            }
        })?;
        if missing_id && fill_ids {
            c.id = content_id(&c);
        }
        if let Some(b) = explicit_label {
            input.labels.insert(c.id.clone(), b);
        }
        input.contributions.push(c);
    }
    Ok(input)
}

/// Base policy: a named preset (default `default`), with `--weights` if given.
fn base_policy(preset: Option<&str>, weights: Option<[f64; 5]>) -> Result<OverturnCompiler, String> {
    let name = preset.unwrap_or("default");
    let mut p = OverturnCompiler::preset(name).ok_or_else(|| format!(
        "unknown preset `{name}` (expected one of: {})", compiler::POLICY_PRESETS.join(", ")))?;
    if let Some(w) = weights {
        p.weights = w;
    }
    Ok(p)
}

/// Base policy plus an optional overlay. `--weights` together with an
/// overlay is an error: the overlay's base would silently change.
fn effective_policy(preset: Option<&str>, weights: Option<[f64; 5]>, overlay: Option<serde_json::Value>) -> Result<OverturnCompiler, String> {
    if weights.is_some() && overlay.is_some() {
        return Err("--weights cannot be combined with a policy overlay (it would change the overlay's base); \
            put \"weights\" in the overlay instead".into());
    }
    let base = base_policy(preset, weights)?;
    match overlay {
        None => Ok(base),
        Some(o) => overlay_policy(base, o),
    }
}

/// `--reduce <claims.json>`: reduce externally supplied contributions.
///
/// Input schema (JSON; `-` reads stdin). Either a bare array of
/// contributions, or:
/// ```text
/// {
///   "intent":      string,              // optional, default ""
///   "criteria":    [string],            // optional, constraint-alignment criteria
///   "calibration": {agent_id: number},  // optional, missing agents get 0.5
///   "policy":      { ...OverturnCompiler... } // optional, overlaid on the base policy
///                                       // (`--preset`, default `default`): each
///                                       // top-level key given replaces that field
///                                       // wholesale (a full policy is used as-is);
///                                       // unknown keys are rejected; combining an
///                                       // overlay with --weights is an error (exit 2).
///                                       // Optional fields (non-default values change
///                                       // the policy hash):
///                                       //   "schulze_dims": 0..31 bitmask over
///                                       //     (ev,conf,cs,rec,ca), bit 3 = rec;
///                                       //     31 = all (default), 23 = no recency
///                                       //   "tiebreak": "schulze" (default)
///                                       //     | "score_then_canonical"
///                                       //   "tiebreak_order": "seq" (default;
///                                       //     canonical (seq, id) order, arrival-
///                                       //     dependent) | "id" (id only)
///                                       //   "functional_predicates": [string]
///                                       //     extra FUNCTIONAL predicates (one slot
///                                       //     per (subject, predicate)), extending
///                                       //     the built-in list; default []
///                                       //   "evidence": { ...EvidencePolicy... }
///                                       //     optional, `bran-evidence-policy/1`;
///                                       //     missing fields take defaults; incl.
///                                       //     "accepted_checkers": [checker_id]
///   "id_scheme": "bran-contribution-id/1", // optional. When given, every
///                                       // supplied contribution id must equal its
///                                       // content id (`ir::content_id`), else
///                                       // exit 2 (supplied ids are never
///                                       // rewritten); an omitted (or null) id is
///                                       // computed. The scheme is sealed into the
///                                       // root hash. Absent: legacy, any unique id
///                                       // string is accepted (output unchanged).
///   "topic":     string,                // optional; --emit-artifact only
///                                       // (artifact `topic`, default "external")
///   "evidence_store": {                 // optional; records keyed by their ids
///       "captures": {capture_id: bran-capture/1 record},
///       "support":  {support_id: bran-support/1 record} },
///                                       // validated at seal time (ids = hashes,
///                                       // refs resolve, claims match); only
///                                       // referenced records are sealed
///   "contributions": [ {
///       "id":       string,             // unique content id (dedup key);
///                                       // optional with id_scheme
///       "agent_id": string,
///       "seq":      integer,            // recorded arrival order (recency)
///       "kind":     "ASSERTION" | "CRITIQUE" | "SYNTHESIS",  // SYNTHESIS is
///                                       // rejected at P3 (out of scope)
///       "canonical_form": null | {
///           "subject": string, "predicate": string, "object": string,
///           "polarity": "AFFIRM" | "NEGATE" },
///       "confidence": number,           // 0..1, self-reported
///       "lowering_confidence": "HIGH" | "MEDIUM" | "LOW",
///       "evidence": [ {                 // optional, default []
///           "type": "TOOL_RESULT" | "EMPIRICAL" | "CITATION" | "AUTHORITY" | "REASONING",
///           "source": string, "weight": number,
///           "reachable": bool,          // optional, default true
///           "verification": "UNVERIFIED" | "REACHABILITY_CHECKED" | "CONTENT_HASHED"
///                         | "CROSS_REFERENCED" | "STALE",   // optional, default UNVERIFIED
///           "capture_ref": string,      // optional, capture_id in evidence_store
///           "support_ref": string } ],  // optional, support_id (needs capture_ref)
///       "raw_text": string,             // optional, default ""
///       "agent_name": string,           // optional, display only
///       "is_correct": bool              // optional, eval label, ignored by reduction
///                                       // (becomes an artifact label when given)
///   } ]
/// }
/// ```
/// Other top-level keys are ignored. Parse errors name the field or the
/// contribution index.
///
/// Output: `ReductionOutput` JSON (root_hash, policy_hash, certificate, admitted and
/// rejected ids, and per-slot selections with quantized scores), plus
/// `p3_rejected` [{id, agent_id, seq, reason}] when P3 dropped any input
/// (reasons `synthesis_out_of_scope`, `no_canonical_form`, `duplicate_id`;
/// omitted when empty, so outputs without drops are unchanged), plus,
/// only under `--explain-rejected`, `rejected_reasons` (one
/// `compiler::RejectionReason` per id in `rejected`, same order).
///
/// `--emit-artifact OUT` also writes a replayable artifact file: the
/// sealed set exactly as reduced (same P3 filter, calibration and
/// evidence-store restriction), the full effective policy, its hash, the
/// outputs (without `p3_rejected`/`rejected_reasons`), `topic` from the
/// input (default `external`), `agents` = distinct sealed agent ids,
/// `seed` 0, `labels` from explicit `is_correct`, and `envelope_hash`.
/// Format `bran-artifact/4` with `id_scheme`, else `/3` with evidence
/// records or an evidence policy, else `/2`. It is replayed in-process
/// before it is written; stdout is unchanged.
fn run_reduce(path: &str, preset: Option<&str>, weights: Option<[f64; 5]>, emit: Option<&str>, explain_rejected: bool) {
    let text = read_or_exit(path);
    let input = parse_reduce_input(&text).unwrap_or_else(|e| {
        eprintln!("Cannot parse {path}: {e}");
        std::process::exit(2);
    });
    let policy = effective_policy(preset, weights, input.policy.clone()).unwrap_or_else(|e| {
        eprintln!("Invalid policy in {path}: {e}");
        std::process::exit(2);
    });
    let (v, file) = reduce_core(&input, policy, explain_rejected, emit.is_some()).unwrap_or_else(|e| {
        eprintln!("{} {path}: {}", e.0, e.1);
        std::process::exit(2);
    });
    if let (Some(out_path), Some(file)) = (emit, file) {
        let text = to_canonical_json(&file);
        let reread: ArtifactFile = serde_json::from_str(&text).expect("artifact round trip");
        if let Err(e) = verify_artifact_opts(&reread, true) {
            eprintln!("internal error: emitted artifact fails its own replay (exit {}): {}", e.exit_code(), e.message(&reread));
            std::process::exit(2);
        }
        std::fs::write(out_path, text).unwrap_or_else(|e| {
            eprintln!("Cannot write {out_path}: {e}");
            std::process::exit(2);
        });
    }
    println!("{}", to_canonical_json(&v));
}

/// Seal and reduce a parsed input under `policy`: the `--reduce` output
/// object and, with `emit`, the artifact file. Errors are (prefix, message).
fn reduce_core(input: &ReduceInput, policy: OverturnCompiler, explain_rejected: bool, emit: bool)
    -> Result<(serde_json::Value, Option<ArtifactFile>), (&'static str, String)> {
    let sealed = match input.id_scheme.as_deref() {
        None => compiler::seal_contributions_with_evidence(&input.intent, input.criteria.clone(), &input.calibration,
            &input.contributions, input.evidence_store.as_ref()).map_err(|e| ("Invalid evidence in", e.to_string()))?,
        Some(ir::CONTRIBUTION_ID_SCHEME) => compiler::seal_contributions_content(&input.intent, input.criteria.clone(),
            &input.calibration, &input.contributions, input.evidence_store.as_ref()).map_err(|e| ("Rejected input", e.to_string()))?,
        Some(other) => return Err(("Unknown id_scheme in", format!("`{other}` (expected {})", ir::CONTRIBUTION_ID_SCHEME))),
    };
    let out = compiler::ReductionOutput::from_result(&policy.reduce(&sealed));
    let (_, p3_rejected) = compiler::p3_validate_audited(&input.contributions);
    let mut v = serde_json::to_value(&out).expect("serialize");
    if !p3_rejected.is_empty() {
        v["p3_rejected"] = serde_json::to_value(&p3_rejected).expect("serialize");
    }
    if explain_rejected {
        v["rejected_reasons"] = serde_json::to_value(out.rejection_reasons(&sealed)).expect("serialize");
    }
    if !emit {
        return Ok((v, None));
    }
    let labels = sealed.contributions.iter()
        .filter_map(|c| input.labels.get(&c.id).map(|&b| (c.id.clone(), b))).collect();
    let agents = sealed.contributions.iter().map(|c| c.agent_id.as_str()).collect::<HashSet<_>>().len();
    let file = ArtifactFile {
        format: artifact_format(&sealed, &policy).to_string(),
        topic: input.topic.clone().unwrap_or_else(|| "external".into()),
        agents,
        seed: 0,
        policy_hash: policy.policy_hash(),
        policy,
        artifact: sealed,
        labels,
        outputs: out,
        envelope_hash: None,
    }.with_envelope();
    Ok((v, Some(file)))
}

/// `--print-policy [POLICY_JSON]`: the effective policy (`--preset` base,
/// plus the overlay object in POLICY_JSON, same rules as the `policy` key
/// of `--reduce`), printed as `{preset, policy, canonical_policy_json,
/// policy_hash, reducer_constants_id}`. `policy_hash` is the 128-bit
/// SHA-256 prefix of the exact `canonical_policy_json` string; `policy`
/// is the full serialized policy (usable as a `--reduce` overlay).
fn run_print_policy(arg: &str, preset: Option<&str>, weights: Option<[f64; 5]>) {
    let overlay = if arg.is_empty() { None } else {
        let text = read_or_exit(arg);
        Some(serde_json::from_str::<serde_json::Value>(&text).unwrap_or_else(|e| {
            eprintln!("Cannot parse {arg}: {e}");
            std::process::exit(2);
        }))
    };
    let policy = effective_policy(preset, weights, overlay).unwrap_or_else(|e| {
        eprintln!("Invalid policy: {e}");
        std::process::exit(2);
    });
    println!("{}", to_canonical_json(&serde_json::json!({
        "preset": preset.unwrap_or("default"),
        "policy": policy,
        "canonical_policy_json": policy.canonical_policy_json(),
        "policy_hash": policy.policy_hash(),
        "reducer_constants_id": compiler::reducer_constants_id(),
    })));
}

/// `--version`: JSON for wrappers checking compatibility.
fn version_json() -> serde_json::Value {
    let presets: std::collections::BTreeMap<&str, String> = compiler::POLICY_PRESETS.iter()
        .map(|&n| (n, OverturnCompiler::preset(n).expect("preset").policy_hash())).collect();
    let exit_codes: std::collections::BTreeMap<String, &str> = EXIT_CODES.iter().map(|&(c, m)| (c.to_string(), m)).collect();
    serde_json::json!({
        "name": env!("CARGO_PKG_NAME"),
        "version": env!("CARGO_PKG_VERSION"),
        "artifact_formats": ARTIFACT_FORMATS,
        "envelope_format": ENVELOPE_FORMAT,
        "policy_format": compiler::POLICY_FORMAT,
        "contribution_id_scheme": CONTRIBUTION_ID_SCHEME,
        "reducer_constants_id": compiler::reducer_constants_id(),
        "default_policy_hash": OverturnCompiler::default().policy_hash(),
        "presets": presets,
        "exit_codes": exit_codes,
    })
}

/// `--assign-ids`: compute content ids for a `--reduce` input. Only the
/// `id` fields change (an object input also gets `"id_scheme"`); other
/// fields pass through as parsed.
fn run_assign_ids(path: &str) {
    let text = read_or_exit(path);
    let mut v: serde_json::Value = serde_json::from_str(&text).unwrap_or_else(|e| {
        eprintln!("Cannot parse {path}: {e}");
        std::process::exit(2);
    });
    let is_obj = v.is_object();
    let arr = if is_obj { v.get_mut("contributions") } else { Some(&mut v) };
    let Some(serde_json::Value::Array(arr)) = arr else {
        eprintln!("{path}: expected a contributions array");
        std::process::exit(2);
    };
    for (i, item) in arr.iter_mut().enumerate() {
        if item.get("id").is_none() {
            item["id"] = serde_json::Value::String(String::new());
        }
        let c: Contribution = serde_json::from_value(item.clone()).unwrap_or_else(|e| {
            eprintln!("{path}: invalid contribution [{i}]: {e}");
            std::process::exit(2);
        });
        item["id"] = serde_json::Value::String(content_id(&c));
    }
    if is_obj {
        v["id_scheme"] = serde_json::Value::String(CONTRIBUTION_ID_SCHEME.into());
    }
    println!("{}", to_canonical_json(&v));
}

/// Overlay the top-level keys of `overlay` (a JSON object) onto `base`.
/// Each given key replaces that policy field wholesale; unknown keys are
/// an error (a typo must not silently fall back to the default).
fn overlay_policy(base: OverturnCompiler, overlay: serde_json::Value) -> Result<OverturnCompiler, String> {
    let serde_json::Value::Object(over) = overlay else {
        return Err("policy must be a JSON object".into());
    };
    let mut v = serde_json::to_value(&base).map_err(|e| e.to_string())?;
    let obj = v.as_object_mut().expect("policy serializes to an object");
    const OPTIONAL: &[&str] = &["schulze_dims", "tiebreak", "tiebreak_order", "candidate_mode", "evidence", "functional_predicates"];
    for (k, val) in over {
        if !obj.contains_key(&k) && !OPTIONAL.contains(&k.as_str()) {
            return Err(format!("unknown policy field `{k}`"));
        }
        obj.insert(k, val);
    }
    serde_json::from_value(v).map_err(|e| e.to_string())
}

fn main() {
    let cli = Cli::parse();

    unsafe { USE_COLOR = !cli.no_color; }
    if let Some(ref m) = cli.candidate_mode {
        value_mode::set_cli_mode(value_mode::CandidateMode::parse_cli(m).unwrap_or_else(|e| {
            eprintln!("{e}");
            std::process::exit(2);
        }));
    }

    let weights_given: Option<[f64; 5]> = cli.weights.as_ref().map(|w| {
        let parts: Vec<f64> = w.split(',').map(|s| s.parse().expect("Invalid weight")).collect();
        assert_eq!(parts.len(), 5, "Need exactly 5 weights: ev,conf,cs,rec,ca");
        [parts[0], parts[1], parts[2], parts[3], parts[4]]
    });
    let weights = weights_given.unwrap_or([0.35, 0.20, 0.25, 0.05, 0.15]);

    if cli.version {
        println!("{}", to_canonical_json(&version_json()));
    } else if let Some(ref arg) = cli.print_policy {
        run_print_policy(arg, cli.preset.as_deref(), weights_given);
    } else if let Some(ref path) = cli.dump_artifact {
        run_dump_artifact(path, &cli.topic, cli.agents, cli.seed, weights, cli.legacy_ids);
    } else if let Some(ref path) = cli.replay_from {
        run_replay_from(path, cli.json, cli.require_envelope);
    } else if let Some(ref path) = cli.reduce {
        run_reduce(path, cli.preset.as_deref(), weights_given, cli.emit_artifact.as_deref(), cli.explain_rejected);
    } else if let Some(ref path) = cli.assign_ids {
        run_assign_ids(path);
    } else if cli.stress {
        run_stress(cli.seed, weights);
    } else if cli.adversarial {
        run_adversarial(cli.seed, weights);
    } else if cli.expert_dropout {
        run_expert_dropout(cli.seed, weights);
    } else if cli.sybil {
        run_sybil(cli.seed, weights);
    } else if cli.noise {
        run_noise(weights);
    } else if cli.family_dominance {
        run_family_dominance(cli.seed, weights);
    } else if cli.pass_timing {
        run_pass_timing(cli.seed, weights);
    } else if cli.ablation {
        run_ablation(cli.seed);
    } else if cli.score_gaps {
        run_score_gaps(cli.seed, weights);
    } else if cli.cpwbft {
        run_cpwbft(cli.seed, weights);
    } else if cli.condorcet {
        run_condorcet(cli.seed, weights);
    } else if cli.baselines {
        run_baselines(cli.seed, weights);
    } else if cli.min_score {
        run_min_score(cli.seed, weights);
    } else if cli.baselines_scale {
        run_baselines_scale(cli.seed, weights);
    } else if cli.topology {
        run_topology(cli.seed, weights);
    } else if cli.real_lowering {
        run_real_lowering(cli.seed, weights);
    } else if cli.properties {
        run_properties(cli.seed, weights);
    } else if cli.replay {
        run_replay(cli.seed, weights, cli.replay_count);
    } else if cli.replay_variance {
        run_replay_variance(cli.seed, weights);
    } else if cli.scaling {
        run_scaling(&cli.topic, cli.seed, weights);
    } else {
        let topic = topics::get_topic(&cli.topic).unwrap_or_else(|| {
            eprintln!("Unknown topic: {}. Available: {:?}", cli.topic, topics::all_topic_keys());
            std::process::exit(1);
        });
        let roster = agents::get_roster(cli.agents);
        let compiler = OverturnCompiler::with_weights(weights);
        let result = compiler.compile(&topic, &roster, cli.seed);
        render(&result, &topic, &roster);
    }
}

#[cfg(test)]
mod reduce_policy_tests {
    use super::*;

    #[test]
    fn overlay_full_policy_is_identity_and_partial_overlays() {
        let w = [0.35, 0.20, 0.25, 0.05, 0.15];
        let d = OverturnCompiler::with_weights(w);
        let full = serde_json::to_value(&d).unwrap();
        assert_eq!(overlay_policy(d.clone(), full).unwrap().policy_hash(), d.policy_hash());
        let p = overlay_policy(d.clone(), serde_json::json!({"schulze_dims": 23, "tiebreak": "score_then_canonical"})).unwrap();
        assert_eq!(p.schulze_dims, compiler::SCHULZE_DIMS_NO_RECENCY);
        assert_eq!(p.tiebreak, compiler::TieBreak::ScoreThenCanonical);
        assert_eq!(p.weights, d.weights);
        assert_ne!(p.policy_hash(), d.policy_hash());
        let p = overlay_policy(d.clone(), serde_json::json!({"weights": [0.4, 0.2, 0.25, 0.0, 0.15]})).unwrap();
        assert_eq!(p.weights[3], 0.0);
        let p = overlay_policy(d.clone(), serde_json::json!({"tiebreak_order": "id"})).unwrap();
        assert_eq!(p.tiebreak_order, compiler::TieOrder::Id);
        assert!(overlay_policy(d.clone(), serde_json::json!({"schulze_dim": 23})).is_err());
        assert!(overlay_policy(d.clone(), serde_json::json!({"tiebreak": "coin_flip"})).is_err());
        assert!(overlay_policy(d, serde_json::json!([1])).is_err());
    }
}

#[cfg(test)]
mod replay_tests {
    use super::*;

    fn roundtrip(f: &ArtifactFile) -> ArtifactFile {
        serde_json::from_str(&to_canonical_json(f)).unwrap()
    }

    fn base() -> ArtifactFile {
        roundtrip(&build_artifact("tcp", 40, 42, [0.35, 0.20, 0.25, 0.05, 0.15]))
    }

    #[test]
    fn dumped_artifact_replays() {
        let f = base();
        assert_eq!(f.policy_hash, OverturnCompiler::default().policy_hash());
        assert_eq!(f.outputs.policy_hash, f.policy_hash);
        let out = verify_artifact(&f).unwrap();
        assert_eq!(out, f.outputs);
    }

    #[test]
    fn tampered_policy_rejected_as_policy_mismatch() {
        let muts: Vec<(&str, Box<dyn Fn(&mut OverturnCompiler)>)> = vec![
            ("weight", Box::new(|c| c.weights[1] = 0.21)),
            ("deadband", Box::new(|c| c.deadband_threshold = 501)),
            ("schulze_eps", Box::new(|c| c.schulze_dim_epsilon = 99)),
            ("hardening", Box::new(|c| c.hardening.max_critiques_per_agent = 4)),
            ("incompatible_values entry", Box::new(|c| {
                c.values.incompatible_values.get_mut("handles_loss_via").unwrap()
                    .get_mut("tcp_loss_recovery").unwrap().pop();
            })),
        ];
        for (name, m) in muts {
            let mut f = base();
            m(&mut f.policy);
            let f = roundtrip(&f);
            match verify_artifact(&f) {
                Err(e @ ReplayError::PolicyHash { .. }) => assert_eq!(e.exit_code(), 4, "{name}"),
                other => panic!("{name}: expected PolicyHash error, got {:?}", other.map(|_| ())),
            }
        }
    }

    #[test]
    fn tampered_stored_policy_hash_rejected() {
        let mut f = base();
        f.policy_hash = "0".repeat(32);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::PolicyHash { .. })));
        let mut f = base();
        f.outputs.policy_hash = "0".repeat(32);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::PolicyHash { .. })));
    }

    #[test]
    fn policy_and_hash_both_forged_caught_by_outputs() {
        // Consistent forgery (policy edited, hash recomputed): passes the
        // policy check, but the certificate covers the policy hash, so the
        // stored outputs no longer match.
        let mut f = base();
        f.policy.deadband_threshold = 2000;
        f.policy_hash = f.policy.policy_hash();
        f.outputs.policy_hash = f.policy_hash.clone();
        match verify_artifact(&f) {
            Err(e @ ReplayError::Output { .. }) => assert_eq!(e.exit_code(), 1),
            other => panic!("expected Output error, got {:?}", other.map(|_| ())),
        }
    }

    #[test]
    fn tampered_artifact_and_outputs_have_distinct_errors() {
        let mut f = base();
        f.artifact.contributions[0].confidence += 0.01;
        assert!(matches!(verify_artifact(&f), Err(ReplayError::ArtifactHash { .. })));
        let mut f = base();
        f.outputs.admitted.pop();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Output { .. })));
        let mut f = base();
        f.format = "bran-artifact/1".into();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Format { .. })));
    }
}

// ── Tests: bran-artifact/3 (evidence records) replay & tamper (spec §4) ──

#[cfg(test)]
mod evidence_replay_tests {
    use super::*;
    use evidence::{CaptureOutcome, CaptureRecord, EvidencePolicy, SupportLabel, SupportRecord};

    const W: [f64; 5] = [0.35, 0.20, 0.25, 0.05, 0.15];
    const FIXTURE: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../v2/evidence/fixtures/tcp-evidence.bran-artifact-3.json");

    fn roundtrip(f: &ArtifactFile) -> ArtifactFile {
        serde_json::from_str(&to_canonical_json(f)).unwrap()
    }

    /// tcp N=40 seed=42 with fixture captures/support (no network, no
    /// model), reduced under the default policy + evidence policy.
    fn evidence_artifact() -> ArtifactFile {
        let base = build_artifact_ids("tcp", 40, 42, W, true);
        let mut contribs = base.artifact.contributions.clone();
        let (store, accepted) = evidence::fixtures::attach(&mut contribs);
        let policy = OverturnCompiler {
            evidence: Some(EvidencePolicy { accepted_checkers: vec![accepted], ..EvidencePolicy::default() }),
            ..base.policy.clone()
        };
        let sealed = compiler::seal_contributions_with_evidence(&base.artifact.intent, base.artifact.criteria.clone(),
            &base.artifact.calibration, &contribs, Some(&store)).unwrap();
        let result = policy.reduce(&sealed);
        roundtrip(&ArtifactFile {
            format: artifact_format(&sealed, &policy).to_string(),
            topic: "tcp".into(), agents: 40, seed: 42,
            policy_hash: policy.policy_hash(),
            outputs: compiler::ReductionOutput::from_result(&result),
            artifact: sealed,
            policy,
            labels: base.labels,
            envelope_hash: None,
        })
    }

    fn store(f: &mut ArtifactFile) -> &mut evidence::EvidenceStore {
        f.artifact.evidence_store.as_mut().unwrap()
    }

    fn reseal(f: &mut ArtifactFile) {
        f.artifact.root_hash = f.artifact.compute_root_hash();
    }

    /// Consistent forgery of a support record: mutate, recompute
    /// checker_id and support_id, re-key, update the ref, reseal the root.
    fn forge_support(f: &mut ArtifactFile, sid: &str, m: impl Fn(&mut SupportRecord)) {
        let mut r = store(f).support.remove(sid).unwrap();
        m(&mut r);
        r.checker.checker_id = r.checker.compute_id();
        let new = store(f).add_support(r);
        for c in &mut f.artifact.contributions {
            for e in &mut c.evidence {
                if e.support_ref.as_deref() == Some(sid) { e.support_ref = Some(new.clone()); }
            }
        }
        reseal(f);
    }

    /// Consistent forgery of a capture record, cascading the new
    /// capture_id into items and support records.
    fn forge_capture(f: &mut ArtifactFile, cid: &str, m: impl Fn(&mut CaptureRecord)) {
        let mut r = store(f).captures.remove(cid).unwrap();
        m(&mut r);
        let new = store(f).add_capture(r);
        for c in &mut f.artifact.contributions {
            for e in &mut c.evidence {
                if e.capture_ref.as_deref() == Some(cid) { e.capture_ref = Some(new.clone()); }
            }
        }
        let dependents: Vec<String> = store(f).support.iter().filter(|(_, s)| s.capture_id == cid).map(|(k, _)| k.clone()).collect();
        for sid in dependents {
            let n = new.clone();
            forge_support(f, &sid, move |s| s.capture_id = n.clone());
        }
        reseal(f);
    }

    fn accepted_supports(f: &ArtifactFile) -> String {
        let acc = &f.policy.evidence.as_ref().unwrap().accepted_checkers;
        f.artifact.evidence_store.as_ref().unwrap().support.iter()
            .find(|(_, s)| s.label == Some(SupportLabel::Supports) && acc.contains(&s.checker.checker_id))
            .map(|(k, _)| k.clone()).unwrap()
    }

    fn capture_with(f: &ArtifactFile, o: CaptureOutcome) -> String {
        f.artifact.evidence_store.as_ref().unwrap().captures.iter()
            .find(|(_, c)| c.outcome == o).map(|(k, _)| k.clone()).unwrap()
    }

    fn expect(f: &ArtifactFile, code: i32, what: &str) {
        match verify_artifact(f) {
            Err(e) => assert_eq!(e.exit_code(), code, "{what}: {e:?}"),
            Ok(_) => panic!("{what}: tampered artifact verified"),
        }
    }

    /// Acceptance 7: dump `/3`, reload, replay — pure function of the file
    /// (no network, no cache, no model).
    #[test]
    fn evidence_artifact_replays_offline() {
        let f = evidence_artifact();
        assert_eq!(f.format, ARTIFACT_FORMAT_V3);
        let st = f.artifact.evidence_store.as_ref().unwrap();
        assert_eq!(st.captures.len(), 3);
        assert!(st.support.len() >= 4);
        assert_eq!(verify_artifact(&f).unwrap(), f.outputs);
        // Evidence scoring actually changed the outcome vs. legacy.
        let legacy = build_artifact_ids("tcp", 40, 42, W, true);
        assert_ne!(f.outputs.selections, legacy.outputs.selections);
        assert_eq!(legacy.format, ARTIFACT_FORMAT);
    }

    /// The committed fixture replays and is reproduced byte-for-byte.
    /// Regenerate with `OVERTURN_WRITE_FIXTURES=1 cargo test --release committed_evidence_fixture`.
    #[test]
    fn committed_evidence_fixture_replays() {
        let fresh = to_canonical_json(&evidence_artifact());
        if std::env::var_os("OVERTURN_WRITE_FIXTURES").is_some() {
            std::fs::write(FIXTURE, &fresh).unwrap();
        }
        let text = std::fs::read_to_string(FIXTURE).expect("fixture missing; run with OVERTURN_WRITE_FIXTURES=1");
        assert_eq!(text, fresh, "fixture drifted from the builder");
        let f: ArtifactFile = serde_json::from_str(&text).unwrap();
        assert_eq!(verify_artifact(&f).unwrap(), f.outputs);
    }

    /// `evidence_artifact` plus one accepted `supports` label on the member
    /// of a contradiction slot backed by the fewest agents, reduced under
    /// the verified-overturn gate.
    fn gated_artifact() -> ArtifactFile {
        let mut f = evidence_artifact();
        let mut contribs = f.artifact.contributions.clone();
        let mut st = f.artifact.evidence_store.clone().unwrap();
        let acc = f.policy.evidence.as_ref().unwrap().accepted_checkers[0].clone();
        let tmpl = st.support.values().find(|s| s.checker.checker_id == acc).unwrap().clone();
        let sel = f.outputs.selections.iter().find(|s| s.typ == "CONTRADICTION").unwrap();
        let value = |id: &str| {
            let c = contribs.iter().find(|c| c.id == id).unwrap();
            let t = c.canonical_form.as_ref().unwrap();
            (normalize_object(&t.object), t.polarity == Polarity::Negate)
        };
        let agents = |m: &str| sel.members.iter().filter(|x| value(x) == value(m))
            .map(|x| contribs.iter().find(|c| &c.id == x).unwrap().agent_id.clone())
            .collect::<HashSet<_>>().len();
        let minority = sel.members.iter().min_by_key(|m| (agents(m), (*m).clone())).unwrap().clone();
        let c = contribs.iter_mut().find(|c| c.id == minority).unwrap();
        let mut sup = tmpl.clone();
        sup.contribution_id = c.id.clone();
        sup.claim = evidence::SupportClaim::of(c.canonical_form.as_ref().unwrap(), &c.raw_text);
        sup.label = Some(SupportLabel::Supports);
        let sid = st.add_support(sup);
        let mut e = EvidenceItem::new(EvidenceType::Citation, "RFC 793 Section 3.3", 1.0, true);
        e.capture_ref = Some(tmpl.capture_id.clone());
        e.support_ref = Some(sid);
        c.evidence.push(e);
        f.artifact = compiler::seal_contributions_with_evidence(&f.artifact.intent, f.artifact.criteria.clone(),
            &f.artifact.calibration, &contribs, Some(&st)).unwrap();
        f.policy.evidence.as_mut().unwrap().overturn_gate = evidence::OverturnGate::Verified;
        let result = f.policy.reduce(&f.artifact);
        f.format = artifact_format(&f.artifact, &f.policy).to_string();
        f.policy_hash = f.policy.policy_hash();
        f.outputs = compiler::ReductionOutput::from_result(&result);
        roundtrip(&f)
    }

    /// Gate: the artifact replays offline; the gate is in the policy hash
    /// (not the root); every contradiction slot carries a trace; removing
    /// the gate, editing a trace, flipping a label, or a consistently
    /// forged label are each rejected.
    #[test]
    fn gated_artifact_replays_and_rejects_tamper() {
        let f = gated_artifact();
        assert_eq!(verify_artifact(&f).unwrap(), f.outputs);
        // the same sealed set reduced without the gate: same root, other policy hash
        let mut ungated = f.clone();
        ungated.policy.evidence.as_mut().unwrap().overturn_gate = evidence::OverturnGate::None;
        ungated.policy_hash = ungated.policy.policy_hash();
        ungated.outputs = compiler::ReductionOutput::from_result(&ungated.policy.reduce(&ungated.artifact));
        assert_eq!(verify_artifact(&ungated).unwrap(), ungated.outputs);
        assert_eq!(f.artifact.root_hash, ungated.artifact.root_hash);
        assert_ne!(f.policy_hash, ungated.policy_hash);
        assert_eq!(ungated.policy_hash, evidence_artifact().policy_hash);
        assert!(f.policy.canonical_policy_json().contains("\"overturn_gate\":\"verified\""));
        assert!(!ungated.policy.canonical_policy_json().contains("overturn_gate"));
        let contra: Vec<_> = f.outputs.selections.iter().filter(|s| s.typ == "CONTRADICTION").collect();
        assert!(!contra.is_empty() && contra.iter().all(|s| s.gate.is_some()));
        assert!(f.outputs.selections.iter().filter(|s| s.typ != "CONTRADICTION").all(|s| s.gate.is_none()));
        assert!(ungated.outputs.selections.iter().all(|s| s.gate.is_none()));
        assert!(contra.iter().any(|s| s.gate.as_ref().unwrap().stage == "verified"));
        // the same scores: the gate only restricts the candidates
        for (g, u) in f.outputs.selections.iter().zip(&ungated.outputs.selections) {
            assert_eq!(g.scores_q, u.scores_q);
        }
        // gate removed, stored hash kept → policy mismatch (4)
        let mut t = f.clone();
        t.policy.evidence.as_mut().unwrap().overturn_gate = evidence::OverturnGate::None;
        expect(&t, 4, "gate removed");
        // gate trace edited → output mismatch (1)
        let mut t = f.clone();
        let s = t.outputs.selections.iter_mut().find(|s| s.gate.is_some()).unwrap();
        s.gate.as_mut().unwrap().overturned ^= true;
        expect(&t, 1, "gate trace edited");
        // witness label flipped, ids kept → hash mismatch (3)
        let mut t = f.clone();
        let sid = accepted_supports(&t);
        store(&mut t).support.get_mut(&sid).unwrap().label = Some(SupportLabel::NotEnoughInfo);
        expect(&t, 3, "witness label flip");
        // every accepted supports label consistently forged to refutes (ids
        // and root recomputed): the sealed set verifies, but no slot can
        // reach the verified stage any more → output mismatch (1)
        let mut t = f.clone();
        let acc = t.policy.evidence.as_ref().unwrap().accepted_checkers.clone();
        loop {
            let next = store(&mut t).support.iter()
                .find(|(_, s)| s.label == Some(SupportLabel::Supports) && acc.contains(&s.checker.checker_id))
                .map(|(k, _)| k.clone());
            let Some(sid) = next else { break };
            forge_support(&mut t, &sid, |s| s.label = Some(SupportLabel::Refutes));
        }
        match verify_artifact(&t) {
            Err(e @ ReplayError::Output { .. }) => {
                assert_eq!(e.exit_code(), 1);
                if let ReplayError::Output { replayed } = e {
                    assert!(replayed.selections.iter().filter_map(|s| s.gate.as_ref()).all(|g| g.stage == "plurality"));
                }
            }
            other => panic!("forged labels: expected output mismatch, got {:?}", other.err()),
        }
    }

    /// Tamper 1: flip a support label without updating ids → root hash
    /// mismatch, exit 3. Re-sealing only the root → record hash, exit 3.
    #[test]
    fn flipped_label_is_hash_mismatch() {
        let mut f = evidence_artifact();
        let sid = accepted_supports(&f);
        store(&mut f).support.get_mut(&sid).unwrap().label = Some(SupportLabel::Refutes);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::ArtifactHash { .. })));
        expect(&f, 3, "label flip");
        reseal(&mut f);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::RecordHash(_))));
        expect(&f, 3, "label flip, root resealed");
    }

    /// Tamper 2/3: consistent forgeries (ids, refs and root recomputed)
    /// pass every hash check but the certificate covers the root, so the
    /// stored outputs differ → exit 1.
    #[test]
    fn consistent_forgeries_fail_on_outputs() {
        let cases: Vec<(&str, Box<dyn Fn(&mut ArtifactFile)>)> = vec![
            ("support label", Box::new(|f| { let s = accepted_supports(f); forge_support(f, &s, |r| r.label = Some(SupportLabel::Refutes)) })),
            ("checker", Box::new(|f| { let s = accepted_supports(f); forge_support(f, &s, |r| r.checker.model_digest.push('0')) })),
            ("capture outcome", Box::new(|f| { let c = capture_with(f, CaptureOutcome::NotFound); forge_capture(f, &c, |r| r.outcome = CaptureOutcome::OkNoText) })),
            ("canonical_url", Box::new(|f| { let c = capture_with(f, CaptureOutcome::Ok); forge_capture(f, &c, |r| r.canonical_url = Some("https://other.example/".into())) })),
            ("content_sha256", Box::new(|f| { let c = capture_with(f, CaptureOutcome::Ok); forge_capture(f, &c, |r| r.content_sha256 = Some("0".repeat(64))) })),
        ];
        for (name, m) in cases {
            let mut f = evidence_artifact();
            m(&mut f);
            assert!(evidence::validate_store(&f.artifact.contributions, f.artifact.evidence_store.as_ref().unwrap()).is_ok(), "{name}");
            match verify_artifact(&f) {
                Err(e @ ReplayError::Output { .. }) => assert_eq!(e.exit_code(), 1, "{name}"),
                other => panic!("{name}: expected Output error, got {:?}", other.map(|_| ())),
            }
        }
    }

    /// Tamper 4: dropping a checker from `accepted_checkers` → exit 4
    /// without recomputing the policy hash, exit 1 with it.
    #[test]
    fn unaccepting_a_checker() {
        let mut f = evidence_artifact();
        f.policy.evidence.as_mut().unwrap().accepted_checkers.clear();
        let f = roundtrip(&f);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::PolicyHash { .. })));
        expect(&f, 4, "accepted_checkers edited");
        let mut f = f;
        f.policy_hash = f.policy.policy_hash();
        f.outputs.policy_hash = f.policy_hash.clone();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Output { .. })));
        expect(&f, 1, "accepted_checkers edited, hash recomputed");
    }

    #[test]
    fn format_tag_must_match_contents() {
        let mut f = evidence_artifact();
        f.format = ARTIFACT_FORMAT.into();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Format { .. })));
        expect(&f, 5, "/2 tag on evidence artifact");
        // /2 with only an evidence policy, or only a store.
        let mut f = evidence_artifact();
        f.format = ARTIFACT_FORMAT.into();
        f.artifact.evidence_store = None;
        expect(&f, 5, "/2 with evidence policy");
        let mut f = evidence_artifact();
        f.format = ARTIFACT_FORMAT.into();
        f.policy.evidence = None;
        expect(&f, 5, "/2 with store");
        // /3 tag on a legacy artifact.
        let mut f = roundtrip(&build_artifact("tcp", 40, 42, W));
        f.format = ARTIFACT_FORMAT_V3.into();
        expect(&f, 5, "/3 tag on legacy artifact");
    }

    // ── Local corpus captures (v3 addendum §4) ──

    /// As `evidence_artifact`, with corpus passages instead of web pages
    /// (`fixtures::attach_corpus`) and the given evidence policy.
    fn corpus_artifact(grounded: bool) -> ArtifactFile {
        let base = build_artifact_ids("tcp", 40, 42, W, true);
        let mut contribs = base.artifact.contributions.clone();
        let (store, accepted) = evidence::fixtures::attach_corpus(&mut contribs);
        let ev = if grounded { EvidencePolicy::grounded(vec![accepted]) }
                 else { EvidencePolicy { accepted_checkers: vec![accepted], ..EvidencePolicy::default() } };
        let policy = OverturnCompiler { evidence: Some(ev), ..base.policy.clone() };
        let sealed = compiler::seal_contributions_with_evidence(&base.artifact.intent, base.artifact.criteria.clone(),
            &base.artifact.calibration, &contribs, Some(&store)).unwrap();
        let result = policy.reduce(&sealed);
        roundtrip(&ArtifactFile {
            format: artifact_format(&sealed, &policy).to_string(),
            topic: "tcp".into(), agents: 40, seed: 42,
            policy_hash: policy.policy_hash(),
            outputs: compiler::ReductionOutput::from_result(&result),
            artifact: sealed,
            policy,
            labels: base.labels,
            envelope_hash: None,
        })
    }

    #[test]
    fn corpus_artifact_replays_offline() {
        for grounded in [false, true] {
            let f = corpus_artifact(grounded);
            assert_eq!(f.format, ARTIFACT_FORMAT_V3);
            let st = f.artifact.evidence_store.as_ref().unwrap();
            assert_eq!(st.captures.len(), 3);
            assert!(st.captures.values().all(|c| c.identifier_kind == evidence::IdentifierKind::Corpus));
            assert!(st.support.values().any(|s| s.status == evidence::SupportStatus::ParseError));
            assert_eq!(verify_artifact(&f).unwrap(), f.outputs, "grounded={grounded}");
            // Text round-trip is byte-stable.
            assert_eq!(to_canonical_json(&roundtrip(&f)), to_canonical_json(&f));
        }
        // Corpus captures change nothing in the policy: same hash as the
        // web-capture fixture; the grounded policy hashes apart.
        assert_eq!(corpus_artifact(false).policy_hash, evidence_artifact().policy_hash);
        assert_ne!(corpus_artifact(true).policy_hash, evidence_artifact().policy_hash);
        // Refused checks score lower under grounded: some quantized score moves.
        let scores = |f: &ArtifactFile| f.outputs.selections.iter().map(|s| s.scores_q.clone()).collect::<Vec<_>>();
        assert_ne!(scores(&corpus_artifact(true)), scores(&corpus_artifact(false)));
    }

    /// Tamper 1 on corpus captures: label flip without ids → exit 3.
    #[test]
    fn corpus_flipped_label_is_hash_mismatch() {
        let mut f = corpus_artifact(true);
        let sid = accepted_supports(&f);
        store(&mut f).support.get_mut(&sid).unwrap().label = Some(SupportLabel::Refutes);
        expect(&f, 3, "corpus label flip");
        reseal(&mut f);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::RecordHash(_))));
        // Edited passage hash without a new capture id → exit 3 as well.
        let mut f = corpus_artifact(true);
        let cid = capture_with(&f, CaptureOutcome::Ok);
        store(&mut f).captures.get_mut(&cid).unwrap().content_sha256 = Some("0".repeat(64));
        reseal(&mut f);
        expect(&f, 3, "corpus content_sha256 edited, id kept");
    }

    /// Tamper 2/3 on corpus captures: consistent forgeries that keep the
    /// corpus record shape pass every hash check and fail on outputs.
    #[test]
    fn corpus_consistent_forgeries_fail_on_outputs() {
        let repoint = |r: &mut CaptureRecord| {
            let u = "corpus://fever17/fever17:Other_page:0".to_string();
            (r.requested, r.request_url, r.resolved_url, r.canonical_url) = (u.clone(), u.clone(), Some(u.clone()), Some(u));
        };
        let cases: Vec<(&str, Box<dyn Fn(&mut ArtifactFile)>)> = vec![
            ("support label", Box::new(|f| { let s = accepted_supports(f); forge_support(f, &s, |r| r.label = Some(SupportLabel::Refutes)) })),
            ("passage text hash", Box::new(|f| { let c = capture_with(f, CaptureOutcome::Ok); forge_capture(f, &c, |r| r.content_sha256 = Some("0".repeat(64))) })),
            ("passage key", Box::new(move |f| { let c = capture_with(f, CaptureOutcome::Ok); forge_capture(f, &c, repoint) })),
            ("empty passage promoted to ok", Box::new(|f| { let c = capture_with(f, CaptureOutcome::OkNoText); forge_capture(f, &c, |r| r.outcome = CaptureOutcome::Ok) })),
            ("corpus pin", Box::new(|f| { let c = capture_with(f, CaptureOutcome::InvalidIdentifier); forge_capture(f, &c, |r| r.capture_tool_version.push('0')) })),
        ];
        for (name, m) in cases {
            let mut f = corpus_artifact(true);
            m(&mut f);
            assert!(evidence::validate_store(&f.artifact.contributions, f.artifact.evidence_store.as_ref().unwrap()).is_ok(), "{name}");
            match verify_artifact(&f) {
                Err(e @ ReplayError::Output { .. }) => assert_eq!(e.exit_code(), 1, "{name}"),
                other => panic!("{name}: expected Output error, got {:?}", other.map(|_| ())),
            }
        }
    }

    /// Consistent forgeries that break the corpus record shape (a fetch
    /// that never happened, a web URL, a non-canonical key) → exit 3.
    #[test]
    fn corpus_shape_forgeries_rejected() {
        let cases: Vec<(&str, Box<dyn Fn(&mut CaptureRecord)>)> = vec![
            ("http_status", Box::new(|r| r.http_status = Some(200))),
            ("robots", Box::new(|r| r.robots.checked = true)),
            ("redirect", Box::new(|r| r.redirects.push(evidence::Redirect { url: r.request_url.clone(), status: 301 }))),
            ("web url", Box::new(|r| { let u = "https://en.wikipedia.org/wiki/TCP".to_string(); (r.requested, r.request_url) = (u.clone(), u); })),
            ("dead outcome", Box::new(|r| r.outcome = CaptureOutcome::NotFound)),
        ];
        for (name, m) in cases {
            let mut f = corpus_artifact(true);
            let c = capture_with(&f, CaptureOutcome::OkNoText);
            forge_capture(&mut f, &c, m);
            assert!(matches!(verify_artifact(&f), Err(ReplayError::RecordHash(_))), "{name}");
            expect(&f, 3, name);
        }
    }

    /// Tamper 4 on the grounded policy: editing unchecked_factor or the
    /// checker list → exit 4; with the hash recomputed → exit 1.
    #[test]
    fn corpus_policy_edits() {
        let edits: Vec<(&str, Box<dyn Fn(&mut EvidencePolicy)>)> = vec![
            ("unchecked_factor back to 1.0", Box::new(|p| p.unchecked_factor = 1.0)),
            ("accepted_checkers cleared", Box::new(|p| p.accepted_checkers.clear())),
        ];
        for (name, m) in edits {
            let mut f = corpus_artifact(true);
            m(f.policy.evidence.as_mut().unwrap());
            let mut f = roundtrip(&f);
            expect(&f, 4, name);
            f.policy_hash = f.policy.policy_hash();
            f.outputs.policy_hash = f.policy_hash.clone();
            assert!(matches!(verify_artifact(&f), Err(ReplayError::Output { .. })), "{name}");
            expect(&f, 1, name);
        }
    }

    #[test]
    fn reduce_input_accepts_evidence_records() {
        let f = evidence_artifact();
        let input = serde_json::json!({
            "intent": f.artifact.intent,
            "criteria": f.artifact.criteria,
            "calibration": f.artifact.calibration,
            "policy": {"evidence": serde_json::to_value(f.policy.evidence.as_ref().unwrap()).unwrap()},
            "evidence_store": f.artifact.evidence_store,
            "contributions": f.artifact.contributions,
        });
        let policy = overlay_policy(OverturnCompiler::with_weights(W), input["policy"].clone()).unwrap();
        assert_eq!(policy.policy_hash(), f.policy_hash);
        let contribs: Vec<Contribution> = serde_json::from_value(input["contributions"].clone()).unwrap();
        let st: evidence::EvidenceStore = serde_json::from_value(input["evidence_store"].clone()).unwrap();
        let sealed = compiler::seal_contributions_with_evidence(&f.artifact.intent, f.artifact.criteria.clone(),
            &f.artifact.calibration, &contribs, Some(&st)).unwrap();
        assert_eq!(compiler::ReductionOutput::from_result(&policy.reduce(&sealed)), f.outputs);
        // Dangling ref is a seal error, not silently unchecked.
        assert!(compiler::seal_contributions_with_evidence("", vec![], &Default::default(), &contribs, None).is_err());
    }
}

// ── Tests: bran-artifact/4 (content-addressed ids) replay & tamper ──

#[cfg(test)]
mod content_id_replay_tests {
    use super::*;

    const W: [f64; 5] = [0.35, 0.20, 0.25, 0.05, 0.15];
    const LEGACY_DUMPS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../v2/evidence/replay/dumps/aarch64-apple-darwin");

    fn roundtrip(f: &ArtifactFile) -> ArtifactFile {
        serde_json::from_str(&to_canonical_json(f)).unwrap()
    }

    fn v4() -> ArtifactFile { roundtrip(&build_artifact("tcp", 40, 42, W)) }

    fn reseal(f: &mut ArtifactFile) { f.artifact.root_hash = f.artifact.compute_root_hash(); }

    #[test]
    fn dumped_v4_artifact_replays() {
        let f = v4();
        assert_eq!(f.format, ARTIFACT_FORMAT_V4);
        assert_eq!(f.policy_hash, "dd8d36e6def3a6d598765e82d461a473");
        assert_eq!(f.artifact.id_scheme.as_deref(), Some(CONTRIBUTION_ID_SCHEME));
        assert!(f.artifact.contributions.iter().all(|c| c.id == content_id(c)));
        assert_eq!(verify_artifact(&f).unwrap(), f.outputs);
    }

    /// `--legacy-ids` reproduces the committed `bran-artifact/2` dumps
    /// byte for byte, so `/2` hashes in the paper remain reproducible.
    #[test]
    fn legacy_ids_reproduce_committed_v2_dumps() {
        for t in ["australia", "pluto", "tides", "tcp", "nutrition"] {
            let fresh = to_canonical_json(&build_artifact_ids(t, 100, 42, W, true));
            let committed = std::fs::read_to_string(format!("{LEGACY_DUMPS}/{t}.json")).unwrap();
            assert_eq!(fresh, committed, "{t}");
            let f: ArtifactFile = serde_json::from_str(&committed).unwrap();
            assert_eq!(f.format, ARTIFACT_FORMAT);
            assert!(verify_artifact(&f).is_ok());
        }
    }

    /// Edit a claim, keep its id, recompute the root hash (a consistent
    /// forgery of everything but the id): rejected as a contribution id
    /// mismatch, exit 3. Without resealing it is a root hash mismatch.
    #[test]
    fn edited_claim_with_kept_id_rejected() {
        let tampers: Vec<(&str, Box<dyn Fn(&mut Contribution)>)> = vec![
            ("object", Box::new(|c| c.canonical_form.as_mut().unwrap().object.push('x'))),
            ("polarity", Box::new(|c| {
                let t = c.canonical_form.as_mut().unwrap();
                t.polarity = if t.polarity == Polarity::Affirm { Polarity::Negate } else { Polarity::Affirm };
            })),
            ("confidence", Box::new(|c| c.confidence = 0.999)),
            ("agent_id", Box::new(|c| c.agent_id = "dr._expert".into())),
            ("evidence", Box::new(|c| c.evidence.push(EvidenceItem::new(EvidenceType::ToolResult, "forged", 1.0, true)))),
        ];
        for (name, t) in tampers {
            let mut f = v4();
            t(&mut f.artifact.contributions[0]);
            assert!(matches!(verify_artifact(&f), Err(ReplayError::ArtifactHash { .. })), "{name} unsealed");
            reseal(&mut f);
            match verify_artifact(&f) {
                Err(e @ ReplayError::ContributionId(_)) => assert_eq!(e.exit_code(), 3, "{name}"),
                other => panic!("{name}: expected ContributionId, got {:?}", other.map(|_| ())),
            }
        }
    }

    #[test]
    fn synthesis_in_v4_set_rejected() {
        let mut f = v4();
        let c = &mut f.artifact.contributions[0];
        c.kind = ContributionKind::Synthesis;
        c.id = content_id(c);
        reseal(&mut f);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::ContributionId(m)) if m.contains("SYNTHESIS")));
    }

    #[test]
    fn scheme_downgrade_and_format_retag_rejected() {
        // Strip the scheme: root hash no longer matches.
        let mut f = v4();
        f.artifact.id_scheme = None;
        f.format = ARTIFACT_FORMAT.into();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::ArtifactHash { .. })));
        // Retag only: format mismatch.
        let mut f = v4();
        f.format = ARTIFACT_FORMAT.into();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Format { .. })));
        // A /4 tag on a legacy file: format mismatch.
        let mut f = roundtrip(&build_artifact_ids("tcp", 40, 42, W, true));
        f.format = ARTIFACT_FORMAT_V4.into();
        assert!(matches!(verify_artifact(&f), Err(ReplayError::Format { .. })));
        // Unknown scheme (resealed) is rejected.
        let mut f = v4();
        f.artifact.id_scheme = Some("bran-contribution-id/0".into());
        reseal(&mut f);
        assert!(matches!(verify_artifact(&f), Err(ReplayError::ContributionId(_))));
    }

    /// Content ids and `bran-support/1` records compose: the id covers
    /// `capture_ref` but not `support_ref`, so support records can name
    /// the (final) content id without a cycle.
    #[test]
    fn v4_with_evidence_records_replays() {
        let base = v4();
        let mut contribs = base.artifact.contributions.clone();
        let _ = evidence::fixtures::attach(&mut contribs); // set capture refs
        assign_content_ids(&mut contribs);                // ids over capture refs
        let (store, accepted) = evidence::fixtures::attach(&mut contribs); // support records name final ids
        assert!(contribs.iter().all(|c| c.id == content_id(c)));
        let policy = OverturnCompiler {
            evidence: Some(evidence::EvidencePolicy { accepted_checkers: vec![accepted], ..Default::default() }),
            ..base.policy.clone()
        };
        let sealed = compiler::seal_contributions_content(&base.artifact.intent, base.artifact.criteria.clone(),
            &base.artifact.calibration, &contribs, Some(&store)).unwrap();
        assert!(sealed.evidence_store.is_some());
        let result = policy.reduce(&sealed);
        let labels = sealed.contributions.iter().map(|c| (c.id.clone(), c.is_correct)).collect();
        let f = roundtrip(&ArtifactFile {
            format: artifact_format(&sealed, &policy).to_string(),
            topic: "tcp".into(), agents: 40, seed: 42,
            policy_hash: policy.policy_hash(),
            outputs: compiler::ReductionOutput::from_result(&result),
            artifact: sealed,
            policy,
            labels,
            envelope_hash: None,
        });
        assert_eq!(f.format, ARTIFACT_FORMAT_V4);
        assert_eq!(verify_artifact(&f).unwrap(), f.outputs);
    }
}

// ── Tests: CLI wrapper features (reduce parsing, --emit-artifact,
//    envelope hash, format errors, presets, --version) ──

#[cfg(test)]
mod cli_feature_tests {
    use super::*;

    const W: [f64; 5] = [0.35, 0.20, 0.25, 0.05, 0.15];
    const V4_DUMPS: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/../v2/evidence/replay-v4/dumps/aarch64-apple-darwin");

    fn roundtrip(f: &ArtifactFile) -> ArtifactFile {
        serde_json::from_str(&to_canonical_json(f)).unwrap()
    }

    fn v4() -> ArtifactFile { roundtrip(&build_artifact("tcp", 40, 42, W)) }

    /// A `--reduce` input reproducing a dump's sealed set.
    fn input_of(f: &ArtifactFile, with_ids: bool) -> serde_json::Value {
        let mut contribs = serde_json::to_value(&f.artifact.contributions).unwrap();
        if !with_ids {
            for c in contribs.as_array_mut().unwrap() { c.as_object_mut().unwrap().remove("id"); }
        }
        serde_json::json!({
            "intent": f.artifact.intent, "criteria": f.artifact.criteria, "calibration": f.artifact.calibration,
            "id_scheme": CONTRIBUTION_ID_SCHEME, "contributions": contribs,
        })
    }

    fn parse(v: &serde_json::Value) -> Result<ReduceInput, String> {
        parse_reduce_input(&v.to_string())
    }

    #[test]
    fn v4_dumps_unchanged_except_envelope() {
        // Root hash, policy hash, certificate and every other byte of the
        // committed `/4` dumps are reproduced; only `envelope_hash` is new.
        for t in ["australia", "pluto", "tides", "tcp", "nutrition"] {
            let fresh = build_artifact(t, 100, 42, W);
            assert!(fresh.envelope_hash.is_some(), "{t}");
            let committed = std::fs::read_to_string(format!("{V4_DUMPS}/{t}.json")).unwrap();
            let stripped = ArtifactFile { envelope_hash: None, ..fresh.clone() };
            assert_eq!(to_canonical_json(&stripped), committed, "{t}");
            let old: ArtifactFile = serde_json::from_str(&committed).unwrap();
            assert!(old.envelope_hash.is_none());
            assert!(verify_artifact(&old).is_ok(), "{t}: committed dump (no envelope) still verifies");
            assert!(matches!(verify_artifact_opts(&old, true), Err(ReplayError::Envelope { stored: None, .. })));
            assert!(verify_artifact_opts(&roundtrip(&fresh), true).is_ok(), "{t}");
        }
    }

    #[test]
    fn envelope_detects_metadata_edits() {
        let edits: Vec<(&str, Box<dyn Fn(&mut ArtifactFile)>)> = vec![
            ("topic", Box::new(|f| f.topic = "pluto".into())),
            ("agents", Box::new(|f| f.agents += 1)),
            ("seed", Box::new(|f| f.seed = 7)),
            ("label flip", Box::new(|f| { let v = f.labels.values_mut().next().unwrap(); *v = !*v; })),
            ("label dropped", Box::new(|f| { let k = f.labels.keys().next().unwrap().clone(); f.labels.remove(&k); })),
            ("agent_name", Box::new(|f| f.artifact.contributions[0].agent_name.push('x'))),
            ("timestamp", Box::new(|f| f.artifact.contributions[0].timestamp += 1.0)),
            ("is_correct", Box::new(|f| f.artifact.contributions[0].is_correct ^= true)),
            ("envelope_hash", Box::new(|f| f.envelope_hash = Some("0".repeat(32)))),
        ];
        for (name, m) in edits {
            let mut f = v4();
            m(&mut f);
            // Every unhashed edit leaves the sealed set, policy and outputs intact...
            assert_eq!(f.artifact.compute_root_hash(), f.artifact.root_hash, "{name}");
            match verify_artifact(&roundtrip(&f)) {
                Err(e @ ReplayError::Envelope { stored: Some(_), .. }) => assert_eq!(e.exit_code(), 6, "{name}"),
                other => panic!("{name}: expected Envelope error, got {:?}", other.map(|_| ())),
            }
        }
        // Sealed-set, policy and output errors keep their own codes on an
        // enveloped file (checked before the envelope).
        let mut f = v4();
        f.artifact.contributions[0].confidence += 0.01;
        assert_eq!(verify_artifact(&f).unwrap_err().exit_code(), 3);
        let mut f = v4();
        f.policy.deadband_threshold = 501;
        assert_eq!(verify_artifact(&f).unwrap_err().exit_code(), 4);
        let mut f = v4();
        f.outputs.admitted.pop();
        assert_eq!(verify_artifact(&f).unwrap_err().exit_code(), 1);
        // Stripping the envelope is accepted unless required.
        let mut f = v4();
        f.envelope_hash = None;
        assert!(verify_artifact(&f).is_ok());
        assert_eq!(verify_artifact_opts(&f, true).unwrap_err().exit_code(), 6);
    }

    #[test]
    fn legacy_dumps_carry_no_envelope() {
        assert!(build_artifact_ids("tcp", 40, 42, W, true).envelope_hash.is_none());
    }

    #[test]
    fn format_errors_have_own_code_and_messages() {
        let mut f = v4();
        f.format = ARTIFACT_FORMAT.into();
        let e = verify_artifact(&f).unwrap_err();
        assert_eq!(e.exit_code(), 5);
        assert_eq!(e.kind(), "format");
        assert_eq!(e.message(&f), "format tag bran-artifact/2 does not match content (expected bran-artifact/4)");
        f.format = "bran-artifact/1".into();
        let e = verify_artifact(&f).unwrap_err();
        assert_eq!(e.exit_code(), 5);
        assert!(e.message(&f).starts_with("unsupported format bran-artifact/1 (supported: bran-artifact/2, "));
        // Exit codes 1/3/4 keep their meanings; table is complete.
        let codes: Vec<i32> = EXIT_CODES.iter().map(|c| c.0).collect();
        assert_eq!(codes, vec![0, 1, 2, 3, 4, 5, 6]);
    }

    #[test]
    fn reduce_parse_errors_name_the_item() {
        let bad = serde_json::json!({"contributions": [{"id": "x", "agent_id": "a", "seq": 0, "kind": "ASSERTON",
            "canonical_form": null, "confidence": 0.5, "lowering_confidence": "HIGH"}]});
        let e = parse(&bad).err().unwrap();
        assert!(e.starts_with("contributions[0]: unknown variant `ASSERTON`"), "{e}");
        assert!(!e.contains("untagged"));
        let e = parse(&serde_json::json!([{"agent_id": "a"}])).err().unwrap();
        assert!(e.contains("contributions[0]: missing field") && e.contains("id_scheme"), "{e}");
        let e = parse(&serde_json::json!({"criteria": "x", "contributions": []})).err().unwrap();
        assert!(e.starts_with("field `criteria`"), "{e}");
        assert_eq!(parse(&serde_json::json!({"intent": "q"})).err().unwrap(), "missing field `contributions`");
        assert!(parse(&serde_json::json!(3)).is_err());
        assert!(parse_reduce_input("{").is_err());
    }

    #[test]
    fn reduce_ids_optional_with_id_scheme() {
        let f = v4();
        let with = parse(&input_of(&f, true)).unwrap();
        let without = parse(&input_of(&f, false)).unwrap();
        assert_eq!(with.contributions.iter().map(|c| &c.id).collect::<Vec<_>>(),
                   without.contributions.iter().map(|c| &c.id).collect::<Vec<_>>());
        // Without the scheme an id is still required.
        let mut legacy = input_of(&f, false);
        legacy.as_object_mut().unwrap().remove("id_scheme");
        assert!(parse(&legacy).is_err());
        // Labels only from explicit is_correct.
        assert_eq!(with.labels.len(), f.artifact.contributions.len());
        let mut v = input_of(&f, true);
        for c in v["contributions"].as_array_mut().unwrap() { c.as_object_mut().unwrap().remove("is_correct"); }
        assert!(parse(&v).unwrap().labels.is_empty());
    }

    #[test]
    fn emit_artifact_reproduces_the_compilers_seal() {
        let f = v4();
        let mut inp = input_of(&f, false);
        inp["topic"] = "tcp".into();
        let input = parse(&inp).unwrap();
        let policy = effective_policy(None, None, None).unwrap();
        let (v, art) = reduce_core(&input, policy, false, true).unwrap();
        let art = roundtrip(&art.unwrap());
        assert_eq!(art.format, ARTIFACT_FORMAT_V4);
        assert_eq!(to_canonical_json(&art.artifact), to_canonical_json(&f.artifact));
        assert_eq!(art.outputs, f.outputs);
        assert_eq!(art.policy_hash, f.policy_hash);
        assert_eq!(art.labels, f.labels);
        assert_eq!((art.topic.as_str(), art.seed), ("tcp", 0));
        assert_eq!(art.agents, f.artifact.calibration.len());
        assert_eq!(serde_json::to_value(&f.outputs).unwrap(), v);
        assert!(verify_artifact_opts(&art, true).is_ok());
        // P3 drops (SYNTHESIS) are filtered as the compiler does; outputs unchanged.
        let mut inp2 = inp.clone();
        let mut syn = inp2["contributions"][0].clone();
        syn["kind"] = "SYNTHESIS".into();
        syn["agent_id"] = "synth".into();
        inp2["contributions"].as_array_mut().unwrap().push(syn);
        let (v2, art2) = reduce_core(&parse(&inp2).unwrap(), OverturnCompiler::default(), false, true).unwrap();
        assert!(v2.get("p3_rejected").is_some());
        let art2 = art2.unwrap();
        assert_eq!(art2.outputs, f.outputs);
        assert!(art2.outputs.rejected == f.outputs.rejected && art2.labels == f.labels);
        // Legacy ids (no scheme) seal as /2.
        let mut legacy = input_of(&f, true);
        legacy.as_object_mut().unwrap().remove("id_scheme");
        let (_, a) = reduce_core(&parse(&legacy).unwrap(), OverturnCompiler::default(), false, true).unwrap();
        let a = roundtrip(&a.unwrap());
        assert_eq!(a.format, ARTIFACT_FORMAT);
        assert!(verify_artifact_opts(&a, true).is_ok());
        // Explain-rejected is opt-in and covers every rejected id.
        let (v3, _) = reduce_core(&input, OverturnCompiler::default(), true, false).unwrap();
        assert_eq!(v3["rejected_reasons"].as_array().unwrap().len(), f.outputs.rejected.len());
        let (v4o, _) = reduce_core(&input, OverturnCompiler::default(), false, false).unwrap();
        assert!(v4o.get("rejected_reasons").is_none());
    }

    #[test]
    fn weights_with_overlay_is_an_error() {
        let ov = serde_json::json!({"tiebreak_order": "id"});
        assert!(effective_policy(None, Some([0.4, 0.2, 0.2, 0.0, 0.2]), Some(ov.clone())).unwrap_err().contains("--weights"));
        let p = effective_policy(None, Some([0.4, 0.2, 0.2, 0.0, 0.2]), None).unwrap();
        assert_eq!(p.weights[0], 0.4);
        assert_eq!(effective_policy(None, None, None).unwrap().policy_hash(), "dd8d36e6def3a6d598765e82d461a473");
        // generic preset == overlay with no value groups.
        let g = effective_policy(Some("generic"), None, None).unwrap();
        let o = effective_policy(None, None, Some(serde_json::json!({"values": {"incompatible_values": {}}}))).unwrap();
        assert_eq!(g.policy_hash(), o.policy_hash());
        assert!(effective_policy(Some("nope"), None, None).is_err());
        let f = effective_policy(None, None, Some(serde_json::json!({"functional_predicates": ["capital_city"]}))).unwrap();
        assert_eq!(f.functional_predicates, vec!["capital_city".to_string()]);
    }

    #[test]
    fn version_reports_compatibility_ids() {
        let v = version_json();
        assert_eq!(v["version"], env!("CARGO_PKG_VERSION"));
        assert_eq!(v["artifact_formats"], serde_json::json!(["bran-artifact/2", "bran-artifact/3", "bran-artifact/4"]));
        assert_eq!(v["reducer_constants_id"], compiler::reducer_constants_id());
        assert_eq!(v["presets"]["default"], "dd8d36e6def3a6d598765e82d461a473");
        assert_eq!(v["exit_codes"]["5"].as_str().map(|s| s.starts_with("format")), Some(true));
    }
}
