# Eval `core-v1` — 20260908-164620

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3.6-27B` @ `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9` T=0.2 thinking=True

- agent accepted: 9/10
- golden pass (independent): 9/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | None | 1 | 479.8 | 6 | 35773 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 355.5 | 5 | 22622 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 239.7 | 5 | 17576 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 493.0 | 6 | 26662 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 365.8 | 5 | 24330 |
| shift_reg | 0 | completed | True | pass | counterexample | 1 | 378.4 | 5 | 25038 |
| stream_acc | 0 | completed | True | pass | counterexample | 2 | 696.0 | 6 | 47200 |
| sync_fifo | 0 | completed | True | pass | bounded_pass | 2 | 505.5 | 7 | 40531 |
| timer | 0 | failed | False | no_rtl | None | 0 | 836.4 | 3 | 25435 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 352.1 | 5 | 23692 |
