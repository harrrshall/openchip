# Eval `heldout-v1` — 20260908-154311

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 5/10
- golden pass (independent): 5/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | pass | counterexample | 2 | 90.3 | 5 | 17625 |
| debounce | 1 | stalled | False | pass | None | 1 | 77.3 | 6 | 19934 |
| prio_enc | 0 | stalled | False | simulate | None | 1 | 216.4 | 8 | 31348 |
| prio_enc | 1 | completed | True | pass | None | 2 | 84.7 | 7 | 20295 |
| rr_arbiter | 0 | stalled | False | lint | None | 4 | 103.7 | 11 | 34023 |
| rr_arbiter | 1 | stalled | False | lint | None | 2 | 69.6 | 8 | 21996 |
| seq_detect | 0 | budget_exhausted | False | simulate | None | 6 | 74.2 | 10 | 30384 |
| seq_detect | 1 | completed | True | simulate | counterexample | 5 | 263.0 | 11 | 45601 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 45.4 | 5 | 15044 |
| tick_gen | 1 | completed | True | pass | None | 1 | 46.1 | 6 | 17101 |
