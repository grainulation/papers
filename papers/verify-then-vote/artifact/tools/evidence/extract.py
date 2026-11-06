#!/usr/bin/env python3
"""Pull evidence identifiers out of raw agent responses.

Spec: v2/evidence-verification-spec.md §3.6, §5.3, §6 L4b acceptance 5.

The v1-v3 harness found source lines next to a claim and then threw the
identifier away (`real-agent-eval/evaluate_v1.py:172` writes
"context-associated"). This module keeps, for every identifier occurrence:

  kind        url | doi | arxiv | rfc | pmid | isbn
  requested   sanitized identifier in a per-kind normal form (see _normalize)
  raw         the exact matched text
  request_url fetch URL per spec §1.1 (None for isbn: not fetched in v1)
  start, end  character offsets into the raw response
  sentence    the segment that contains it
  supports    the assertion it supports: the containing segment if that is
              an assertion, else the nearest preceding assertion segment

and, per claim, the identifiers in the claim sentence plus those in the
source lines that follow it (`identifiers_for_claim`).

Stdlib only. Usage:
  python3 -I tools/evidence/extract.py ids --raw-dir real-agent-eval/v3/results/raw --out ids.jsonl
  python3 -I tools/evidence/extract.py measure --raw-dir real-agent-eval/v3/results/raw \
      --results-dir real-agent-eval/v3/results [--json out.json]
"""

import argparse
import glob
import json
import os
import re
import statistics
import sys
import unicodedata
import urllib.parse

EXTRACT_VERSION = "bran-extract/1"
MAX_IDENTIFIER_CHARS = 2048

# ── identifier patterns ──

_URL = re.compile(r"(?:https?://|(?<![\w@/.])www\.)[^\s<>\"'`|\\^{}]+", re.I)
_DOI = re.compile(r"(?<![\w/.])(?:doi:\s*)?(10\.\d{4,9}/[^\s\"<>]+)", re.I)
_ARXIV = re.compile(
    r"\barXiv\s*:?\s*(\d{4}\.\d{4,5}(?:v\d+)?|[a-z][a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)", re.I
)
_RFC = re.compile(r"\bRFC[\s\-]?(\d{1,5})\b")
_PMID = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b")
_ISBN = re.compile(r"\bISBN(?:-1[03])?\s*:?\s*((?:97[89][\s\-]?)?(?:\d[\s\-]?){9}[\dXx])(?![\dXx])")

_TRAIL = ".,;:!?'\"*_>"  # spec §5.3 plus markdown emphasis
_PAIRS = {")": "(", "]": "[", "}": "{"}
_CTRL = re.compile(r"[\x00-\x20\x7f-\x9f]")


def _trim(s):
    """Strip trailing punctuation and unbalanced closing brackets (spec §5.3)."""
    while s:
        c = s[-1]
        if c in _TRAIL:
            s = s[:-1]
        elif c in _PAIRS and s.count(_PAIRS[c]) < s.count(c):
            s = s[:-1]
        else:
            break
    return s


def _valid(s):
    return bool(s) and len(s) <= MAX_IDENTIFIER_CHARS and not _CTRL.search(s)


