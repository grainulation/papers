#!/usr/bin/env python3
"""Support propositions for eval v5 (v3/SWARM3_DESIGN.md §3.4, lane L5).

The support checker labels (proposition, passage) pairs. This module turns
(item, proposed value) into the proposition the checker sees, and maps the
checker's label on that proposition back to a label for the value:

| source            | proposition for value v                         | label mapping                         |
|-------------------|-------------------------------------------------|---------------------------------------|
| fever, scifact    | the item claim C                                | SUPPORTED: identity                   |
|                   |                                                 | REFUTED: supports <-> refutes swapped |
| truthfulqa (MC)   | "Q: <question> A: <option text of v>"           | identity                              |
| popqa             | relation template with subject and v            | identity                              |

Properties (tested in tests/test_propositions.py):

  * Gold-blind. The renderer reads only `id`, `source.key`, `question` /
    `claim`, option letters and texts, and (PopQA) `source.prop` and
    `source.subj`. It never reads `gold`, `gold_triples`, `options[].correct`,
    `source.label`, `context` or `contested_rationale`. Changing any of those
    leaves every output byte unchanged.
  * Headcount-blind. A proposition depends on (item, value) only; nothing
    about other answers, votes or agents enters it.
  * Binary items share one check. SUPPORTED and REFUTED render the same text,
    so de-duplication by (proposition_key, passage_key) issues one check per
    passage and both sides read it through their own label map.
  * Deterministic. Text is NFC-normalized and whitespace-collapsed; keys are
    `sha256_hex16` over canonical JSON (tools/evidence/canonical.py), so the
    same inputs give the same keys in any process.

How the proposition reaches the checker: the v5 lowering sets each answer
contribution's `raw_text` to `Proposition.text`. `check.claim_text()` uses
`raw_text` when present, and the Rust seal requires the support record's
`claim` to equal (canonical_form, raw_text) of the contribution, so the text
the checker judged is sealed with the record. The sealed `label` is the
*mapped* label (the label for the contribution's value); the raw checker label
stays recoverable from the check cache via `raw_output_sha256`.

Stdlib only. Run with `python3 -I`.
"""

import os
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # tools/evidence
from canonical import canonical_bytes, sha256_hex16  # noqa: E402

FORMAT = "bran-proposition/1"
RENDERER_VERSION = "1.0.0"
LABELS = ("supports", "refutes", "not_enough_info")
IDENTITY = "identity"
SWAP = "swap_supports_refutes"
LABEL_MAPS = {
    IDENTITY: {"supports": "supports", "refutes": "refutes", "not_enough_info": "not_enough_info"},
    SWAP: {"supports": "refutes", "refutes": "supports", "not_enough_info": "not_enough_info"},
}
BINARY_SOURCES = ("fever", "scifact")
BINARY_VALUES = ("SUPPORTED", "REFUTED")
MAX_ENTITY_CHARS = 60  # §3.3: PopQA answers are strings of at most 60 characters

# PopQA relation templates (declarative forms of the 16 PopQA relations;
# `{s}` = subject, `{v}` = proposed value). Versioned with RENDERER_VERSION.
POPQA_TEMPLATES = {
    "occupation": "The occupation of {s} is {v}.",
    "place of birth": "{s} was born in {v}.",
    "genre": "The genre of {s} is {v}.",
    "father": "The father of {s} is {v}.",
    "mother": "The mother of {s} is {v}.",
    "country": "{s} is in the country {v}.",
    "producer": "The producer of {s} is {v}.",
    "director": "The director of {s} is {v}.",
    "capital of": "{s} is the capital of {v}.",
    "capital": "The capital of {s} is {v}.",
    "screenwriter": "The screenwriter of {s} is {v}.",
    "composer": "The composer of {s} is {v}.",
    "color": "The color of {s} is {v}.",
    "religion": "The religion of {s} is {v}.",
    "sport": "The sport of {s} is {v}.",
    "author": "The author of {s} is {v}.",
}


class PropositionError(ValueError):
    pass


def clean(s):
    """NFC, control characters dropped, whitespace collapsed, trimmed."""
    s = unicodedata.normalize("NFC", str(s))
    s = "".join(ch if unicodedata.category(ch) != "Cc" else " " for ch in s)
    return " ".join(s.split())


def clean_value(v):
    """Surface form of a free-text value inside a sentence: cleaned, one
    trailing period removed when it is the only one (the template adds its own;
    "U.S." and "St. Louis." keep theirs)."""
    v = clean(v)
    return v[:-1].rstrip() if v.endswith(".") and v.count(".") == 1 else v


