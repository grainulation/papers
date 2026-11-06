# Support checker

Implements the `bran-support/1` support check of `v2/evidence-verification-spec.md` §2, §5.3–§5.4 and §6: given a claim and a `bran-capture/1` record with outcome `ok`, select at most three passages of the captured text with BM25, ask an independent LLM whether they support, refute or do not address the claim, and seal the result as a content-addressed record.

The checker is the Claude Code CLI in headless mode (`claude -p`), not Ollama. The spec's deviation section below gives the reasons and what changes.

## Files

| Path | Role |
|---|---|
| `check.py` | span selection (`bm25/1`), prompt rendering, CLI call, strict parsing, support cache, record writing; CLI `check` and `checker-id` |
| `prompt_template.txt` | fixed SYSTEM and USER template; its SHA-256 is sealed as `prompt_template_sha256` |
| `pin.json` | pinned backend, model id, effort, per-call budget cap, timeout |
| `validate.py` | public-slice validation, injection suite, stability re-run, report |
| `validation/slice.jsonl`, `pilot.jsonl`, `injection.jsonl` | sealed validation inputs (hashes in the report) |
| `validation/<checker_id>.json` | validation report (spec §2.2 item 4) |
| `validation/results/` | per-item outputs, cost and latency telemetry |
| `validation/cache/` | support cache for the validation runs (model outputs only, no transcripts) |
| `tests/` | unit tests against `tests/mock_claude.py`, a stub CLI, plus golden cross-language ids |
| `smoke/` | live smoke test on 4 real v3 captures, plus the Rust `--reduce` input and output |
| `VALIDATION.md` | validation results, compared with the spec thresholds |

## Usage

```sh
# checker identity (checker_id, flags, model, template hash, CLI version)
python3 -I tools/evidence/support/check.py checker-id

# items.jsonl: {"contribution_id", "evidence_index", "capture_id", "claim": {subject, predicate, object, polarity, raw_text}}
python3 -I tools/evidence/support/check.py check --items items.jsonl --cache real-agent-eval/v4/evidence-cache

# tests (mocked CLI, no network)
python3 -m unittest discover tools/evidence/support

# validation (live CLI calls; about $0.001 per uncached check warm, $0.006 cold)
python3 -I tools/evidence/support/validate.py build
python3 -I tools/evidence/support/validate.py run
python3 -I tools/evidence/support/validate.py report
```

`check` reads the capture tool's cache (`captures/<id>.json`, `text/sha256/..`), and verifies that each record and text hashes to its id before using it. It writes only under `support/` and `index/support*.jsonl` (layout in spec §1.5). Captures whose outcome is not `ok` produce no record, as the spec requires.

## How a check works

1. **Spans (`bm25/1`, params `k1_x1000=1200, b_x1000=750, chunk_chars=1000, overlap_chars=200`).** If the text is at most 3 × 1,000 chars, it is split into ⌈n/1000⌉ equal, non-overlapping spans, so the whole text is sent. Otherwise it is cut into 1,000-char windows with a stride of 800, and each window is scored with BM25 (casefolded `\w+` tokens, a fixed stopword list, IDF over the windows of this text). The query is the claim's `raw_text` plus its subject and object. The top three non-overlapping windows are kept; scores are quantized to 1e-6 and ties go to the lower offset. Spans are returned in offset order. If no window shares a term with the query, the first window is used. Offsets are Unicode scalar indices (Python `str` indices).
2. **Prompt.** The claim and span texts are passed through `neutralize()`: NFC normalization, control characters removed, and any run of three or more `<`/`>` or look-alike characters (‹›«»＜＞〈〉 etc.) replaced by `[x]` (3 chars, so a span never grows past the 1,000-char limit; the sealed text is also capped at 1,000). They are then inserted once each, in a single substitution pass, between `<<<CLAIM`/`CLAIM>>>` and `<<<PASSAGE`/`PASSAGE>>>`. The SYSTEM section says that both are untrusted data and that instructions inside them must be ignored. The sealed span `text` is the neutralized text that was sent.
3. **Call.** `claude` gets a fixed argv (no shell) and receives the prompt on stdin, so fetched text is never part of a command line. Flags: `-p --model <pin> --output-format json --json-schema <schema> --tools "" --strict-mcp-config --safe-mode --setting-sources "" --disable-slash-commands --no-session-persistence --effort low --max-budget-usd 0.05 --system-prompt <template SYSTEM>`. The CLI runs in an empty working directory. With these flags the only tool the model sees is the CLI's built-in `StructuredOutput` tool, bound to the response schema. There are no MCP servers, no file or shell tools, and no CLAUDE.md, skills, plugins or hooks.
4. **Parse (strict).** The result event must be `subtype: success`, and `structured_output` must be exactly `{label, confidence}`, with `label` ∈ {supports, refutes, not_enough_info} and `confidence` a non-boolean integer in 0..10000 (sealed as `score_q`). Anything else gives `parse_error` and a null label. Every assistant message's reported `model` must equal the pin, or the status is `model_mismatch` and the label is null.
5. **Cache.** `check_key = sha256_hex16({checker_id, sha256(rendered user prompt)})`, which amounts to keying on (claim text, span texts, checker). Answers are cached in `index/support_checks.jsonl`, and raw model output goes in `support/raw/`. A cached key is never queried again. `ok`, `parse_error`, `model_mismatch`, `input_too_long` and `refused` are cached. `timeout` and `checker_error` are transient: nothing is sealed, and the check is retried on the next run. `--recheck` (regeneration) queries anyway, but the first cached answer stays authoritative.

