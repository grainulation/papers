#!/usr/bin/env python3
"""
Deterministic, rule-based object canonicalizer for the real-agent eval (lane L10).

canon(object) -> canonical object string. Used IDENTICALLY before
  * Python conflict-set construction (evaluate_v1.detect_conflicts),
  * majority vote (evaluate_v2.majority_idx), and
  * the Rust reducer input (canonical_form.object in `bran --reduce`).

No ML, no network, no randomness, no locale dependence. CANON_VERSION identifies the
rule set; run_canon.py also records the sha256 of this file so a run can be sealed.

Consistency with Rust (bran/src/ir.rs normalize_object = collapse whitespace +
lowercase; compiler.rs value_key = lowercase; evaluate_v1 conflict key = lower+strip):
canon() output is already lowercase with single spaces and no leading/trailing
space, so all three keyings are the identity on it (tested in test_canon.py). The
Rust binary is NOT changed; canonicalization happens in the lowering step.

Rules, applied in this order (each is meant to be meaning-preserving):
  R1  unicode NFKC; curly quotes -> straight
  R2  markdown: strip `**`, `__`, `*`, backticks, leading list/heading markers
  R3  citation parentheticals: "(3)", "[3]", "(source: ...)", "(Name, 2018)", "(Name, n.d.)"
  R4  contractions: n't -> " not", it's -> "it is", 're/'ve/'ll, possessive 's dropped
      (negation is expanded, never dropped)
  R5  lowercase (acronyms ending in "s" that are not plurals -- https, cors, dns, aws,
      saas, ... -- are in SINGULAR_EXCEPTIONS; "ACKs"/"VMs" do singularize)
  R6  numbers: digit-group commas removed (299,792,458 -> 299792458); trailing decimal
      zeros removed (3.00 -> 3, 88.0 -> 88); number words zero..ninety-nine -> digits,
      also inside hyphen compounds (three-way -> 3-way)
  R7  units, only directly after a number: meters per second -> m/s, kilometers -> km,
      miles -> mi, degrees celsius / °C -> °c, percent -> %, ... (table UNITS)
  R8  approximation hedge before a number: approximately/about/around/roughly/circa/~ N -> N
      ("up to", "over", "more than", "nearly", "at least" are NOT hedges and are kept)
  R9  redundant parentheticals: "(X)" dropped when X equals the canonical text right
      before it ("m/s (m/s)", "299792 km/s (299792 km/s)") or X is the acronym of the
      words right before it ("astronomical unit (au)")
  R10 leading discourse adverb "also" dropped
  R11 punctuation -> space (keeps - / % ° + ^ = < > and decimal points)
  R12 "a"/"an" directly before a time/length unit word -> "1" ("a month" -> "1 month");
      then articles a/an/the dropped (except "a" after vitamin/type/hepatitis/...)
  R13 simple plural -> singular (suffix rules, explicit exception list, acronyms exempt)
  R14 synonym table SYNONYMS (each entry cites the item it came from)
  R15 empty result -> fall back to Rust normalize_object(raw)
"""

import re
import unicodedata

CANON_VERSION = "canon-1.0.0"

# ── tables ──────────────────────────────────────────────────────

# Explicit synonym table. ONLY entries observed in the v1orig / v3 contradiction sets.
# Applied to single tokens after singularization. Each maps to a form that keeps
# polarity explicit (never drops a negation).
SYNONYMS = {
    # v3 q23_goldfish_memory, ('the claim that goldfish have a 3-second memory', 'is'):
    #   'a myth' / 'a misconception' / 'a common myth'
    "misconception": ["myth"],
    # v3 q46_antibiotics_virus ('antibiotics','is'): 'not effective against these viruses'
    #   vs 'ineffective against viral infections'; v1orig q46: 'ineffective against viruses'.
    #   Rewritten to an explicit negation so polarity stays visible.
    "ineffective": ["not", "effective"],
}
SYNONYM_SOURCES = {
    "misconception": "v3 q23_goldfish_memory (the claim that goldfish have a 3-second memory, is): "
                     "'a myth' / 'a misconception' / 'a common myth'",
    "ineffective": "v3 q46_antibiotics_virus (antibiotics, is): 'not effective against these viruses' / "
                   "'ineffective against viral infections'; v1orig q46: 'ineffective against viruses'",
}

