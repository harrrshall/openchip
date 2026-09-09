# Eval `core-v1` — 20260908-164638

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3.5-9B` @ `c202236235762e1c871ad0ccb60c8ee5ba337b9a` T=0.2 thinking=True

- agent accepted: 7/10
- golden pass (independent): 7/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 4 | 306.9 | 11 | 64756 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 57.4 | 5 | 15459 |
| gray_counter | 0 | completed | True | pass | counterexample | 1 | 71.1 | 6 | 19836 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 2 | 70.3 | 5 | 20807 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 109.9 | 6 | 27365 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 85.7 | 6 | 24893 |
| stream_acc | 0 | stalled | False | lint | None | 3 | 132.5 | 7 | 37426 |
| sync_fifo | 0 | budget_exhausted | False | simulate | None | 5 | 363.6 | 12 | 78680 |
| timer | 0 | completed | True | pass | counterexample | 1 | 132.5 | 7 | 36132 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 65.8 | 5 | 18132 |
