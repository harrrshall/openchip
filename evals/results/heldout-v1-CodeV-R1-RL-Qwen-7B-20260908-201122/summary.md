# Eval `heldout-v1` — 20260908-201122

n = 10 (5 tasks x 2); budget 15m; model `zhuyaoyu/CodeV-R1-RL-Qwen-7B` @ `286cf433f596f1b8525529c1163eb81c19425c22` T=0.2 thinking=True

- agent accepted: 4/10
- golden pass (independent): 5/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 2 | 354.4 | 6 | 40745 |
| debounce | 1 | completed | True | pass | counterexample | 2 | 23.3 | 5 | 11826 |
| prio_enc | 0 | completed | True | pass | None | 1 | 113.2 | 7 | 23584 |
| prio_enc | 1 | failed | False | no_rtl | None | 0 | 23.1 | 4 | 9872 |
| rr_arbiter | 0 | failed | False | no_rtl | None | 0 | 327.5 | 4 | 35832 |
| rr_arbiter | 1 | failed | False | no_rtl | None | 0 | 255.6 | 4 | 29981 |
| seq_detect | 0 | stalled | False | pass | None | 2 | 266.4 | 7 | 35624 |
| seq_detect | 1 | completed | True | pass | counterexample | 2 | 90.0 | 7 | 22410 |
| tick_gen | 0 | failed | False | no_rtl | None | 0 | 39.1 | 3 | 6203 |
| tick_gen | 1 | failed | False | no_rtl | None | 0 | 38.0 | 3 | 6121 |
