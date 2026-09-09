# Eval `heldout-v1` — 20260908-135248

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 4/10
- golden pass (independent): 3/10
- false acceptance: 2/10
- interface mismatch: 2/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | interface_mismatch | counterexample | 2 | 42.4 | 5 | 13276 |
| debounce | 1 | completed | True | interface_mismatch | counterexample | 2 | 43.8 | 6 | 15919 |
| prio_enc | 0 | completed | True | pass | None | 3 | 102.3 | 8 | 23427 |
| prio_enc | 1 | stalled | False | pass | None | 2 | 58.0 | 7 | 16660 |
| rr_arbiter | 0 | stalled | False | lint | None | 4 | 109.6 | 11 | 34550 |
| rr_arbiter | 1 | stalled | False | lint | None | 2 | 68.3 | 8 | 22009 |
| seq_detect | 0 | budget_exhausted | False | simulate | None | 6 | 154.0 | 10 | 34834 |
| seq_detect | 1 | stalled | False | simulate | None | 2 | 212.7 | 9 | 35810 |
| tick_gen | 0 | completed | True | pass | counterexample | 1 | 55.2 | 6 | 17958 |
| tick_gen | 1 | failed | False | no_rtl | None | 0 | 68.0 | 3 | 7799 |