`raw_output_sha256` hashes the model's answer: the canonical `{confidence,label}` JSON for `ok`, otherwise the CLI's `result` string. It does not cover the CLI transcript, which carries session ids and timestamps. As a result, a re-check that gives the same answer yields the same `support_id`.

## Record (`bran-support/1`) as emitted

The record has exactly the fields of the Rust `SupportRecord`/`Checker` structs in `overturn/src/evidence.rs`. Those structs use `deny_unknown_fields`, require every field, and need `label`/`score_q` present iff `status = ok`. The CLI checker is mapped onto the Ollama-shaped `checker` block:

```json
"checker": {
  "checker_id": "76d44ce22b1ea2f476539e36daacc81a",   // = Rust Checker::compute_id
  "model": "claude-sonnet-5-5",                      // pinned id (pin.json)
  "model_digest": "hosted:none",                     // no weights digest exists
  "prompt_template_sha256": "9e035ba0…",
  "decoding": {"temperature_x1000": -1, "top_k": -1, "top_p_x1000": -1,
               "num_ctx": -1, "num_predict": -1, "seed": -1},   // -1 = not settable via the CLI
  "ollama_version": "claude-code/2.1.306",           // runtime version; recorded, not in the id
  "checker_tool_version": "0.1.0+<blob(check.py)>.<blob(prompt_template.txt)>.f<sha256(backend, flags, response schema)[:12]>"
}
```

- **Id.** `checker_id = sha256_hex16(canonical_json({model, model_digest, prompt_template_sha256, decoding, checker_tool_version}))`, the same formula as Rust.
- **What the id binds.** The CLI flags (`--tools ""`, `--safe-mode`, `--effort`, budget, …) and the response schema enter the id through the `.f<hash>` suffix of `checker_tool_version`. This follows the precedent of the capture tool's config hash in `capture_tool_version`. `check.py checker-id` prints the full flags.
- **Reported model.** The model id reported by the CLI is not a record field. Any mismatch with the pin yields `model_mismatch`; the per-call value goes to telemetry and to the validation report.
- **No floats.** Records contain none.
- **Telemetry.** Duration, cost, exit code and the cached flag go to `support/<id>.telemetry.json`, which is never hashed.

