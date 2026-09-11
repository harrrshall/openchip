# Eval `heldout-v1` — 20260909-064224

n = 10 (5 tasks x 2); budget 15m; model `glm-5.3` @ `remote` T=0.2 thinking=False

- agent accepted: 10/10
- golden pass (independent): 10/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 1 | 91.6 | 7 | 26246 |
| debounce | 1 | completed | True | pass | counterexample | 1 | 73.9 | 6 | 21352 |
| prio_enc | 0 | completed | True | pass | bounded_pass | 1 | 44.9 | 6 | 16815 |
| prio_enc | 1 | completed | True | pass | bounded_pass | 1 | 61.3 | 6 | 18666 |
| rr_arbiter | 0 | completed | True | pass | counterexample | 1 | 92.2 | 7 | 21980 |
| rr_arbiter | 1 | completed | True | pass | bounded_pass | 1 | 67.2 | 6 | 20552 |
| seq_detect | 0 | completed | True | pass | counterexample | 1 | 72.5 | 6 | 20334 |
| seq_detect | 1 | completed | True | pass | bounded_pass | 1 | 84.8 | 6 | 20079 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 75.7 | 6 | 23634 |
| tick_gen | 1 | completed | True | pass | counterexample | 1 | 70.5 | 6 | 24032 |
