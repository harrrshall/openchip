# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-183615

n = 39; pass = 28 (71.8%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `openai/gpt-oss-120b` @ `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` T=0.2 thinking_roles=[]

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 6379 | 6.1 |
| Prob005_notgate | pass | True | 1 | 4 | 6750 | 7.3 |
| Prob009_popcount3 | pass | True | 1 | 4 | 8264 | 10.3 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 7767 | 9.1 |
| Prob017_mux2to1v | pass | True | 1 | 4 | 9084 | 12.8 |
| Prob021_mux256to1v | pass | True | 1 | 4 | 10891 | 16.7 |
| Prob025_reduction | pass | True | 1 | 4 | 8372 | 10.9 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 8979 | 12.1 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 4 | 9916 | 13.0 |
| Prob037_review2015_count1k | pass | True | 1 | 5 | 12165 | 17.3 |
| Prob041_dff8r | pass | True | 1 | 5 | 13294 | 16.1 |
| Prob045_edgedetect2 | pass | True | 1 | 5 | 14382 | 19.6 |
| Prob049_m2014_q4b | pass | True | 3 | 6 | 15332 | 21.5 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5297 | 11.3 |
| Prob057_kmap2 | pass | True | 2 | 4 | 11984 | 18.0 |
| Prob061_2014_q4a | pass | True | 1 | 5 | 15538 | 20.2 |
| Prob065_7420 | pass | True | 1 | 4 | 11309 | 12.0 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 10016 | 13.1 |
| Prob073_dff16e | pass | True | 1 | 5 | 16087 | 19.8 |
| Prob077_wire_decl | pass | True | 1 | 4 | 10353 | 10.9 |
| Prob081_7458 | pass | True | 1 | 4 | 15377 | 19.4 |
| Prob085_shift4 | pass | True | 1 | 5 | 16578 | 24.4 |
| Prob089_ece241_2014_q5a | pass | True | 1 | 5 | 18686 | 29.6 |
| Prob093_ece241_2014_q3 | fail | True | 1 | 4 | 12597 | 16.5 |
| Prob097_mux9to1v | pass | False | 3 | 6 | 17814 | 23.7 |
| Prob101_circuit4 | pass | True | 1 | 4 | 11190 | 13.4 |
| Prob105_rotate100 | pass | True | 1 | 6 | 19940 | 28.8 |
| Prob109_fsm1 | pass | True | 2 | 6 | 19633 | 25.2 |
| Prob113_2012_q1g | fail | True | 1 | 4 | 9695 | 16.0 |
| Prob117_circuit9 | fail | True | 1 | 5 | 15133 | 20.1 |
| Prob121_2014_q3bfsm | pass | True | 1 | 5 | 17057 | 24.3 |
| Prob125_kmap3 | fail | True | 1 | 4 | 11269 | 16.4 |
| Prob129_ece241_2013_q8 | fail | True | 1 | 5 | 18942 | 27.3 |
| Prob133_2014_q3fsm | pass | True | 1 | 5 | 21848 | 38.3 |
| Prob137_fsm_serial | fail | True | 1 | 5 | 19005 | 27.4 |
| Prob141_count_clock | fail | True | 1 | 5 | 22754 | 34.9 |
| Prob145_circuit8 | fail | False | 3 | 8 | 28947 | 38.6 |
| Prob149_ece241_2013_q4 | fail | True | 1 | 5 | 24802 | 37.7 |
| Prob153_gshare | fail | True | 2 | 7 | 44281 | 62.5 |
