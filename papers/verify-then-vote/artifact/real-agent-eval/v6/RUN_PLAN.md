# Eval v6 run plan

This document records the revision-3 collection plan accompanying
`PREREGISTRATION.md`. The experiment is complete; its released results are in
`results/conf/`. Planning steps and estimates below describe the original process,
not work required to reanalyse the release. For reproduction from sealed records,
use `make secondpool-reanalysis` from the artifact directory.

- VV/VDF is the primary method (F1), and BE-G is the replication family (F2).
- A secondary alias grader (G-AK+A) is included.

Commands below use a POSIX shell and run from `papers/verify-then-vote/artifact/`.
Collection needs the pinned models, corpora, and hosted checker; the frozen-file
checks also require the publication compatibility procedure in `FROZEN_REDACTIONS.md`.
Do not run collection over the released result directories. Use an isolated copy
for any new collection. Public setup paths replace the original machine-specific
paths; the publication hash mapping records this documentation change.

```sh
# Starting from the public repository root:
cd papers/verify-then-vote/artifact
PY=".venv/bin/python -I"                # install artifact requirements in this environment
V5=real-agent-eval/v5; V6=real-agent-eval/v6
CHECKER=f2a14bd8988371bd231ca6ff137be13e
export BRAN_CLAUDE_BIN="${BRAN_CLAUDE_BIN:-claude}"  # CLI 2.1.307 on PATH or explicit executable
```

## 0. Preconditions (5 min)

```sh
ollama --version                       # must print 0.17.7 (v5 pin); do not upgrade
pgrep -fl "collect_v|ollama run"       # nothing else on Ollama
df -h .                                # allow space for the ~12.3 GB pool and copied caches
"$BRAN_CLAUDE_BIN" --version             # must report CLI pin 2.1.307
shasum -a 256 $V5/frozen-bin/bran      # af420a5d...045e (released frozen executable)
```

## 1. Pull the pool and fill the digests (about 15–30 min, mostly download)

```sh
for m in falcon3:3b olmo2:7b exaone3.5:7.8b nemotron-mini:4b granite3.3:2b; do ollama pull "$m"; done
for m in falcon3:3b olmo2:7b exaone3.5:7.8b nemotron-mini:4b granite3.3:2b; do ollama show "$m" --license | head -3; done
curl -s localhost:11434/api/tags | python3 -I -c '
import json,sys
want=["falcon3:3b","olmo2:7b","exaone3.5:7.8b","nemotron-mini:4b","granite3.3:2b","nomic-embed-text:latest"]
t={m["name"]:m for m in json.load(sys.stdin)["models"]}
out={"format":"bran-v6-pool/1","model_digests":{w:{"digest":t[w]["digest"],
     "quantization":t[w]["details"].get("quantization_level"),
     "parameter_size":t[w]["details"].get("parameter_size")} for w in want}}
print(json.dumps(out,indent=1,sort_keys=True))' > $V6/pool_manifest.json
```

Copy each digest into the `[[POOL: …]]` slots of `PREREGISTRATION.md` §4.1. The
nomic-embed-text digest must still be `0a109f422b47…`, as in v5. The v5 models stay installed.
Deleting them is not needed.

Before the dev run, add `real-agent-eval/v6/results/*/evidence-cache/` and
`real-agent-eval/v6/results/*/eval/rust/` to `.gitignore`. This mirrors the v5 lines. It is the only
edit to an existing file, and the author makes it.

## 2. Write the v6 wrappers (no v5 file is edited)

### 2.1 Why `collect_v5.py` cannot run a new pool as it is

- `MODELS` is hardcoded to the v5 list.
- `verify_digests()` compares every model's `/api/tags` digest with
  `v3/results/run_manifest.json` → `model_digests`, which is v5's pool. It aborts with "model digest
  mismatch vs v3 run manifest", or with "missing" for any model not in that file.
- `FREEZE` points to `v5/FREEZE.json`. `--split conf` therefore checks v5's freeze, which lacks the
  v6 files.
