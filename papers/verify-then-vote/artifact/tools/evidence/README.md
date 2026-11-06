# tools/evidence — evidence capture

Implements the capture side of `v2/evidence-verification-spec.md`: §1 (`bran-capture/1` record, cache layout, limits, outcome enum), §5.2–§5.5 (SSRF, TLS, sanitization, robots) and the §6 capture-tool acceptance tests. Python stdlib only. `support/` is the support checker and is not covered here.

| File | Role |
|---|---|
| `extract.py` | Pulls URLs, DOIs, arXiv ids, RFCs, PMIDs and ISBNs out of raw responses. For each one it keeps the identifier, its offsets, the sentence that contains it, and the assertion it supports. `identifiers_for_claim` gives the identifiers for one claim. This replaces the `"context-associated"` placeholder (`real-agent-eval/evaluate_v1.py:172`). |
| `capture.py` | Fetches each identifier, writes it to the content-addressed cache, extracts text (HTML → text, plain text; no PDF in v1), classifies the outcome, and provides `verify-cache`. |
| `canonical.py` | Canonical JSON (sorted keys, compact, UTF-8, floats rejected), `sha256_hex16` record ids, `canonical_url`, git blob hash. |
| `tests/` | Unit tests, a local fixture server bound to 127.0.0.1, fixtures, and the golden cross-language id fixture for the Rust tests. |

## Commands

```sh
# tests (no outbound traffic; see "Test isolation")
python3 -m unittest discover tools/evidence

# identifier recovery on v3
python3 -I tools/evidence/extract.py measure \
  --raw-dir real-agent-eval/v3/results/raw --results-dir real-agent-eval/v3/results

# unique identifiers -> JSONL (input to capture)
python3 -I tools/evidence/extract.py ids --raw-dir real-agent-eval/v3/results/raw --out ids.jsonl

# capture (online needs --network-approved; refuses with exit 2 otherwise)
python3 -I tools/evidence/capture.py capture --ids ids.jsonl --cache tools/evidence/cache \
  --epoch v3-YYYYMMDD --network-approved [--ca-file corp-ca.pem] --out captures.jsonl

# replay from the cache only: a miss exits 3 and writes nothing
python3 -I tools/evidence/capture.py capture --ids ids.jsonl --cache tools/evidence/cache --epoch v3-YYYYMMDD --offline

# integrity check: recomputes every blob, text and record hash (exit 1 on any mismatch)
python3 -I tools/evidence/capture.py verify-cache --cache tools/evidence/cache

python3 -I tools/evidence/capture.py version   # capture_tool_version for the default config
```

`capture_tool_version` = `0.1.0+<git blob of capture.py>.<git blob of canonical.py>.k<hash of config>`. Changing any limit, signature list, or loopback setting changes the version, and so changes every capture id.

## Cache layout (§1.5)

```
blobs/sha256/<h[0:2]>/<h>             raw bytes received (truncated at max_body_bytes)
text/sha256/<t[0:2]>/<t>.txt          sanitized extracted text
captures/<capture_id>.json            sealed record, canonical JSON bytes
captures/<capture_id>.telemetry.json  list of telemetry entries (fetched_at, duration_ms, retries, headers, TLS issuer, resolved IPs, detail); never hashed
index/captures.jsonl                  append-only {epoch, request_url, capture_id}
```

There is one record per (request_url, epoch). The first capture in an epoch is authoritative, and a re-run reuses it without fetching again. `requested` holds the sanitized identifier in a per-kind normal form: a URL as written with `https://` added to a bare `www.`, a lowercased DOI, `RFC<n>`, digits for a PMID. So `doi:10.x/Y` and `https://doi.org/10.x/y` share one record. This is a small, deliberate reading of §1.1's "exactly as extracted". The raw match text stays in the `extract.py` output.

## Safety rules (each one is tested)

- **SSRF.** Only http and https are fetched. Every resolved address of every hop must be globally routable, and that includes each redirect target. Blocked: loopback, including `localhost:11434` (Ollama); RFC 1918; link-local and `169.254.169.254`; CGNAT; IPv6 ULA and link-local; IPv4-mapped and 6to4 forms; legacy numeric hosts (`2130706433`, `0x7f.1`, `127.1`); multicast and reserved ranges. A host resolving to a mix of good and bad addresses is blocked. The connection goes to the vetted IP, so there is no second DNS lookup. URLs containing credentials are rejected. A blocked URL is never contacted, robots.txt included.
- **Test loopback.** `--allow-loopback-for-tests PORT[,PORT]` opens only the listed loopback ports, and also turns on loopback-only mode, which refuses every non-loopback destination. Port 11434 can never be opened.
- **TLS.** Uses `ssl.create_default_context()` with `CERT_REQUIRED` and hostname checking. Verification is never disabled. A corporate interception CA can be added with `SSL_CERT_FILE` or `--ca-file`. Telemetry records the presented issuer and flags known interception vendors.
- **robots.txt.** Checked for every hop's origin with user-agent token `bran-evidence-capture`. 2xx: parsed. 401/403: disallow. Other 4xx: allowed, with a null `robots_sha256`. 5xx or network error: `allowed: null`, and the fetch proceeds. A disallowed URL gives `robots_disallowed` and is never fetched.
- **Limits (§1.4).** 5 MiB body (truncated, hashed and extracted; `truncated: true`). 200,000 text chars. 10 s connect and 30 s total. At most 5 redirects; a loop counts as `too_many_redirects`. 1 request/s per host. 2 retries, only for connect error, timeout, 5xx and 429. `Accept-Encoding: identity`, and gzip/deflate are decoded with a bounded output. No cookies, auth or JavaScript.
- **Sanitization (§5.3).** NFC; `<script>`, `<style>`, `<noscript>` and `<template>` dropped; control characters removed except `\n`; whitespace collapsed; length capped. Extracted identifiers: trailing `.,;:)]>'"` stripped while brackets stay balanced; no whitespace or control characters; at most 2,048 chars.
- **Proxy block pages.** A text body that matches a known interception or URL-filter signature (Zscaler, Netskope, Forcepoint, Blue Coat, Palo Alto, Umbrella, Fortinet, Sophos, generic "blocked by your organization") with status 2xx, 403 or 407 gives `blocked_proxy`.

