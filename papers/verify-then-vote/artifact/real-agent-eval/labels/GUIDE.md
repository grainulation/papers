# Labeling guide

You label one extracted claim at a time. The page shows the question, the question's gold triples, the raw
sentence the model wrote, and the triple the regex extractor pulled out of it. It never shows what the
graders decided until you have finished every item and choose to reveal.

Label every item with three fields and optional notes:

| field | values | question it answers |
|---|---|---|
| `correct` | `true`, `false`, `partially`, `unclear` | Is what this claim asserts true about the world? |
| `matches_gold` | `yes`, `no` | Does this claim assert one of the listed gold triples? |
| `well_formed_extraction` | `yes`, `no` | Does the extracted triple faithfully and self-sufficiently represent the sentence's assertion? |
| `notes` | free text | Anything a second labeler should know: which gold triple, why borderline, what is wrong with the extraction. |

Do not look at the grader code, the CSVs in `v3/results/`, or `sample.json` while labeling.
`sample.json` contains the grader verdicts.

## What you are judging

**The claim** is the assertion the triple is trying to capture. Read the triple first, then the raw sentence.
The raw sentence is the authority when the triple is a lossy view of it.

- Use the **question** to resolve a pronoun or an elided subject only when the reference is unambiguous
  ("This value is 299,792.458 km/s" under "What is the speed of light in a vacuum?"). If the referent is
  unclear, `correct = unclear` and `matches_gold = no`.
- Judge `correct` and `matches_gold` on the content, and record extraction damage separately in
  `well_formed_extraction`. A heading fragment as the subject does not by itself make a claim wrong. Section 2
  of the analysis recomputes agreement on well-formed items only, so the two kinds of error can be told apart.
- If the triple **reverses or drops** something the sentence says (it loses a "not", or keeps only half of a
  comparison), judge the **sentence** for `correct` and `matches_gold`, set `well_formed_extraction = no`, and
  say what was lost in `notes`.
- Ignore citations like "(Pohl et al., 2009)" or "(source: ...)". Do not check whether the source exists or
  says this.

## `correct`

- `true`: the assertion is accurate as stated, including a sensible reading of hedges ("typically",
  "approximately"). Rounded values that are presented as approximate count as true
  ("approximately 300,000 km/s").
- `false`: the main assertion is wrong, or it contradicts the scientific consensus the gold encodes.
- `partially`: one part is right and another part is wrong ("Napoleon was 5'2", ... below average": the
  height is wrong in modern units, and the conclusion is wrong), or the claim overstates (it says "exactly"
  for an approximation, or "always" for "usually").
- `unclear`: there is no factual assertion (meta-statements such as "This information is widely accepted",
  confidence notes, or advice with no truth value), the referent cannot be resolved, or you cannot judge it
  without outside research. Say which one in `notes`.

## `matches_gold`

