#!/usr/bin/env python3
"""
Bran Real-Agent Collection Harness

Sends questions to multiple Ollama models, collects raw responses,
then structures them as Bran-compatible claim sets via simple extraction.

Usage:
    python3 collect.py                    # collect all questions, all models
    python3 collect.py --questions q01    # specific question(s)
    python3 collect.py --models llama3.2:3b mistral  # specific models
    python3 collect.py --skip-existing    # skip already-collected responses
"""

import json
import sys
import time
import hashlib
import re
import argparse
import urllib.request
import urllib.error
from pathlib import Path

# ── Configuration ──

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODELS = ["llama3.2:3b", "mistral", "gemma2:2b", "phi3:mini", "qwen2.5:3b"]
RESULTS_DIR = Path(__file__).parent / "results"

# System prompt that encourages structured factual responses
SYSTEM_PROMPT = """You are a knowledgeable assistant. Answer the question with specific factual claims.
For each major point, cite a source if you know one (e.g., a study, organization, or standard).
Be concise but thorough. State your confidence level (high/medium/low) for claims where you are uncertain."""


def ollama_generate(model: str, prompt: str, timeout: int = 120) -> str:
    """Call Ollama API and return the full response text."""
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 1024,
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "")
    except urllib.error.URLError as e:
        print(f"    ERROR: Ollama connection failed: {e}")
        return ""
    except Exception as e:
        print(f"    ERROR: {e}")
        return ""


# ── Lightweight claim extraction ──
# This extracts (subject, predicate, object) triples from raw LLM text
# using simple heuristics. The Bran pipeline's real lowering handles
# the heavy lifting; this just structures the raw output enough.

def extract_claims_from_text(text: str, model_name: str) -> list:
    """Extract structured claims from raw LLM response text.

    Uses sentence-level heuristic extraction similar to Bran's P2 lowering.
    Returns list of claim dicts compatible with evaluate.py.
    """
    claims = []
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 10 or len(sent) > 800:
            continue
        # Skip truncated/incomplete sentences (ending with dangling article/preposition)
        if re.search(r'\b(a|an|the|of|to|in|by|for|with|from)\s*$', sent.strip()):
            continue

        # Skip filler/meta sentences
        if re.match(r'^(here|let me|i\'ll|sure|okay|well|so,|in summary)', sent, re.I):
            continue

        # Detect hedge level
        confidence = "HIGH"
        evidence_type = "REASONING"
        evidence_items = []

        hedge_strong = r'\b(might|may|could|possibly|perhaps|arguably|uncertain|debat)\b'
        hedge_moderate = r'\b(generally|typically|often|usually|tends? to|likely)\b'
        if re.search(hedge_strong, sent, re.I):
            confidence = "LOW"
        elif re.search(hedge_moderate, sent, re.I):
            confidence = "MEDIUM"

        # Detect evidence markers
        if re.search(r'(according to|study|research|found that)', sent, re.I):
            evidence_type = "EMPIRICAL"
            evidence_items.append({
                "type": "EMPIRICAL",
                "weight": 0.8,
                "text": sent[:100]
            })
        if re.search(r'(RFC\s*\d+|\d{4}\)|et al\.|[A-Z]\w+ \d{4})', sent):
            evidence_type = "CITATION"
            evidence_items.append({
                "type": "CITATION",
                "weight": 0.85,
                "text": sent[:100]
            })
        if re.search(r'(WHO|CDC|FDA|NASA|IEEE|IETF|NIH|EPA)', sent):
            evidence_items.append({
                "type": "AUTHORITY",
                "weight": 0.7,
                "text": sent[:100]
            })
        if not evidence_items:
            evidence_items.append({
                "type": "REASONING",
                "weight": 0.5,
                "text": sent[:100]
            })

        # Extract triple via pattern matching
        triple = extract_triple(sent)
        if triple:
            subj, pred, obj = triple
            claims.append({
                "subject": subj,
                "predicate": pred,
                "object": obj,
                "confidence": {"HIGH": 0.85, "MEDIUM": 0.65, "LOW": 0.45}[confidence],
                "lowering_confidence": confidence,
                "evidence": evidence_items,
                "constraint_alignment": 1.0,
                "raw_sentence": sent[:200],
            })

    return claims


