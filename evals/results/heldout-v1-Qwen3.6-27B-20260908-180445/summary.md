# Eval `heldout-v1` — 20260908-180445

n = 10 (5 tasks x 2); budget 15m; model `Qwen/Qwen3.6-27B` @ `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` T=0.2 thinking=True

- agent accepted: 6/10
- golden pass (independent): 6/10
- false acceptance: 0/10
- interface mismatch: 2/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| debounce | 0 | failed | False | no_rtl | None | 0 | 694.3 | 3 | 21588 |
| debounce | 1 | failed | False | no_rtl | None | 0 | 694.1 | 3 | 21588 |
| prio_enc | 0 | stalled | False | interface_mismatch | None | 3 | 583.6 | 8 | 34751 |
| prio_enc | 1 | stalled | False | interface_mismatch | None | 3 | 638.3 | 8 | 36268 |
| rr_arbiter | 0 | completed | True | pass | counterexample | 2 | 471.5 | 6 | 28982 |
| rr_arbiter | 1 | completed | True | pass | counterexample | 2 | 469.6 | 6 | 28982 |
| seq_detect | 0 | completed | True | pass | counterexample | 4 | 425.2 | 9 | 33748 |
| seq_detect | 1 | completed | True | pass | counterexample | 4 | 447.4 | 9 | 34397 |
| tick_gen | 0 | completed | True | pass | bounded_pass | 1 | 334.6 | 5 | 22621 |
| tick_gen | 1 | completed | True | pass | bounded_pass | 1 | 333.1 | 5 | 22621 |