## Outcomes

`ok` means 2xx, HTML or plain text, and at least 200 chars of extracted text. The other outcomes: `ok_no_text` (PDF, image, JS-only or short page), `not_found` (404/410), `invalid_identifier` (malformed, credentials, or a DOI resolver 404 with no redirect), `dns_nxdomain`, `http_error`, `connect_error`, `timeout`, `tls_error`, `too_many_redirects`, `robots_disallowed`, `blocked_ssrf`, `blocked_proxy`, `unsupported_identifier` (ISBN). Each has a fixture test.

## Test isolation

All capture tests run under `tests/fixture_server.NoNetwork`. That guard raises on any connect to a non-loopback address, on any loopback connect to port 11434, and on any real DNS lookup. It also logs every connect attempt, so the SSRF tests can assert that nothing at all was contacted. Hostnames such as `fixture.test` resolve through a stub resolver. The TLS tests generate a throwaway self-signed certificate with the `openssl` CLI and are skipped if it is missing.

## Once gate Q5 is approved (live run)

1. `extract.py ids` over `real-agent-eval/v3/results/raw` produces 332 unique identifiers: 372 URL occurrences, 32 RFC, 18 DOI and 6 arXiv.
2. `capture.py capture --network-approved --epoch v3-<date>` fetches each one at 1 request/s per host, checking robots.txt first. With retries, the worst case is about 30 s × 3 per identifier, but most finish in under a second.
3. Report the outcome distribution, `verify-cache`, and claims with at least one `ok` source, using `extract.identifiers_for_claim` with the capture outcomes.
4. If TLS interception breaks verification, captures come back as `tls_error` with `CERTIFICATE_VERIFY_FAILED` in telemetry `detail`. In that case, supply the corporate CA with `--ca-file`. Never turn verification off.
5. The cache path must be git-ignored when it is large, because the bodies are third-party content (§5.6).

## Operational notes from the first live run

- **TLS interception on the collection host (a TLS-inspection gateway).** The gateway re-signs TLS with its own CAs. Those CAs sit in the macOS System keychain, so curl works. Python's Homebrew OpenSSL bundle does not have them, so every HTTPS capture comes back as `tls_error` (`CERTIFICATE_VERIFY_FAILED`). The fix keeps verification on and does not change any system or global CA setting. Export the two gateway certs and pass them per run:

  ```sh
  security find-certificate -a -c "<gateway CA name>" -p /Library/Keychains/System.keychain > /path/outside/repo/gateway-ca.pem
  python3 -I tools/evidence/capture.py capture ... --network-approved --ca-file /path/outside/repo/gateway-ca.pem
  ```

  So on this host, `content_sha256` attests the bytes received through the gateway, not origin integrity (§5.2). Telemetry `tls_issuer` names the gateway CA, and `tls_interception_suspected` is not raised for it unless the gateway vendor is added to `PROXY_CA_HINTS`.
- **Failed records are reused within an epoch.** The cache keeps exactly one record per (request_url, epoch), and the first record is authoritative (§1.5). A second `capture` run with the same `--epoch` therefore reuses earlier `tls_error`, `timeout`, `connect_error` and other transient records; it does not fetch them again. To retry after fixing the cause (CA bundle, network), use a new epoch, for example `v3-2026-10-21-gw`. Older failed records stay in the cache and the index under their old epoch, and `verify-cache` still passes. A `--retry-failed` option, which would re-fetch transient-class outcomes as a new epoch entry, is not implemented in v1.
- The live v3 capture ran into `real-agent-eval/v4/evidence-cache/` (git-ignored) under three epochs:
  - `v3-2026-10-21`: no gateway CA, so TLS failed.
  - `v3-2026-10-21-gw`: gateway CA added, but `extraction.method_version` was written as an integer.
  - `v3-2026-10-21-gw2`: the authoritative run. It has `method_version` as a string, which the Rust reducer requires, and the paper's §9.4 counts come from it: 332 identifiers, 109 ok, 15 ok_no_text, 146 not_found, 10 dns_nxdomain, 10 invalid_identifier, 21 http_error, 16 robots_disallowed, 2 tls_error, 2 connect_error, 1 timeout.
