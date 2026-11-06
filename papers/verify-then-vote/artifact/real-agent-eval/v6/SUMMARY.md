# Eval v6: summary (revision 3, frozen 2026-10-24)

1. **Design.** A second, family-disjoint pool (falcon3:3b, olmo2:7b, exaone3.5:7.8b,
   nemotron-mini:4b, granite3.3:2b) on the same 1,100 items. Everything else is frozen as in v5.
2. **Primary (F1): VV/VDF.** A fixed sequence: H1a (McNemar vs MAJ, α 0.05), then H3a (CP 97.5% < 0.05).
3. **Replication (F2).** v5's BE-G and BE hypotheses, unchanged (Holm; H3a and H3b at their own α).
4. **Secondary, unadjusted.**
   - BE-G/VDF;
   - VV/VDF on T;
   - pooled H3a (BE-G only);
   - every F1/F2 statistic under the alias grader G-AK+A.
5. **No local checker.** A MiniCheck arm was drafted and removed before the freeze: as a binary
   checker it loses the correct REFUTED answers (exploratory v5 re-decision, VV/VDF 0.873 → 0.778).
6. **Power, F1.** H1a 0.992 at half the post-hoc effect. H3a 0.997 / 0.863 / 0.425 at
   q = 0.0106 / 0.02 / 0.03.
7. **Power, F2.** H3a-rep 0.34 at v5's rate and 0.86 at 0.02. Pooled 0.68 / 0.98.
8. **Disclosed post hoc.** VDF, the alias file, and the tuning screens
   (threshold and discriminative support dropped; tie rule unchanged; wording stability exploratory).
9. **Overfitting check.** A design-set exclusion of 15 items.
10. **Cost and time.** About $43 hosted (cap $60), with $0 for the local arm and the alias grader.
    About 12–14 h elapsed.

**Pool after qualification:** exaone3.5:2.4b failed (Ollama runner crash on every request) and was
replaced by its first pre-declared alternate, exaone3.5:7.8b. All five agents pass Q1–Q3; Q4 0.61,
Q5 0.33; BEST exaone3.5:7.8b (119/160).

**Approved by the author (2026-10-24):** VV/VDF primary, item reuse, the F1/F2 structure, the pool,
removal of the MiniCheck arm, and the $60 cap.
