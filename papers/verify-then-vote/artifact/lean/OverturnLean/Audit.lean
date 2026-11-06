/- Axiom audit: every catalogued theorem should depend only on
`propext`, `Classical.choice`, `Quot.sound` (no `sorryAx`). -/
import OverturnLean.Counterexample
import OverturnLean.Robustness
import OverturnLean.Quantized
import OverturnLean.Gate

open Overturn
#print axioms separated_iff_min_sub_max
#print axioms prop1_i
#print axioms prop1_ii
#print axioms prop1_ii_strict
#print axioms prop1_i_needs_nonneg_delta
#print axioms prop1_needs_nonempty_pos
#print axioms lemma1
#print axioms lemma1_strict
#print axioms prop2
#print axioms prop2_condition_unit_beta
#print axioms default_condition_iff_gamma_gt_two
#print axioms default_weights_no_gamma
#print axioms default_max_evidence_gap_not_separated
#print axioms dvec_mem_Icc
#print axioms cor1
#print axioms simplex_robust_iff
#print axioms prop1_i_quantized
#print axioms prop1_ii_quantized
#print axioms quantized_nonstrict_fails
#print axioms old_prop1_false
#print axioms not_separated
#print axioms prop2_quantities
#print axioms mirror_correct_but_not_separated
#print axioms recency_swap_is_separated
#print axioms Overturn.Gate.P_nonempty
#print axioms Overturn.Gate.D_mem_P
#print axioms Overturn.Gate.gated_mem_vals
#print axioms Overturn.Gate.gate_winner_verified
#print axioms Overturn.Gate.gate_harm
#print axioms Overturn.Gate.gate_no_loss
#print axioms Overturn.Gate.gate_correct_iff
#print axioms Overturn.Gate.gate_cD_le_F
