# Eval `heldout-v1` — 20260908-170958

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3.5-9B` @ `c202236235762e1c871ad0ccb60c8ee5ba337b9a` T=0.2 thinking=True

- agent accepted: 10/10
- golden pass (independent): 8/10
- false acceptance: 2/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 1 | 208.7 | 6 | 28567 |
| debounce | 1 | completed | True | pass | counterexample | 1 | 64.8 | 5 | 17536 |
| prio_enc | 0 | completed | True | pass | bounded_pass | 1 | 50.4 | 5 | 14830 |
| prio_enc | 1 | completed | True | pass | bounded_pass | 1 | 48.8 | 5 | 14830 |
| rr_arbiter | 0 | completed | True | pass | counterexample | 3 | 153.9 | 9 | 35090 |
| rr_arbiter | 1 | completed | True | pass | counterexample | 3 | 154.0 | 9 | 35167 |
| seq_detect | 0 | completed | True | simulate | error | 2 | 137.3 | 7 | 29369 |
| seq_detect | 1 | completed | True | simulate | error | 3 | 145.2 | 7 | 29958 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 83.9 | 5 | 21245 |
| tick_gen | 1 | completed | True | pass | counterexample | 1 | 82.8 | 5 | 21245 |