_UNITS_RAW = [
    # (aliases, canonical). Matched case-insensitively, longest alias first, only
    # directly after a number (optionally followed by thousand/million/billion/trillion).
    (["meters per second", "metres per second", "meter per second", "metre per second", "m/s"], "m/s"),
    (["kilometers per second", "kilometres per second", "kilometer per second",
      "kilometre per second", "km/s"], "km/s"),
    (["kilometers per hour", "kilometres per hour", "km/h", "kph"], "km/h"),
    (["miles per hour", "mph"], "mph"),
    (["square kilometers", "square kilometres", "square kilometer", "square kilometre", "sq km", "km2", "km²"], "km2"),
    (["square miles", "square mile", "sq mi", "mi2", "mi²"], "mi2"),
    (["kilometers", "kilometres", "kilometer", "kilometre", "km"], "km"),
    (["centimeters", "centimetres", "centimeter", "centimetre", "cm"], "cm"),
    (["millimeters", "millimetres", "millimeter", "millimetre", "mm"], "mm"),
    (["meters", "metres", "meter", "metre"], "m"),   # bare "m" not an alias ("$5m")
    (["miles", "mile", "mi"], "mi"),
    (["feet", "foot", "ft"], "ft"),
    (["inches", "inch"], "inch"),
    (["kilograms", "kilogram", "kg"], "kg"),
    (["grams", "gram"], "g"),                         # bare "g" not an alias ("5G")
    (["degrees celsius", "degree celsius", "degrees c", "°c", "° c", "ºc", "celsius"], "°c"),
    (["degrees fahrenheit", "degree fahrenheit", "degrees f", "°f", "° f", "ºf", "fahrenheit"], "°f"),
    (["kelvin", "kelvins"], "kelvin"),
    (["percent", "per cent", "%"], "%"),
]
UNITS = sorted(((a, c) for al, c in _UNITS_RAW for a in al), key=lambda x: -len(x[0]))

# R12: words after which "a"/"an" means exactly one. "second" is deliberately absent
# ("a second opinion" means "another").
ONE_UNIT_WORDS = {"minute", "minutes", "hour", "hours", "day", "days", "week", "weeks",
                  "month", "months", "year", "years", "decade", "decades", "century",
                  "mile", "kilometer", "kilometre", "meter", "metre", "foot", "inch"}
ARTICLES = {"a", "an", "the"}
ARTICLE_A_KEEP_AFTER = {"vitamin", "type", "hepatitis", "grade", "class", "group", "blood",
                        "plan", "category", "option", "exhibit", "appendix", "section"}

_ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
         "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
         "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
         "eighteen": 18, "nineteen": 19}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
         "seventy": 70, "eighty": 80, "ninety": 90}

# R13 exceptions: words ending in "s" that are not plurals (or whose singular would
# collide with a different word: https/http, sometimes/sometime, means/mean).
SINGULAR_EXCEPTIONS = {
    "this", "his", "its", "has", "was", "does", "is", "as", "us", "yes", "thus", "plus",
    "always", "perhaps", "sometimes", "towards", "afterwards", "besides", "whereas",
    "nowadays", "nevertheless", "news", "means", "series", "species", "physics",
    "mathematics", "genetics", "economics", "politics", "ethics", "statistics", "aerobics",
    "athletics", "linguistics", "electronics", "dynamics", "mechanics", "thermodynamics",
    "analysis", "basis", "crisis", "thesis", "hypothesis", "diagnosis", "synthesis",
    "status", "virus", "bonus", "campus", "census", "focus", "corpus", "consensus",
    "chaos", "gas", "bias", "alias", "atlas", "canvas", "lens", "aids", "diabetes",
    "herpes", "measles", "mumps", "rabies", "kudos", "https", "cors", "dns", "aws", "gps",
    "sms", "ios", "macos", "windows", "saas", "paas", "iaas", "ddos", "dos", "nas", "kubernetes", "postgres", "redis", "less", "unless",
    "across", "upstairs", "downstairs", "overseas", "whereabouts", "kelvins",
}

