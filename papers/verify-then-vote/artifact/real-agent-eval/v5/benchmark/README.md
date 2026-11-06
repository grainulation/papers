# Eval v5 benchmark

**Current build: `v5-benchmark-1.1.0`.** This is the pre-declared TruthfulQA quota switch of
`real-agent-eval/v5/PREREGISTRATION.md` §6.1–§6.3, applied on top of the base draw
`v5-benchmark-1.0.0` (seed **20261201**; spec `v3/DESIGN.md` §4, §6.2, §8).

- The 1.0.0 outputs, script and README are kept unchanged in `1.0.0/`.
- Every gold answer is copied from the source dataset.
- No model was called and no model output was read. No accuracy was computed on any item.
- The only grading run is a gold-consistency check: G-AK, given each item's own gold answer, grades
  it correct. It passes on all 1,260 items (160 dev + 1,100 collect).

Rebuild from the repo root. The builder regenerates 1.0.0 in memory and stops unless the result is
byte-identical to `1.0.0/`. It then writes 1.1.0.

```
python3 -I real-agent-eval/v5/benchmark/build_benchmark_v5.py \
  --v4-benchmark real-agent-eval/v4/benchmark \
  --validation tools/evidence/support/validation \
  --v4-conf-run-manifest real-agent-eval/v4/results/conf/run_manifest.json \
  --out real-agent-eval/v5/benchmark
```

The outputs are byte-identical across rebuilds. This was verified with four builds under different
`PYTHONHASHSEED` values. `exclusion_proofs.json` and `manifest.json` also record the sha256 of the
v4 Stage B `run_manifest.json`, so those two files change if that input changes.

The builder reads only the local v4 downloads and never uses the network. It stops if any of these
checks fails:

- every download matches the sha256 in the v4 manifest;
- the frozen v4 builder, loaded read-only by path, reproduces the v4 pools, and the v4 item files
  match them field for field;
- the 1.0.0 rebuild is byte-identical to `1.0.0/` (dev, confirmatory and reserve);
- all five switch list hashes equal the prereg values;
- the 800 retained records equal their 1.0.0 records on every field except `order` and `tier`;
- the G-AK gold-consistency check and the answer-schema check pass;
- every `required_zero` intersection is 0.

## Files (1.1.0)

| file | content |
|---|---|
| `items_dev.jsonl` | 160 dev items, byte-identical to 1.0.0 |
| `items_confirmatory.jsonl` | **1,100 items to collect**, frozen `order` 0–1099: `collect_v5.py --split conf --n-items 1100` |
| `reserve_order.json` | unchanged from 1.0.0 (prereg §6.3 item 3). The used ids are identified by position in `manifest.json` → `switch` |
| `exclusion_proofs.json` | the 1.0.0 sets plus every validation slice; `required_zero` for the 1,100 and for the 300 added items; disclosures |
| `manifest.json` | switch parameters and list hashes, sources and licences, 1.0.0 pool accounting, composition, checks, input and output hashes, script sha256 |
| `1.0.0/` | the archived base build (1,400-item confirmatory file, its manifest, proofs, script and README) |

## The switch (1.1.0)

| source | from 1.0.0 primary | from the reserve | total | `tier` |
|---|---|---|---|---|
| SciFact | 250 (201 SUPPORTED / 49 REFUTED) | 0 | 250 | `primary` (P) |
| PopQA | 250 | `reserve.popqa[0:150]` | 400 | `primary` (P) |
| FEVER | 200 | `reserve.fever[0:150]` | 350 | `primary` (P) |
| TruthfulQA | first 100 primary items in 1.0.0 order | 0 | 100 | `tqa_stratum` (T) |
| **total** | 800 | 300 | **1,100** | |

- **Order.** A smooth weighted round-robin over the four streams with quotas 250 / 400 / 350 / 100.
  Each stream is its 1.0.0 primary order, followed by the reserve slice where one applies. Every
  prefix stays within 0.64 items of the quota mix.
- **Added records.** The 300 added items are built by the same mechanical rules (`to_v5`) and carry
  `switch_added: true` and `build_version: v5-benchmark-1.1.0`.
- **Retained records.** They keep every 1.0.0 field except `order` and `tier`, including
  `build_version: v5-benchmark-1.0.0`.
- **Strata.**
  - P: PopQA 134 / 133 / 133 across the popularity strata; FEVER 190 SUPPORTED / 160 REFUTED.
  - The 300 added: PopQA 50 / 50 / 50; FEVER 89 / 61.
  - T: 60 Adversarial / 40 Non-Adversarial.
