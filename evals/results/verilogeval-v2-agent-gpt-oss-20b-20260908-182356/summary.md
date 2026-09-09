# VerilogEval v2 spec-to-rtl — mode `agent` — 20260908-182356

n = 39; pass = 22 (56.4%); protocol: full OpenChip pipeline with tool feedback, budget 6m/problem; not comparable to single-generation pass@1
model `openai/gpt-oss-20b` @ `6cee5e81ee83917806bbde320786a8fb61efebee` T=0.2 thinking_roles=[]

| problem | status | accepted | attempts | calls | tokens | wall s |
|---|---|---|---|---|---|---|
| Prob001_zero | pass | True | 1 | 4 | 6310 | 4.6 |
| Prob005_notgate | pass | True | 1 | 4 | 6358 | 4.1 |
| Prob009_popcount3 | fail | True | 3 | 8 | 19632 | 18.6 |
| Prob013_m2014_q4e | pass | True | 1 | 4 | 7049 | 4.7 |
| Prob017_mux2to1v | fail | True | 3 | 6 | 13733 | 13.1 |
| Prob021_mux256to1v | pass | True | 1 | 5 | 12130 | 9.6 |
| Prob025_reduction | pass | True | 1 | 4 | 7775 | 5.9 |
| Prob029_m2014_q4g | fail | True | 1 | 5 | 13535 | 11.4 |
| Prob033_ece241_2014_q1c | pass | True | 1 | 4 | 9174 | 8.0 |
| Prob037_review2015_count1k | pass | True | 2 | 6 | 15601 | 13.9 |
| Prob041_dff8r | pass | True | 1 | 5 | 10922 | 7.3 |
| Prob045_edgedetect2 | pass | True | 2 | 9 | 23892 | 21.7 |
| Prob049_m2014_q4b | pass | True | 1 | 9 | 23701 | 21.4 |
| Prob053_m2014_q4d | no_rtl | False | 0 | 3 | 5169 | 7.3 |
| Prob057_kmap2 | pass | True | 1 | 4 | 10539 | 11.2 |
| Prob061_2014_q4a | pass | True | 1 | 6 | 15670 | 13.0 |
| Prob065_7420 | pass | True | 1 | 4 | 11242 | 9.3 |
| Prob069_truthtable1 | pass | True | 1 | 4 | 8535 | 6.3 |
| Prob073_dff16e | pass | True | 1 | 6 | 20710 | 17.5 |
| Prob077_wire_decl | pass | True | 1 | 5 | 13249 | 8.7 |
| Prob081_7458 | pass | True | 1 | 4 | 12942 | 9.6 |
| Prob085_shift4 | pass | True | 1 | 5 | 15929 | 13.1 |
| Prob089_ece241_2014_q5a | fail | False | 2 | 7 | 23188 | 19.8 |
| Prob093_ece241_2014_q3 | fail | False | 1 | 5 | 18391 | 17.4 |
| Prob097_mux9to1v | pass | False | 3 | 5 | 12407 | 10.5 |
| Prob101_circuit4 | fail | True | 1 | 4 | 10127 | 6.4 |
| Prob105_rotate100 | pass | True | 2 | 8 | 35174 | 52.8 |
| Prob109_fsm1 | pass | True | 2 | 6 | 17692 | 16.5 |
| Prob113_2012_q1g | fail | True | 1 | 4 | 9289 | 10.0 |
| Prob117_circuit9 | fail | True | 1 | 6 | 16688 | 15.6 |
| Prob121_2014_q3bfsm | pass | True | 1 | 6 | 17963 | 15.5 |
| Prob125_kmap3 | fail | True | 1 | 5 | 16643 | 13.7 |
| Prob129_ece241_2013_q8 | compile_error | False | 3 | 6 | 19379 | 18.7 |
| Prob133_2014_q3fsm | fail | False | 4 | 8 | 33179 | 30.1 |
| Prob137_fsm_serial | fail | True | 2 | 5 | 17743 | 16.0 |
| Prob141_count_clock | fail | True | 1 | 6 | 23641 | 18.3 |
| Prob145_circuit8 | fail | True | 2 | 8 | 25898 | 25.2 |
| Prob149_ece241_2013_q4 | fail | True | 3 | 10 | 43481 | 36.3 |
| Prob153_gshare | fail | True | 5 | 12 | 80735 | 72.3 |
