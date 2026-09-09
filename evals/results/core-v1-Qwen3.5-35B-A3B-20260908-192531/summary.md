# Eval `core-v1` — 20260908-192531

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3.5-35B-A3B` @ `59d61f3ce65a6d9863b86d2e96597125219dc754` T=0.2 thinking=True

- agent accepted: 7/10
- golden pass (independent): 7/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 3 | 138.7 | 7 | 55715 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 65.7 | 6 | 28133 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 2 | 24.2 | 6 | 22815 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 2 | 24.7 | 6 | 22236 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 77.5 | 6 | 36118 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 26.4 | 5 | 21070 |
| stream_acc | 0 | stalled | False | lint | None | 3 | 111.8 | 8 | 56660 |
| sync_fifo | 0 | stalled | False | simulate | None | 3 | 147.1 | 9 | 71276 |
| timer | 0 | completed | True | pass | counterexample | 1 | 34.0 | 5 | 25140 |
| updown_counter | 0 | completed | True | pass | error | 1 | 27.1 | 5 | 21270 |
