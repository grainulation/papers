# Public field reproduction plan: does evidence strength predict which claim survives revision?

This plan describes how to test, on public data only, whether arbitration rules that weight evidence strength pick the claims that survive real-world revision. It reports hypotheses in generic terms and contains no data from any private source.

## Hypotheses

- **H1 (survival).** Claims backed by stronger evidence are deprecated, removed or reverted less often than weakly supported claims, controlling for recency (claim age, and which claim in a competing set came later).
- **H2 (conflict-moment rewind).** Take each conflict (two incompatible values for the same slot) and rewind to the revision where the second value appeared. Score three arbiters on predicting the eventual survivor, using only what was visible at that revision:
  - (a) evidence-weighted: the stronger-referenced value wins, ties go to the newer value;
  - (b) newest wins;
  - (c) first wins.
  The key quantity is accuracy on the **discordant subset**, the pairs where the evidence-weighted and newest rules disagree. That subset is the only part of the data that separates "evidence wins" from "latest wins".
- **H3 (mechanism).** Evidence strength predicts the survivor when the conflict is settled by further sourcing. It predicts much less when the conflict is settled by an authority decision, such as policy, an editorial ruling or a constraint. This is the hypothesis to falsify if H2 comes out null.
- **H4 (incidence).** Conflict and revision rates differ by claim kind. Normative or predictive claims churn more than descriptive facts. Strongly supported claims are checked, and therefore contested, more often.

Pre-registered nulls. H2 is falsified if evidence-weighted accuracy on the discordant subset is at or below 50%. H1 is falsified if the stratified odds ratio for deprecation (weak vs strong) has a 95% CI that includes 1. A null result is reported, not reframed.

## Candidate datasets

### 1. Wikidata (recommended)

- **Licence:** CC0 (structured data). The revision API and the SPARQL endpoint (WDQS) are public. Requests must carry a descriptive User-Agent and stay at a low rate.
- **Size:** about 120M items. The full JSON dump is over 100 GB compressed and the history dumps are TB-scale, so this plan uses the **API only**, not dumps.
- **Unit of conflict:** one item and one single-valued property with two or more statements. Examples:
  - date of birth or death (P569, P570);
  - place of birth (P19);
  - sex or gender (P21);
  - publication date (P577);
  - population figures with point-in-time qualifiers.
- **Outcome:** statement rank, where `deprecated` marks the loser and `preferred`/`normal` the survivor, plus the qualifier "reason for deprecated rank" (P2241). A second outcome is plain removal of a statement, found from history.
- **Evidence-strength signal:** the statement's references, as an ordinal scale:
  - 0: no reference;
  - 1: only "imported from Wikimedia project" (P143), "inferred from" or other heuristics;
  - 2: a reference URL (P854) only;
  - 3: "stated in" (P248) an identified source (an authority file, database or publication).
  Optional refinements: the count of independent references, and the source-type class of the P248 target.
- **Timestamp and recency:** the revision in which each statement GUID first appears, found by binary search over the item's revision list (`action=query&prop=revisions`). The rank-change revision gives time to resolution. Statement GUIDs persist across rank and reference edits, so the "state at the conflict moment" is well defined.
- **Mechanism (H3):** P2241 reason codes. "Incorrect value", "error", "typographical error", "logical contradiction" and "age fabrication" are evidential. Calendar-model or precision duplicates are a representational fix, not a dispute. An edit summary that cites a source or a bot is an evidential settlement; a policy or community decision is an authority settlement.
- **Circularity guard:** exclude deprecations whose reason is "uncitedness" (Q2492572), since their outcome is defined by the evidence signal. Also exclude calendar-conversion (Q2478595) and false-precision (Q3467464) duplicates from the main analysis.
- **Known bias:** Wikidata convention keeps the deprecated value together with the reference to the source that asserted it. So deprecated statements are often well referenced, which works *against* H1 and H2 and makes this a conservative test.

### 2. Wikipedia revision history with reliability templates

