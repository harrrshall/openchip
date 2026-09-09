# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-184327

n = 39; pass = 21 (53.8%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 9137 | 101.1 |
| Prob005_notgate | pass | True | 1 | 5 | 15833 | 327.6 |
| Prob009_popcount3 | pass | True | 1 | 4 | 14085 | 217.4 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 12256 | 170.5 |
| Prob017_mux2to1v | pass | True | 1 | 4 | 13609 | 159.7 |
| Prob021_mux256to1v | pass | True | 1 | 4 | 19023 | 343.2 |
| Prob025_reduction | pass | True | 1 | 5 | 17038 | 324.6 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 14470 | 206.0 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 4 | 17739 | 265.6 |
| Prob037_review2015_count1k | pass | True | 1 | 5 | 23518 | 320.2 |
| Prob041_dff8r | no_rtl | False | 0 | 1 | 10647 | 368.9 |
| Prob045_edgedetect2 | no_rtl | False | 0 | 2 | 20388 | 696.9 |
| Prob049_m2014_q4b | pass | True | 1 | 5 | 13147 | 85.8 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5464 | 97.5 |
| Prob057_kmap2 | fail | True | 2 | 4 | 24802 | 407.9 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 6914 | 150.5 |
| Prob065_7420 | pass | True | 1 | 4 | 12830 | 75.2 |
| Prob069_truthtable1 | fail | True | 1 | 4 | 9703 | 48.9 |
| Prob073_dff16e | pass | True | 1 | 5 | 15933 | 120.8 |
| Prob077_wire_decl | pass | True | 1 | 4 | 10448 | 53.9 |
| Prob081_7458 | pass | True | 1 | 4 | 14651 | 89.1 |
| Prob085_shift4 | pass | True | 1 | 5 | 17214 | 120.8 |
| Prob089_ece241_2014_q5a | fail | True | 1 | 5 | 21008 | 167.7 |
| Prob093_ece241_2014_q3 | fail | True | 2 | 5 | 27765 | 390.6 |
| Prob097_mux9to1v | pass | False | 2 | 6 | 25876 | 256.1 |
| Prob101_circuit4 | pass | True | 1 | 4 | 14708 | 67.5 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 7128 | 141.6 |
| Prob109_fsm1 | pass | True | 2 | 6 | 19448 | 131.2 |
| Prob113_2012_q1g | fail | True | 2 | 6 | 28480 | 590.2 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 14067 | 394.5 |
| Prob121_2014_q3bfsm | fail | True | 1 | 5 | 24968 | 266.4 |
| Prob125_kmap3 | pass | True | 1 | 4 | 20036 | 104.3 |
| Prob129_ece241_2013_q8 | pass | True | 1 | 5 | 20344 | 157.5 |
| Prob133_2014_q3fsm | no_rtl | False | 0 | 1 | 11044 | 379.6 |
| Prob137_fsm_serial | fail | True | 1 | 5 | 20889 | 235.1 |
| Prob141_count_clock | fail | True | 2 | 6 | 32553 | 252.8 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 8854 | 149.3 |
| Prob149_ece241_2013_q4 | fail | True | 1 | 5 | 28099 | 321.4 |
| Prob153_gshare | fail | True | 1 | 5 | 29622 | 261.5 |
