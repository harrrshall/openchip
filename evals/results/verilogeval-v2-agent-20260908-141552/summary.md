# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-141552

n = 39; pass = 13 (33.3%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | compile_error | False | 3 | 8 | 9152 | 24.4 |
| Prob005_notgate | pass | True | 2 | 5 | 6927 | 16.5 |
| Prob009_popcount3 | pass | True | 1 | 6 | 11816 | 29.9 |
| Prob013_m2014_q4e | pass | True | 1 | 5 | 10476 | 32.1 |
| Prob017_mux2to1v | pass | True | 1 | 4 | 8354 | 26.1 |
| Prob021_mux256to1v | compile_error | False | 3 | 7 | 15056 | 38.5 |
| Prob025_reduction | no_rtl | False | 0 | 4 | 8004 | 26.0 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 9242 | 39.3 |
| Prob033_ece241_2014_q1c | fail | False | 1 | 5 | 14714 | 79.6 |
| Prob037_review2015_count1k | fail | True | 3 | 8 | 19932 | 43.6 |
| Prob041_dff8r | pass | True | 1 | 5 | 10077 | 32.6 |
| Prob045_edgedetect2 | pass | True | 1 | 7 | 21675 | 124.3 |
| Prob049_m2014_q4b | compile_error | False | 2 | 7 | 13138 | 29.4 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 9829 | 101.6 |
| Prob057_kmap2 | no_rtl | False | 0 | 3 | 32240 | 424.8 |
| Prob061_2014_q4a | pass | True | 1 | 5 | 16152 | 85.4 |
| Prob065_7420 | pass | True | 1 | 4 | 11598 | 37.8 |
| Prob069_truthtable1 | compile_error | False | 4 | 7 | 17020 | 61.0 |
| Prob073_dff16e | pass | True | 1 | 8 | 23949 | 95.0 |
| Prob077_wire_decl | pass | True | 1 | 4 | 10395 | 32.4 |
| Prob081_7458 | pass | True | 1 | 4 | 14362 | 42.0 |
| Prob085_shift4 | fail | False | 3 | 8 | 26324 | 82.9 |
| Prob089_ece241_2014_q5a | fail | False | 4 | 9 | 30556 | 110.5 |
| Prob093_ece241_2014_q3 | no_rtl | False | 0 | 3 | 33115 | 430.2 |
| Prob097_mux9to1v | compile_error | False | 4 | 7 | 19024 | 58.3 |
| Prob101_circuit4 | pass | True | 1 | 4 | 15967 | 118.8 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 13522 | 147.5 |
| Prob109_fsm1 | compile_error | False | 3 | 6 | 19353 | 137.8 |
| Prob113_2012_q1g | fail | True | 1 | 4 | 14797 | 122.1 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 33154 | 430.2 |
| Prob121_2014_q3bfsm | compile_error | False | 2 | 7 | 19380 | 87.8 |
| Prob125_kmap3 | fail | True | 1 | 5 | 25401 | 252.5 |
| Prob129_ece241_2013_q8 | fail | True | 5 | 9 | 27353 | 93.8 |
| Prob133_2014_q3fsm | fail | True | 2 | 7 | 29755 | 151.8 |
| Prob137_fsm_serial | fail | False | 2 | 7 | 22964 | 105.3 |
| Prob141_count_clock | fail | False | 3 | 10 | 50273 | 331.0 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 27162 | 324.0 |
| Prob149_ece241_2013_q4 | fail | False | 1 | 9 | 51280 | 362.0 |
| Prob153_gshare | no_rtl | False | 0 | 5 | 44921 | 406.8 |
