# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-210332

n = 39; pass = 20 (51.3%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `zhuyaoyu/CodeV-R1-RL-Qwen-7B` @ `286cf433f596f1b8525529c1163eb81c19425c22` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 5467 | 6.2 |
| Prob005_notgate | pass | True | 1 | 5 | 8280 | 11.2 |
| Prob009_popcount3 | pass | True | 1 | 7 | 14003 | 34.5 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 6479 | 9.1 |
| Prob017_mux2to1v | pass | True | 1 | 4 | 8621 | 15.3 |
| Prob021_mux256to1v | pass | True | 3 | 8 | 33050 | 152.4 |
| Prob025_reduction | pass | True | 1 | 6 | 10629 | 14.3 |
| Prob029_m2014_q4g | no_rtl | False | 0 | 4 | 8308 | 17.6 |
| Prob033_ece241_2014_q1c | pass | True | 2 | 7 | 24986 | 155.4 |
| Prob037_review2015_count1k | pass | True | 1 | 5 | 16431 | 91.7 |
| Prob041_dff8r | pass | True | 2 | 5 | 23923 | 201.9 |
| Prob045_edgedetect2 | no_rtl | False | 0 | 3 | 4898 | 26.3 |
| Prob049_m2014_q4b | pass | True | 2 | 5 | 23213 | 196.1 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 4653 | 24.1 |
| Prob057_kmap2 | fail | False | 5 | 9 | 38935 | 211.5 |
| Prob061_2014_q4a | no_rtl | False | 0 | 4 | 16240 | 162.7 |
| Prob065_7420 | pass | True | 1 | 4 | 10999 | 22.9 |
| Prob069_truthtable1 | fail | False | 2 | 6 | 20509 | 116.8 |
| Prob073_dff16e | pass | False | 1 | 8 | 52108 | 406.0 |
| Prob077_wire_decl | pass | True | 1 | 4 | 11332 | 29.1 |
| Prob081_7458 | pass | True | 1 | 5 | 17720 | 33.9 |
| Prob085_shift4 | pass | True | 1 | 6 | 17047 | 34.4 |
| Prob089_ece241_2014_q5a | pass | True | 1 | 8 | 49096 | 397.8 |
| Prob093_ece241_2014_q3 | no_rtl | False | 0 | 5 | 31629 | 261.6 |
| Prob097_mux9to1v | pass | False | 1 | 4 | 20993 | 156.8 |
| Prob101_circuit4 | pass | False | 1 | 5 | 40008 | 364.0 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 24122 | 273.3 |
| Prob109_fsm1 | pass | True | 1 | 5 | 11659 | 26.9 |
| Prob113_2012_q1g | fail | True | 3 | 9 | 46724 | 346.8 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 6794 | 42.0 |
| Prob121_2014_q3bfsm | fail | False | 1 | 6 | 29439 | 208.5 |
| Prob125_kmap3 | fail | False | 1 | 8 | 50317 | 409.5 |
| Prob129_ece241_2013_q8 | fail | False | 3 | 9 | 39788 | 223.3 |
| Prob133_2014_q3fsm | fail | False | 1 | 7 | 45876 | 360.7 |
| Prob137_fsm_serial | fail | False | 2 | 8 | 53807 | 418.5 |
| Prob141_count_clock | fail | False | 1 | 7 | 56819 | 424.6 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 7927 | 40.2 |
| Prob149_ece241_2013_q4 | no_rtl | False | 0 | 4 | 41022 | 365.6 |
| Prob153_gshare | fail | False | 3 | 11 | 83704 | 484.3 |
