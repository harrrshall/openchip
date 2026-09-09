# Eval `core-v1` — 20260908-164627

n = 10 (10 tasks x 1); budget 15m; model `AS-SiliconMind/SiliconMind-V1-Qwen3-8B` @ `901f9c51184334ef7270211862c42369ad7bb177` T=0.2 thinking=True

- agent accepted: 6/10
- golden pass (independent): 7/10
- false acceptance: 0/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | completed | True | pass | None | 1 | 241.6 | 8 | 42438 |
| edge_detector | 0 | completed | True | pass | counterexample | 1 | 60.0 | 7 | 25396 |
| gray_counter | 0 | completed | True | pass | bounded_pass | 1 | 69.2 | 7 | 20005 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 70.4 | 8 | 34914 |
| regfile | 0 | completed | True | pass | counterexample | 1 | 90.2 | 6 | 27658 |
| shift_reg | 0 | failed | False | no_rtl | None | 0 | 43.9 | 4 | 16376 |
| stream_acc | 0 | stalled | False | simulate | None | 1 | 323.3 | 9 | 69197 |
| sync_fifo | 0 | stalled | False | simulate | None | 2 | 594.4 | 11 | 87538 |
| timer | 0 | stalled | False | pass | None | 1 | 254.9 | 8 | 45238 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 46.8 | 6 | 19901 |
