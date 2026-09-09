# Eval `heldout-v1` — 20260908-193652

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3.5-35B-A3B` @ `59d61f3ce65a6d9863b86d2e96597125219dc754` T=0.2 thinking=True

- agent accepted: 8/10
- golden pass (independent): 8/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | stalled | False | lint | None | 3 | 135.1 | 8 | 48195 |
| debounce | 1 | stalled | False | lint | None | 3 | 85.9 | 7 | 37164 |
| prio_enc | 0 | completed | True | pass | None | 1 | 13.8 | 4 | 12796 |
| prio_enc | 1 | completed | True | pass | None | 1 | 14.1 | 4 | 12796 |
| rr_arbiter | 0 | completed | True | pass | bounded_pass | 2 | 45.3 | 6 | 27583 |
| rr_arbiter | 1 | completed | True | pass | bounded_pass | 2 | 44.8 | 6 | 27583 |
| seq_detect | 0 | completed | True | pass | counterexample | 2 | 34.1 | 6 | 21639 |
| seq_detect | 1 | completed | True | pass | counterexample | 2 | 32.6 | 6 | 21639 |
| tick_gen | 0 | completed | True | pass | error | 2 | 79.0 | 7 | 39132 |
| tick_gen | 1 | completed | True | pass | error | 2 | 78.6 | 7 | 39132 |
