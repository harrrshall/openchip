# VerilogEval v2 spec-to-rtl — mode `agent` — 20260909-071514

n = 39; pass = 28 (71.8%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `glm-5.3` @ `remote` T=0.2 thinking_roles=[]

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 5 | 7886 | 23.7 |
| Prob005_notgate | pass | True | 1 | 5 | 7966 | 20.6 |
| Prob009_popcount3 | pass | True | 1 | 5 | 10798 | 28.9 |
| Prob013_m2014_q4e | pass | True | 1 | 5 | 8383 | 23.1 |
| Prob017_mux2to1v | pass | True | 1 | 5 | 11444 | 49.6 |
| Prob021_mux256to1v | pass | True | 1 | 5 | 12003 | 40.1 |
| Prob025_reduction | pass | True | 1 | 5 | 11260 | 36.8 |
| Prob029_m2014_q4g | pass | True | 1 | 5 | 12899 | 46.3 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 5 | 13054 | 38.4 |
| Prob037_review2015_count1k | pass | True | 1 | 6 | 15011 | 41.6 |
| Prob041_dff8r | pass | True | 1 | 6 | 15593 | 74.0 |
| Prob045_edgedetect2 | pass | True | 2 | 7 | 22777 | 91.7 |
| Prob049_m2014_q4b | pass | True | 1 | 6 | 13738 | 49.1 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 7104 | 65.8 |
| Prob057_kmap2 | pass | True | 2 | 6 | 22436 | 103.6 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 8316 | 91.0 |
| Prob065_7420 | pass | True | 1 | 5 | 15499 | 40.9 |
| Prob069_truthtable1 | fail | True | 1 | 5 | 12044 | 33.2 |
| Prob073_dff16e | pass | True | 1 | 6 | 19796 | 69.6 |
| Prob077_wire_decl | pass | True | 1 | 5 | 13917 | 35.4 |
| Prob081_7458 | pass | True | 1 | 5 | 17942 | 38.4 |
| Prob085_shift4 | pass | True | 1 | 6 | 19480 | 50.1 |
| Prob089_ece241_2014_q5a | fail | True | 1 | 6 | 20670 | 89.7 |
| Prob093_ece241_2014_q3 | fail | True | 1 | 6 | 25084 | 78.0 |
| Prob097_mux9to1v | pass | False | 3 | 7 | 22186 | 111.7 |
| Prob101_circuit4 | pass | True | 1 | 5 | 13719 | 27.3 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 9033 | 91.0 |
| Prob109_fsm1 | pass | True | 2 | 7 | 23948 | 65.2 |
| Prob113_2012_q1g | fail | True | 1 | 6 | 23176 | 84.4 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 9010 | 97.1 |
| Prob121_2014_q3bfsm | pass | True | 1 | 6 | 20816 | 86.4 |
| Prob125_kmap3 | pass | True | 1 | 5 | 14324 | 44.8 |
| Prob129_ece241_2013_q8 | pass | True | 1 | 6 | 21129 | 115.4 |
| Prob133_2014_q3fsm | pass | True | 1 | 6 | 26517 | 115.2 |
| Prob137_fsm_serial | pass | True | 1 | 6 | 26166 | 79.1 |
| Prob141_count_clock | fail | True | 1 | 6 | 27061 | 107.1 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 12809 | 179.0 |
| Prob149_ece241_2013_q4 | fail | True | 1 | 6 | 32388 | 179.0 |
| Prob153_gshare | pass | True | 2 | 7 | 44096 | 198.8 |