- The default `--out` is `v5/results/<split>`. With v5's raw records present, the resume path would
  skip every item, then abort on "resume dispatch-order mismatch", because the model names differ. A
  wrapper must make `--out` mandatory and under `v6/results/`.

Everything else carries over. The prompts, schemas and item files resolve from `collect_v5.HERE`,
which is v5, so they are byte-identical to v5's. `retriever_assignment`, `closed_book_set`,
`run_item` and `cmd_audit` read the module-global `MODELS` at call time, so patching the global is
enough. The dispatch shuffle and the SciFact dense split permute list positions, so the v6 agent in
position k inherits v5 position k's slots (prereg §4.1).

### 2.2 `collect_v6.py` (sketch; write, test on dev, then hash)

```python
#!/usr/bin/env python3
"""Eval v6 collector: the frozen v5 collector with the v6 pool. Overrides constants only."""
import importlib.util, sys
from pathlib import Path

V6 = Path(__file__).resolve().parent
V5 = V6.parent / "v5"
MODELS_V6 = ["falcon3:3b", "olmo2:7b", "exaone3.5:7.8b", "nemotron-mini:4b", "granite3.3:2b"]  # v5 positions

spec = importlib.util.spec_from_file_location("collect_v5", V5 / "collect_v5.py")
C = importlib.util.module_from_spec(spec); spec.loader.exec_module(C)
C.MODELS = MODELS_V6
C.V3_MANIFEST = V6 / "pool_manifest.json"          # same {"model_digests": {m: {"digest"}}} shape
C.FREEZE = V6 / "FREEZE.json"
C.CONF_FROZEN = C.CONF_FROZEN + ["real-agent-eval/v6/collect_v6.py", "real-agent-eval/v6/pool_manifest.json",
                                 "real-agent-eval/v6/PREREGISTRATION.md"]

if __name__ == "__main__":
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    if sub not in ("audit", "judge-inputs", "build-dense"):
        if "--out" not in sys.argv:
            sys.exit("ABORT: v6 requires an explicit --out under real-agent-eval/v6/results/")
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
        if V6 / "results" not in out.parents:
            sys.exit(f"ABORT: --out {out} is not under {V6 / 'results'}")
    if sub == "build-dense":
        sys.exit("ABORT: v6 reuses the v5 dense index unchanged")
    C.main()
```

The session record keeps `collect_v5_py_sha256`, which is the hash of the frozen v5 file. The
wrapper's own hash is checked through `FREEZE.json`, because `CONF_FROZEN` now includes it. The
abort text "vs v3 run manifest" is cosmetic; the file it compares against is
`v6/pool_manifest.json`.

### 2.3 The other wrappers

