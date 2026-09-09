# Eval `core-v1` — 20260908-181249

n = 10 (10 tasks x 1); budget 15m; model `openai/gpt-oss-20b` @ `6cee5e81ee83917806bbde320786a8fb61efebee` T=0.2 thinking=True

- agent accepted: 8/10
- golden pass (independent): 8/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | bounded_pass | 1 | 38.4 | 7 | 29615 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 17.1 | 6 | 18802 |
| gray_counter | 0 | completed | True | pass | counterexample | 1 | 15.0 | 5 | 14906 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 16.2 | 5 | 18208 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 18.5 | 5 | 18511 |
| shift_reg | 0 | completed | True | pass | counterexample | 1 | 14.1 | 5 | 17834 |
| stream_acc | 0 | stalled | False | simulate | None | 4 | 46.1 | 9 | 50634 |
| sync_fifo | 0 | stalled | False | compile | None | 3 | 33.5 | 7 | 31811 |
| timer | 0 | completed | True | pass | counterexample | 1 | 18.9 | 5 | 20588 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 13.8 | 5 | 14965 |
