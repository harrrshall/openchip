# VerilogEval v2 spec-to-rtl — mode `agent` — 20260909-080655

n = 39; pass = 32 (82.0%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `deepseek-v4-flash` @ `remote` T=0.2 thinking_roles=[]

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 5 | 9413 | 25.3 |
| Prob005_notgate | pass | True | 1 | 5 | 10508 | 28.6 |
| Prob009_popcount3 | pass | True | 1 | 5 | 12404 | 27.9 |
| Prob013_m2014_q4e | pass | True | 1 | 5 | 10974 | 31.5 |
| Prob017_mux2to1v | pass | True | 1 | 5 | 12592 | 37.6 |
| Prob021_mux256to1v | pass | True | 1 | 5 | 14781 | 42.5 |
| Prob025_reduction | pass | True | 1 | 5 | 12343 | 37.0 |
| Prob029_m2014_q4g | pass | True | 1 | 5 | 13832 | 36.5 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 5 | 15959 | 51.3 |
| Prob037_review2015_count1k | pass | True | 1 | 6 | 25028 | 108.4 |
| Prob041_dff8r | pass | True | 1 | 6 | 24138 | 102.8 |
| Prob045_edgedetect2 | pass | False | 2 | 7 | 69434 | 409.5 |
| Prob049_m2014_q4b | pass | True | 1 | 7 | 42755 | 242.6 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 10560 | 58.5 |
| Prob057_kmap2 | pass | True | 1 | 6 | 37846 | 164.7 |
| Prob061_2014_q4a | pass | False | 3 | 9 | 44147 | 170.0 |
| Prob065_7420 | pass | True | 1 | 5 | 18414 | 47.1 |
| Prob069_truthtable1 | pass | True | 1 | 5 | 14908 | 39.5 |
| Prob073_dff16e | pass | True | 1 | 6 | 26757 | 97.0 |
| Prob077_wire_decl | pass | True | 1 | 5 | 15624 | 43.9 |
| Prob081_7458 | pass | True | 1 | 5 | 18816 | 41.0 |
| Prob085_shift4 | pass | True | 1 | 6 | 32603 | 120.1 |
| Prob089_ece241_2014_q5a | no_rtl | False | 0 | 3 | 33841 | 250.6 |
| Prob093_ece241_2014_q3 | fail | True | 1 | 7 | 46377 | 229.1 |
| Prob097_mux9to1v | pass | False | 1 | 5 | 19278 | 63.2 |
| Prob101_circuit4 | pass | True | 1 | 5 | 17363 | 47.2 |
| Prob105_rotate100 | pass | True | 1 | 7 | 39636 | 161.6 |
| Prob109_fsm1 | pass | True | 1 | 6 | 30668 | 135.0 |
| Prob113_2012_q1g | pass | True | 1 | 5 | 25770 | 110.5 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 34141 | 280.0 |
| Prob121_2014_q3bfsm | pass | True | 1 | 6 | 33341 | 147.8 |
| Prob125_kmap3 | pass | True | 1 | 5 | 28633 | 121.1 |
| Prob129_ece241_2013_q8 | pass | True | 1 | 7 | 47250 | 223.7 |
| Prob133_2014_q3fsm | no_rtl | False | 0 | 3 | 34075 | 277.9 |
| Prob137_fsm_serial | pass | True | 1 | 7 | 68104 | 362.0 |
| Prob141_count_clock | pass | True | 1 | 6 | 56136 | 247.2 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 34987 | 236.4 |
| Prob149_ece241_2013_q4 | no_rtl | False | 0 | 6 | 67387 | 370.6 |
| Prob153_gshare | pass | True | 1 | 6 | 64453 | 280.9 |
