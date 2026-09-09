# Eval `core-v1` — 20260908-104235

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 4/10
- golden pass (independent): 5/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 2 | 105.5 | 7 | 30461 |
| edge_detector | 0 | budget_exhausted | False | pass | None | 5 | 64.8 | 10 | 26616 |
| gray_counter | 0 | stalled | False | simulate | None | 4 | 104.6 | 10 | 22975 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 50.0 | 5 | 13222 |
| regfile | 0 | completed | True | pass | counterexample | 2 | 58.9 | 5 | 14132 |
| shift_reg | 0 | stalled | False | pass | None | 3 | 62.0 | 7 | 21230 |
| stream_acc | 0 | stalled | False | simulate | None | 2 | 241.1 | 8 | 45991 |
| sync_fifo | 0 | budget_exhausted | False | simulate | None | 5 | 131.8 | 11 | 38473 |
| timer | 0 | completed | True | simulate | None | 2 | 115.6 | 9 | 25518 |
| updown_counter | 0 | completed | True | pass | None | 1 | 53.9 | 5 | 13315 |