| file | content |
|---|---|
| `post_collect_v6.py` | Load `post_collect_v5` by path. Set `OUT = V6/results/conf`. Replace `step_checks` with the same four `run_checks_v5.py` calls, each adding `--out $V6/results/conf --cache $V6/results/conf/evidence-cache --raw-dir $V6/results/conf/raw`. Everything else (`inputs`, `judges`, `regen`, `loao`, `local`, `rows`) derives its paths from `OUT`. The CLI pin check and the 1,100-record check are kept. |
| `evaluate_v6.py` | Load `evaluate_v5` by path. Set `E.PREREG_BEST = "<v6 BEST agent id>"`. Verify every hash in `v6/FREEZE.json`. Run `E.main(argv)`. That gives F2 (H1a-rep, H1b-rep, H3a-rep, H3b-rep), H4 and H5, exactly as v5. **Then** run `vdf_v6.run(argv-derived inputs, eval_dir)`, which writes `evaluation_v6_vdf.json`. The v5 guard still checks `evaluate_v5.py` and the binary against `v5/FREEZE.json`, and both are unchanged. |
| `vdf_v6.py` (**new; needed for F1**) | Rule `vdf-1` (prereg §5.2), adapted from `v5/selector_study/selector_study.py`. It rebuilds each eligible item with `E.prepare_item`. It takes W from `E.supports_effective` (accepted checker only). It reads MAJ, VV, BE-G and D objects from the evaluator's `paired_decisions_v5.csv`, and asserts BE-G and D against `E.mirror`. Then VV/VDF = MAJ if MAJ ∈ W else VV, and BE-G/VDF = D if D ∈ W else BE-G. It grades with the evaluator's correctness columns. It writes: F1 (H1a-VDF McNemar at α 0.05, then H3a-VDF CP only if step 1 rejects with b > c); the BE-G/VDF secondary; VV/VDF on T (Newcombe, −0.03); the VDF H4 rows (c_D ⊆ F); and the 15-item design-set exclusion (list sha256 `b675a5e6…3832`). It has a `--reproduce-v5` mode for the gate in §2.4 below. |
| `local_checks_v6.py` (**new; not used: the arm was removed, prereg §2.5**) | MiniCheck driver. It reads `$O/checks_plan.jsonl` (cited pairs only) and builds `minicheck_check`'s checker from `minicheck_pin.json`. It asserts checker_id `98751cc07911d57a1586848dfb8c4e7b` and digest `66607904…7a00` against `/api/tags`, then calls `run_checks_v5.run_checks(plan, checker, cache, cache)`. Output: `$O/checks_local.jsonl`. |
| `build_alias_items_v6.py` (**new**) | Writes `items_confirmatory_aliases.jsonl`: the v5 item file with `gold.aliases` ∪ `aliases.json[id]` on PopQA items, and nothing else changed. It asserts the input sha256 `38987c42…` and the aliases sha256 `77d1fce0…`, and runs the G-AK gold-consistency check on all 1,100 items. It is deterministic. |
| `futility_v6.py` (**new**) | The look on VV/VDF. It runs the frozen BE-G reduction only to get D and W, then calls `vdf_v6` and prints b and c for VV/VDF vs MAJ on the decisive P conflicts of the first 300 items. Nothing else is printed. |
| `make_results_v6.py` | Load `make_results` by path and patch the BEST label string. Render F1 from `evaluation_v6_vdf.json` first, then call v5's `main` for F2 and the rest, relabelling its H1/H3 headings "-rep". Then add the secondary block (BE-G/VDF, VV/VDF on T, H3a-pool). |
| `qualify_v6.py` | Run on the dev raw records. Q1 and Q2 come from `parse_audit.json` and the answer-turn `ollama_meta`. Q3 is the citing rate. Q4 and Q5 are yield and m, from `evaluate_v5` helpers (`load_items`, `response_view` and G-AK grading). BEST is `max(sorted(agents), key=correct)`. Output: `results/dev/qualification_v6.json`. No hosted calls. |
| `pooled_h3a_v6.py` | Read `prereg.H3a` of the v5 and v6 `evaluation_v5.json` (c, n_R and the per-item rows from `paired_decisions_v5.csv`). Compute the exact pooled CP test, the dependence-robust bound, the count of items that are c-events in both pools, the item-cluster bootstrap and the §2.4 cross-pool table. Reuse `power_v6.cp_upper`. |

**Tests.**

- `$PY $V5/evaluate_v5.py --selftest`.
- `evaluate_v6.py --synthetic-test` on the v5 synthetic fixtures (`v5/tests/synth_v5.py`).
- `collect_v6.py --split dev --out $V5/results/x` must abort.
- `collect_v6.py --split conf …` must abort until `FREEZE.json` is frozen.
- A unit test for `pooled_h3a_v6.py`: 12/376 + 13/376 rejects, and 12/376 + 14/376 does not.
- A unit test for `vdf_v6.py` on hand-built items covering each branch:
  - MAJ ∈ W;
  - MAJ ∉ W with W ≠ ∅;
  - W = ∅;
  - a tied verified plurality, which takes the `v5-vv:` seed;
  - D ≠ MAJ on a tied majority.

### 2.4 VDF reproduction gate on v5 data (binding before the freeze; local, $0)

This step reads only already-unblinded v5 data. It makes no model or hosted call, and does not run
the binary.

```sh
$PY $V6/vdf_v6.py --reproduce-v5 --eval-dir $V5/results/conf/eval --raw-dir $V5/results/conf/raw \
   --captures $V5/results/conf/captures.jsonl --checks $V5/results/conf/checks.jsonl \
   --items $V5/benchmark/items_confirmatory.jsonl --expect $V5/selector_study/results.json \
   --out $V6/results/vdf_reproduction_v5.json
```