- **List hashes.** All match the prereg. List hashes are sha256 of `"\n".join(ids) + "\n"`; set
  hashes use the same rule over the sorted ids.
  - PopQA added: `875f7a97…73c0`
  - FEVER added: `a076d664…28dc`
  - TQA stratum: `60811e82…7cc7`
  - sorted 1,100: `d649d362…19a5`
  - sorted not-collected 600: `ed08e1b0…2a05`
- **Not collected (600).** The other 200 TQA primary items and the 400 1.0.0 extension items.

**1.1.0 exclusion proofs.** All of these are asserted 0, for the 1,100 and for the 300 added items
separately:

- intersections with v4 dev, v4 primary, v4 Stage B requested and v5 dev, by id and text;
- intersections with every checker-validation slice by id: `slice`, `pilot`, `injection`,
  `scifact_slice_fresh2`, `fever_slice` and `fever_slice_fresh2`. The local checker validates on
  the fresh2 slices plus `slice.jsonl`, so it is covered;
- the same text check for the slices the 1.0.0 draw had to exclude (slice, pilot, injection);
- v5 dev against every slice by id;
- the 1,100 against the not-collected 600;
- duplicates inside the 1,100.

**Disclosed, not zero: 5 same-text collisions with `fever_slice_fresh2.jsonl` (0.2.0 validation).**

- **What collides.** FEVER paper_dev repeats claims under different ids. The checker validation excluded v5 items by
  id, so 5 slice claims have the same text as a v5 item:
  - 3 in the 1,100: `v5-fever204352`, `v5-fever144922` and `v5-fever168961`, orders 112, 87 and
    656 of 1.0.0 primary;
  - 1 dev item: `v5-fever120372`;
  - 1 extension item that is not collected.
- **Golds agree in every case.**
- **Remedy.** The 1,100 are fixed by the prereg hashes, so they are not replaced. If wanted, the checker validation can
  re-score the fresh2 FEVER validation without these 5 pairs. That needs no new checker calls.
- **Where listed.** All pairs are in `exclusion_proofs.json` →
  `disclosed_not_required_zero.same_text_collisions_with_later_validation_slices`.

**Provenance from the v4 extension.** 159 of the 1,100 come from the uncollected v4 extension: TQA
15, SciFact 91, PopQA 49, FEVER 4.

**Note on `1.0.0/exclusion_proofs.json`.** One dict in it, `n_in_v4_eligible_pool_by_label`, had a
key order that depended on the hash seed. Its content is the same. The builder now sorts that dict;
the archived file is left as it was.

---

# Base draw `v5-benchmark-1.0.0` (archived in `1.0.0/`)

The sections below describe the base draw. The exclusions, item fields and deviations still apply
to 1.1.0.

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

## Item fields (what the harness, checker and evaluation consume)

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
- **Bookkeeping.** `split`, `tier`, `order`, `build_version`, `contested_rationale` and
  `review_note`.
  - In 1.0.0, `tier` is `dev`, `primary` or `extension`.
  - In 1.1.0, `tier` is `dev`, `primary` (P) or `tqa_stratum` (T), and the 300 reserve items
    also carry `switch_added: true`.

**Gold-bearing fields that the harness must never show an agent, the checker or the judge:**

- `gold`, `gold_triples` and `options[].correct`;
- `source.label`, `source.doc_id` and `source.n_evidence_docs`;
- `source.obj_wikidata`;
- `source.reference_url` (TruthfulQA), which also must not enter the corpus (design §7.4);
- `stratum` for FEVER and SciFact, and `contested_rationale`.

**No prompts are rendered here.** The harness owns `v5/prompts/`. In particular, SciFact items no longer
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
     analysis team may prefer a pre-declared rule taking all 54 REFUTED (54 / 196). That would also
     be gold-label stratification, not model-based selection, but it is not what this build does.
     Flag before the freeze.
3. **FEVER is not stratified by label.** The design names label strata only within SciFact.
   Primary is close to balanced (101 SUPPORTED / 99 REFUTED).
4. **TQA switch (§2.2).** Resolved by the prereg (§6.1: k = 150 / 150 plus a 100-item TQA
   stratum) and built as 1.1.0, described above.
5. **FEVER checker-validation slices.** The checker validation drew both outside every v5 FEVER id: `fever_slice` from
   the reserve tail, and `fever_slice_fresh2` from outside the items and the reserve. The ids are
   asserted disjoint. The 5 same-text collisions with `fever_slice_fresh2` are disclosed in the
   1.1.0 section.

## Licences

The item files mix licences:

- FEVER-derived lines: CC BY-SA 3.0, with share-alike;
- SciFact claims: CC BY 4.0; abstracts: ODC-By 1.0;
- TruthfulQA: Apache-2.0;
- PopQA: MIT, with facts from Wikidata (CC0).

Per-source versions and file hashes are in `manifest.json` → `sources`.