def _url_kind(url):
    """Reclassify resolver URLs so `doi:X` and `https://doi.org/X` share a record."""
    p = urllib.parse.urlsplit(url if "://" in url else "https://" + url)
    host = (p.hostname or "").lower()
    path = urllib.parse.unquote(p.path)
    if host in ("doi.org", "dx.doi.org", "www.doi.org") and re.match(r"^/10\.\d{4,9}/.+", path):
        return "doi", path[1:]
    if host in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
        m = re.match(r"^/(?:abs|pdf)/(.+?)(?:\.pdf)?$", path)
        if m and re.match(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z][a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$", m.group(1), re.I):
            return "arxiv", m.group(1)
    if host in ("pubmed.ncbi.nlm.nih.gov",):
        m = re.match(r"^/(\d{1,9})$", path.rstrip("/"))
        if m:
            return "pmid", m.group(1)
    return "url", url


def _normalize(kind, value):
    if kind == "doi":
        return value.lower()
    if kind == "arxiv":
        return value
    if kind == "rfc":
        return "RFC" + str(int(value))
    if kind == "pmid":
        return str(int(value))
    if kind == "isbn":
        return re.sub(r"[\s\-]", "", value).upper()
    # url: requested == request_url, so (epoch, request_url) keys one record
    return value if "://" in value else "https://" + value


def request_url(kind, requested):
    """Spec §1.1 request_url normalization."""
    if kind == "url":
        return requested if "://" in requested else "https://" + requested
    if kind == "doi":
        return "https://doi.org/" + urllib.parse.quote(requested, safe="/:;()._-")
    if kind == "arxiv":
        return "https://arxiv.org/abs/" + requested
    if kind == "rfc":
        return "https://www.rfc-editor.org/rfc/rfc%d.txt" % int(requested[3:])
    if kind == "pmid":
        return "https://pubmed.ncbi.nlm.nih.gov/%s/" % requested
    return None  # isbn: unsupported_identifier in v1


def find_identifiers(text):
    """All identifier occurrences in `text`, ordered by offset, non-overlapping.

    URLs win over DOI/arXiv/PMID/RFC matches that fall inside them."""
    text = text or ""
    out = []
    taken = []

    def overlaps(a, b):
        return any(a < e and s < b for s, e in taken)

    for m in _URL.finditer(text):
        raw = _trim(m.group(0))
        if not _valid(raw) or "." not in raw.split("//")[-1].split("/")[0]:
            continue
        s, e = m.start(), m.start() + len(raw)
        kind, val = _url_kind(raw)
        if kind != "url":
            val = _trim(val)
        out.append((s, e, kind, val, raw))
        taken.append((s, e))
    for rx, kind in ((_DOI, "doi"), (_ARXIV, "arxiv"), (_PMID, "pmid"), (_RFC, "rfc"), (_ISBN, "isbn")):
        for m in rx.finditer(text):
            val = _trim(m.group(1)) if kind == "doi" else m.group(1)
            s = m.start()
            e = m.start(1) + len(val)
            if overlaps(s, e) or not _valid(val):
                continue
            out.append((s, e, kind, val, text[s:e]))
            taken.append((s, e))
    out.sort()
    res = []
    for s, e, kind, val, raw in out:
        req = _normalize(kind, val)
        res.append({
            "kind": kind,
            "requested": req,
            "raw": raw,
            "request_url": request_url(kind, req),
            "start": s,
            "end": e,
        })
    return res


# ── segmentation and source-line detection ──

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•–]|\d{1,3}[.)]|\[\d{1,3}\]|\(\d{1,3}\))\s+")
_LABEL = re.compile(
    r"^(?:\*\*)?(?:Sources?|References?|Cited?|Citations?|See also|Further reading|Bibliography|Retrieved from)\b\s*(?:\*\*)?\s*:",
    re.I,
)
_HEADER_ONLY = re.compile(r"^(?:\*\*|#+\s*)?(?:Sources?|References?|Citations?|Bibliography|Further reading)\s*:?\s*(?:\*\*)?\s*:?$", re.I)


def segments(text):
    """Split into (start, end, text) segments: lines, then sentences in a line."""
    text = text or ""
    segs = []
    pos = 0
    for line in text.split("\n"):
        lstart = pos
        pos += len(line) + 1
        if not line.strip():
            continue
        st = line.strip()
        if (_BULLET.match(st) or _LABEL.match(st)) and find_identifiers(st):
            # a citation line ("- Author (2021). https://...") stays one segment
            off = len(line) - len(line.lstrip())
            segs.append((lstart + off, lstart + off + len(st), st))
            continue
        cur = 0
        for m in _SENT_SPLIT.finditer(line):
            piece = line[cur:m.start()]
            if piece.strip():
                off = len(piece) - len(piece.lstrip())
                segs.append((lstart + cur + off, lstart + m.start(), piece.strip()))
            cur = m.end()
        piece = line[cur:]
        if piece.strip():
            off = len(piece) - len(piece.lstrip())
            segs.append((lstart + cur + off, lstart + cur + off + len(piece.strip()), piece.strip()))
    return segs


def is_source_line_v1(text):
    """Exact port of evaluate_v1._is_source_line (for the v1-window measurement)."""
    text = text.strip()
    if re.match(r'^(?:Source|Reference|Cited?|See also)\s*:', text, re.I):
        return True
    if re.match(r'^[\(\[]\d+[\)\]]\s+[A-Z]', text):
        return True
    if re.match(r'^https?://\S+$', text.strip()):
        return True
    if re.match(r'^Confidence\s*(level)?\s*:', text, re.I):
        return True
    return False