The step must match `selector_study/results.json` per item and in aggregate:

| set | method | acc | b / c vs MAJ | other |
|---|---|---|---|---|
| P | VV/VDF | .8726 | 87 / 4 | UB .0270 |
| P | BE-G/VDF | .8688 | 87 / 6 | c_D 4, UB .0344 |
| T | VV/VDF | | 6 / 1 | |
| T | BE-G/VDF | | 9 / 1 | |

Any mismatch blocks the freeze.

## 3. Seed the caches (allow disk space for ordinary copies)

```sh
mkdir -p $V6/results/conf
cp -R $V5/results/conf/evidence-cache  $V6/results/conf/evidence-cache
cp -R $V5/results/conf/judge-store-cbs $V6/results/conf/judge-store-cbs
find $V6/results/conf/evidence-cache -type f | wc -l     # record in FREEZE.json
find $V6/results/conf/judge-store-cbs -type f | wc -l
```

The v5 caches are only read and never written to. The J and RS stores start empty, because their
prompts contain the new agents' answers.

## 4. Pool qualification on v5 dev (about 1.1 h local, $0)

```sh
$PY $V6/collect_v6.py --split dev --out $V6/results/dev            # 160 items x ~25 s
$PY $V6/collect_v6.py audit --out $V6/results/dev                   # parse_audit.json
$PY $V6/qualify_v6.py --raw-dir $V6/results/dev/raw --out $V6/results/dev/qualification_v6.json
```

If an agent fails Q1–Q3, pull its first alternate (prereg §4.1). Edit `MODELS_V6` and
`pool_manifest.json`, then re-run the dev collection into a fresh `--out $V6/results/dev_alt1`. Q1–Q3
are judged for the replacement, and Q4–Q5 for the new pool. Record BEST.

## 5. Freeze (author)

Write `$V6/FREEZE.json` (format `bran-v6-freeze/1`). It contains:

- v5's 56 `sha256` entries;
- `v5/FREEZE.json`, `post_collect_v5.py` and `futility_look.py`;
- `v5/results/conf/eval/evaluation_v5.json`;
- every v6 file of prereg §12.2;
- `identities`: v5's, plus the pool digests and BEST;
- the cache file counts.

Fill the `[[POOL]]` slots, empty `pending`, set status FROZEN, add this prereg's sha256, then commit.
Do not push without the author's explicit go.

## 6. Confirmatory collection (about 8 h local, $0)

```sh
nohup $PY $V6/collect_v6.py --split conf --n-items 1100 \
    --out $V6/results/conf > $V6/results/conf_collect.log 2>&1 &
```

**Futility look**, once `find $V6/results/conf/raw -name '*.json' | wc -l` reaches 300. Collection
keeps running, as in v5.

```sh
python3 -I -c 'import json,sys; it=sorted((json.loads(l) for l in open(sys.argv[1])), key=lambda x:x["order"])[:300]
open(sys.argv[2],"w").writelines(json.dumps(x,ensure_ascii=False)+"\n" for x in it)' \
  $V5/benchmark/items_confirmatory.jsonl $V6/results/conf_futility/items_first300.jsonl
mkdir -p $V6/results/conf_futility/raw
find $V6/results/conf/raw -name '*.json' | while read f; do      # link the first 300 by id
  id=$(basename "$f" .json); grep -q "\"id\": \"$id\"" $V6/results/conf_futility/items_first300.jsonl && ln -sf "$PWD/$f" $V6/results/conf_futility/raw/; done
RC="$PY tools/evidence/support/run_checks_v5.py"
A="--split conf --items $V6/results/conf_futility/items_first300.jsonl --raw-dir $V6/results/conf_futility/raw \
   --out $V6/results/conf_futility --cache $V6/results/conf/evidence-cache"
$RC captures $A && $RC plan $A --gold-scope none
DISABLE_AUTOUPDATER=1 $RC --claude-bin "$BRAN_CLAUDE_BIN" check $A \
   --workers 6 --retries 2 --max-usd 15 --expect-checker $CHECKER
$PY $V6/futility_v6.py --items $V6/results/conf_futility/items_first300.jsonl \
   --raw-dir $V6/results/conf_futility/raw --captures $V6/results/conf_futility/captures.jsonl \
   --checks $V6/results/conf_futility/checks.jsonl --bin $V5/frozen-bin/bran --out $V6/results/conf_futility
```