# Negation cues: canon() must preserve their total count (R4/R14 only ever add an
# explicit "not"; nothing removes one). Checked by test_canon.py.
NEGATION_TOKENS = {"not", "no", "never", "cannot", "none", "neither", "nor", "nothing",
                   "without", "ineffective"}

# ── helpers ─────────────────────────────────────────────────────


def rust_normalize_object(o):
    """bran/src/ir.rs normalize_object: split_whitespace().join(" ").to_lowercase()."""
    return " ".join(o.split()).lower()


_RE_CITATIONS = [
    re.compile(r"\(\s*\d{1,3}\s*\)"),
    re.compile(r"\[\s*\d{1,3}\s*\]"),
    re.compile(r"\(\s*(?:source|sources|ref|reference|see)\s*:[^()]*\)", re.I),
    re.compile(r"\(\s*[A-Z][^()]{0,80}?,\s*(?:(?:19|20)\d{2}[a-z]?|n\.d\.?)\s*\)"),
    re.compile(r"\(\s*n\.d\.?\s*\)", re.I),
]

_NUM = r"-?\d+(?:\.\d+)?(?:\s+(?:thousand|million|billion|trillion))?"
_UNIT_ALT = "|".join(re.escape(a) for a, _ in UNITS)
_RE_UNIT = re.compile(r"(?<![\w.])(" + _NUM + r")\s*(" + _UNIT_ALT + r")(?![\w/²])")
_UNIT_MAP = {a: c for a, c in UNITS}
_RE_HEDGE = re.compile(r"(?<![\w-])(?:approximately|approx\.?|about|around|roughly|circa|ca\.)\s+(?=-?\d)")
_RE_TILDE = re.compile(r"~\s*(?=-?\d)")


def _numwords(s):
    tens = "|".join(_TENS)
    ones = "|".join(k for k in _ONES)
    ones1 = "|".join(k for k, v in _ONES.items() if 1 <= v <= 9)

    def comp(m):
        return str(_TENS[m.group(1)] + _ONES[m.group(2)])
    s = re.sub(r"\b(" + tens + r")[- ](" + ones1 + r")\b", comp, s)
    s = re.sub(r"\b(" + tens + r")\b", lambda m: str(_TENS[m.group(1)]), s)
    s = re.sub(r"\b(" + ones + r")\b", lambda m: str(_ONES[m.group(1)]), s)
    return s


def _decimals(s):
    def fix(m):
        i, f = m.group(1), m.group(2).rstrip("0")
        return i + ("." + f if f else "")
    return re.sub(r"(?<![\d.])(\d+)\.(\d+)(?![\d.])", fix, s)


def _units(s):
    def rep(m):
        return m.group(1) + " " + _UNIT_MAP[m.group(2)]
    return _RE_UNIT.sub(rep, s)


def _paren_tokens(t):
    return re.findall(r"[^\s()]+", t)


def _drop_redundant_parens(s):
    """R9: drop '(X)' when X repeats the canonical text right before it, or X is the
    acronym of the preceding words. Innermost, balanced, non-nested parens only."""
    out, pos = [], 0
    for m in re.finditer(r"\(([^()]*)\)", s):
        before = s[:m.start()]
        inner = _paren_tokens(m.group(1).strip().strip(",;:"))
        prev = _paren_tokens(before)
        drop = False
        if inner and len(inner) <= len(prev) and prev[-len(inner):] == inner:
            drop = True
        elif len(inner) == 1 and re.fullmatch(r"[a-z]{2,6}", inner[0]):
            a = inner[0]
            for cand in (a, a[:-1] if a.endswith("s") and len(a) > 2 else None):
                if not cand:
                    continue
                words = [w for w in prev if re.match(r"[a-z]", w)]
                k = len(cand)
                if len(words) >= k and "".join(w[0] for w in words[-k:]) == cand:
                    drop = True
                    break
        if drop:
            out.append(s[pos:m.start()])
            pos = m.end()
    out.append(s[pos:])
    return "".join(out)


