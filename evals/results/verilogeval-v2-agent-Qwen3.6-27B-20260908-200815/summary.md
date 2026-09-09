# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-200815

n = 39; pass = 18 (46.2%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `Qwen/Qwen3.6-27B` @ `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 9819 | 137.1 |
| Prob005_notgate | pass | True | 1 | 4 | 8666 | 107.6 |
| Prob009_popcount3 | pass | True | 1 | 4 | 14448 | 246.6 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 10519 | 152.4 |
| Prob017_mux2to1v | no_rtl | False | 0 | 4 | 12645 | 152.9 |
| Prob021_mux256to1v | pass | True | 1 | 4 | 16033 | 281.3 |
| Prob025_reduction | pass | True | 1 | 4 | 12877 | 209.4 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 11922 | 173.2 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 5 | 19593 | 290.3 |
| Prob037_review2015_count1k | pass | True | 1 | 5 | 15485 | 198.1 |
| Prob041_dff8r | pass | True | 1 | 5 | 16410 | 238.5 |
| Prob045_edgedetect2 | no_rtl | False | 0 | 2 | 12626 | 404.4 |
| Prob049_m2014_q4b | pass | True | 1 | 5 | 17010 | 279.4 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 2 | 12733 | 410.3 |
| Prob057_kmap2 | no_rtl | False | 0 | 1 | 10460 | 360.4 |
| Prob061_2014_q4a | no_rtl | False | 0 | 2 | 11956 | 379.5 |
| Prob065_7420 | no_rtl | False | 0 | 3 | 16645 | 515.8 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 14462 | 219.0 |
| Prob073_dff16e | pass | True | 1 | 5 | 22017 | 335.7 |
| Prob077_wire_decl | pass | True | 1 | 4 | 13043 | 183.1 |
| Prob081_7458 | pass | True | 1 | 4 | 19582 | 255.5 |
| Prob085_shift4 | no_rtl | False | 0 | 2 | 14047 | 451.9 |
| Prob089_ece241_2014_q5a | no_rtl | False | 0 | 2 | 14293 | 368.4 |
| Prob093_ece241_2014_q3 | fail | True | 1 | 4 | 20228 | 359.3 |
| Prob097_mux9to1v | pass | False | 3 | 5 | 21711 | 324.1 |
| Prob101_circuit4 | pass | True | 1 | 4 | 16545 | 236.9 |
| Prob105_rotate100 | no_rtl | False | 0 | 2 | 13276 | 418.3 |
| Prob109_fsm1 | pass | True | 1 | 5 | 21368 | 342.7 |
| Prob113_2012_q1g | no_rtl | False | 0 | 2 | 13296 | 369.2 |
| Prob117_circuit9 | no_rtl | False | 0 | 2 | 19335 | 642.5 |
| Prob121_2014_q3bfsm | no_rtl | False | 0 | 3 | 16744 | 377.8 |
| Prob125_kmap3 | fail | False | 1 | 4 | 22664 | 502.4 |
| Prob129_ece241_2013_q8 | fail | True | 1 | 5 | 25153 | 431.5 |
| Prob133_2014_q3fsm | no_rtl | False | 0 | 3 | 17396 | 372.0 |
| Prob137_fsm_serial | no_rtl | False | 0 | 3 | 16937 | 363.4 |
| Prob141_count_clock | no_rtl | False | 0 | 3 | 17832 | 382.3 |
| Prob145_circuit8 | no_rtl | False | 0 | 2 | 20321 | 648.0 |
| Prob149_ece241_2013_q4 | no_rtl | False | 0 | 2 | 15103 | 376.5 |
| Prob153_gshare | no_rtl | False | 0 | 1 | 11027 | 363.9 |
