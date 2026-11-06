# Evidence spec addendum: local-corpus captures (eval v5)

Status: implemented. This file amends `v2/evidence-verification-spec.md` (the spec) as
`v3/DESIGN.md` §2.4 asks. Where the two disagree, this file wins for `corpus` captures.
Nothing here changes web captures, `bran-support/1`, the store, `bran-artifact/3` or replay.

Code: `tools/evidence/corpus_capture.py` (capture), `overturn/src/evidence.rs` (`IdentifierKind::Corpus`,
`parse_corpus_url`, `check_corpus_capture`, corpus xref key, `EvidencePolicy::grounded`).
Tests: `tools/evidence/tests/test_corpus_capture.py`, `evidence.rs` `mod tests`, and
`main.rs` `evidence_replay_tests::corpus_*`. Golden fixture: `tools/evidence/tests/golden/corpus_captures.json`.

## 1. The `corpus` identifier kind

### 1.1 Identifier

`corpus://<corpus_id>/<encoded passage_key>`

- `corpus_id` must match `[a-z0-9][a-z0-9._-]{0,63}`. The current ids are `fever17` and `scifact`.
- `passage_key` is the corpus key, `<corpus_id>:<page_id>:<chunk>` (§2). It can be up to 1,024 characters.
  FEVER page ids can contain `/`, `#`, `?`, `:`, spaces and non-ASCII text, so the key is
  percent-encoded:
  - These characters stay as they are: RFC 3986 unreserved characters (`A–Z a–z 0–9 - . _ ~`) and `:`.
  - Every other UTF-8 byte becomes `%XX`, with uppercase hex.
  - This is exactly Python `urllib.parse.quote(key, safe=":")`.
- **Exactly one URL per passage.** Lowercase hex, an encoded verbatim character (`%41`), a raw
  reserved or non-ASCII character, and non-UTF-8 escapes are all rejected.
  - Python: `corpus_capture.parse_corpus_url`. Rust: `evidence::parse_corpus_url`.
  - Both have the same accept/reject tests.
- Example: `fever17:AC/DC:1` → `corpus://fever17/fever17:AC%2FDC:1`.

### 1.2 Record (`bran-capture/1`, unchanged schema)

| field | found passage | key not in corpus |
|---|---|---|
| `identifier_kind` | `corpus` | `corpus` |
| `requested`, `request_url` | the corpus URL | the corpus URL |
| `resolved_url`, `canonical_url` | the corpus URL | `null` |
| `redirects` | `[]` | `[]` |
| `http_status` | `null` | `null` |
| `content_type` | `text/plain` | `null` |
| `content_length` | UTF-8 bytes of the content | `0` |
| `truncated` | `false` | `false` |
| `content_sha256` | SHA-256 of the content's UTF-8 bytes | `null` |
| `extraction` | `{method: "corpus/1", method_version: "1", text_sha256, text_chars}` | `null` |
| `outcome` | `ok` if the sanitized text is non-empty, `ok_no_text` if it is empty (`ok_rule` `corpus-nonempty/1`, §1.4) | `invalid_identifier` |
| `robots` | `{checked: false, allowed: null, robots_sha256: null}` | same |
| `license_note` | the manifest's `license` string, verbatim | `null` |
| `capture_tool_version` | see §1.4 | same |

- **Content.** The content is the corpus's indexed and displayed string, `title + "\n" + text`
  (`build.passage_content`). It is what agents see and what retrieval scores.
- **Extracted text.** `text_sha256` is taken over the same content after the web sanitizer
  (`capture.sanitize_text`). For corpus passages the two hashes are equal, because the corpus builder already
  collapses whitespace.
- **Cache.** Records, blobs and text go into the existing cache layout (spec §1.5) through
  `capture.Cache`. So `capture.py verify-cache` and `support/check.py` (`load_capture`,
  `load_capture_text`) work on corpus captures unchanged, and both are tested.
- **No 200-character threshold.** This is an analysis-team decision. The spec §1.3 threshold is a
  web-page heuristic. A corpus passage is the sealed unit of evidence by construction, so a short
  FEVER lead such as `Neptune\nNeptune is the eighth planet.` is `ok` and goes to the checker. Web
  captures keep the threshold. Rust checks the record shape, not the rule; the rule is pinned
  through `capture_tool_version`.
