# Eval v5 benchmark (Swarm 3, lane L4)

Built by `build_benchmark_v5.py` (`v5-benchmark-1.0.0`, seed **20261201**) to the spec in
`v3/SWARM3_DESIGN.md` §4, §6.2 and §8. Every gold answer is copied from the source dataset. No
model was called, no model output was read, and no accuracy was computed on any item. The only
grading run was a gold-consistency check: G-AK, given each item's own gold answer, grades it correct
on all 1,560 items.

Rebuild from the repo root. The outputs are byte-identical, and their hashes are in `manifest.json`.

```
python3 -I real-agent-eval/v5/benchmark/build_benchmark_v5.py \
  --v4-benchmark real-agent-eval/v4/benchmark \
  --validation tools/evidence/support/validation \
  --v4-conf-run-manifest real-agent-eval/v4/results/conf/run_manifest.json \
  --out real-agent-eval/v5/benchmark
```

The builder reads the local v4 downloads only (`real-agent-eval/v4/benchmark/downloads/`) and
does not use the network. It runs four checks and stops if any fails:

- it compares every download against the sha256 recorded in the v4 manifest;
- it loads the frozen v4 builder read-only by path and rebuilds the v4 eligible pools;
- it confirms that both v4 item files match the rebuilt pool records field for field;
- it asserts every exclusion below.

## Files

| file | content |
|---|---|
| `items_dev.jsonl` | 160 items: the v4 dev split, re-rendered for open retrieval, in v4 dev order |
| `items_confirmatory.jsonl` | 1,400 items in frozen `order` 0–1399: `primary` 0–999, `extension` 1000–1399 |
| `reserve_order.json` | the unused fresh items per source, in frozen seeded order (for any pre-declared quota move) |
| `exclusion_proofs.json` | each exclusion set (n, sha256 of sorted ids), the required-zero intersections, disclosures, and the v4 Stage B check |
| `manifest.json` | sources, licences and file hashes, pool accounting, stratification, composition, input and output hashes, script sha256 |

## Counts

| source | dev | primary | extension | fresh pool | unused reserve |
|---|---|---|---|---|---|
| TruthfulQA MC1 | 40 | 300 | 160 | 551 | 91 |
| SciFact (open retrieval) | 40 | 250 | 0 | 275 | 25 |
| PopQA | 40 | 250 | 133 | 1,024 | 641 |
| FEVER | 40 | 200 | 107 | 6,161 | 5,854 |
| **total** | **160** | **1,000** | **400** | | |

Composition by stratum:

- **Primary.** SciFact 201 SUPPORTED / 49 REFUTED. PopQA 84 / 83 / 83 across the strata [1e3, 1e4),
  [1e4, 1e5) and ≥ 1e5. FEVER (unstratified) 101 SUPPORTED / 99 REFUTED.
- **Extension.** PopQA 44 / 45 / 44 across the same strata. FEVER 47 SUPPORTED / 60 REFUTED.
- **Interleaving.** Sources are interleaved by a smooth weighted round-robin. In both tiers, every
  prefix of the order is within 0.7 items of the quota proportions, so any prefix chosen by the
  stopping rule (I ∈ [1,000, 1,400]) is balanced.
- **Extension split.** The extension's 400 items are split across TQA, PopQA and FEVER in
  proportion to their primary quotas (300 : 250 : 200, giving 160 / 133 / 107). The design says
  only that the extension draws on these three sources.

## Fresh pool and exclusions

The fresh pool is the v4 eligible pool (same mechanical eligibility rules, see
`v4/benchmark/BENCHMARK.md`), minus the following:

1. **v4 dev (160).** These items become v5 dev.
2. **v4 confirmatory primary (600), which is v4 Stage B.**
   - `run_manifest.json` requested exactly these 600 items (`--n-items 600`), so the 400 v4
     *extension* items were never collected.
   - The extension items stay eligible, as the design's pool counts assume.
   - 225 v5 confirmatory items come from that uncollected v4 extension: TQA 83, SciFact 91, PopQA
     45, FEVER 6. Field `v4_tier = "extension_uncollected"` marks them.
3. **All SciFact claims used by the support checker.**
   - Sources: `slice.jsonl`, `pilot.jsonl`, and the `base_id`s in `injection.jsonl`, 340 claim
     ids in total.
   - 227 of them are in the eligible pool (114 SUPPORTED, 113 REFUTED). The other 113 are NEI and
     were never eligible.
4. **Text matches.** Any item whose normalized question or claim text equals the text of an
   excluded item. This removed FEVER 11 and SciFact 1.
5. **Same-text conflicts.** Items whose text appears again in the pool with a different gold label,
   all dropped (FEVER 5).
6. **Within-pool duplicate texts.** The lowest id is kept (FEVER 138).

These intersections are asserted to be 0 (`exclusion_proofs.json` → `required_zero`):

- confirmatory against v4 dev, v4 primary, v4 Stage B requested, the validation claims and v5 dev,
  checked by id and also by text where applicable;
- duplicates inside the confirmatory set;
- reserve against confirmatory.