def is_source_line(text, ids_in_text=None):
    """Superset of the v1 rule: labelled source lines, section headers,
    bulleted/numbered lines carrying an identifier, and lines that are
    (almost) only identifiers."""
    t = text.strip()
    if is_source_line_v1(t) or _LABEL.match(t) or _HEADER_ONLY.match(t):
        return True
    ids = ids_in_text if ids_in_text is not None else find_identifiers(t)
    if ids:
        if _BULLET.match(t):
            return True
        rest = t
        for i in sorted(ids, key=lambda d: -d["start"]):
            rest = rest[:i["start"]] + rest[i["end"]:]
        if len(re.sub(r"[\W_]+", "", rest)) < 12:
            return True
    return False


def _is_meta(text):
    return bool(re.match(r"^(?:\*\*)?Confidence\s*(level)?\s*:", text.strip(), re.I))


def analyze_response(text):
    """Identifier occurrences with their containing sentence and supported assertion."""
    text = text or ""
    ids = find_identifiers(text)
    segs = segments(text)
    seg_ids = [[] for _ in segs]
    for d in ids:
        for k, (s, e, _) in enumerate(segs):
            if s <= d["start"] < e:
                seg_ids[k].append(d)
                d["segment_index"] = k
                break
    src = [is_source_line(t, [dict(x, start=x["start"] - s, end=x["end"] - s) for x in seg_ids[k]])
           for k, (s, _, t) in enumerate(segs)]
    for d in ids:
        k = d.get("segment_index")
        if k is None:
            d["sentence"] = None
            d["supports"] = None
            d["supports_segment_index"] = None
            d["in_source_line"] = False
            continue
        d["sentence"] = segs[k][2]
        d["in_source_line"] = src[k]
        j = k
        if src[k]:
            j = k - 1
            while j >= 0 and (src[j] or _is_meta(segs[j][2])):
                j -= 1
        d["supports"] = segs[j][2] if j >= 0 else None
        d["supports_segment_index"] = j if j >= 0 else None
    return {"identifiers": ids, "segments": segs, "source_flags": src}


def _find_claim_index(sents, raw_sent):
    for i, sent in enumerate(sents):
        if raw_sent[:40] in sent or sent[:40] in raw_sent:
            return i
    return None


def identifiers_for_claim(raw_response, raw_sentence, method="extended"):
    """Identifiers supporting one claim.

    method="v1": the exact evaluate_v1 window (v1 sentence split, claim
      sentence + up to 3 following sentences that pass the v1 source rule).
    method="extended": newline-aware segments; claim segment + the run of
      source segments that follows it (up to 8), stopping at the next
      assertion. Identifiers inside the claim sentence always count.
    """
    if not raw_response or not raw_sentence:
        return []
    if method == "v1":
        sents = _SENT_SPLIT.split(raw_response.strip())
        ci = _find_claim_index(sents, raw_sentence)
        if ci is None:
            return []
        picked = list(find_identifiers(sents[ci]))
        for off in range(1, 4):
            ni = ci + off
            if ni >= len(sents):
                break
            if not is_source_line_v1(sents[ni]):
                if off > 1:
                    break
                continue
            picked.extend(find_identifiers(sents[ni]))
        return picked
    a = analyze_response(raw_response)
    segs, src = a["segments"], a["source_flags"]
    ci = _find_claim_index([t for _, _, t in segs], raw_sentence)
    if ci is None:
        return []
    window = {ci}
    j = ci + 1
    while j < len(segs) and j <= ci + 8 and (src[j] or _is_meta(segs[j][2])):
        window.add(j)
        j += 1
    return [d for d in a["identifiers"] if d.get("segment_index") in window]


# ── corpus helpers ──

REF_URL = re.compile(r"https?://\S+")
REF_DOI = re.compile(r"10\.\d{4,9}/\S+")


def reference_recovery(text, ids):
    """Count reference-regex matches (URL, DOI) covered by an extracted identifier span."""
    res = {}
    for name, rx in (("url", REF_URL), ("doi", REF_DOI)):
        found = rec = 0
        for m in rx.finditer(text or ""):
            found += 1
            if any(d["start"] < m.end() and m.start() < d["end"] for d in ids):
                rec += 1
        res[name] = (found, rec)
    return res


def iter_raw(raw_dir):
    for f in sorted(glob.glob(os.path.join(raw_dir, "*.json"))):
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        for r in d.get("responses", []):
            yield d.get("id") or os.path.basename(f)[:-5], r.get("agent") or r.get("model"), r.get("raw_response") or ""


