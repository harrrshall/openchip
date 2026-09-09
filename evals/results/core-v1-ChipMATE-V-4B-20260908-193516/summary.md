# Eval `core-v1` — 20260908-193516

n = 10 (10 tasks x 1); budget 15m; model `core12345/ChipMATE-V-4B` @ `7fbb17249a49d109787bbc024a7a21b83302a1c2` T=0.2 thinking=True

- agent accepted: 5/10
- golden pass (independent): 5/10
- false acceptance: 1/10
- interface mismatch: 0/10

| task | rep | state | accepted | golden | formal | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | stalled | False | simulate | None | 3 | 58.8 | 10 | 45509 |
| edge_detector | 0 | failed | False | no_rtl | None | 0 | 193.9 | 6 | 34938 |
| gray_counter | 0 | completed | True | pass | counterexample | 2 | 20.2 | 6 | 14996 |
| pwm_gen | 0 | completed | True | pass | bounded_pass | 1 | 18.2 | 5 | 14837 |
| regfile | 0 | stalled | False | pass | None | 1 | 42.6 | 9 | 36017 |
| shift_reg | 0 | completed | True | pass | counterexample | 2 | 27.2 | 5 | 19273 |
| stream_acc | 0 | failed | False | no_rtl | None | 0 | 23.1 | 4 | 17294 |
| sync_fifo | 0 | failed | False | no_rtl | None | 0 | 26.0 | 4 | 18203 |
| timer | 0 | completed | True | simulate | bounded_pass | 1 | 31.5 | 7 | 27018 |
| updown_counter | 0 | completed | True | pass | bounded_pass | 1 | 21.6 | 6 | 19631 |
