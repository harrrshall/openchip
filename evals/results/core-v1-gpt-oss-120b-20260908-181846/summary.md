# Eval `core-v1` — 20260908-181846

n = 10 (10 tasks x 1); budget 15m; model `openai/gpt-oss-120b` @ `b5c939de8f754692c1647ca79fbf85e8c1e70f8a` T=0.2 thinking=True

- agent accepted: 10/10
- golden pass (independent): 9/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | None | 1 | 54.5 | 6 | 29596 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 28.7 | 6 | 20199 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 23.0 | 5 | 16311 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 25.4 | 5 | 17297 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 36.3 | 5 | 22548 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 27.9 | 5 | 18351 |
| stream_acc | 0 | completed | True | simulate | counterexample | 2 | 51.4 | 5 | 30672 |
| sync_fifo | 0 | completed | True | pass | counterexample | 1 | 36.7 | 5 | 22581 |
| timer | 0 | completed | True | pass | counterexample | 1 | 35.0 | 5 | 21430 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 23.0 | 5 | 16811 |
