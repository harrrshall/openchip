# Eval `core-v1` — 20260908-115153

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 7/10
- golden pass (independent): 6/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 5 | 188.4 | 12 | 57450 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 38.8 | 5 | 13095 |
| gray_counter | 0 | completed | True | pass | counterexample | 1 | 87.0 | 7 | 16892 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 42.7 | 5 | 14346 |
| regfile | 0 | completed | True | pass | bounded_pass | 2 | 211.3 | 7 | 30653 |
| shift_reg | 0 | completed | True | pass | counterexample | 1 | 41.9 | 5 | 14092 |
| stream_acc | 0 | stalled | False | simulate | None | 1 | 250.2 | 8 | 46575 |
| sync_fifo | 0 | stalled | False | simulate | None | 2 | 137.2 | 12 | 42909 |
| timer | 0 | completed | True | simulate | None | 1 | 103.3 | 9 | 25284 |
| updown_counter | 0 | completed | True | pass | counterexample | 1 | 56.3 | 6 | 17276 |
