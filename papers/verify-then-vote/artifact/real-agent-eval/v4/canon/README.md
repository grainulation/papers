# Object canonicalization for a fair majority baseline

In v3 (`../../v3/RESULTS.md`, paper §9.2.1), majority vote gave the same correctness as
first-member on 26/26 eligible sets, because extracted objects rarely repeat verbatim. Some
"conflicts" were also formatting-only ("**Canberra**" vs "Canberra"). This component adds a
deterministic, rule-based object canonicalizer. It applies the canonicalizer identically
before Python conflict-set construction, majority vote and the Rust reducer input, then
re-runs the v3 analysis on both datasets (v3 and v1orig). All numbers are in `RESULTS.md`,
which is generated.

## Files

| file | what it is |
|---|---|
| `canon.py` | The canonicalizer. `canon(str) -> str`, `CANON_VERSION = "canon-1.0.0"`. Rules R1–R15 are in its docstring: markdown, citations, contractions, case, number grouping and number words, units after a number, approximation hedges before a number, redundant and acronym parentheticals, punctuation, articles, plural → singular, and a two-entry synonym table that cites its sources. No ML, no network. |
| `test_canon.py` | 27 unit tests. They cover required merges, adversarial non-merges (negation, differing numbers, quantifiers such as "up to" or "more than", http/https, "a second", bare `m`/`g`) and invariants over all 2,029 extracted objects: deterministic, idempotent, Rust/Python keyings are the identity on the output, negation count is preserved, output is non-empty. |
| `run_canon.py` | Imports `../../v3/evaluate_v3.py` unmodified and re-binds its module globals for this process only: `OUT`, `build_contribs`, `DEFAULT_POLICY` and `correct`. It runs `evaluate_v3.analyse` in `raw` mode (a reproduction check) and in `canon` mode. It calls the same `overturn --reduce` path. |
| `make_results.py` | Renders `RESULTS.md` from `results/`. |
| `results/evaluation_canon.json` | All statistics for both modes and datasets, plus the seal: `CANON_VERSION`, the sha256 of `canon.py`, `run_canon.py`, `evaluate_v3.py` and the binary, the bootstrap seed, and the synonym table. |
| `results/{raw,canon}/` | The v3 output layout per mode: `rust/<ds>/<qid>/<policy>.{in,out}.json`, `paired_decisions_*`, `separation_margins_*`, `equivalence_*` and `precision_adjudication_*`. |
| `results/conflict_sets_raw_vs_canon_<ds>.csv` | One row per raw Python contradiction set. Each row has the distinct-object counts, whether the set dissolved, majority top count, strict plurality, whether majority equals first, and eligibility/decisiveness per grader. |
| `results/merge_audit_<ds>.csv` | Every canonical class that merged more than one distinct raw string, with each member's grade under both graders. |
| `results/canon_map_<ds>.csv` | Every contribution's object: raw, canonical, and Rust `normalize_object`. |
| `results/test_canon.txt` | Unit-test log for the reported run. |

## Exact commands

```sh
cd real-agent-eval/v4/canon
BIN=<scratch>/bran-v3-eval
shasum -a 256 "$BIN"     # 263469c2...136df83 (the v3 binary)

python3 -B -m unittest -v test_canon > results/test_canon.txt 2>&1
python3 -B run_canon.py --bin "$BIN" --bootstrap 10000 --seed 42 \
        > results/run_stdout.txt 2> results/run_stderr.txt      # about 20 s
python3 -B make_results.py
```

`-B`, together with `sys.dont_write_bytecode` in `run_canon.py`, keeps `__pycache__` out of
the read-only `v3/` directory.

## Method notes

- **Where canonicalization applies.** Each contribution is built exactly as in v3:
  `evaluate_v3.build_contribs`, which runs `evaluate_v2.load_contributions` (truncation
  filter and evidence association). After that, `object := canon(object)`. Contribution ids
  are hashed from the raw object, so they match v3 one-to-one. The canonical object is the
  only object seen by `evaluate_v1.detect_conflicts`, `evaluate_v2.majority_idx`, the Python
  mirror and the Rust input `canonical_form.object`. The forced-policy groups are built from
  it. The three `incompatible_values` fixture strings in the default policy are
  canonicalized the same way, so the native policy hash changes.
- **Graders see the raw object.** Canonicalization changes what reducers compare, never what
  is judged. The merge audit lists the classes whose members the lexical graders score
  differently: 3 classes under the original grader and 1 under the stricter grader, over
  both datasets.
- **Consistency with Rust.** `canon()` output is lowercase and single-spaced, so the
  following are all the identity on it (tested over all 2,029 objects):
  - `ir.rs normalize_object` (whitespace collapse plus lowercase);
  - `compiler.rs value_key` (lowercase);
  - `evaluate_v1.conflict_key`/`detect_conflicts` (`lower().strip()`).

  Before canonicalization, Python (`lower().strip()`) and Rust (whitespace collapse) could
  key objects differently. They cannot afterwards. The Rust binary is unchanged.
- **Objects only.** Subjects and predicates are untouched, so the (subject, predicate) groups
  are identical and only a set's contradiction/redundancy type and its majority can change.
- **Reproduction check.** `raw` mode reproduces `v3/results/evaluation_v3.json` exactly, for
  every summary statistic on both datasets (`RESULTS.md`, "Reproduction check").

## Not done / limits

- The rules handle formatting only. Paraphrases stay distinct, for example "a strong
  scientific consensus" vs "a high level of scientific consensus", or "not a liquid" vs "not
  a liquid; it is an amorphous solid". Semantic clustering would need a model and a new
  protocol.
- The plural rule is a suffix heuristic. When it is wrong, it fails to merge (for example
  "viruses" → `viruse` while "virus" stays `virus`). It never false-merges, as far as the
  adversarial tests reach.
