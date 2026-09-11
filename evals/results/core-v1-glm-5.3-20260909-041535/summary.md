# Eval `core-v1` — 20260909-041535

n = 10 (10 tasks x 1); budget 15m; model `glm-5.3` @ `remote` T=0.2 thinking=False

- agent accepted: 10/10
- golden pass (independent): 10/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | bounded_pass | 1 | 65.3 | 6 | 28841 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 59.5 | 6 | 20296 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 46.2 | 6 | 19574 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 59.2 | 6 | 21648 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 125.0 | 6 | 27310 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 73.0 | 6 | 24228 |
| stream_acc | 0 | completed | True | pass | counterexample | 1 | 142.1 | 6 | 32831 |
| sync_fifo | 0 | completed | True | pass | timeout | 1 | 409.5 | 6 | 28306 |
| timer | 0 | completed | True | pass | counterexample | 1 | 65.4 | 6 | 24981 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 84.3 | 6 | 19470 |