The rule is in prereg §8.2. If VV/VDF's b − c ≤ 0, stop the collector (`pkill -f collect_v6.py`) and report.
The look shares the v6 evidence cache, so the final check step reuses its labels.

## 7. Post-collection (about 1.5 h: hosted ≈ 45 min, J_local ≈ 1.3 h in parallel)

```sh
$PY $V6/collect_v6.py audit --out $V6/results/conf
python3 -I $V6/post_collect_v6.py --steps checks,inputs,judges,regen,loao,rows
python3 -I $V6/post_collect_v6.py --steps local,rows     # optional, exploratory J_local (mistral, non-participant)
```

## 8. Evaluate once (≤ 1 h), then render

```sh
O=$V6/results/conf
$PY $V6/evaluate_v6.py --split conf --bin $V5/frozen-bin/bran \
   --items $V5/benchmark/items_confirmatory.jsonl --raw-dir $O/raw \
   --captures $O/captures.jsonl --checks $O/checks.jsonl --judge $O/judge.jsonl \
   --judge-local $O/judge_local.jsonl --local-judge-agent mistral \
   --accepted-checker $CHECKER --be-g-config member/nei0.5/gated --be-config member/nei0.1 \
   --best-model <BEST from qualification_v6.json> --expect-judge-id CB-S=1de78d843c35f57cfa9d2ebfd708f681 \
   --out $O/eval                     # F2 + H4/H5 via frozen evaluate_v5, then F1 via vdf_v6 -> $O/eval/evaluation_v6_vdf.json
# secondary grader (same frozen evaluator, second run)
python3 -I $V6/build_alias_items_v6.py --items $V5/benchmark/items_confirmatory.jsonl \
   --aliases $V6/tuning/aliases/aliases.json --out $V6/results/items_confirmatory_aliases.jsonl
$PY $V6/evaluate_v6.py <same flags as above> --items $V6/results/items_confirmatory_aliases.jsonl --out $O/eval_aliases
$PY $V6/make_results_v6.py --eval $O/eval/evaluation_v5.json --vdf $O/eval/evaluation_v6_vdf.json --out $O/RESULTS.md
$PY $V6/pooled_h3a_v6.py --v5 $V5/results/conf/eval --v6 $O/eval --out $O/pooled_h3a_v6.json
```

Drop `--judge-local` if step 7's `local` was skipped.

## 9. Estimates

### 9.1 Wall time

From the v5 raw records (`item_wall_s`, 1,100 items), v5 collection took **8.03 h** in total. The
median was 24.4 s per item, the p95 37.4 s, and one outlier took 369.5 s while capture ran
concurrently. The new pool is of similar size (12.3 GB against 12.1 GB). olmo2:7b takes mistral's
role, nemotron-mini:4b is slightly larger than phi3:mini, and the rest are 2–3 B.

| step | estimate |
|---|---|
| pulls | 15–30 min (≈ 12.3 GB download) |
| wrappers + tests (incl. `vdf_v6.py` + v5 reproduction gate) | 3–5 h of author or agent time |
| dev qualification (160 items) | ≈ 1.1 h |
| confirmatory collection (1,100 items) | **≈ 8 h (range 7.5–10 h)** |
| futility look (captures + ~400–700 live checks) | ≈ 20–30 min, concurrent with collection |
| post-collect hosted (checks, J, RS, CB-S, regen, LOAO) | ≈ 45 min (v5: checks 26 min for 2,850 calls; judges ≈ 25 min) |
| J_local (optional) | ≈ 1.3 h (702 × 6.8 s in v5) |
| second evaluator run (alias grader) | ≤ 1 h |
| evaluate + render | ≤ 1 h |
| **total elapsed** | **≈ 12–14 h**, mostly unattended local time |