`yes` if the claim, read as above, asserts at least one gold triple with the same polarity. Paraphrase is
allowed. Being more specific than the gold triple is allowed ("Canberra" vs "the capital is Canberra, in the
ACT"). Being only topically related is not enough. Put the gold triple number in `notes` when it is not
obvious.

`matches_gold` is independent of `correct`. A claim can match a gold triple and also add a false clause; then
it is `partially` + `yes`. A claim can be true and match nothing; then it is `true` + `no`
("extra-but-true").

## `well_formed_extraction`

The reducer groups claims by their exact (subject, predicate) strings. So the subject must be the entity
alone, or else the same entity gets keyed differently. `yes` when all of these hold:

- the subject names only the thing the sentence is about. Articles and ordinary modifiers are fine. The
  subject must not carry any non-content prefix: bullets or bold markers (`* **Pluto`), list headings
  (`**Flow Control**: TCP`), answer or discourse markers (`Claim:`, `Yes,`, `No,`, `However,`,
  `According to NASA,`), a framing clause ("A study found that sugar"), or a bare pronoun;
- the predicate plus the object together keep the sentence's assertion, including its polarity;
- the object is not cut off mid-phrase.

The object may contain emphasis (`**46 chromosomes**`), an extra clause or a trailing citation. Formatting
in the object is not content.

**The raw sentence is stored cut at 200 characters** (`collect.py` keeps `sent[:200]`). The page marks
these sentences. The extracted object often runs past the cut. The cut alone is not a malformed extraction,
so judge the full object.

## Decision rules with examples

All examples below are real claims from the v3 or v1 data that are **not** in the sample (#3 is made up).
They show the rule and are not part of the labeling set.

### Polarity

1. q55, gold 1 `(Napoleon | was | average height for his era (about 5'7"))`
   Sentence: "Yes, Napoleon Bonaparte was notably shorter than the average Frenchman of his time."
   Triple: `(Yes, Napoleon Bonaparte | is | notably shorter than the average Frenchman of his time)`
   Label: `correct = false`, `matches_gold = no` (it asserts the opposite of the gold triple),
   `well_formed_extraction = no` (the subject keeps "Yes,").
2. q12, gold 2 `(Great Wall of China | is_not_visible_from | the Moon)`
   Sentence: "From the Moon, the Great Wall of China is not visible at all."
   Label: `true`, `yes`, `well_formed_extraction = no` ("From the Moon," was put into the subject). The
   negation agrees with the gold predicate, so the polarity is the same.
3. Made-up illustration: the claim "X is not uncommon" against the gold `(X | is | common)`. A negated
   antonym, or a negation placed in a different field ("does not cause" vs "does_not_cause"), keeps the same
   polarity. Count the meaning, not the "not"s.

### Predicate mismatch

4. q05, gold `(coffee | associated_with | reduced risk of type 2 diabetes)`
   "Coffee consumption is linked to a lower risk of depression and type 2 diabetes ..."
   Label: `true`, `yes`, `yes`. "Is linked to" is the same relation as "associated_with". A different verb
   is fine when the relation is the same.
5. q42, gold `(acids | donate | protons (H+ ions))`
   "When dissolved in water, an acid increases the concentration of H+ ions in the solution."
   Label: `true`, `no`, `well_formed_extraction = no` (the subject keeps "When dissolved in water,").
   This is the Arrhenius definition, not proton donation. Same entities, different relation, so it is
   extra-but-true.

### Formatting-only differences

6. q09, gold 1 `(Pluto | is_classified_as | dwarf planet)`
   "* **Pluto is now classified as a dwarf planet.** This classification was adopted by the IAU ..."
   Triple: `(* **Pluto | is | now classified as a dwarf planet.** This classification ...)`
   Label: `true`, `yes`, `well_formed_extraction = no`. The bullet and bold markers do not change the
   content, but they leave the subject keyed as `* **pluto` instead of `pluto`.
7. q06, gold `(Pacific Ocean | is | largest ocean on Earth)`
   "According to their data, the Pacific Ocean is the largest, covering more than 63 million square miles ..."
   Label: `true`, `yes`, `well_formed_extraction = no` (the subject keeps "According to their data,").
   "The largest" with "ocean" left implicit by the question still matches.
8. Units and digit grouping (`299,792,458 m/s` vs `299792458 m/s`, `km/s` vs `m/s`, `5 feet 7 inches` vs
   `5'7"` vs `170 cm`) are formatting. Judge whether the value is the same.

### Extra-but-true facts

9. q04, gold about Go/Rust web-API advantages.
   "Go, on the other hand, has a more traditional syntax and a gentler learning curve (5)."
   Label: `true`, `no`, `well_formed_extraction = no` (the subject is "Go, on the other hand,").
   It is a reasonable claim, but no gold triple says it.

### Malformed subjects, non-assertions, cut sentences

10. q01. "This is confirmed by the Australian Government's official website (https://...)."
    Triple `(This | is | confirmed by ...)`. Label: `unclear` (a meta-statement), `no`, `no`.
11. q45, gold 2 `(SQL | advantage | ACID transactions and relational integrity)`
    "**Strict data consistency and ACID compliance**: SQL databases provide stronger consistency guarantees
    and ACID compliance, making them suitable for applications with strict data consistency requireme"
    (cut at 200). Triple `(**Strict data consistency and ACID compliance**: SQL databases | provide |
    stronger consistency guarantees and ACID compliance, ... requirements)`.
    Label: `true`, `yes`, `no` (the subject carries a heading).
12. q30, gold about OOP/FP advantages.
    "Both object-oriented (OO) and functional programming (FP) have their strengths and weaknesses, and which
    one is "better" ultimately depends on the specific problem, project requirements, and team pref" (cut at
    200). The object ends "... and team preferences".
    Label: `true`, `no` (it names no specific advantage), `yes` (the cut is in the stored sentence, and the
    triple is intact).

## Pace and hygiene

- Expect about 30 seconds per item. Use `notes` freely on borderline items.
- Do not change a label after you reveal the grader verdicts. If you must, the export flags the item
  (`edited_after_reveal = 1`), and `analyze.py` drops it unless you pass `--include-post-reveal`.
- A second labeler should label independently, under their own labeler id, from this guide alone. Do not
  discuss items until both of you have exported.
