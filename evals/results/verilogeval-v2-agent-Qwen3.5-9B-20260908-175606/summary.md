# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-175606

n = 39; pass = 17 (43.6%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `Qwen/Qwen3.5-9B` @ `c202236235762e1c871ad0ccb60c8ee5ba337b9a` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 5 | 17029 | 158.0 |
| Prob005_notgate | pass | True | 1 | 4 | 9714 | 29.9 |
| Prob009_popcount3 | pass | True | 2 | 5 | 13298 | 39.4 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 9167 | 25.4 |
| Prob017_mux2to1v | pass | True | 1 | 4 | 12419 | 44.3 |
| Prob021_mux256to1v | compile_error | False | 5 | 8 | 25668 | 67.0 |
| Prob025_reduction | pass | True | 1 | 4 | 10144 | 34.8 |
| Prob029_m2014_q4g | pass | True | 2 | 5 | 14362 | 45.8 |
| Prob033_ece241_2014_q1c | pass | True | 2 | 5 | 17811 | 77.5 |
| Prob037_review2015_count1k | fail | True | 1 | 6 | 25436 | 192.0 |
| Prob041_dff8r | pass | True | 1 | 5 | 13224 | 40.3 |
| Prob045_edgedetect2 | pass | True | 1 | 7 | 23187 | 109.6 |
| Prob049_m2014_q4b | fail | True | 1 | 6 | 18606 | 75.5 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5531 | 38.0 |
| Prob057_kmap2 | pass | True | 2 | 5 | 31257 | 107.8 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 6520 | 51.3 |
| Prob065_7420 | pass | True | 1 | 4 | 15544 | 58.8 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 11096 | 42.8 |
| Prob073_dff16e | pass | True | 2 | 5 | 17861 | 70.8 |
| Prob077_wire_decl | pass | True | 1 | 4 | 13335 | 44.4 |
| Prob081_7458 | pass | True | 1 | 4 | 15860 | 57.9 |
| Prob085_shift4 | fail | True | 2 | 6 | 20947 | 83.2 |
| Prob089_ece241_2014_q5a | no_rtl | False | 0 | 4 | 27791 | 202.8 |
| Prob093_ece241_2014_q3 | fail | False | 3 | 6 | 54519 | 424.3 |
| Prob097_mux9to1v | pass | False | 2 | 6 | 31829 | 210.9 |
| Prob101_circuit4 | fail | True | 1 | 4 | 12493 | 37.7 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 7448 | 58.2 |
| Prob109_fsm1 | fail | True | 2 | 6 | 20916 | 76.0 |
| Prob113_2012_q1g | fail | True | 4 | 9 | 53122 | 264.8 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 17591 | 200.0 |
| Prob121_2014_q3bfsm | fail | False | 5 | 11 | 53703 | 330.4 |
| Prob125_kmap3 | fail | False | 5 | 9 | 56894 | 254.0 |
| Prob129_ece241_2013_q8 | fail | True | 1 | 5 | 18983 | 74.3 |
| Prob133_2014_q3fsm | compile_error | False | 2 | 8 | 73808 | 389.5 |
| Prob137_fsm_serial | fail | False | 4 | 10 | 57625 | 326.6 |
| Prob141_count_clock | fail | True | 2 | 7 | 33799 | 122.1 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 25848 | 302.4 |
| Prob149_ece241_2013_q4 | fail | False | 1 | 8 | 61764 | 449.2 |
| Prob153_gshare | no_rtl | False | 0 | 4 | 41849 | 375.7 |
