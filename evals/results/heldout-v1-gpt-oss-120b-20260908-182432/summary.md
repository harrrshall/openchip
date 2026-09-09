# Eval `heldout-v1` — 20260908-182432

n = 10 (5 tasks x 2); budget 15m; model `openai/gpt-oss-120b` @ `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` T=0.2 thinking=True

- agent accepted: 8/10
- golden pass (independent): 8/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | stalled | False | lint | None | 3 | 32.7 | 6 | 18729 |
| debounce | 1 | completed | True | pass | counterexample | 1 | 29.6 | 5 | 18376 |
| prio_enc | 0 | stalled | False | simulate | None | 4 | 38.1 | 8 | 25630 |
| prio_enc | 1 | completed | True | pass | bounded_pass | 1 | 24.3 | 5 | 16032 |
| rr_arbiter | 0 | completed | True | pass | counterexample | 1 | 42.4 | 6 | 23400 |
| rr_arbiter | 1 | completed | True | pass | None | 1 | 34.2 | 6 | 21186 |
| seq_detect | 0 | completed | True | pass | counterexample | 2 | 26.9 | 6 | 18022 |
| seq_detect | 1 | completed | True | pass | counterexample | 2 | 23.3 | 6 | 19049 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 29.5 | 5 | 18688 |
| tick_gen | 1 | completed | True | pass | bounded_pass | 1 | 35.7 | 6 | 20943 |
