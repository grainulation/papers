# Blind PopQA gold-alias supplement (OVERTURN, v5 confirmatory)

Purpose: add missing Wikidata spelling/alias variants to the PopQA gold so a replication can adopt one
frozen list. Built blind to outcomes: `build_aliases.py` reads only `v5/benchmark/items_confirmatory.jsonl`
(gold, ids, Wikidata uris) and the public Wikidata API. No agent answer, decision or result was opened
before `aliases.json` was frozen.

## Files
- `build_aliases.py`: reproducible build (`python3 -I build_aliases.py`; uses `wikidata_cache.json`, network only if absent; `--refresh` re-fetches).
- `wikidata_cache.json`: English label + aliases for the 731 entities (400 objects + subjects), fetched with wbgetentities, 50 per call.
- `aliases.json`: item id -> added aliases (normalised). `aliases.json.sha256`: its digest.
- `explore_v5.py`: exploratory regrade of v5, run only after the freeze. Writes nothing.

## Rules
Candidates are the English label and aliases of the gold object (`source.obj_wikidata`). Normalised as the frozen
grader does (`answer_key.grade`: lowercase, strip; whitespace collapsed). Kept only if not already in the item's gold.
Dropped if 2 or fewer characters, or if also a label/alias of a different candidate entity: the item's subject, or the
object/subject of another PopQA item with the same subject. (Each item's gold has one object entity, so "same gold set"
reduces to these.)

## Counts
400 PopQA items; 214 gain aliases; 747 aliases added; dropped: 1,368 already in gold, 0 short, 3 conflict.

## Exploratory v5 result (P set, n=526, post hoc, not preregistered)
Unaugmented gold reproduces the published numbers exactly. Augmented gold, in the same run:
MAJ .7148 -> .7167; VV .8650 -> .8669; VV/VDF .8726 -> .8745; BE-G .8650 -> .8650; BE-G/VDF .8688 -> .8707.
Only one item changes, so overturn counts and harms are otherwise unchanged. 0 previously correct answers became
incorrect (2,000 parsed PopQA responses: 18 wrong -> right, 0 right -> wrong).

## Adoption
sha256 of `aliases.json`: see `aliases.json.sha256`. The list is frozen once adopted; rebuild must reproduce this hash from the cache.
