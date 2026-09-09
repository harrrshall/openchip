# Eval `heldout-v1` — 20260908-133453

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 4/10
- golden pass (independent): 2/10
- false acceptance: 2/10
- interface mismatch: 2/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | completed | True | interface_mismatch | counterexample | 1 | 38.5 | 5 | 12482 |
| debounce | 1 | completed | True | interface_mismatch | counterexample | 1 | 59.9 | 6 | 15266 |
| prio_enc | 0 | failed | False | no_rtl | None | 0 | 60.0 | 4 | 12453 |
| prio_enc | 1 | failed | False | no_rtl | None | 0 | 75.2 | 4 | 13083 |
| rr_arbiter | 0 | failed | False | no_rtl | None | 0 | 42.5 | 4 | 12226 |
| rr_arbiter | 1 | failed | False | no_rtl | None | 0 | 41.9 | 4 | 12719 |
| seq_detect | 0 | budget_exhausted | False | simulate | None | 6 | 74.1 | 11 | 31006 |
| seq_detect | 1 | completed | True | pass | counterexample | 2 | 48.5 | 5 | 12962 |
| tick_gen | 0 | stalled | False | lint | None | 2 | 81.1 | 9 | 23778 |
| tick_gen | 1 | completed | True | pass | None | 1 | 54.9 | 6 | 17615 |