def cmd_ids(args):
    agg = {}
    for qid, agent, text in iter_raw(args.raw_dir):
        for d in analyze_response(text)["identifiers"]:
            key = (d["kind"], d["requested"])
            e = agg.setdefault(key, {"kind": d["kind"], "requested": d["requested"],
                                     "request_url": d["request_url"], "occurrences": []})
            e["occurrences"].append({"qid": qid, "agent": agent, "raw": d["raw"],
                                     "sentence": d["sentence"], "supports": d["supports"]})
    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        for key in sorted(agg):
            out.write(json.dumps(agg[key], sort_keys=True, ensure_ascii=False) + "\n")
    finally:
        if args.out:
            out.close()
    print(f"{len(agg)} unique identifiers", file=sys.stderr)
    return 0


def measure(raw_dir, results_dir=None):
    per_resp = []
    kinds = {}
    ref = {"url": [0, 0], "doi": [0, 0]}
    unique = set()
    n_with_supports = 0
    n_ids = 0
    for qid, agent, text in iter_raw(raw_dir):
        a = analyze_response(text)
        ids = a["identifiers"]
        per_resp.append(len(ids))
        n_ids += len(ids)
        for d in ids:
            kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
            unique.add((d["kind"], d["requested"]))
            if d["supports"]:
                n_with_supports += 1
        for k, (f, r) in reference_recovery(text, ids).items():
            ref[k][0] += f
            ref[k][1] += r
    m = {
        "extract_version": EXTRACT_VERSION,
        "responses": len(per_resp),
        "identifier_occurrences": n_ids,
        "unique_identifiers": len(unique),
        "by_kind": dict(sorted(kinds.items())),
        "occurrences_with_supported_sentence": n_with_supports,
        "per_response": {
            "mean": round(statistics.mean(per_resp), 3) if per_resp else 0,
            "median": statistics.median(per_resp) if per_resp else 0,
            "max": max(per_resp) if per_resp else 0,
            "responses_with_any": sum(1 for x in per_resp if x),
        },
        "reference_regex": {
            k: {"found": f, "recovered": r, "recall": round(r / f, 4) if f else None}
            for k, (f, r) in ref.items()
        },
    }
    tf, tr = ref["url"][0] + ref["doi"][0], ref["url"][1] + ref["doi"][1]
    m["reference_regex"]["total"] = {"found": tf, "recovered": tr, "recall": round(tr / tf, 4) if tf else None}
    if results_dir:
        m["per_claim"] = measure_claims(results_dir)
    return m


def measure_claims(results_dir):
    files = sorted(glob.glob(os.path.join(results_dir, "q*.json")))
    stats = {meth: {"claims_with_any": 0, "identifier_links": 0, "covered_occurrences": 0}
             for meth in ("in_sentence", "v1", "extended")}
    n_claims = 0
    n_occ = 0
    total_u = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            rows = json.load(fh)
        for row in rows:
            raw = row.get("raw_response") or ""
            all_ids = find_identifiers(raw)
            n_occ += len(all_ids)
            covered = {m: set() for m in stats}
            for c in row.get("claims", []):
                n_claims += 1
                rs = c.get("raw_sentence", "")
                ins = find_identifiers(rs)
                ext = identifiers_for_claim(raw, rs, "extended")
                v1 = identifiers_for_claim(raw, rs, "v1")
                for meth, got in (("in_sentence", ins), ("v1", v1), ("extended", ext)):
                    if got:
                        stats[meth]["claims_with_any"] += 1
                    stats[meth]["identifier_links"] += len(got)
                    for d in got:
                        covered[meth].add((d["kind"], d["requested"]))
            uniq_resp = {(d["kind"], d["requested"]) for d in all_ids}
            for meth in stats:
                stats[meth]["covered_occurrences"] += len(covered[meth] & uniq_resp)
            total_u += len(uniq_resp)
    out = {"claims": n_claims, "identifier_occurrences_in_results": n_occ,
           "unique_identifiers_summed_over_responses": total_u}
    for meth, s in stats.items():
        s["identifiers_reaching_a_claim"] = s.pop("covered_occurrences")
        s["identifiers_reaching_a_claim_frac"] = round(s["identifiers_reaching_a_claim"] / total_u, 4) if total_u else None
        out[meth] = s
    return out


def cmd_measure(args):
    m = measure(args.raw_dir, args.results_dir)
    s = json.dumps(m, indent=2, sort_keys=True)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(s + "\n")
    print(s)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ids", help="write unique identifiers (JSONL) from raw response files")
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_ids)
    p = sub.add_parser("measure", help="identifier recovery statistics")
    p.add_argument("--raw-dir", required=True)
    p.add_argument("--results-dir")
    p.add_argument("--json")
    p.set_defaults(fn=cmd_measure)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
