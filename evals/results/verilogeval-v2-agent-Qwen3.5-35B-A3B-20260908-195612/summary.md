# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-195612

n = 39; pass = 23 (59.0%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `Qwen/Qwen3.5-35B-A3B` @ `59d61f3ce65a6d9863b86d2e96597125219dc754` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 9547 | 20.6 |
| Prob005_notgate | pass | True | 1 | 5 | 17825 | 51.0 |
| Prob009_popcount3 | pass | True | 1 | 4 | 9017 | 8.2 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 7905 | 6.9 |
| Prob017_mux2to1v | pass | True | 1 | 6 | 27754 | 57.7 |
| Prob021_mux256to1v | pass | True | 3 | 5 | 12980 | 14.3 |
| Prob025_reduction | pass | True | 1 | 4 | 8728 | 7.2 |
| Prob029_m2014_q4g | pass | True | 1 | 4 | 9463 | 8.2 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 4 | 12343 | 14.3 |
| Prob037_review2015_count1k | pass | True | 1 | 5 | 13947 | 13.9 |
| Prob041_dff8r | pass | True | 1 | 5 | 13803 | 13.0 |
| Prob045_edgedetect2 | compile_error | False | 3 | 7 | 21484 | 28.4 |
| Prob049_m2014_q4b | pass | True | 1 | 6 | 39340 | 108.5 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5856 | 13.8 |
| Prob057_kmap2 | no_rtl | False | 0 | 5 | 43517 | 143.3 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 6614 | 16.1 |
| Prob065_7420 | pass | True | 1 | 4 | 13962 | 15.6 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 15931 | 21.7 |
| Prob073_dff16e | pass | True | 1 | 5 | 19927 | 24.4 |
| Prob077_wire_decl | pass | True | 1 | 4 | 11019 | 9.3 |
| Prob081_7458 | pass | True | 1 | 4 | 17150 | 20.6 |
| Prob085_shift4 | pass | True | 1 | 6 | 27632 | 31.3 |
| Prob089_ece241_2014_q5a | pass | False | 1 | 7 | 45804 | 112.0 |
| Prob093_ece241_2014_q3 | fail | False | 5 | 9 | 54340 | 89.5 |
| Prob097_mux9to1v | pass | False | 5 | 8 | 50786 | 111.2 |
| Prob101_circuit4 | fail | True | 1 | 4 | 12840 | 10.2 |
| Prob105_rotate100 | pass | True | 1 | 5 | 23949 | 31.9 |
| Prob109_fsm1 | fail | False | 3 | 7 | 42904 | 109.8 |
| Prob113_2012_q1g | fail | True | 1 | 4 | 14838 | 15.3 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 15889 | 56.3 |
| Prob121_2014_q3bfsm | fail | True | 3 | 8 | 50046 | 121.3 |
| Prob125_kmap3 | pass | False | 3 | 7 | 65201 | 170.4 |
| Prob129_ece241_2013_q8 | pass | True | 1 | 6 | 35770 | 85.2 |
| Prob133_2014_q3fsm | compile_error | False | 4 | 11 | 105916 | 204.8 |
| Prob137_fsm_serial | fail | True | 1 | 7 | 46164 | 116.5 |
| Prob141_count_clock | fail | False | 3 | 8 | 54801 | 99.7 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 26016 | 96.8 |
| Prob149_ece241_2013_q4 | fail | True | 4 | 10 | 85551 | 190.2 |
| Prob153_gshare | fail | False | 4 | 12 | 113724 | 245.0 |
