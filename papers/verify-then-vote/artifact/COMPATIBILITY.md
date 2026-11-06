# Compatibility with frozen study records

The public project names are `overturn` (Rust crate and CLI), `OverturnLean` / `Overturn` (Lean), and `overturn-arbiter` / `overturn_arbiter` (Python distribution/import).

Frozen study records retain their exact schema identifiers, hashes, filenames, and execution provenance. Those identifiers are a compatibility boundary, not the current project name. The study freezes predate release preparation; no earlier public release is implied. Rewriting these records would obscure the relationship between the pre-specified analyses and the evidence, so public reconstruction verifies their original identities with only the exact mappings in [FROZEN_REDACTIONS.md](FROZEN_REDACTIONS.md).

## Serialized identifiers

These spellings remain in protocol readers/writers and their tests where required to read or reproduce frozen records. Changing them can change recorded hashes and IDs or make archived files unreadable.

| identifier | where it is used |
|---|---|
| `bran-artifact/1` to `bran-artifact/4`, `bran-envelope/1` | artifact file format tags and the envelope hash (`overturn/src/main.rs`) |
| `bran-policy/1`, `bran-evidence-policy/1` | canonical policy serialization behind the policy hash (`overturn/src/compiler.rs`, `overturn/src/evidence.rs`) |
| `bran-contribution-id/1` | content-addressed contribution ids (`overturn/src/ir.rs`) |
| `bran-capture/1`, `bran-support/1` | evidence capture and support records, whose ids are their hashes |
| `bran-retrieval/1`, `bran-corpus-manifest/1`, `bran-dense-index/1`, `bran-bm25-index/1`, `bran-chunk/1` | retrieval records and corpus build (`tools/corpus/`) |
| `bran-v5-raw/1`, `bran-eval-v5/1`, `bran-v5-freeze/1`, `bran-v5-dev-code-manifest/1`, `bran-v5-check-plan/1` | OVERTURN raw records, evaluation output, freeze record and check plan |
| `bran-judge/1`, `bran-judge-input/1`, `bran-proposition/1`, `bran-extract/1` | judge rows, judge inputs, propositions and identifier extraction |
| `bran-support-validation/1`, `/2`, `/fever/1`, `/dedup/1`, `bran-golden/1` | checker validation reports and test golden files |


## Historical filenames and configuration

The archived executables retain `real-agent-eval/v5/frozen-bin/bran` and `real-agent-eval/v4/frozen-bin/bran-v4-eval`, as named in the freeze manifests. Public reproduction uses a locally built `overturn` binary instead. Historical logs and build manifests retain the names recorded during collection. The capture user-agent token `bran-evidence-capture` is also preserved in frozen capture code and records.

Current configuration uses `OVERTURN_BIN`, `OVERTURN_CORPUS_CACHE`, `OVERTURN_CLAUDE_BIN`, and `OVERTURN_OLLAMA_LOG`. The tools accept `BRAN_CORPUS_CACHE`, `BRAN_CLAUDE_BIN`, and `BRAN_OLLAMA_LOG` only as compatibility fallbacks; the corresponding `OVERTURN_*` value takes precedence. Current Rust code uses `OverturnCompiler`; the former type alias has been removed.
