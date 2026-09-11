# Eval `heldout-v1` — 20260909-064225

n = 10 (5 tasks x 2); budget 15m; model `deepseek-v4-flash` @ `remote` T=0.2 thinking=False

- agent accepted: 10/10
- golden pass (independent): 10/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | bounded_pass | 2 | 242.7 | 7 | 52084 |
| debounce | 1 | completed | True | pass | None | 1 | 286.6 | 7 | 58627 |
| prio_enc | 0 | completed | True | pass | bounded_pass | 1 | 154.3 | 7 | 35350 |
| prio_enc | 1 | completed | True | pass | None | 1 | 55.1 | 5 | 18952 |
| rr_arbiter | 0 | completed | True | pass | bounded_pass | 1 | 175.9 | 6 | 38501 |
| rr_arbiter | 1 | completed | True | pass | bounded_pass | 1 | 196.8 | 6 | 42160 |
| seq_detect | 0 | completed | True | pass | None | 1 | 289.2 | 7 | 55794 |
| seq_detect | 1 | completed | True | pass | bounded_pass | 1 | 195.9 | 6 | 39874 |
| tick_gen | 0 | completed | True | pass | bounded_pass | 1 | 237.2 | 6 | 47250 |
| tick_gen | 1 | completed | True | pass | bounded_pass | 1 | 156.7 | 6 | 37996 |
