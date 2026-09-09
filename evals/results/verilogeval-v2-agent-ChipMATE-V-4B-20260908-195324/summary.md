# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-195324

n = 39; pass = 7 (17.9%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `core12345/ChipMATE-V-4B` @ `7fbb17249a49d109787bbc024a7a21b83302a1c2` T=0.2 thinking_roles=['intake']

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 6 | 9778 | 9.2 |
| Prob005_notgate | no_rtl | False | 0 | 5 | 9271 | 17.7 |
| Prob009_popcount3 | pass | True | 1 | 7 | 16374 | 16.9 |
| Prob013_m2014_q4e | pass | True | 1 | 5 | 9666 | 10.2 |
| Prob017_mux2to1v | pass | True | 1 | 6 | 22278 | 101.6 |
| Prob021_mux256to1v | no_rtl | False | 0 | 4 | 9260 | 12.3 |
| Prob025_reduction | no_rtl | False | 0 | 4 | 7918 | 9.6 |
| Prob029_m2014_q4g | no_rtl | False | 0 | 4 | 10197 | 13.6 |
| Prob033_ece241_2014_q1c | fail | True | 1 | 7 | 15239 | 28.2 |
| Prob037_review2015_count1k | no_rtl | False | 0 | 4 | 10287 | 13.4 |
| Prob041_dff8r | pass | True | 1 | 7 | 23489 | 101.8 |
| Prob045_edgedetect2 | no_rtl | False | 0 | 3 | 7641 | 41.5 |
| Prob049_m2014_q4b | no_rtl | False | 0 | 4 | 9004 | 12.6 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 4668 | 16.0 |
| Prob057_kmap2 | no_rtl | False | 0 | 4 | 9391 | 14.4 |
| Prob061_2014_q4a | no_rtl | False | 0 | 3 | 14533 | 103.9 |
| Prob065_7420 | no_rtl | False | 0 | 4 | 11708 | 16.9 |
| Prob069_truthtable1 | pass | True | 2 | 6 | 13417 | 19.3 |
| Prob073_dff16e | no_rtl | False | 0 | 4 | 11048 | 15.6 |
| Prob077_wire_decl | pass | True | 1 | 6 | 14679 | 15.3 |
| Prob081_7458 | no_rtl | False | 0 | 4 | 13444 | 16.8 |
| Prob085_shift4 | compile_error | False | 2 | 10 | 31192 | 29.6 |
| Prob089_ece241_2014_q5a | fail | True | 2 | 8 | 29637 | 32.8 |
| Prob093_ece241_2014_q3 | no_rtl | False | 0 | 4 | 11074 | 15.4 |
| Prob097_mux9to1v | no_rtl | False | 0 | 6 | 28112 | 116.9 |
| Prob101_circuit4 | no_rtl | False | 0 | 4 | 11134 | 13.5 |
| Prob105_rotate100 | no_rtl | False | 0 | 3 | 6361 | 26.5 |
| Prob109_fsm1 | no_rtl | False | 0 | 4 | 11346 | 17.2 |
| Prob113_2012_q1g | no_rtl | False | 0 | 4 | 8939 | 12.4 |
| Prob117_circuit9 | no_rtl | False | 0 | 3 | 24175 | 184.2 |
| Prob121_2014_q3bfsm | no_rtl | False | 0 | 4 | 12973 | 18.0 |
| Prob125_kmap3 | no_rtl | False | 0 | 4 | 9722 | 14.8 |
| Prob129_ece241_2013_q8 | fail | True | 1 | 5 | 17549 | 31.2 |
| Prob133_2014_q3fsm | no_rtl | False | 0 | 4 | 13818 | 19.2 |
| Prob137_fsm_serial | no_rtl | False | 0 | 4 | 16123 | 23.6 |
| Prob141_count_clock | compile_error | False | 2 | 9 | 35582 | 50.0 |
| Prob145_circuit8 | no_rtl | False | 0 | 3 | 6878 | 17.8 |
| Prob149_ece241_2013_q4 | fail | False | 1 | 9 | 39268 | 59.4 |
| Prob153_gshare | no_rtl | False | 0 | 4 | 21806 | 32.3 |