- **Licence:** text CC BY-SA 4.0. Wiki-Reliability (Wong, Redi, Saez-Trumper, SIGIR 2021, figshare 14113799; check the record's licence) gives about 1M revisions labelled by template, such as {{unreliable sources}} and {{contradictory}}.
- **Unit:** a sentence or claim span. Evidence is citation presence and type (`<ref>` with a DOI or ISBN vs a bare URL vs {{citation needed}}). Outcome is persistence, measured as revisions survived or as a revert (identity revert via SHA1, from the `mwreverts` methodology).
- **Pros:** very large, and natural claims in text.
- **Cons:** claim segmentation and "conflict" are hard to define. Survival is dominated by vandalism reverts. Rewinding needs diff alignment (`mwpersistence`), so this is heavier engineering.
- VitaminC (Schuster et al., NAACL 2021) gives over 100K fact-changing revisions with contrastive evidence. It is useful for H4-style "facts change" analyses but has no evidence-strength signal per side. Check its licence on the repo.

### 3. Stack Exchange data dump

- **Licence:** CC BY-SA. Official dumps are now gated behind a profile download. A community mirror of the 2025-12-31 dump is on archive.org (about 92 GB total; single small sites are a few MB to hundreds of MB). Some 2025 dumps contain watermarking, so filter them.
- **Unit:** competing answers to the same question. Evidence is links to official docs, code blocks, or quoted sources. Outcomes:
  - accepted answer, which is an **authority** outcome (the asker decides) and maps naturally to H3;
  - the score-leader at the dump date, which is a crowd outcome;
  - "obsolete" comments.
- **Rewind:** the PostHistory and Votes tables give the score and acceptance state at the moment the second answer appeared. Newest = the later answer; first = the earliest.
- **Pros:** an explicit contrast between authority (accept) and crowd (votes), and good for H3.
- **Cons:** answers are not strictly incompatible, so "conflict" is weaker. There is a known first-mover advantage. The evidence signal is noisy.

## Recommendation

Use **Wikidata single-valued-property conflicts**. It has the cleanest conflict definition (incompatible values in one slot) and an explicit loser marker with a reason code, which supports the H3 split. It also has an ordinal evidence signal that does not depend on the outcome once the circularity guard is applied, and per-statement first-appearance times, so the conflict-moment rewind can be exact. Everything runs through public APIs on a laptop, under a CC0 licence. Stack Exchange is the secondary replication for H3 (authority vs evidence).

## Exact tests (Wikidata)

1. **Sampling.** Use WDQS to list items with at least one deprecated statement on the target properties, stratified by property. Draw a random sample (target n ≈ 2,000 conflict pairs per property family). Also draw a **control sample** of items with two or more statements on the same property and no deprecation, to estimate H1 base rates.
2. **Pair construction.** Pair each deprecated statement with each non-deprecated statement on the same item and property. Main analysis: items with exactly one surviving statement.
3. **Rewind.** For every statement, find the revision of its first appearance by binary search on the revision list. The conflict moment is the later of the pair's two first-appearance revisions. Read both statements' references and ranks at that revision, and drop pairs where one side was already deprecated at that point (a sensitivity analysis keeps them). Also record:
   - the editor type of the resolving edit (bot vs human);
   - its edit summary;
   - the time from conflict to resolution.
4. **Scores.** Accuracy of the evidence-weighted, newest and first rules, with Wilson CIs and an item-cluster bootstrap. Report the 2×2 table of evidence-weighted vs newest correctness and McNemar's test on the discordant subset. Repeat under evidence tiers measured at the final revision, to quantify post-hoc re-referencing.
5. **H1 (recency-controlled survival).** Fit a logistic or conditional-logit model of deprecation on evidence tier, with the item as stratum. Covariates:
   - order within the competing set (newer vs older);
   - log age at the conflict moment;
   - property;
   - whether the statement was added by a bot.
   Report the Mantel–Haenszel OR stratified by order.
6. **H3.** Fit the rule accuracies separately by mechanism: P2241 evidential reasons vs representational reasons; resolving edits that add a reference vs those that do not; bot vs human resolution.
7. **H4.** Compute deprecation and conflict rates per property class: descriptive biography facts vs time-varying statistics vs classification properties.

## Feasibility sample

Run on 2026-10-22 against the live Wikidata APIs. It is a convenience sample, not the study sample. Scripts are kept local and are not part of the paper.

1. **Snapshot.** WDQS returned the first 400 items that have a date-of-birth (P569) statement carrying a "reason for deprecated rank" qualifier. `wbgetentities` gave 849 P569 statements: 403 deprecated, 366 normal and 80 preferred. 362 items have both a deprecated and a live value. The evidence scale was extractable for every statement (0: none, 1: Wikimedia-import only, 2: URL, 3: stated-in).
   - Deprecation reasons were dominated by typographical error (91), **uncitedness (86)**, error (67), false precision (28), logical contradiction (19), anachronism (18) and Julian/Gregorian conversion (14).
   - All reasons pooled: the deprecated value has a weaker best reference than the best surviving value in 63% of the pairs where strengths differ (122 vs 72; 95% CI 56–69%). This looks like support for H1.
   - That apparent effect is **entirely the circularity artefact**:
     - "uncitedness" deprecations alone: weaker in 72 of 73 differing pairs (99%);
     - truth-related reasons only (error, typo, contradiction, anachronism, age fabrication, incorrect value; n = 192 pairs): weaker in 30, stronger in 31, equal in 131, giving **49% (CI 37–61%)**, which is chance.
   - Deprecated values are usually well referenced: 70% carry a stated-in reference, as the keep-the-sourced-wrong-value convention predicts. **Lesson:** the circularity guard is mandatory, and a naive snapshot analysis would report a spurious evidence-wins effect.
2. **Rewind.** For 19 truth-reason items with exactly one surviving value (out of 153 eligible candidates, stopped by the time budget), binary search over revision history recovered each statement's first-appearance revision and its references and rank at the conflict moment. This works end to end.
   - In 9 of 19 pairs the losing value was **already deprecated when the surviving value was added**. That is a replacement edit, not an open dispute, so the study must analyse it as a separate stratum, as the plan above specifies.
   - Across all 19: newest-wins 58% (CI 36–77%), first-wins 42%, evidence-weighted 55% on the 11 strength-differing pairs (CI 28–79%). On the discordant subset, newest-wins was right in 5 of 7 cases.
   - The numbers are uninformative at this n. They are reported only to show that every quantity in the test plan can be computed.
3. **Throughput.** Sequential binary search cost about 1–2 minutes per item (about 10–15 full-entity fetches at a polite rate, with 3 parallel workers). The production run must instead fetch revisions in batches of 50 with content in a single request per page, and cap items at 1,000 revisions. Without that change, 2,000 pairs would take days.

## Effort and compute on a laptop

- **Sampling and snapshot extraction:** under 1 hour of wall time for thousands of items. The wbgetentities API returns 50 items per call.
- **Rewind:** with batched content fetches (50 revisions per request, one page), an item with at most 500 revisions needs at most 10 requests. About 2,000 pairs is roughly 15–25k requests, or 4–8 hours at a polite rate, with a few GB streamed; only the extracted property snapshots are stored. Sequential binary search, as used in the feasibility sample, is about 5 times slower.
- **Analysis code:** about 1–2 days, reusing the rule evaluator. Writing up: about 1 day.
- **Stack Exchange replication (H3):** about 2–3 more days, using one or two mid-size sites (under 200 MB each).
