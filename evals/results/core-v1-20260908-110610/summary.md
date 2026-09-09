# Eval `core-v1` — 20260908-110610

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 4/10
- golden pass (independent): 6/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 2 | 111.5 | 7 | 30559 |
| edge_detector | 0 | stalled | False | pass | None | 2 | 48.6 | 8 | 20213 |
| gray_counter | 0 | completed | True | pass | counterexample | 2 | 90.6 | 7 | 16329 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 42.0 | 4 | 10739 |
| regfile | 0 | completed | True | pass | counterexample | 2 | 59.4 | 5 | 14218 |
| shift_reg | 0 | stalled | False | pass | None | 3 | 65.0 | 8 | 24246 |
| stream_acc | 0 | stalled | False | simulate | None | 3 | 129.6 | 9 | 41716 |
| sync_fifo | 0 | stalled | False | simulate | None | 4 | 132.5 | 12 | 41611 |
| timer | 0 | stalled | False | simulate | None | 1 | 106.7 | 9 | 25546 |
| updown_counter | 0 | completed | True | pass | counterexample | 1 | 40.0 | 4 | 10397 |