Disclosed: v5 dev overlaps neither the validation claims nor v4 primary (both 0).

## Item fields (what L3, L5 and L7 consume)

- **Identity.**
  - `id` = `v5-<sid>`. This is the lowering subject: the design's `(v5-<id>, answer, …)` means
    this id. Use the id as is with `Random("v5-cb:"+id)` and `Random("v5-judge:"+id)`.
  - `v4_id` = `v4-<sid>`. For dev it pairs the item with its closed-book v4 run.
- **`corpus`.** Routes retrieval: `scifact` for SciFact items, `fever17` for all other items
  (design §2.2). The routing uses gold-blind metadata.
- **Question and options.**
  - `question`: the TQA question, PopQA question, or FEVER/SciFact claim C.
  - `options` (TQA only): v4's frozen shuffle, reused so dev stays paired.
- **Answer format.**
  - `answer_format` (`letter`, `supported_refuted` or `entity`) is unchanged from v4, so v4
    `answer_key.py` (G-AK) grades v5 items without modification.
  - `answer_schema` is the per-item fragment for the §3.3 `answer` property: the item's letters,
    `["SUPPORTED","REFUTED"]`, or `{"type":"string","maxLength":60}` for PopQA.
- **Proposition inputs (§3.4).**
  - FEVER and SciFact use `question`.
  - TQA uses `options[].text`.
  - PopQA uses `source.subj` and `source.prop`; `subj` was lifted from v4's readability triple.
- **Strata.** `stratum` is the PopQA popularity stratum, or the gold label for FEVER and SciFact,
  or `all` for TQA. It is metadata for reporting.
- **Gold.**
  - `gold.answer` and `gold.aliases`. The aliases are PopQA `possible_answers` verbatim.
  - `gold.evidence_sentences` (FEVER `[page, sentence_id]`) and `gold.evidence_doc_ids`
    (SciFact) are for diagnostics only, never for retrieval or the corpus.
  - `gold_triples` holds one graded triple. SciFact uses G-SCI-1o: every evidence abstract of the
    claim agrees, so the label is well defined under open retrieval.
- **Bookkeeping.** `split`, `tier` (`dev`, `primary` or `extension`), `order`, `build_version`,
  `contested_rationale` and `review_note`.

**Gold-bearing fields that the harness must never show an agent, the checker or the judge:**

- `gold`, `gold_triples` and `options[].correct`;
- `source.label`, `source.doc_id` and `source.n_evidence_docs`;
- `source.obj_wikidata`;
- `source.reference_url` (TruthfulQA), which also must not enter the corpus (design §7.4);
- `stratum` for FEVER and SciFact, and `contested_rationale`.

**No prompts are rendered here.** L3 owns `v5/prompts/`. In particular, SciFact items no longer
carry the abstract (`context`). This is the "re-rendered without SciFact abstracts" dev of §4.

## Deviations from the design and open points

1. **SciFact fresh pool is 275, not 283.**
   - The design subtracted 220 validation claims. The actual overlap with the eligible pool is
     227, because 7 eligible claims are injection-suite bases. One further claim is a text
     duplicate of an excluded claim.
   - 275 ≥ 250, so the primary quota holds, and 25 SciFact items remain unused in reserve.
   - The extension draws no SciFact items, as the design specifies.
2. **SciFact primary is REFUTED-light: 49 of 250 (20%).** v4 primary was 36% REFUTED.
   - The checker validation consumed 113 of the eligible REFUTED claims, leaving 54 fresh.
   - The stratification is proportional to the fresh pool (largest remainder).
   - The design highlights REFUTED gold as the strongest majority-wrong regime (77%). The
     integrator may prefer a pre-declared rule taking all 54 REFUTED (54 / 196). That would also
     be gold-label stratification, not model-based selection, but it is not what this build does.
     Flag before the freeze.
3. **FEVER is not stratified by label.** The design names label strata only within SciFact.
   Primary is close to balanced (101 SUPPORTED / 99 REFUTED).
4. **TQA switch (§2.2).** If TQA evidence availability on dev is below 30%, TQA's quota moves to
   PopQA and FEVER. The design does not give the split. `reserve_order.json` freezes the next
   items per source, so the move can be pre-declared as "take the next k items of PopQA and FEVER
   from the reserve, in order". The integrator must fix k (for example 150 / 150) in the prereg.
5. **The FEVER checker-validation slice (L5) is not yet drawn.** L5 must draw it outside every
   FEVER id in these files. The sha256 of the dev and confirmatory id sets is available from the
   files themselves, and the reserve is listed. Its claims should come from the FEVER reserve
   tail or from outside paper_dev, never from these 347 FEVER items.

## Licences

The item files mix licences:

- FEVER-derived lines: CC BY-SA 3.0, with share-alike;
- SciFact claims: CC BY 4.0; abstracts: ODC-By 1.0;
- TruthfulQA: Apache-2.0;
- PopQA: MIT, with facts from Wikidata (CC0).

Per-source versions and file hashes are in `manifest.json` → `sources`.