**Statuses.** The internal statuses are `ok`, `parse_error`, `timeout`, `input_too_long`, `model_mismatch`, `refused` and `checker_error`.
- `refused` (the model's safeguards declined, `stop_reason: refusal`) is cached and sealed as `parse_error`, because Rust `SupportStatus` has no `refused`. The refusal text is in the raw output, whose hash is sealed.
- `timeout` and `checker_error` are transient. They are never sealed, and the check is retried on the next run.

**Cross-language and Rust checks.** `tests/test_check.py::TestGoldenCrossLanguage` reproduces the Rust goldens (`v2/evidence/fixtures/golden-records.json`): capture id, checker id, support id, and a record built by `build_record` that is byte-identical to the golden. Another test asserts the exact Rust field sets for every status.

**Smoke test** (`smoke/`): four real v3 captures from `real-agent-eval/v4/evidence-cache` (RFC 793, Wikipedia ×2, git docs) were checked live.
- Labels: supports, NEI, refutes, NEI. The NEI on "standard gravity = 9.80665 m/s²" is correct, because the captured page is a Wikipedia disambiguation page.
- The records were sealed by the Rust binary's `--reduce` with `policy.evidence.accepted_checkers` (exit 0). Removing the checker from `accepted_checkers` changes the certificate. Flipping one label without updating its id is rejected (exit 2, "support id mismatch").
- **Caveat:** the capture tool's live captures write `extraction.method_version` as the integer `1`, while the Rust `Extraction` struct expects a string. As written, every v3 capture therefore fails Rust parsing. For the smoke test, the captures were copied with `method_version: "1"`, their ids recomputed, and stored in `smoke/reduce-input*.json`. This needs fixing in the capture tool (or the Rust integration).

## Deviations from the spec

1. **Backend.** The spec calls for Ollama with a digest-pinned local model. This checker uses the Claude Code CLI (`claude -p`, v2.1.306) with model `claude-sonnet-5-5`, by author decision (no new Ollama pull). Claude is a different model family from all five collector models (`llama3.2:3b, mistral, gemma2:2b, phi3:mini, qwen2.5:3b`, `real-agent-eval/collect.py:28`), which is what the independence requirement needs.
2. **No digest, no seed.** A hosted model has no weight digest, and the CLI exposes no temperature, top-k or seed. `model_digest` is therefore the sentinel `hosted:none`, every `decoding` field is `-1`, and the controllable settings (`--effort low`, the budget cap, tools off) are bound through the flags hash in `checker_tool_version`. The digest check in acceptance test 1 becomes a check of the reported model id: if the id the CLI reports differs from the pin, the record gets `model_mismatch` and no label. This proves which model the API says it served, not which weights it used. **Labels are deterministic only because they are sealed.** Re-running the checker is regeneration (spec §4); it is not replay, and the stability figure in VALIDATION.md measures how much regeneration drifts.
3. **Internal statuses `checker_error` and `refused`.** `checker_error` covers CLI or API failures (a non-zero exit, `is_error`, a budget stop, unparseable stdout). It is transient: never sealed or cached. `refused` covers safeguard refusals, about 1.3% of SciFact items, all biology. It is stable for a given input, so it is cached and sealed as `parse_error`. A distinct sealed `refused` status would need L4d to add it to `SupportStatus`.
4. **Output constraint.** The spec's Ollama `format` schema `{label, confidence: number}` becomes the CLI's `--json-schema` with an integer `confidence` on the 0..10000 scale. That makes it equal to `score_q` with no float conversion.
5. **Short texts.** When the whole text fits in 3 × 1,000 chars it is sent whole rather than ranked. This is part of `bm25/1`.
6. **Validation.** The validation uses no human labels. Only the public SciFact slice is run; FEVER evidence text is not downloaded. The injection suite has 50 spans, which meets the spec's ≥ 50. The model was chosen on a disjoint 30-pair pilot. Details and their consequences are in VALIDATION.md. The spec's human-labeled v4-capture slice (§2.2 item 1) is still required before any `checker_id` can enter `accepted_checkers`.
7. **Template and system prompt.** The prompt template carries a SYSTEM section that is passed with `--system-prompt`, replacing the CLI's default system prompt. The record's `flags` show it as `@prompt_template.txt#SYSTEM`, and it is covered by `prompt_template_sha256`.

## Runtime configuration

Set `OVERTURN_CLAUDE_BIN` to select the checker executable and `OVERTURN_OLLAMA_LOG` to locate the local server configuration log. The corresponding historical `BRAN_CLAUDE_BIN` and `BRAN_OLLAMA_LOG` variables are fallback inputs only when the public variable is unset. Record formats and stored checker identities remain unchanged; running changed checker source produces a new tool identity rather than relabeling historical checks.