def _singular(tok):
    if tok in SINGULAR_EXCEPTIONS:
        return tok
    if not re.fullmatch(r"[a-z]+", tok) or len(tok) < 4:
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("sses"):
        return tok[:-2]
    if re.search(r"(?:ch|sh|x|z)es$", tok):
        return tok[:-2]
    if tok.endswith("s") and not re.search(r"(?:ss|us|is|os)$", tok):
        return tok[:-1]
    return tok


# ── main entry point ────────────────────────────────────────────

def canon(raw):
    if raw is None:
        return ""
    s = unicodedata.normalize("NFKC", str(raw))
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    # R2 markdown
    s = re.sub(r"^\s*(?:[-*+•]|#{1,6}|\d+[.)])\s+", "", s)
    s = s.replace("**", "").replace("__", "").replace("`", "").replace("*", "")
    # R3 citations (before lowercasing: author-year needs a capital)
    for rx in _RE_CITATIONS:
        s = rx.sub(" ", s)
    # R4 contractions / possessives
    s = re.sub(r"\b(can|won)'t\b", lambda m: {"can": "can not", "won": "will not"}[m.group(1).lower()], s, flags=re.I)
    s = re.sub(r"n't\b", " not", s, flags=re.I)
    s = re.sub(r"\b(it|that|there|what|here)'s\b", r"\1 is", s, flags=re.I)
    s = re.sub(r"'re\b", " are", s)
    s = re.sub(r"'ve\b", " have", s)
    s = re.sub(r"'ll\b", " will", s)
    s = re.sub(r"(?<=\w)'s\b", "", s)
    s = re.sub(r"(?<=s)'(?=\s|$)", "", s)
    # R5 lowercase. (Acronyms that end in "s" but are not plurals -- https, cors, dns,
    # aws, ... -- are listed in SINGULAR_EXCEPTIONS; protection is lowercase-only so
    # that canon() is idempotent.)
    s = s.lower()
    # R6 numbers
    s = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", s)
    s = _decimals(s)
    s = _numwords(s)
    # R7 units, R8 hedges
    s = _units(s)
    s = _RE_HEDGE.sub("", s)
    s = _RE_TILDE.sub("", s)
    s = " ".join(s.split())
    # R9 redundant parentheticals
    s = _drop_redundant_parens(s)
    # R10 leading "also"
    s = re.sub(r"^\s*also\s+", "", s)
    # R11 punctuation
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    s = re.sub(r"[()\[\]{},;:!?\"'|…]", " ", s)
    toks = []
    for t in s.split():
        t = t.rstrip("-") if re.match(r"-\d", t) else t.strip("-")   # keep a minus sign
        if t:
            toks.append(t)
    # R12 a/an + unit -> 1; articles dropped
    out = []
    for i, t in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        prv = toks[i - 1] if i > 0 else ""
        if t in ("a", "an") and nxt in ONE_UNIT_WORDS:
            out.append("1")
        elif t in ARTICLES and not (t == "a" and prv in ARTICLE_A_KEEP_AFTER):
            continue
        else:
            out.append(t)
    # R13 singular, R14 synonyms
    final = []
    for t in out:
        t = _singular(t)
        final.extend(SYNONYMS.get(t, [t]))
    res = " ".join(final)
    # R15 fallback
    return res if res else rust_normalize_object(str(raw))


def negation_count(text):
    toks = re.findall(r"[a-z]+", re.sub(r"n't\b", " not", unicodedata.normalize("NFKC", str(text)).lower()
                                        .replace("’", "'")))
    return sum(t in NEGATION_TOKENS for t in toks)


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:] or sys.stdin.read().splitlines():
        print(f"{line!r} -> {canon(line)!r}")