def source_key(item):
    return item["source"]["key"]


def item_claim(item):
    """FEVER / SciFact claim C (v5 items carry `claim`; v4 items keep it in `question`)."""
    c = item.get("claim") or item.get("question")
    if not c:
        raise PropositionError(f"{item.get('id')}: binary item without a claim")
    return clean(c)


def option_text(item, letter):
    for o in item.get("options") or []:
        if o.get("letter") == letter:
            return clean(o["text"])
    raise PropositionError(f"{item.get('id')}: no option {letter!r}")


def popqa_subject(item):
    s = item["source"].get("subj")
    if not s:
        raise PropositionError(f"{item.get('id')}: PopQA item without source.subj (L4 must carry the PopQA `subj`)")
    return clean(s)


def proposition_key(text):
    return sha256_hex16(canonical_bytes({"format": FORMAT, "text": text}))


def check_key(prop_key, passage_key):
    """De-duplication key for one (proposition, passage) check."""
    return sha256_hex16(canonical_bytes({"proposition_key": prop_key, "passage_key": passage_key}))


def render(item, value):
    """Proposition for `value` on `item`.

    value: the answer as the agent gave it in the `answer` field: an option
    letter (TruthfulQA), SUPPORTED / REFUTED (FEVER, SciFact), or the free-text
    entity (PopQA; the surface string, not canon(), because canon lowercases and
    strips words).

    Returns a dict: {format, renderer_version, item_id, source, value, text,
    label_map, proposition_key}."""
    src = source_key(item)
    if src in BINARY_SOURCES:
        if value not in BINARY_VALUES:
            raise PropositionError(f"{item.get('id')}: binary value {value!r} not in {BINARY_VALUES}")
        text = item_claim(item)
        lmap = IDENTITY if value == "SUPPORTED" else SWAP
        v = value
    elif src == "truthfulqa":
        v = str(value).strip().upper()
        text = f"Q: {clean(item['question'])} A: {option_text(item, v)}"
        lmap = IDENTITY
    elif src == "popqa":
        prop = item["source"].get("prop")
        if prop not in POPQA_TEMPLATES:
            raise PropositionError(f"{item.get('id')}: no template for PopQA relation {prop!r}")
        v = clean_value(value)
        if not v:
            raise PropositionError(f"{item.get('id')}: empty PopQA value")
        if len(v) > MAX_ENTITY_CHARS:
            raise PropositionError(f"{item.get('id')}: PopQA value longer than {MAX_ENTITY_CHARS} chars")
        text = POPQA_TEMPLATES[prop].format(s=popqa_subject(item), v=v)
        lmap = IDENTITY
    else:
        raise PropositionError(f"{item.get('id')}: unknown source {src!r}")
    return {"format": FORMAT, "renderer_version": RENDERER_VERSION, "item_id": item["id"], "source": src,
            "value": v, "text": text, "label_map": lmap, "proposition_key": proposition_key(text)}


def map_label(raw_label, label_map):
    """Checker label on the proposition -> label for the value. None stays None
    (a non-ok check has no label)."""
    if raw_label is None:
        return None
    if raw_label not in LABELS:
        raise PropositionError(f"unknown label {raw_label!r}")
    return LABEL_MAPS[label_map][raw_label]


def check_requests(item, values_with_passages):
    """De-duplicated check list for one item.

    values_with_passages: iterable of (value, passage_key) pairs (e.g. every
    citation of every parsed answer). Returns a list of {check_key,
    proposition_key, proposition_text, passage_key} sorted by check_key, one
    per distinct (proposition, passage)."""
    out = {}
    for value, pk in values_with_passages:
        p = render(item, value)
        k = check_key(p["proposition_key"], pk)
        out.setdefault(k, {"check_key": k, "proposition_key": p["proposition_key"],
                           "proposition_text": p["text"], "passage_key": pk})
    return [out[k] for k in sorted(out)]


def renderer_identity():
    """Hashable identity for the run manifest (the templates are part of it)."""
    return {"format": FORMAT, "renderer_version": RENDERER_VERSION,
            "templates_sha16": sha256_hex16(canonical_bytes(POPQA_TEMPLATES)),
            "label_maps_sha16": sha256_hex16(canonical_bytes(LABEL_MAPS))}


if __name__ == "__main__":
    import json
    print(json.dumps(renderer_identity(), indent=1, sort_keys=True))
