#!/usr/bin/env python3
"""Eval-v4 answer-line parser and answer-key grader (lane L3; preregistered grader G-AK).

Two strictly separated steps:

  parse_answer(item, response_text) -> canonical object (str) or None      GOLD-BLIND
      Used to build the reducer's input triple (v4-<id>, answer, <object>) and the
      majority-vote input. Never reads item["gold"].

  grade(item, obj) -> bool                                                   uses gold
      Used only for scoring selections.

Formats
  letter             final ANSWER line -> option letter (A..), or the letter of the option whose
                     canonical text equals the line; else None.
  supported_refuted  -> "SUPPORTED" | "REFUTED" by keyword sets; both or neither -> None.
  entity             -> canon(line) with L10's canonicalizer (real-agent-eval/v4/canon/canon.py),
                     loaded read-only by path; CANON_VERSION and the file sha256 are reported by
                     canon_provenance().

Entity grading (primary, borrowed from PopQA, Mallen et al. 2023): correct iff some gold alias,
lowercased, occurs in the lowercased ANSWER line on word boundaries. Secondary: exact match of
canon(answer) with canon(alias).

Self-test:  python3 -I answer_key.py --selftest
"""
import hashlib
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CANON_PATH = os.path.normpath(os.path.join(HERE, "..", "..", "canon", "canon.py"))
_canon_mod = None


def _canon():
    global _canon_mod
    if _canon_mod is None:
        spec = importlib.util.spec_from_file_location("v4_canon", CANON_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _canon_mod = mod
    return _canon_mod


def canon_provenance():
    with open(CANON_PATH, "rb") as f:
        sha = hashlib.sha256(f.read()).hexdigest()
    return {"path": CANON_PATH, "sha256": sha, "CANON_VERSION": getattr(_canon(), "CANON_VERSION", None)}


ANSWER_RE = re.compile(r"^[\s>*_#-]*answer[\s*_]*[:：]\s*(.*?)\s*$", re.IGNORECASE)


def answer_line(text):
    """Content of the LAST line that starts with 'ANSWER:' (markdown decoration tolerated)."""
    if not text:
        return None
    hit = None
    for line in text.splitlines():
        m = ANSWER_RE.match(line)
        if m:
            hit = m.group(1).strip().strip("*_`").strip()
    return hit if hit else None


SUP = {"supported", "supports", "support", "true"}
REF = {"refuted", "refutes", "refute", "contradicted", "contradicts", "contradict", "false"}


def parse_answer(item, text):
    line = answer_line(text)
    if line is None:
        return None
    fmt = item["answer_format"]
    if fmt == "letter":
        letters = [o["letter"] for o in item["options"]]
        m = re.match(r"^\(?([A-Pa-p])\)?(?:[.):\s]|$)", line)
        if m and m.group(1).upper() in letters:
            return m.group(1).upper()
        c = _canon().canon
        cl = c(line)
        for o in item["options"]:
            if c(o["text"]) == cl:
                return o["letter"]
        return None
    if fmt == "supported_refuted":
        toks = set(re.findall(r"[a-z]+", line.lower()))
        s, r = bool(toks & SUP), bool(toks & REF)
        if s == r:
            return None
        return "SUPPORTED" if s else "REFUTED"
    if fmt == "entity":
        o = _canon().canon(line)
        return o or None
    raise ValueError(fmt)


def grade(item, obj, raw_line=None, mode="primary"):
    """obj = parse_answer output; raw_line = answer_line(text) (needed for entity primary)."""
    if obj is None:
        return False
    fmt = item["answer_format"]
    if fmt in ("letter", "supported_refuted"):
        return obj == item["gold"]["answer"]
    if fmt == "entity":
        if mode == "primary":
            hay = (raw_line if raw_line is not None else obj).lower()
            for a in item["gold"]["aliases"]:
                a = a.lower().strip()
                if a and re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", hay):
                    return True
            return False
        c = _canon().canon
        return any(c(a) == obj for a in item["gold"]["aliases"])
    raise ValueError(fmt)


def _selftest():
    mc = {"answer_format": "letter", "gold": {"answer": "B"},
          "options": [{"letter": "A", "text": "You die"}, {"letter": "B", "text": "Nothing happens"}]}
    assert parse_answer(mc, "blah\nANSWER: B") == "B"
    assert parse_answer(mc, "**ANSWER:** (b)") == "B"
    assert parse_answer(mc, "ANSWER: Nothing happens.") == "B"
    assert parse_answer(mc, "ANSWER: C") is None
    assert parse_answer(mc, "no answer line") is None
    assert parse_answer(mc, "ANSWER: A\nmore\nANSWER: B") == "B"          # last line wins
    sr = {"answer_format": "supported_refuted", "gold": {"answer": "REFUTED"}}
    assert parse_answer(sr, "ANSWER: REFUTED") == "REFUTED"
    assert parse_answer(sr, "Answer: Supported") == "SUPPORTED"
    assert parse_answer(sr, "ANSWER: SUPPORTED or REFUTED") is None
    assert grade(sr, "REFUTED") and not grade(sr, "SUPPORTED")
    ent = {"answer_format": "entity", "gold": {"answer": "Prague", "aliases": ["Prague", "Praha"]}}
    t = "ANSWER: Prague, Czech Republic"
    o = parse_answer(ent, t)
    assert o and grade(ent, o, answer_line(t))
    assert not grade(ent, parse_answer(ent, "ANSWER: Pragueville"), "Pragueville")
    assert not grade(ent, o, answer_line(t), mode="secondary")             # exact canon is stricter
    assert grade(ent, parse_answer(ent, "ANSWER: **Prague**"), "Prague", mode="secondary")
    print("answer_key selftest ok", canon_provenance())


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
