# Eval `core-v1` — 20260908-164755

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` T=0.2 thinking=True

- agent accepted: 10/10
- golden pass (independent): 10/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | counterexample | 2 | 672.3 | 7 | 42243 |
| edge_detector | 0 | completed | True | pass | bounded_pass | 1 | 157.7 | 5 | 18427 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 115.3 | 5 | 17026 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 151.3 | 5 | 20107 |
| regfile | 0 | completed | True | pass | counterexample | 2 | 304.1 | 6 | 27581 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 144.6 | 5 | 18637 |
| stream_acc | 0 | completed | True | pass | counterexample | 1 | 288.2 | 5 | 28565 |
| sync_fifo | 0 | completed | True | pass | bounded_pass | 1 | 295.2 | 6 | 34730 |
| timer | 0 | completed | True | pass | bounded_pass | 1 | 181.9 | 5 | 21767 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 137.5 | 5 | 18118 |