### 9.2 Hosted cost

**v5 actuals.**

- **Checks.** 7,249 live calls cost **$34.09** (RUN_NOTES note 9, from the three call logs).
  - Cited checks: 4,742 calls, $22.74, $0.0048 each.
  - Gold-shown diagnostics: 2,506 calls, $11.35, $0.0045 each.
- **Judges.** Per decision over 702 disagreement items (RESULTS.md, pooled): J $0.0142 → $9.97, RS
  $0.0152 → $10.67, CB-S $0.0044 → $3.09. J regeneration (200) cost ≈ $2.86 and J LOAO (50 × 5) ≈ $3.55.
  The judges total ≈ **$30.1**.
- **v5 hosted total ≈ $64.**

**Cache overlap estimate, from v5 data.** For each split of the five v5 agents into groups, we
measured the share of one group's unique cited (item, proposition, passage) keys that the other
group also cited:

| keys | 1 agent vs the other 4 | 2 agents vs the other 3 |
|---|---|---|
| cited | 0.54–0.69, mean 0.64 | 0.45–0.58, mean 0.52 |
| shown (gold diagnostic) | mean 0.78 | mean 0.67 |

A new 5-agent pool against v5's 5-agent cache falls between these. We assume a cited hit rate of
**0.40–0.60** (central 0.50), and a gold-shown hit rate of **0.55–0.70**. Both are discounted
because a new family may phrase queries differently.

| item | with item reuse (recommended) | fresh items, no cache |
|---|---|---|
| cited checks | 4,740 × (1 − 0.5) × $0.0048 ≈ **$11.4** ($9.1–13.7) | ≈ $22.7 |
| gold-shown diagnostic checks | 2,506 × (1 − 0.65) × $0.0045 ≈ **$4.0** ($3.4–5.1) | ≈ $11.4 |
| J + RS (all disagreement items) | ≈ $20.6 | ≈ $20.6 |
| J regeneration + LOAO | ≈ $6.4 | ≈ $6.4 |
| CB-S (only items not in v5's 702 disagreement set) | ≈ $0.9 ($0.6–1.5) | ≈ $3.1 |
| **total** | **≈ $43 (range $40–47)** | **≈ $64** |

**Scaling risk.** A family-disjoint pool may disagree on more items than v5's 702. Judge cost scales
with the number of disagreement items, and check cost with the number of citations. At 900
disagreement items and 30% more citations, the reuse total is ≈ $55. Ask for a **$60 cap**
(`--max-usd` stays on every check step). This is the same order as v5's approved G3 of $50–60.

**VDF and the alias grader add no hosted cost.** It is a deterministic rule over labels the run already has.

**Reporting.** Because cached labels carry `cost_usd: null` in `checks.jsonl`, the evaluator's
"$ / decision" for BE-G, BE and VV would show only the marginal v6 spend. Report it as marginal
**and** as full-label cost, priced from the v5 + v6 call logs (prereg §7). This avoids repeating
v5's RUN_NOTES note 9 correction.

## 10. Things that can go wrong (and the pre-declared response)

| risk | response |
|---|---|
| A 4K-context agent (olmo2, nemotron-mini) truncates or overflows | Q2 in qualification; swap in the alternate |
| An agent rarely cites (no verifiable evidence) | Q3; swap in the alternate |
| The pool agrees too much (yield < 0.30 or m < 0.20) | stop before the freeze (Q4/Q5) |
| The CLI auto-updates mid-run (it did in v5) | the pinned binary, plus `DISABLE_AUTOUPDATER=1`; `--expect-checker` refuses any other checker_id |
| Disk: the pool adds about 12.3 GB, plus copied caches and collected outputs | check free space before step 6 |
| The v5 raw dir is overwritten by accident | `collect_v6.py` refuses any `--out` outside `v6/results/` |
| `vdf_v6.py` disagrees with the selector study on v5 data | the freeze is blocked until it is fixed (§2.4); `selector_study.py` is the reference |
