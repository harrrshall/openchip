# Eval `core-v1` — 20260909-041529

n = 10 (10 tasks x 1); budget 15m; model `deepseek-v4-flash` @ `remote` T=0.2 thinking=False

- agent accepted: 9/10
- golden pass (independent): 9/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | bounded_pass | 1 | 160.9 | 6 | 48410 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 133.3 | 6 | 32999 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 100.3 | 6 | 27137 |
| pwm_gen | 0 | completed | True | pass | counterexample | 1 | 141.0 | 6 | 34251 |
| regfile | 0 | completed | True | pass | timeout | 1 | 534.9 | 6 | 50567 |
| shift_reg | 0 | completed | True | pass | bounded_pass | 1 | 130.4 | 6 | 36833 |
| stream_acc | 0 | failed | False | no_rtl | None | 0 | 218.3 | 3 | 34660 |
| sync_fifo | 0 | completed | True | pass | None | 2 | 404.3 | 9 | 97805 |
| timer | 0 | completed | True | pass | counterexample | 1 | 186.0 | 6 | 46334 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 179.3 | 7 | 41713 |
