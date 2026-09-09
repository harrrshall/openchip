# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-183402

n = 39; pass = 19 (48.7%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `AS-SiliconMind/SiliconMind-V1-Qwen3-8B` @ `901f9c51184334ef7270211862c42369ad7bb177` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 5 | 16250 | 148.3 |
| Prob005_notgate | pass | True | 1 | 4 | 7287 | 12.6 |
| Prob009_popcount3 | pass | True | 1 | 4 | 9251 | 18.9 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 6473 | 10.0 |
| Prob017_mux2to1v | pass | True | 1 | 5 | 12453 | 25.2 |
| Prob021_mux256to1v | pass | True | 1 | 5 | 13798 | 27.5 |
| Prob025_reduction | pass | True | 1 | 7 | 15744 | 23.4 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 9517 | 17.8 |
| Prob033_ece241_2014_q1c | fail | True | 2 | 11 | 50510 | 257.0 |
| Prob037_review2015_count1k | pass | True | 2 | 8 | 21717 | 59.7 |
| Prob041_dff8r | pass | True | 1 | 6 | 16253 | 35.2 |
| Prob045_edgedetect2 | pass | True | 2 | 8 | 24848 | 72.1 |
| Prob049_m2014_q4b | pass | True | 1 | 8 | 21395 | 52.1 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5639 | 38.4 |
| Prob057_kmap2 | fail | True | 1 | 4 | 11773 | 37.8 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 5908 | 41.3 |
| Prob065_7420 | pass | True | 1 | 5 | 15127 | 30.2 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 9257 | 15.5 |
| Prob073_dff16e | fail | False | 1 | 7 | 34388 | 200.7 |
| Prob077_wire_decl | pass | True | 1 | 5 | 15253 | 25.9 |
| Prob081_7458 | pass | True | 1 | 4 | 13319 | 28.9 |
| Prob085_shift4 | pass | True | 1 | 6 | 23388 | 87.6 |
| Prob089_ece241_2014_q5a | no_rtl | False | 0 | 4 | 28023 | 209.9 |
| Prob093_ece241_2014_q3 | fail | True | 2 | 8 | 51481 | 103.0 |
| Prob097_mux9to1v | pass | False | 0 | 7 | 27108 | 71.3 |
| Prob101_circuit4 | fail | True | 1 | 4 | 16232 | 30.7 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 6468 | 43.3 |
| Prob109_fsm1 | pass | True | 2 | 10 | 38332 | 101.5 |
| Prob113_2012_q1g | fail | True | 1 | 4 | 9329 | 19.5 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 6819 | 44.4 |
| Prob121_2014_q3bfsm | fail | False | 2 | 9 | 62266 | 491.2 |
| Prob125_kmap3 | fail | True | 1 | 5 | 20933 | 160.4 |
| Prob129_ece241_2013_q8 | fail | False | 1 | 8 | 52855 | 370.1 |
| Prob133_2014_q3fsm | fail | False | 3 | 9 | 70622 | 497.2 |
| Prob137_fsm_serial | fail | False | 1 | 7 | 47789 | 364.9 |
| Prob141_count_clock | fail | True | 1 | 8 | 37995 | 149.6 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 16650 | 166.4 |
| Prob149_ece241_2013_q4 | fail | False | 1 | 7 | 49999 | 251.1 |
| Prob153_gshare | no_rtl | False | 0 | 4 | 51192 | 386.5 |