def extract_triple(sentence: str) -> tuple | None:
    """Extract (subject, predicate, object) from a single sentence.

    Uses the most reliable subset of Bran's 34 extraction rules.
    """
    sent = sentence.strip().rstrip('.')

    # Rule: "X is/are Y"
    m = re.match(r'^(.+?)\s+(is|are|was|were)\s+(an?\s+)?(.+)$', sent, re.I)
    if m:
        subj = m.group(1).strip()
        pred = "is"
        obj = (m.group(3) or "") + m.group(4).strip()
        if len(subj) < 80 and len(obj) < 150:
            return (subj, pred, obj.strip())

    # Rule: "X verb Y" for common technical predicates
    patterns = [
        (r'^(.+?)\s+(uses?|provides?|requires?|supports?|implements?|enables?)\s+(.+)$', None),
        (r'^(.+?)\s+(can cause|causes?|leads? to|results? in)\s+(.+)$', None),
        (r'^(.+?)\s+(has|have|had)\s+(.+)$', None),
        (r'^(.+?)\s+(should be|must be|needs? to be)\s+(.+)$', None),
        (r'^(.+?)\s+(works? by|functions? by|operates? via)\s+(.+)$', None),
        (r'^(.+?)\s+(translates?|converts?|transforms?)\s+(.+)$', None),
        (r'^(.+?)\s+(does not|doesn\'t|cannot|can\'t)\s+(.+)$', "negation"),
        (r'^(.+?)\s+(prevents?|reduces?|increases?|improves?)\s+(.+)$', None),
        (r'^(.+?)\s+(excels? at|is better (?:for|at)|advantage)\s+(.+)$', None),
    ]
    for pat, tag in patterns:
        m = re.match(pat, sent, re.I)
        if m:
            subj = m.group(1).strip()
            pred = m.group(2).strip().lower()
            obj = m.group(3).strip()
            if len(subj) < 80 and len(obj) < 150:
                return (subj, pred, obj)

    # Rule: passive "Y is/are verb-ed by X"
    m = re.match(r'^(.+?)\s+(?:is|are|was|were)\s+(\w+ed)\s+by\s+(.+)$', sent, re.I)
    if m:
        obj_text = m.group(1).strip()
        pred = m.group(2).strip().lower()
        subj = m.group(3).strip()
        if len(subj) < 80 and len(obj_text) < 150:
            return (subj, pred, obj_text)

    return None


def collect_responses(questions: list, models: list, skip_existing: bool = False):
    """Query each model for each question and save structured results."""
    RESULTS_DIR.mkdir(exist_ok=True)
    total = len(questions) * len(models)
    done = 0

    for q in questions:
        qid = q["id"]
        out_file = RESULTS_DIR / f"{qid}.json"

        # Load existing or start fresh
        existing = []
        existing_agents = set()
        if out_file.exists():
            with open(out_file) as f:
                existing = json.load(f)
                existing_agents = {r.get("agent") for r in existing}

        responses = list(existing)

        for model in models:
            done += 1
            agent_name = model.replace(":", "_")

            if skip_existing and agent_name in existing_agents:
                print(f"  [{done}/{total}] SKIP {qid} / {model} (exists)")
                continue

            print(f"  [{done}/{total}] {qid} / {model} ...", end=" ", flush=True)
            t0 = time.time()
            raw = ollama_generate(model, q["question"])
            elapsed = time.time() - t0

            if not raw:
                print(f"EMPTY ({elapsed:.1f}s)")
                continue

            claims = extract_claims_from_text(raw, model)
            print(f"{len(claims)} claims ({elapsed:.1f}s)")

            # Remove old response from same agent if re-running
            responses = [r for r in responses if r.get("agent") != agent_name]

            responses.append({
                "agent": agent_name,
                "model": model,
                "raw_response": raw,
                "claims": claims,
                "calibration": 0.7,
                "response_time_s": round(elapsed, 2),
            })

        with open(out_file, "w") as f:
            json.dump(responses, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Collect LLM responses for Bran eval")
    parser.add_argument("--questions", nargs="*", help="Question IDs to collect (default: all)")
    parser.add_argument("--models", nargs="*", help="Ollama model names (default: all 5)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip already-collected")
    parser.add_argument("--list-models", action="store_true", help="List available Ollama models")
    args = parser.parse_args()

    if args.list_models:
        import subprocess
        subprocess.run(["ollama", "list"])
        return

    questions_file = Path(__file__).parent / "questions.json"
    with open(questions_file) as f:
        questions = json.load(f)

    if args.questions:
        questions = [q for q in questions if q["id"] in args.questions]
        if not questions:
            print("No matching questions found")
            sys.exit(1)

    models = args.models or DEFAULT_MODELS

    # Verify Ollama is running
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5)
    except Exception:
        print("ERROR: Ollama not running. Start with: ollama serve")
        sys.exit(1)

    # Verify models are available
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=5) as resp:
            available = {m["name"] for m in json.loads(resp.read()).get("models", [])}
    except Exception:
        available = set()

    missing = [m for m in models if m not in available and f"{m}:latest" not in available]
    if missing:
        print(f"Missing models: {missing}")
        print("Pull them with: ollama pull <model>")
        for m in missing:
            print(f"  ollama pull {m}")
        sys.exit(1)

    print(f"Collecting {len(questions)} questions × {len(models)} models = {len(questions)*len(models)} calls")
    print(f"Models: {models}")
    print()

    t0 = time.time()
    collect_responses(questions, models, args.skip_existing)
    elapsed = time.time() - t0

    print(f"\nDone in {elapsed:.0f}s")
    print(f"Results in: {RESULTS_DIR}")


if __name__ == "__main__":
    main()
