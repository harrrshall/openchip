# Eval `core-v1` — 20260908-102638

n = 10 (10 tasks x 1); budget 15m; model `Qwen/Qwen3-8B` @ `b968826d9c46dd6066d109eabc6255188de91218` T=0.2 thinking=True

- agent accepted: 3/10
- golden pass (independent): 4/10
- false acceptance: 1/10
- interface mismatch: 3/10

| task | rep | state | accepted | golden | attempts | wall s | calls | tokens |
|---|---|---|---|---|---|---|---|---|
| alu8 | 0 | budget_exhausted | False | lint | 5 | 107.9 | 7 | 30612 |
| edge_detector | 0 | stalled | False | pass | 2 | 36.9 | 5 | 13180 |
| gray_counter | 0 | completed | True | interface_mismatch | 1 | 32.1 | 3 | 6580 |
| pwm_gen | 0 | stalled | False | simulate | 1 | 65.3 | 5 | 13573 |
| regfile | 0 | completed | True | pass | 1 | 36.7 | 3 | 8199 |
| shift_reg | 0 | stalled | False | pass | 4 | 78.5 | 9 | 24774 |
| stream_acc | 0 | stalled | False | simulate | 1 | 101.1 | 5 | 21914 |
| sync_fifo | 0 | stalled | False | interface_mismatch | 3 | 68.4 | 5 | 20076 |
| timer | 0 | stalled | False | interface_mismatch | 1 | 50.4 | 4 | 12991 |
| updown_counter | 0 | completed | True | pass | 1 | 30.1 | 3 | 7042 |