- **No network.** The tool never opens a socket, resolves a name, or reads robots.txt. Every test runs
  under `NoNetwork` and asserts that no connection was attempted.

**Reducer-side shape check.** `verify_record_ids` runs `check_corpus_capture` for `identifier_kind = corpus`.
A record that breaks the table is a seal error, and on replay it fails with exit 3. Three things
break it:

- fetch fields that cannot occur for a local read: redirects, an HTTP status, `truncated`, or a robots
  check;
- a URL that is not canonical;
- URL fields that differ from each other, a content type other than `text/plain`, a missing or
  malformed hash, or an extraction method other than `corpus/1`.

The outcome must be `ok`, `ok_no_text` or `invalid_identifier`. Web records are not affected.

### 1.3 Cross-reference key

For a corpus capture of class `reachable+text` or `reachable`, the key is
`corpus:<corpus_id>/<encoded passage_key>`, which is the canonical URL without the `corpus://` prefix.
Web captures keep `url:<canonical_url>`.

**Deviation from design §2.4 item 5.** The design gives the key as `corpus:<passage_key>` "via the
existing canonical_url rule". As written, that existing rule would yield `url:corpus://…`. We used a
`corpus:` prefix instead, so no web page can ever share a key with a passage, and we kept the corpus
id in the key. Because corpus keys already start with the corpus id, the key is a fixed one-to-one
rewrite of the design's key. Agents earn the xref bonus exactly as the design says: distinct agents
whose items cite the same passage and are labelled `supports`.

### 1.4 Corpus pinning

`capture_tool_version = 0.1.0+<blob12 corpus_capture.py>.<blob12 capture.py>.<blob12 canonical.py>.c<corpus_sha256>.k<config hash12>`

- `corpus_sha256` is the corpus's full 64-hex value. A new corpus therefore means new capture ids, even for
  passages whose content is unchanged (tested).
- `capture.py` is included because its sanitizer determines `text_sha256`.
- The config is `{ok_rule: "corpus-nonempty/1", max_text_chars: 200000, extraction: "corpus/1", url_encoding}`.
  `ok_rule` is versioned. An unknown rule is an error, and a different rule changes the config
  hash, so it gives new capture ids (tested).

### 1.5 Citations that cannot be resolved

Agents cite `P1`–`Pk`. `citation_keys(retrieval_record, labels)` maps each label to `results[n-1].passage_key`.
If a label is out of range or malformed, the label itself is used as the key, for example
`corpus://fever17/P7`. No such passage exists, so the capture is `invalid_identifier`, which falls in
the dead class (design §2.4 item 4). A `corpus_id` that does not match the retrieval record is an
error, not a capture.

### 1.6 CLI

```sh
python3 -I tools/evidence/corpus_capture.py capture --corpus fever17 --keys keys.txt \
    --cache real-agent-eval/v5/evidence-cache [--epoch corpus] [--offline] [--verify-passages] --out caps.jsonl
python3 -I tools/evidence/corpus_capture.py version --corpus fever17
```

- `--manifest` defaults to `tools/corpus/corpus_manifest.json`.
- `--keys` takes one key per line, or JSONL with `key` or `passage_key`.
- Offline mode reads only `index/` and `captures/`. A miss exits 3 and writes nothing.
- `--verify-passages` re-hashes `passages.jsonl` against the manifest's `passages_sha256`.

## 2. The corpus passage format we read (adapter)

Only `CorpusSource` knows this layout. It was read from `tools/corpus/build.py` and `README.md`
on 2026-10-22.

- **Manifest** `tools/corpus/corpus_manifest.json`. `format = "bran-corpus-manifest/1"`, plus
  `corpora.<corpus_id>`, which holds:
  - `corpus_sha256` (64 hex);
  - `license` (string);
  - `passages.file`, relative to the repo root (the manifest's grandparent directory, which
    `--repo-root` overrides);
  - `passages.passages_sha256`.
- **Passages** `corpus-cache/<corpus_id>/passages.jsonl`. One canonical-JSON object per line:
  `{key, page_id, chunk, title, sent_ids, text}`. We use `key`, `title` and `text`.
- **Lookup.** We make one streaming pass over the file for the batch of keys we need. That is
  enough for about 25k captures over 5.4M FEVER passages. The corpus offsets file is not used, because it
  needs numpy and we use the standard library only.
- If the corpus layout changes, only `CorpusSource.from_manifest` and `lookup` change. The record format
  does not.

