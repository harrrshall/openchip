# Eval `core-v1` — 20260908-112718

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 7/10
- golden pass (independent): 6/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 2 | 115.8 | 7 | 31333 |
| edge_detector | 0 | completed | True | pass | None | 1 | 44.7 | 6 | 15083 |
| gray_counter | 0 | completed | True | pass | counterexample | 1 | 90.1 | 7 | 16850 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 49.3 | 5 | 14555 |
| regfile | 0 | completed | True | pass | counterexample | 2 | 65.9 | 6 | 17990 |
| shift_reg | 0 | completed | True | pass | counterexample | 1 | 54.3 | 6 | 16739 |
| stream_acc | 0 | stalled | False | simulate | None | 1 | 124.0 | 8 | 37437 |
| sync_fifo | 0 | stalled | False | simulate | None | 2 | 144.3 | 12 | 42895 |
| timer | 0 | completed | True | simulate | counterexample | 1 | 97.7 | 8 | 22315 |
| updown_counter | 0 | completed | True | pass | counterexample | 1 | 45.2 | 5 | 13961 |