## 3. Policy: `unchecked_factor` 0.5 for grounded runs

- **The default stays 1.0.** `EvidencePolicy::default()`, spec §7 Q1 and the v4 preregistration are
  unchanged.
- **The grounded value.** `EvidencePolicy::grounded(accepted)` and
  `evidence::UNCHECKED_FACTOR_GROUNDED = 0.5` give the v5 value. In a `--reduce` input it is written
  `"policy": {"evidence": {"unchecked_factor": 0.5, "accepted_checkers": [...]}}`.
- **Effect.** An `ok` passage whose check was refused, failed or came from an unaccepted checker now
  scores 0.85·0.75·0.5 = 0.319. That is the not-enough-info level, against 0.638 under the default.
  Empty passages drop from 0.525 to 0.263, and invalid passage ids from 0.090 to 0.045. All
  of these are tested to the quantized integer.

**Hashes.** The default policy hash stays `dd8d36e6def3a6d598765e82d461a473`, because the `evidence` key
is absent when there is no policy. The default evidence policy's JSON is unchanged too. The committed
`/3` fixture still hashes to its stored policy hash `2068997d…`, and a test asserts this. The grounded
policy differs in exactly one hashed key, so it hashes apart.

**Why `unchecked_factor` is always serialized, not "only when non-default".** The design brief said to
serialize it only when non-default. But the field has been part of `bran-evidence-policy/1` since
v4 and is always serialized. The committed `/3` fixture stores `"unchecked_factor": 1.0`. If 1.0
were now skipped, re-serializing that policy would drop the key, and its hash would change (replay exit
4). Serializing it always is the only choice that leaves every existing hash unchanged.

## 4. Regressions and tamper tests (design §2.4 list)

| check | where | result |
|---|---|---|
| `cargo test --release` | `overturn/` | 111 passed, 1 ignored (was 99 + 1). 12 new: 7 in `evidence.rs`, 5 in `main.rs` |
| `make replay-file` | repo root | exit 0. Committed `/2` and `/3` files replay. `--legacy-ids` reproduces the committed dumps |
| `/3` round-trip with corpus captures | `corpus_artifact_replays_offline` | dump → text → reload → verify, under both the default and the grounded policy. The policy hash equals the web-capture fixture's under the default and differs under grounded. Scores move |
| tamper 1 (label flip, kept ids) | `corpus_flipped_label_is_hash_mismatch` | exit 3. Also an edited `content_sha256` with the id kept → exit 3 |
| tamper 2/3 (consistent forgeries) | `corpus_consistent_forgeries_fail_on_outputs` | label, passage hash, passage key, empty→ok, corpus pin → exit 1 |
| shape forgeries | `corpus_shape_forgeries_rejected` | http_status, robots, redirect, web URL, dead outcome → exit 3 |
| tamper 4 (policy edits) | `corpus_policy_edits` | `unchecked_factor` back to 1.0, or checkers cleared: exit 4. With the hash recomputed: exit 1 |
| tamper 5 (every field sealed) | `every_corpus_record_field_changes_ids_and_root` | every leaf changes the capture id and the root |
| tamper 6 (telemetry) | `test_telemetry_is_not_sealed` (Python) and `telemetry_cannot_enter_a_record` (Rust) | a sidecar edit changes nothing |
| cross-language ids | `golden_corpus_capture_ids` and `test_golden_fixture` | 4 golden records (ok; short ok with reserved and non-ASCII key characters; empty ok_no_text; invalid). Python and Rust ids are equal |
| Python | `python3 -m unittest discover tools/evidence` | 74 tests OK, including 16 corpus tests. One of them captures a real SciFact passage when the corpus cache is present |

## 5. Open issues for the preregistration, checker and evaluation

1. **Resolved: the 200-character threshold.** The analysis team decided that corpus captures use
   `ok_rule` `corpus-nonempty/1` (§1.2, §1.4). Web captures are unchanged.
2. **The corpus pin is trusted, not recomputed.** `corpus_sha256` comes from the manifest. Recomputing
   it needs the corpus builder's formula over the source file. `--verify-passages` checks `passages.jsonl` against
   `passages_sha256`, which takes minutes on FEVER. Run it once before the freeze.
3. **`license_note` is a free-text string** (`"CC BY-SA 3.0"`), not the web capture's slug
   (`cc-by-4.0`). It is informational only and is not read by the reducer.
